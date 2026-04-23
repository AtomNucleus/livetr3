from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

import numpy as np
from fastapi import WebSocket

from mlx_worker import MLXWorkerService, WorkerStatusEvent
from protocol import (
    ConfigMessage,
    ErrorMessage,
    LevelMessage,
    SpeechStartMessage,
    StatusMessage,
    TranscriptMessage,
    parse_control_message,
)
from segmenter import FRAME_SAMPLES, RMSGate, make_segmenter

MAINTENANCE_INTERVAL_SECONDS = max(
    60.0, float(os.getenv("MAINTENANCE_INTERVAL_SECONDS", str(20 * 60)))
)
MAINTENANCE_INTERVAL_UTTERANCES = max(
    1, int(os.getenv("MAINTENANCE_INTERVAL_UTTERANCES", "100"))
)
ARCHIVE_AUTOSAVE_SECONDS = max(5, int(os.getenv("SESSION_AUTOSAVE_SECONDS", "60")))
ARCHIVE_ROOT = (
    Path.home() / "Library" / "Application Support" / "LiveTR3" / "sessions"
)


@dataclass(slots=True)
class SessionState:
    config: ConfigMessage = field(default_factory=ConfigMessage)
    running: bool = False
    utterance_id: int = 0
    active_utterance_id: int | None = None
    prior_context: list[tuple[str, str]] = field(default_factory=list)
    last_maintenance_at: float = field(default_factory=time.monotonic)
    utterances_since_maintenance: int = 0


@dataclass(slots=True)
class SharedSessionRoom:
    session_id: str
    producer: TranscriptionSession | None = None
    viewers: set[TranscriptionSession] = field(default_factory=set)
    transcript_state: dict[int, dict] = field(default_factory=dict)
    saved_state: dict | None = None


class SessionHub:
    def __init__(self) -> None:
        self._rooms: dict[str, SharedSessionRoom] = {}
        self._lock = asyncio.Lock()

    async def attach_producer(self, session_id: str, session: TranscriptionSession) -> None:
        async with self._lock:
            room = self._rooms.setdefault(session_id, SharedSessionRoom(session_id=session_id))
            room.producer = session

    async def attach_viewer(self, session_id: str, session: TranscriptionSession) -> list[dict]:
        async with self._lock:
            room = self._rooms.setdefault(session_id, SharedSessionRoom(session_id=session_id))
            room.viewers.add(session)
            return [room.transcript_state[key] for key in sorted(room.transcript_state)]

    async def detach(self, session_id: str, session: TranscriptionSession) -> None:
        async with self._lock:
            room = self._rooms.get(session_id)
            if room is None:
                return
            if room.producer is session:
                room.saved_state = session.export_session_snapshot()
                room.producer = None
            room.viewers.discard(session)
            if room.producer is None and not room.viewers and room.saved_state is None:
                self._rooms.pop(session_id, None)

    async def broadcast_transcript(
        self,
        session_id: str,
        payload: dict,
        sender: TranscriptionSession,
    ) -> None:
        async with self._lock:
            room = self._rooms.setdefault(session_id, SharedSessionRoom(session_id=session_id))
            if payload.get("type") in {"partial", "final", "polished"}:
                room.transcript_state[payload["utterance_id"]] = payload
            viewers = list(room.viewers)
        await asyncio.gather(
            *(viewer.send_viewer_payload(payload) for viewer in viewers if viewer is not sender),
            return_exceptions=True,
        )

    async def restore_saved_state(self, session_id: str) -> dict | None:
        async with self._lock:
            room = self._rooms.get(session_id)
            if room is None:
                return None
            return room.saved_state.copy() if room.saved_state is not None else None


class TranscriptionSession:
    def __init__(self, websocket: WebSocket, worker: MLXWorkerService, hub: SessionHub) -> None:
        self.websocket = websocket
        self.worker = worker
        self.hub = hub
        self.state = SessionState()
        self.segmenter: RMSGate = self._build_segmenter(self.state.config)
        self.ring: deque[np.ndarray] = deque(maxlen=int(30 / 0.02))
        self._send_lock = asyncio.Lock()
        self._jobs: set[asyncio.Task] = set()
        self._last_partial_at = 0.0
        self._last_level_at = 0.0
        self._finalized: set[int] = set()
        self._partial_inflight: set[int] = set()
        self._pending_config: ConfigMessage | None = None
        self._skip_next_polish = False
        self.session_id = websocket.query_params.get("session") or str(uuid4())
        self.role: Literal["unknown", "producer", "viewer"] = "unknown"
        self._archive_dir: Path | None = None
        self._archive_started_at: datetime | None = None
        self._archive_started_at_monotonic: float | None = None
        self._archive_events: list[dict] = []
        self._archive_utterances: dict[int, dict] = {}
        self._archive_autosave_task: asyncio.Task | None = None

    async def run(self) -> None:
        await self.websocket.accept()
        await self.worker.add_status_listener(self._handle_worker_status)
        try:
            while True:
                message = await self.websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    await self._receive_audio(message["bytes"])
                elif message.get("text") is not None:
                    await self._receive_text(message["text"])
        finally:
            self.worker.remove_status_listener(self._handle_worker_status)
            await self.hub.detach(self.session_id, self)
            await self._finalize_archive()
            for task in self._jobs:
                task.cancel()
            await asyncio.gather(*self._jobs, return_exceptions=True)

    async def _receive_text(self, text: str) -> None:
        try:
            payload = json.loads(text)
            msg = parse_control_message(payload)
        except Exception as exc:
            await self._send_error(f"Invalid control message: {exc}")
            return

        if msg.type == "join_viewer":
            self.role = "viewer"
            snapshot = await self.hub.attach_viewer(self.session_id, self)
            for payload in snapshot:
                await self._send(payload)
            return

        if self.role == "viewer":
            await self._send_error("Viewer connections are read-only")
            return

        if self.role == "unknown":
            self.role = "producer"
            await self.hub.attach_producer(self.session_id, self)

        if self._archive_dir is not None:
            self._record_archive_payload({"type": "client_control", "payload": payload})

        if msg.type == "config":
            if msg.apply_target == "next_utterance":
                self._pending_config = msg.model_copy(update={"apply_target": "immediate"})
            else:
                await self._apply_config(msg)
            return

        if msg.type == "resume":
            snapshot = await self.hub.restore_saved_state(self.session_id)
            if snapshot is not None:
                await self._restore_from_snapshot(snapshot)
            else:
                self.state.running = True
                self.segmenter.reset()
            return

        if msg.type == "start":
            self._begin_archive()
            self.state.running = True
            self.segmenter.reset()
            self._last_partial_at = 0.0
            self.state.last_maintenance_at = time.monotonic()
            self.state.utterances_since_maintenance = 0
            return

        if msg.type == "commit_now":
            await self._flush_active_final()
            return

        if msg.type == "skip_polish":
            self._skip_next_polish = True
            return

        if msg.type == "stop":
            await self._flush_active_final()
            self.state.running = False
            self.segmenter.reset()
            await self._write_archive_snapshot()

    async def _receive_audio(self, data: bytes) -> None:
        if self.role == "viewer":
            return
        if self.role == "unknown":
            self.role = "producer"
            await self.hub.attach_producer(self.session_id, self)
        if not self.state.running:
            return
        if len(data) % 4 != 0:
            await self._send_error("Audio frame was not float32-aligned")
            return

        samples = np.frombuffer(data, dtype="<f4").astype(np.float32, copy=True)
        if samples.size < FRAME_SAMPLES:
            return

        frame_count = samples.size // FRAME_SAMPLES
        for frame in np.split(samples[: frame_count * FRAME_SAMPLES], frame_count):
            await self._receive_frame(frame)

    async def _receive_frame(self, frame: np.ndarray) -> None:
        self.ring.append(frame.copy())
        result = self.segmenter.ingest(frame)
        now = time.monotonic()

        if now - self._last_level_at >= 0.05:
            self._last_level_at = now
            await self._send(LevelMessage(rms=result.rms).model_dump())

        if result.speech_started:
            if self._pending_config is not None:
                await self._apply_config(self._pending_config)
                self._pending_config = None
            self.state.utterance_id += 1
            self.state.active_utterance_id = self.state.utterance_id
            self._last_partial_at = now
            await self._send_and_broadcast(
                SpeechStartMessage(utterance_id=self.state.utterance_id).model_dump()
            )

        if result.speech_active and now - self._last_partial_at >= float(
            self.state.config.partial_interval_seconds
            or float(os.getenv("PARTIAL_INTERVAL_SECONDS", "2"))
        ):
            self._last_partial_at = now
            audio = self.segmenter.current_audio()
            if audio.size and not self.worker.is_busy_or_backlogged:
                self._schedule_ast("partial", self.state.active_utterance_id, audio)

        if result.speech_ended and result.audio is not None:
            utterance_id = self.state.active_utterance_id
            self.state.active_utterance_id = None
            self._schedule_ast("final", utterance_id, result.audio)

    async def _flush_active_final(self) -> None:
        if not self.segmenter.speech_active or self.state.active_utterance_id is None:
            return
        audio = self.segmenter.current_audio()
        utterance_id = self.state.active_utterance_id
        self.state.active_utterance_id = None
        self.segmenter.reset()
        if audio.size:
            self._schedule_ast("final", utterance_id, audio)

    def _schedule_ast(
        self,
        priority: str,
        utterance_id: int | None,
        audio: np.ndarray,
    ) -> None:
        if utterance_id is None:
            return
        if priority == "partial":
            if utterance_id in self._partial_inflight or utterance_id in self._finalized:
                return
            self._partial_inflight.add(utterance_id)
        task = asyncio.create_task(
            self._run_ast(priority, utterance_id, audio.copy()),
            name=f"{priority}-ast-{utterance_id}",
        )
        self._jobs.add(task)
        task.add_done_callback(self._jobs.discard)

    async def _run_ast(self, priority: str, utterance_id: int, audio: np.ndarray) -> None:
        try:
            original, translation = await self.worker.submit_ast(
                priority="final" if priority == "final" else "partial",
                audio_f32_16k=audio,
                src=self.state.config.source_lang,
                tgt=self.state.config.target_lang,
                prior_context=self.state.prior_context[-2:],
                custom_vocab=self.state.config.custom_vocab,
                code_switching_enabled=self.state.config.code_switching_enabled,
                max_tokens=self._max_tokens_for_ast(priority, audio),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._send_error(f"Inference failed: {exc}")
            return
        finally:
            if priority == "partial":
                self._partial_inflight.discard(utterance_id)

        if priority == "partial":
            if utterance_id in self._finalized:
                return
            await self._send_and_broadcast(
                TranscriptMessage(
                    type="partial",
                    utterance_id=utterance_id,
                    original=original,
                    translation=translation,
                ).model_dump()
            )
            return

        self._finalized.add(utterance_id)
        self.state.prior_context.append((original, translation))
        self.state.prior_context = self.state.prior_context[-2:]
        self.state.utterances_since_maintenance += 1
        await self._send_and_broadcast(
            TranscriptMessage(
                type="final",
                utterance_id=utterance_id,
                original=original,
                translation=translation,
            ).model_dump()
        )

        skip_polish = self._skip_next_polish
        self._skip_next_polish = False
        if self.state.config.polish_enabled and not skip_polish:
            task = asyncio.create_task(
                self._run_polish(utterance_id, original, translation),
                name=f"polish-{utterance_id}",
            )
            self._jobs.add(task)
            task.add_done_callback(self._jobs.discard)
        await self._maybe_run_maintenance()

    async def _run_polish(self, utterance_id: int, original: str, translation: str) -> None:
        try:
            polished_original = await self.worker.submit_polish(original)
            polished_translation = await self.worker.submit_polish(translation)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._send_error(f"Polish failed: {exc}")
            return
        await self._send_and_broadcast(
            TranscriptMessage(
                type="polished",
                utterance_id=utterance_id,
                original=polished_original,
                translation=polished_translation,
            ).model_dump()
        )

    async def _send_error(self, message: str) -> None:
        await self._send(ErrorMessage(message=message).model_dump())

    async def _send(self, payload: dict) -> None:
        self._record_archive_payload(payload)
        async with self._send_lock:
            await self.websocket.send_json(payload)

    async def _send_and_broadcast(self, payload: dict) -> None:
        await self._send(payload)
        if self.role == "producer":
            await self.hub.broadcast_transcript(self.session_id, payload, sender=self)

    async def _handle_worker_status(self, event: WorkerStatusEvent) -> None:
        await self._send(
            StatusMessage(
                state=event.state,
                message=event.message,
            ).model_dump()
        )

    async def _maybe_run_maintenance(self) -> None:
        if self.state.active_utterance_id is not None or not self.state.running:
            return

        now = time.monotonic()
        due_for_time = now - self.state.last_maintenance_at >= MAINTENANCE_INTERVAL_SECONDS
        due_for_utterances = (
            self.state.utterances_since_maintenance >= MAINTENANCE_INTERVAL_UTTERANCES
        )
        if not due_for_time and not due_for_utterances:
            return

        self.segmenter.reset()
        self._last_partial_at = 0.0
        self.state.last_maintenance_at = now
        self.state.utterances_since_maintenance = 0

        task = asyncio.create_task(self._run_maintenance(), name="session-maintenance")
        self._jobs.add(task)
        task.add_done_callback(self._jobs.discard)

    async def _run_maintenance(self) -> None:
        try:
            await self.worker.submit_maintenance()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._send_error(f"Worker maintenance failed: {exc}")

    async def send_viewer_payload(self, payload: dict) -> None:
        if self.role != "viewer":
            return
        await self._send(payload)

    async def _apply_config(self, config: ConfigMessage) -> None:
        self.state.config = config.model_copy(update={"apply_target": "immediate"})
        try:
            self.segmenter = self._build_segmenter(self.state.config)
        except Exception as exc:
            await self._send_error(str(exc))

    async def _restore_from_snapshot(self, snapshot: dict) -> None:
        await self._apply_config(ConfigMessage.model_validate(snapshot["config"]))
        self.state.running = bool(snapshot.get("running", False))
        self.state.utterance_id = int(snapshot.get("utterance_id", 0))
        self.state.active_utterance_id = None
        self.state.prior_context = [
            (item[0], item[1]) for item in snapshot.get("prior_context", [])
        ]
        self._finalized = set(snapshot.get("finalized_ids", []))
        self.segmenter.reset()

    def export_session_snapshot(self) -> dict:
        return {
            "config": self.state.config.model_dump(),
            "running": self.state.running,
            "utterance_id": self.state.utterance_id,
            "prior_context": self.state.prior_context,
            "finalized_ids": sorted(self._finalized),
        }

    def _build_segmenter(self, config: ConfigMessage) -> RMSGate:
        rms_threshold = config.rms_threshold or float(os.getenv("RMS_THRESHOLD", "0.01"))
        silero_threshold = min(max(config.silero_threshold or 0.5, 0.1), 0.95)
        speech_pad_ms = min(max(config.speech_pad_ms or 300, 0), 2000)
        min_silence_ms = min(max(config.min_silence_ms or 400, 100), 5000)
        max_utterance_seconds = min(max(config.max_utterance_seconds or 25.0, 5.0), 29.0)
        return make_segmenter(
            config.segmenter,
            rms_threshold,
            silero_threshold=silero_threshold,
            speech_pad_ms=speech_pad_ms,
            min_silence_ms=min_silence_ms,
            max_utterance_s=max_utterance_seconds,
        )

    def _max_tokens_for_ast(self, priority: str, audio: np.ndarray) -> int:
        if priority == "partial":
            return 64
        duration_seconds = audio.shape[0] / 16_000
        if duration_seconds <= 8:
            return 80
        if duration_seconds <= 15:
            return 128
        return 192

    def _begin_archive(self) -> None:
        if self._archive_dir is not None:
            return
        started_at = datetime.now().astimezone()
        started_at_slug = started_at.strftime("%Y-%m-%dT%H-%M-%S%z")
        self._archive_dir = ARCHIVE_ROOT / started_at_slug
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        self._archive_started_at = started_at
        self._archive_started_at_monotonic = time.monotonic()
        self._archive_events = []
        self._archive_utterances = {}
        if self._archive_autosave_task is None:
            self._archive_autosave_task = asyncio.create_task(
                self._run_archive_autosave(),
                name=f"archive-autosave-{self.session_id}",
            )

    async def _run_archive_autosave(self) -> None:
        try:
            while True:
                await asyncio.sleep(ARCHIVE_AUTOSAVE_SECONDS)
                await self._write_archive_snapshot()
        except asyncio.CancelledError:
            raise

    def _record_archive_payload(self, payload: dict) -> None:
        if self.role == "viewer" or self._archive_dir is None or payload.get("type") == "level":
            return
        elapsed_seconds = self._archive_elapsed_seconds()
        self._archive_events.append(
            {
                "timestamp_seconds": elapsed_seconds,
                "payload": payload,
            }
        )

        payload_type = payload.get("type")
        if payload_type == "speech_start":
            self._archive_utterances[payload["utterance_id"]] = {
                "utterance_id": payload["utterance_id"],
                "started_at": elapsed_seconds,
                "ended_at": elapsed_seconds,
                "original": "",
                "translation": "",
                "state": "partial",
            }
            return

        if payload_type not in {"partial", "final", "polished"}:
            return

        utterance = self._archive_utterances.setdefault(
            payload["utterance_id"],
            {
                "utterance_id": payload["utterance_id"],
                "started_at": elapsed_seconds,
                "ended_at": elapsed_seconds,
                "original": "",
                "translation": "",
                "state": payload_type,
            },
        )
        utterance["original"] = payload["original"]
        utterance["translation"] = payload["translation"]
        utterance["state"] = payload_type
        if payload_type != "partial":
            utterance["ended_at"] = elapsed_seconds

    def _archive_elapsed_seconds(self) -> float:
        if self._archive_started_at_monotonic is None:
            return 0.0
        return max(0.0, time.monotonic() - self._archive_started_at_monotonic)

    async def _write_archive_snapshot(self) -> None:
        if self._archive_dir is None or self._archive_started_at is None:
            return
        archive_dir = self._archive_dir
        events = list(self._archive_events)
        utterances = [self._archive_utterances[key] for key in sorted(self._archive_utterances)]
        duration_seconds = self._archive_elapsed_seconds()
        meta = {
            "session_id": self.session_id,
            "started_at": self._archive_started_at.isoformat(),
            "duration_seconds": duration_seconds,
            "config": self.state.config.model_dump(),
            "device": {
                "id": self.state.config.input_device_id,
                "label": self.state.config.input_device_label,
            },
        }
        await asyncio.to_thread(
            self._write_archive_files,
            archive_dir,
            utterances,
            events,
            meta,
        )

    async def _finalize_archive(self) -> None:
        if self._archive_dir is None:
            return
        if self._archive_autosave_task is not None:
            self._archive_autosave_task.cancel()
            try:
                await self._archive_autosave_task
            except asyncio.CancelledError:
                pass
            self._archive_autosave_task = None
        await self._write_archive_snapshot()
        self._archive_dir = None

    def _write_archive_files(
        self,
        archive_dir: Path,
        utterances: list[dict],
        events: list[dict],
        meta: dict,
    ) -> None:
        archive_dir.mkdir(parents=True, exist_ok=True)
        (archive_dir / "transcript.srt").write_text(
            self._render_srt(utterances),
            encoding="utf-8",
        )
        (archive_dir / "transcript.vtt").write_text(
            self._render_vtt(utterances),
            encoding="utf-8",
        )
        (archive_dir / "transcript.json").write_text(
            json.dumps(events, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (archive_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _render_srt(self, utterances: list[dict]) -> str:
        cues: list[str] = []
        for index, utterance in enumerate(utterances, start=1):
            cues.append(
                "\n".join(
                    [
                        str(index),
                        f"{_format_subtitle_time(utterance['started_at'])} --> {_format_subtitle_time(utterance['ended_at'])}",
                        utterance["original"],
                        utterance["translation"],
                    ]
                )
            )
        return "\n\n".join(cues).strip() + ("\n" if cues else "")

    def _render_vtt(self, utterances: list[dict]) -> str:
        cues = ["WEBVTT"]
        for utterance in utterances:
            cues.append(
                "\n".join(
                    [
                        f"{_format_subtitle_time(utterance['started_at'], vtt=True)} --> {_format_subtitle_time(utterance['ended_at'], vtt=True)}",
                        utterance["original"],
                        utterance["translation"],
                    ]
                )
            )
        return "\n\n".join(cues).strip() + "\n"


def _format_subtitle_time(seconds: float, *, vtt: bool = False) -> str:
    total_millis = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(total_millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    separator = "." if vtt else ","
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"
