from __future__ import annotations

import asyncio
from difflib import SequenceMatcher
import json
import logging
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

import numpy as np
from mlx_worker import InferenceTimeoutError, MLXWorkerService, WorkerStatusEvent
from parakeet_worker import ASRResult, ParakeetASRService
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
from transport import SessionTransport

logger = logging.getLogger("uvicorn.error")

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
LEARNING_PROFILE_PATH = (
    Path.home() / "Library" / "Application Support" / "LiveTR3" / "learning_profile.json"
)
MAX_LEARNED_ASR_CORRECTIONS = max(
    8, int(os.getenv("MAX_LEARNED_ASR_CORRECTIONS", "64"))
)
PARTIAL_INTERVAL_MIN_SECONDS = 0.2
PARTIAL_INTERVAL_MAX_SECONDS = 3.0
SOURCE_END_PUNCTUATION = ".?!"
TRAILING_PUNCTUATION_QUOTES = " \t\r\n\"'“”‘’)]}"
ABBREVIATIONS_BEFORE_END_PUNCTUATION = {
    "mr",
    "mrs",
    "ms",
    "dr",
    "prof",
    "st",
    "jr",
    "sr",
    "vs",
    "etc",
    "ie",
    "i.e",
    "eg",
    "e.g",
}
DEFAULT_EARLY_COMMIT_ENABLED = os.getenv("EARLY_COMMIT_ENABLED", "false").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DEFAULT_EARLY_COMMIT_MIN_SECONDS = max(
    0.0, float(os.getenv("EARLY_COMMIT_MIN_SECONDS", "1.0"))
)
DEFAULT_EARLY_COMMIT_PUNCTUATION = os.getenv(
    "EARLY_COMMIT_PUNCTUATION", "true"
).lower() not in {"0", "false", "no", "off"}
DEFAULT_EARLY_COMMIT_STABILITY = os.getenv("EARLY_COMMIT_STABILITY", "true").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DEFAULT_STABILITY_WINDOW = max(2, int(os.getenv("STABILITY_WINDOW", "2")))
DEFAULT_PRIOR_CONTEXT_ENABLED = os.getenv(
    "PRIOR_CONTEXT_ENABLED", "false"
).lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DEFAULT_PARTIAL_MIN_AUDIO_SECONDS = max(
    0.0, float(os.getenv("PARTIAL_MIN_AUDIO_SECONDS", "0.25"))
)
DEFAULT_PARTIAL_MIN_NEW_SPEECH_SECONDS = max(
    0.1, float(os.getenv("PARTIAL_MIN_NEW_SPEECH_SECONDS", "0.20"))
)
DEFAULT_PARTIAL_AST_ENABLED = os.getenv("PARTIAL_AST_ENABLED", "true").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
MIN_TRANSCRIBABLE_RMS = max(0.0, float(os.getenv("MIN_TRANSCRIBABLE_RMS", "0.0004")))
MIN_TRANSCRIBABLE_PEAK = max(0.0, float(os.getenv("MIN_TRANSCRIBABLE_PEAK", "0.003")))
MIN_TRANSCRIBABLE_FRAME_RMS = max(
    0.0, float(os.getenv("MIN_TRANSCRIBABLE_FRAME_RMS", "0.0006"))
)
MIN_TRANSCRIBABLE_VOICED_MS = max(
    0, int(os.getenv("MIN_TRANSCRIBABLE_VOICED_MS", "60"))
)
TRANSCRIBABLE_TRIM_PAD_SECONDS = min(
    1.0, max(0.0, float(os.getenv("TRANSCRIBABLE_TRIM_PAD_SECONDS", "0.30")))
)


CommitReason = Literal["punctuation", "stability", "silero_end", "max_utterance_cap"]


@dataclass(slots=True)
class UtteranceRuntime:
    partials: deque[str] = field(default_factory=deque)
    last_audio_frame_unix_seconds: float | None = None
    last_partial_wall_seconds: float = 0.0
    last_partial_audio_samples: int = 0
    last_voiced_audio_samples: int = 0
    voiced_audio_samples: int = 0
    latest_partial_original: str = ""
    latest_partial_translation: str = ""
    latest_translation_original: str = ""
    translation_incomplete: bool = False


def _source_text_ends_sentence(text: str) -> bool:
    stripped = text.rstrip(TRAILING_PUNCTUATION_QUOTES)
    if not stripped or stripped[-1] not in SOURCE_END_PUNCTUATION:
        return False
    before_punctuation = stripped[:-1].rstrip(TRAILING_PUNCTUATION_QUOTES)
    match = re.search(r"([A-Za-z](?:[A-Za-z]|\.)*)$", before_punctuation)
    if match and match.group(1).rstrip(".").lower() in ABBREVIATIONS_BEFORE_END_PUNCTUATION:
        return False
    return True


def _normalize_stability_text(text: str) -> str:
    return text.strip().rstrip(TRAILING_PUNCTUATION_QUOTES + SOURCE_END_PUNCTUATION).lower()


def _normalize_learned_text(text: str) -> str:
    text = re.sub(r"[^\w\s]", "", text, flags=re.UNICODE)
    return " ".join(text.lower().split())


def _source_extends_translation(current: str, translated_source: str) -> bool:
    """A translated prefix remains valid when speech grows, but not when ASR revises it."""
    current = _normalize_learned_text(current)
    translated_source = _normalize_learned_text(translated_source)
    return bool(translated_source) and (
        current == translated_source or current.startswith(translated_source + " ")
    )


SPANISH_HINT_WORDS = {
    "a",
    "al",
    "como",
    "con",
    "de",
    "del",
    "dios",
    "el",
    "en",
    "evangelio",
    "iglesia",
    "la",
    "las",
    "lo",
    "los",
    "nosotros",
    "para",
    "palabra",
    "por",
    "que",
    "se",
    "señor",
    "tu",
    "un",
    "una",
    "vida",
    "viva",
    "y",
}
ENGLISH_HINT_WORDS = {
    "a",
    "all",
    "and",
    "are",
    "christian",
    "christians",
    "church",
    "for",
    "god",
    "gospel",
    "in",
    "is",
    "it",
    "life",
    "new",
    "them",
    "of",
    "that",
    "the",
    "this",
    "to",
    "we",
    "word",
    "you",
}


def _language_hint_score(text: str, words: set[str]) -> int:
    tokens = re.findall(r"[\wñáéíóúü]+", text.lower(), flags=re.UNICODE)
    return sum(1 for token in tokens if token in words)


def _spanish_hint_score(text: str) -> int:
    return _language_hint_score(text, SPANISH_HINT_WORDS) + len(
        re.findall(r"[ñáéíóúü]", text.lower())
    )


def _english_hint_score(text: str) -> int:
    return _language_hint_score(text, ENGLISH_HINT_WORDS)


def _looks_like_translation_pair(heard: str, corrected: str) -> bool:
    heard_spanish = _spanish_hint_score(heard)
    heard_english = _english_hint_score(heard)
    corrected_spanish = _spanish_hint_score(corrected)
    corrected_english = _english_hint_score(corrected)
    return (
        heard_spanish >= heard_english + 2
        and corrected_english >= corrected_spanish + 2
    ) or (
        heard_english >= heard_spanish + 2
        and corrected_spanish >= corrected_english + 2
    ) or (
        heard_spanish >= 1
        and corrected_english >= 1
        and corrected_spanish == 0
    ) or (
        heard_english >= 1
        and corrected_spanish >= 1
        and heard_spanish == 0
    )


def _language_hint(text: str) -> Literal["English", "Spanish"] | None:
    spanish = _spanish_hint_score(text)
    english = _english_hint_score(text)
    if spanish >= english + 1:
        return "Spanish"
    if english >= spanish + 1:
        return "English"
    return None


def _bounded_partial_interval_seconds(value: float, *, source: str) -> float:
    bounded = min(max(value, PARTIAL_INTERVAL_MIN_SECONDS), PARTIAL_INTERVAL_MAX_SECONDS)
    if bounded != value:
        logger.warning(
            "%s %.3fs is outside %.1f-%.1fs; clamping to %.3fs",
            source,
            value,
            PARTIAL_INTERVAL_MIN_SECONDS,
            PARTIAL_INTERVAL_MAX_SECONDS,
            bounded,
        )
    return bounded


def _load_default_partial_interval_seconds() -> float:
    raw_value = os.getenv("PARTIAL_INTERVAL_SECONDS", "0.25")
    try:
        value = float(raw_value)
    except ValueError:
        logger.warning(
            "PARTIAL_INTERVAL_SECONDS=%r is not a float; using default 0.250s",
            raw_value,
        )
        return 0.25
    return _bounded_partial_interval_seconds(value, source="PARTIAL_INTERVAL_SECONDS")


DEFAULT_PARTIAL_INTERVAL_SECONDS = _load_default_partial_interval_seconds()


def _audio_energy_stats(audio: np.ndarray) -> tuple[float, float, int, int]:
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if audio.size < FRAME_SAMPLES:
        return 0.0, 0.0, 0, max(1, int(np.ceil(MIN_TRANSCRIBABLE_VOICED_MS / 20)))

    rms = float(np.sqrt(float(np.mean(np.square(audio)))))
    peak = float(np.max(np.abs(audio)))

    frame_count = audio.size // FRAME_SAMPLES
    if frame_count <= 0:
        return rms, peak, 0, max(1, int(np.ceil(MIN_TRANSCRIBABLE_VOICED_MS / 20)))
    framed = audio[: frame_count * FRAME_SAMPLES].reshape(frame_count, FRAME_SAMPLES)
    frame_rms = np.sqrt(np.mean(np.square(framed), axis=1))
    voiced_frames = int(np.count_nonzero(frame_rms >= MIN_TRANSCRIBABLE_FRAME_RMS))
    required_frames = max(1, int(np.ceil(MIN_TRANSCRIBABLE_VOICED_MS / 20)))
    return rms, peak, voiced_frames, required_frames


def _audio_has_transcribable_energy(audio: np.ndarray) -> bool:
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if audio.size < FRAME_SAMPLES:
        return False
    rms, peak, voiced_frames, required_frames = _audio_energy_stats(audio)
    if peak < MIN_TRANSCRIBABLE_PEAK:
        return False
    if voiced_frames < required_frames:
        return False
    return rms >= MIN_TRANSCRIBABLE_RMS or voiced_frames >= required_frames * 2


def _trim_to_transcribable_audio(audio: np.ndarray) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    frame_count = audio.size // FRAME_SAMPLES
    if frame_count <= 0:
        return np.zeros(0, dtype=np.float32)

    framed = audio[: frame_count * FRAME_SAMPLES].reshape(frame_count, FRAME_SAMPLES)
    frame_rms = np.sqrt(np.mean(np.square(framed), axis=1))
    voiced_indices = np.flatnonzero(frame_rms >= MIN_TRANSCRIBABLE_FRAME_RMS)
    if voiced_indices.size == 0:
        return audio

    pad_frames = max(1, int(np.ceil(TRANSCRIBABLE_TRIM_PAD_SECONDS / 0.02)))
    start_frame = max(0, int(voiced_indices[0]) - pad_frames)
    end_frame = min(frame_count, int(voiced_indices[-1]) + pad_frames + 1)
    return audio[start_frame * FRAME_SAMPLES : end_frame * FRAME_SAMPLES].astype(
        np.float32,
        copy=False,
    )


@dataclass(slots=True)
class SessionState:
    config: ConfigMessage = field(default_factory=ConfigMessage)
    running: bool = False
    utterance_id: int = 0
    active_utterance_id: int | None = None
    prior_context: list[tuple[str, str]] = field(default_factory=list)
    bilingual_context: list[tuple[str, str]] = field(default_factory=list)
    asr_corrections: list[tuple[str, str]] = field(default_factory=list)
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

    async def begin_producer_run(self, session_id: str) -> int:
        async with self._lock:
            room = self._rooms.setdefault(session_id, SharedSessionRoom(session_id=session_id))
            highest_utterance_id = max(room.transcript_state.keys(), default=0)
            if room.saved_state is not None:
                highest_utterance_id = max(
                    highest_utterance_id,
                    int(room.saved_state.get("utterance_id", 0)),
                )
            room.transcript_state.clear()
            room.saved_state = None
            return highest_utterance_id

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

    async def active_producer_count(self) -> int:
        async with self._lock:
            return sum(1 for room in self._rooms.values() if room.producer is not None)


class TranscriptionSession:
    def __init__(
        self,
        websocket: SessionTransport,
        worker: MLXWorkerService,
        hub: SessionHub,
        *,
        transcription_engine: str = "gemma",
        asr_worker: ParakeetASRService | None = None,
    ) -> None:
        self.websocket = websocket
        self.worker = worker
        self.asr_worker = asr_worker
        self.hub = hub
        self.transcription_engine = transcription_engine
        self.state = SessionState()
        self.segmenter: RMSGate = self._build_segmenter(self.state.config)
        self.ring: deque[np.ndarray] = deque(maxlen=int(30 / 0.02))
        self._send_lock = asyncio.Lock()
        self._jobs: set[asyncio.Task] = set()
        self._last_level_at = 0.0
        self._finalized: set[int] = set()
        self._finalizing: dict[int, CommitReason] = {}
        self._finalize_lock = asyncio.Lock()
        self._utterance_runtime: dict[int, UtteranceRuntime] = {}
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
        if self.transcription_engine == "gemma":
            await self.worker.add_status_listener(self._handle_worker_status)
        if self.asr_worker is not None:
            await self.asr_worker.add_status_listener(self._handle_worker_status)
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
            if self.transcription_engine == "gemma":
                self.worker.remove_status_listener(self._handle_worker_status)
            if self.asr_worker is not None:
                self.asr_worker.remove_status_listener(self._handle_worker_status)
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
                await self._resume_archive_from_disk()
                self.state.running = True
                self.segmenter.reset()
                self._finalizing.clear()
                self._utterance_runtime.clear()
            self._schedule_worker_warmup()
            return

        if msg.type == "start":
            highest_utterance_id = await self.hub.begin_producer_run(self.session_id)
            self._begin_archive()
            self.state.running = True
            self.state.utterance_id = max(self.state.utterance_id, highest_utterance_id)
            self.segmenter.reset()
            self._finalized.clear()
            self._finalizing.clear()
            self._utterance_runtime.clear()
            self.state.last_maintenance_at = time.monotonic()
            self.state.utterances_since_maintenance = 0
            self._schedule_worker_warmup()
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
            self._utterance_runtime[self.state.utterance_id] = UtteranceRuntime(
                partials=deque(maxlen=self._stability_window()),
            )
            await self._send_and_broadcast(
                SpeechStartMessage(utterance_id=self.state.utterance_id).model_dump()
            )

        if (
            result.speech_active
            and self.state.active_utterance_id is not None
            and result.rms >= MIN_TRANSCRIBABLE_FRAME_RMS
        ):
            runtime = self._utterance_runtime.setdefault(
                self.state.active_utterance_id,
                UtteranceRuntime(partials=deque(maxlen=self._stability_window())),
            )
            runtime.last_audio_frame_unix_seconds = time.time()
            runtime.last_voiced_audio_samples = self.segmenter.current_audio().shape[0]
            runtime.voiced_audio_samples += FRAME_SAMPLES

        if (
            result.speech_active
            and DEFAULT_PARTIAL_AST_ENABLED
            and self.state.active_utterance_id not in self._finalizing
            and self._active_utterance_has_new_speech_for_partial()
        ):
            audio = self.segmenter.current_audio()
            trimmed_audio = _trim_to_transcribable_audio(audio)
            if (
                trimmed_audio.size
                and trimmed_audio.shape[0] / 16_000 >= DEFAULT_PARTIAL_MIN_AUDIO_SECONDS
                and _audio_has_transcribable_energy(trimmed_audio)
            ):
                # Each hypothesis replaces the previous one; preserve the whole utterance.
                inference_audio = trimmed_audio
                runtime = self._active_utterance_runtime()
                if runtime is not None:
                    runtime.last_partial_wall_seconds = time.monotonic()
                    runtime.last_partial_audio_samples = runtime.voiced_audio_samples
                self._schedule_ast("partial", self.state.active_utterance_id, inference_audio)

        if result.speech_ended and result.audio is not None:
            utterance_id = self.state.active_utterance_id
            reason: CommitReason = "max_utterance_cap" if result.force_flushed else "silero_end"
            await self._commit_utterance(utterance_id, result.audio, reason=reason, reset_segmenter=False)

    async def _flush_active_final(self) -> None:
        if not self.segmenter.speech_active or self.state.active_utterance_id is None:
            return
        audio = self.segmenter.current_audio()
        utterance_id = self.state.active_utterance_id
        if audio.size:
            await self._commit_utterance(utterance_id, audio, reason="silero_end", reset_segmenter=True)

    async def _commit_utterance(
        self,
        utterance_id: int | None,
        audio: np.ndarray,
        *,
        reason: CommitReason,
        reset_segmenter: bool,
    ) -> bool:
        if utterance_id is None or not audio.size:
            return False
        transcribable_audio = _trim_to_transcribable_audio(audio)
        if not _audio_has_transcribable_energy(transcribable_audio):
            rms, peak, voiced_frames, required_frames = _audio_energy_stats(transcribable_audio)
            if reset_segmenter:
                self.segmenter.reset()
            if self.state.active_utterance_id == utterance_id:
                self.state.active_utterance_id = None
            self._finalized.add(utterance_id)
            self._finalizing.pop(utterance_id, None)
            self._utterance_runtime.pop(utterance_id, None)
            logger.info(
                (
                    "final_commit skipped reason=low_energy utterance_id=%s "
                    "audio_seconds=%.3f rms=%.6f peak=%.6f voiced_frames=%s required_frames=%s"
                ),
                utterance_id,
                audio.shape[0] / 16_000,
                rms,
                peak,
                voiced_frames,
                required_frames,
            )
            return False
        async with self._finalize_lock:
            if utterance_id in self._finalized or utterance_id in self._finalizing:
                return False
            self._finalizing[utterance_id] = reason
            self.worker.finish_partials(utterance_id)
            if self.state.active_utterance_id == utterance_id:
                self.state.active_utterance_id = None
            if reset_segmenter:
                self.segmenter.reset()
            logger.info(
                "final_commit reason=%s utterance_id=%s audio_seconds=%.3f",
                reason,
                utterance_id,
                audio.shape[0] / 16_000,
            )
            self._schedule_ast("final", utterance_id, audio)
            return True

    def _schedule_ast(
        self,
        priority: str,
        utterance_id: int | None,
        audio: np.ndarray,
    ) -> None:
        if utterance_id is None:
            return
        if priority == "partial" and (
            utterance_id in self._finalized or utterance_id in self._finalizing
        ):
            return
        task = asyncio.create_task(
            self._run_ast(priority, utterance_id, audio.copy()),
            name=f"{priority}-ast-{utterance_id}",
        )
        self._jobs.add(task)
        task.add_done_callback(self._jobs.discard)

    async def _run_ast(self, priority: str, utterance_id: int, audio: np.ndarray) -> None:
        started_at = time.monotonic()
        try:
            if self._should_use_parakeet_asr():
                await self._run_parakeet_asr(priority, utterance_id, audio)
            else:
                await self._run_mlx_ast(priority, utterance_id, audio)
        finally:
            # Errors, empty decodes, and cancellation must not leave a commit pending.
            if priority == "final":
                self._finalizing.pop(utterance_id, None)
                self._utterance_runtime.pop(utterance_id, None)
            elapsed = time.monotonic() - started_at
            if elapsed >= 1.0:
                logger.warning(
                    "slow_caption stage=asr priority=%s utterance_id=%s elapsed_seconds=%.3f audio_seconds=%.3f",
                    priority, utterance_id, elapsed, audio.size / 16_000,
                )

    async def _run_mlx_ast(self, priority: str, utterance_id: int, audio: np.ndarray) -> None:
        try:
            result = await self.worker.submit_ast(
                priority="final" if priority == "final" else "partial",
                utterance_id=utterance_id,
                audio_f32_16k=audio,
                src=self.state.config.source_lang,
                tgt=self.state.config.target_lang,
                prior_context=self.state.prior_context[-2:]
                if DEFAULT_PRIOR_CONTEXT_ENABLED
                else [],
                custom_vocab=[] if priority == "partial" else self.state.config.custom_vocab,
                code_switching_enabled=self.state.config.code_switching_enabled,
                max_tokens=self._max_tokens_for_ast(priority, audio),
            )
        except asyncio.CancelledError:
            raise
        except InferenceTimeoutError as exc:
            if priority == "partial":
                logger.info("partial_inference dropped after timeout: %s", exc)
                return
            await self._send_error(f"Inference failed: {exc}")
            return
        except Exception as exc:
            await self._send_error(f"Inference failed: {exc}")
            return

        if result is None:
            return
        original, translation = result

        if priority == "partial":
            if utterance_id in self._finalized or utterance_id in self._finalizing:
                return
            runtime = self._utterance_runtime.setdefault(
                utterance_id,
                UtteranceRuntime(partials=deque(maxlen=self._stability_window())),
            )
            merged_original = original.strip()
            merged_translation = (
                translation.strip() if self._should_translate_final(merged_original) else merged_original
            )
            if (
                merged_original == runtime.latest_partial_original
                and merged_translation == runtime.latest_partial_translation
            ):
                return
            runtime.latest_partial_original = merged_original
            runtime.latest_partial_translation = merged_translation
            await self._send_and_broadcast(
                TranscriptMessage(
                    type="partial",
                    utterance_id=utterance_id,
                    original=merged_original,
                    translation=merged_translation,
                ).model_dump(exclude_none=True)
            )
            await self._maybe_commit_early(utterance_id, merged_original)
            return

        self._finalized.add(utterance_id)
        commit_reason = self._finalizing.pop(utterance_id, "silero_end")
        runtime = self._utterance_runtime.pop(utterance_id, None)
        self.state.prior_context.append((original, translation))
        self.state.prior_context = self.state.prior_context[-2:]
        self._remember_bilingual_context(original, translation)
        self.state.utterances_since_maintenance += 1
        await self._send_and_broadcast(
            TranscriptMessage(
                type="final",
                utterance_id=utterance_id,
                original=original,
                translation=translation,
                commit_reason=commit_reason,
                last_audio_frame_unix_seconds=(
                    runtime.last_audio_frame_unix_seconds if runtime is not None else None
                ),
            ).model_dump(exclude_none=True)
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

    def _should_use_parakeet_asr(self) -> bool:
        return (
            self.transcription_engine == "parakeet"
            and self.state.config.source_lang in {
                "English", "Spanish", "French", "German", "Italian", "Portuguese"
            }
            and not self.state.config.code_switching_enabled
        )

    async def _run_parakeet_asr(self, priority: str, utterance_id: int, audio: np.ndarray) -> None:
        if self.asr_worker is None:
            await self._send_error("Parakeet ASR is not configured; set TRANSCRIPTION_ENGINE=gemma to use Gemma AST fallback")
            return
        try:
            result = await self.asr_worker.submit_asr(
                priority="final" if priority == "final" else "partial",
                utterance_id=utterance_id,
                audio_f32_16k=audio,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._send_error(f"Parakeet ASR failed: {exc}")
            return

        if result is None:
            return

        original = result.text.strip() if isinstance(result, ASRResult) else str(result).strip()
        if not original:
            return

        if priority == "partial":
            if utterance_id in self._finalized or utterance_id in self._finalizing:
                return
            runtime = self._utterance_runtime.setdefault(
                utterance_id,
                UtteranceRuntime(partials=deque(maxlen=self._stability_window())),
            )
            translation = (
                runtime.latest_partial_translation
                if _source_extends_translation(original, runtime.latest_translation_original)
                else ""
            )
            if (not translation or _normalize_learned_text(original)
                    != _normalize_learned_text(runtime.latest_translation_original)):
                task = asyncio.create_task(
                    self._run_partial_translation_update(utterance_id, original),
                    name=f"partial-translation-{utterance_id}",
                )
                self._jobs.add(task)
                task.add_done_callback(self._jobs.discard)
            if utterance_id in self._finalized or utterance_id in self._finalizing:
                return
            runtime.latest_partial_original = original
            runtime.latest_partial_translation = translation
            await self._send_and_broadcast(
                TranscriptMessage(
                    type="partial",
                    utterance_id=utterance_id,
                    original=original,
                    translation=translation,
                ).model_dump(exclude_none=True)
            )
            await self._maybe_commit_early(utterance_id, original)
            return

        commit_reason = self._finalizing.pop(utterance_id, "silero_end")
        runtime = self._utterance_runtime.pop(utterance_id, None)
        correction_context = self.state.prior_context[-3:]
        last_audio_frame_unix_seconds = (
            runtime.last_audio_frame_unix_seconds if runtime is not None else None
        )
        translation = self._promotable_partial_translation(runtime, original) or (
            original if not self._should_translate_final(original) else ""
        )

        self._finalized.add(utterance_id)
        if translation:
            self._remember_final_context(original, translation)
        self.state.utterances_since_maintenance += 1
        await self._send_and_broadcast(
            TranscriptMessage(
                type="final",
                utterance_id=utterance_id,
                original=original,
                translation=translation,
                commit_reason=commit_reason,
                last_audio_frame_unix_seconds=last_audio_frame_unix_seconds,
            ).model_dump(exclude_none=True)
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
        if self._should_run_final_translation_refresh(original):
            task = asyncio.create_task(
                self._run_final_translation_refresh(
                    utterance_id,
                    original,
                    commit_reason,
                    correction_context,
                    translation,
                ),
                name=f"refresh-final-{utterance_id}",
            )
            self._jobs.add(task)
            task.add_done_callback(self._jobs.discard)
        await self._maybe_run_maintenance()

    async def _run_partial_translation_update(self, utterance_id: int, original: str) -> None:
        translation = await self._translate_partial(utterance_id, original)
        if translation is None:
            return
        await self._publish_translation_preview(utterance_id, original, translation, complete=True)

    async def _publish_translation_preview(
        self, utterance_id: int, original: str, translation: str, *, complete: bool = False,
    ) -> None:
        if not translation.strip():
            return
        runtime = self._utterance_runtime.get(utterance_id)
        if (runtime is None or utterance_id in self._finalizing
                or utterance_id in self._finalized):
            return
        current_original = runtime.latest_partial_original
        if not _source_extends_translation(current_original, original):
            return
        # Never let a late, shorter translation overwrite one covering more speech.
        if (runtime.latest_partial_translation
                and _source_extends_translation(runtime.latest_translation_original, original)
                and _normalize_learned_text(runtime.latest_translation_original)
                != _normalize_learned_text(original)):
            return
        # A fresh decode repeats its prefix; keep the existing words until it catches up.
        if (not complete and runtime.latest_partial_translation
                and runtime.latest_partial_translation.startswith(translation)
                and _source_extends_translation(original, runtime.latest_translation_original)):
            return
        runtime.translation_incomplete = not complete
        runtime.latest_translation_original = original
        runtime.latest_partial_translation = translation
        await self._send_and_broadcast(
            TranscriptMessage(
                type="partial",
                utterance_id=utterance_id,
                original=current_original,
                translation=translation,
            ).model_dump(exclude_none=True)
        )

    async def _run_final_translation_refresh(
        self,
        utterance_id: int,
        original: str,
        commit_reason: CommitReason,
        correction_context: list[tuple[str, str]],
        previous_translation: str,
    ) -> None:
        translation = await self._translate_final(utterance_id, original)
        if translation is not None and translation.strip() != previous_translation.strip():
            self._remember_final_context(original, translation, replacing_original=original)
            await self._send_and_broadcast(
                TranscriptMessage(
                    type="final",
                    utterance_id=utterance_id,
                    original=original,
                    translation=translation,
                    commit_reason=commit_reason,
                ).model_dump(exclude_none=True)
            )

        if not self._should_run_async_asr_correction(original):
            return

        corrected_original = await self._correct_final_asr(original, correction_context)
        if corrected_original is None:
            corrected_original = original
        corrected_original = corrected_original.strip() or original
        if _normalize_learned_text(corrected_original) == _normalize_learned_text(original):
            return

        corrected_translation = await self._translate_final(utterance_id, corrected_original)
        if corrected_translation is None:
            return
        self._remember_asr_correction(original, corrected_original)
        if (
            corrected_translation.strip() == (translation or previous_translation).strip()
        ):
            return
        self._remember_final_context(corrected_original, corrected_translation, replacing_original=original)
        await self._send_and_broadcast(
            TranscriptMessage(
                type="final",
                utterance_id=utterance_id,
                original=corrected_original,
                translation=corrected_translation,
                commit_reason=commit_reason,
            ).model_dump(exclude_none=True)
        )

    def _promotable_partial_translation(
        self,
        runtime: UtteranceRuntime | None,
        original: str,
    ) -> str | None:
        if runtime is None or runtime.translation_incomplete or not runtime.latest_partial_translation.strip():
            return None
        partial = runtime.latest_translation_original.strip()
        if not partial:
            return None
        normalized_partial = _normalize_learned_text(partial)
        normalized_original = _normalize_learned_text(original)
        if not normalized_partial or not normalized_original:
            return None
        if normalized_partial == normalized_original:
            return runtime.latest_partial_translation
        return None

    def _should_run_final_translation_refresh(self, original: str) -> bool:
        return self._should_translate_final(original) or self._should_run_async_asr_correction(original)

    def _should_run_async_asr_correction(self, original: str) -> bool:
        return (
            self.transcription_engine == "parakeet"
            and self.state.config.asr_correction_enabled
            and bool(original.strip())
        )

    def _remember_final_context(
        self,
        original: str,
        translation: str,
        *,
        replacing_original: str | None = None,
    ) -> None:
        if replacing_original is not None:
            for index, (prior_original, _) in enumerate(self.state.prior_context):
                if prior_original == replacing_original:
                    self.state.prior_context[index] = (original, translation)
                    break
            else:
                self.state.prior_context.append((original, translation))
        else:
            self.state.prior_context.append((original, translation))
        self.state.prior_context = self.state.prior_context[-2:]
        self._remember_bilingual_context(original, translation)

    def _should_translate_final(self, original: str) -> bool:
        return (
            bool(original.strip())
            and self.state.config.source_lang.strip().lower()
            != self.state.config.target_lang.strip().lower()
        )

    async def _translate_partial(self, utterance_id: int, original: str) -> str | None:
        if not self._should_translate_final(original):
            return original
        try:
            await self.worker.start()
            translation = await self.worker.submit_translate_text(
                original,
                self.state.config.source_lang,
                self.state.config.target_lang,
                priority="partial",
                utterance_id=utterance_id,
                on_progress=lambda text: self._publish_translation_preview(utterance_id, original, text),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._send_error(f"Partial translation failed: {exc}")
            return None
        return translation

    async def _translate_final(self, utterance_id: int, original: str) -> str | None:
        if not self._should_translate_final(original):
            return original
        try:
            await self.worker.start()
            translation = await self.worker.submit_translate_text(
                original,
                self.state.config.source_lang,
                self.state.config.target_lang,
                priority="final",
                utterance_id=utterance_id,
                bilingual_context=self._bilingual_context_for_translation(),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._send_error(f"Translation failed: {exc}")
            return None
        return translation

    async def _correct_final_asr(
        self,
        original: str,
        correction_context: list[tuple[str, str]],
    ) -> str | None:
        if self.transcription_engine != "parakeet":
            return original
        if not self.state.config.asr_correction_enabled:
            return original
        if not original.strip():
            return original
        try:
            await self.worker.start()
            corrected = await self.worker.submit_correct_asr_text(
                original,
                self.state.config.source_lang,
                custom_vocab=self.state.config.custom_vocab,
                prior_context=correction_context,
                learned_corrections=self._learned_asr_corrections_for_prompt(),
                code_switching_enabled=self.state.config.code_switching_enabled,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._send_error(f"ASR correction failed: {exc}")
            return original
        return corrected.strip() or original

    def _remember_asr_correction(self, heard: str, corrected: str) -> None:
        if not self.state.config.transcript_learning_enabled:
            return
        heard = " ".join(heard.strip().split())
        corrected = " ".join(corrected.strip().split())
        if not heard or not corrected:
            return
        if _normalize_learned_text(heard) == _normalize_learned_text(corrected):
            return
        if _looks_like_translation_pair(heard, corrected):
            return
        pair = (heard, corrected)
        if pair in self.state.asr_corrections:
            self.state.asr_corrections.remove(pair)
        self.state.asr_corrections.append(pair)
        self.state.asr_corrections = self.state.asr_corrections[
            -MAX_LEARNED_ASR_CORRECTIONS:
        ]

    def _learned_asr_corrections_for_prompt(self) -> list[tuple[str, str]]:
        if not self.state.config.transcript_learning_enabled:
            return []
        return self.state.asr_corrections[-8:]

    def _load_global_learning_profile(self) -> None:
        try:
            profile = json.loads(LEARNING_PROFILE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for item in profile.get("asr_corrections", []):
            if not isinstance(item, list | tuple) or len(item) != 2:
                continue
            heard, corrected = item
            if isinstance(heard, str) and isinstance(corrected, str):
                self._remember_asr_correction(heard, corrected)
        for item in profile.get("bilingual_context", []):
            if not isinstance(item, list | tuple) or len(item) != 2:
                continue
            original, translation = item
            if isinstance(original, str) and isinstance(translation, str):
                self._remember_bilingual_context(original, translation)

    def _write_global_learning_profile(self) -> None:
        LEARNING_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        profile = {
            "version": 1,
            "updated_at": datetime.now().astimezone().isoformat(),
            "asr_corrections": self.state.asr_corrections[
                -MAX_LEARNED_ASR_CORRECTIONS:
            ],
            "bilingual_context": self.state.bilingual_context[-32:],
        }
        LEARNING_PROFILE_PATH.write_text(
            json.dumps(profile, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _remember_bilingual_context(self, original: str, translation: str) -> None:
        if not self.state.config.bilingual_context_enabled:
            return
        original = " ".join(original.strip().split())
        translation = " ".join(translation.strip().split())
        if not original or not translation or original == translation:
            return
        pair = (original, translation)
        if pair in self.state.bilingual_context:
            self.state.bilingual_context.remove(pair)
        self.state.bilingual_context.append(pair)
        self.state.bilingual_context = self.state.bilingual_context[-8:]

    def _bilingual_context_for_translation(self) -> list[tuple[str, str]]:
        if not self.state.config.bilingual_context_enabled:
            return []
        return self.state.bilingual_context[-5:]

    def _partial_inference_is_busy_or_backlogged(self) -> bool:
        if self._should_use_parakeet_asr() and self.asr_worker is not None:
            return self.asr_worker.is_busy_or_backlogged
        return self.worker.is_busy_or_backlogged

    def _schedule_worker_warmup(self) -> None:
        if not self._session_uses_mlx_worker():
            return
        task = asyncio.create_task(self._warm_mlx_worker(), name="mlx-worker-warmup")
        self._jobs.add(task)
        task.add_done_callback(self._jobs.discard)

    def _session_uses_mlx_worker(self) -> bool:
        if not self._should_use_parakeet_asr():
            return True
        if self.state.config.asr_correction_enabled:
            return True
        return (
            self.state.config.source_lang.strip().lower()
            != self.state.config.target_lang.strip().lower()
        )

    async def _warm_mlx_worker(self) -> None:
        try:
            await self.worker.start()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._send_error(f"Model warmup failed: {exc}")

    async def _maybe_commit_early(self, utterance_id: int, original: str) -> None:
        if not self._early_commit_enabled():
            return
        if self.state.active_utterance_id != utterance_id:
            return
        audio = self.segmenter.current_audio()
        if audio.shape[0] / 16_000 < self._early_commit_min_seconds():
            return
        if self._early_commit_punctuation() and _source_text_ends_sentence(original):
            await self._commit_utterance(utterance_id, audio, reason="punctuation", reset_segmenter=True)
            return
        if self._early_commit_stability() and self._source_text_is_stable(utterance_id, original):
            await self._commit_utterance(utterance_id, audio, reason="stability", reset_segmenter=True)

    def _source_text_is_stable(self, utterance_id: int, original: str) -> bool:
        normalized = _normalize_stability_text(original)
        if not normalized:
            return False
        runtime = self._utterance_runtime.setdefault(
            utterance_id,
            UtteranceRuntime(partials=deque(maxlen=self._stability_window())),
        )
        if runtime.partials.maxlen != self._stability_window():
            runtime.partials = deque(runtime.partials, maxlen=self._stability_window())
        runtime.partials.append(normalized)
        return (
            len(runtime.partials) >= self._stability_window()
            and len(set(runtime.partials)) == 1
        )

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
            ).model_dump(exclude_none=True)
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
        partial_interval_seconds = config.partial_interval_seconds
        if partial_interval_seconds is not None:
            partial_interval_seconds = _bounded_partial_interval_seconds(
                float(partial_interval_seconds),
                source="config.partial_interval_seconds",
            )
        self.state.config = config.model_copy(
            update={
                "apply_target": "immediate",
                "partial_interval_seconds": partial_interval_seconds,
            }
        )
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
        self.state.bilingual_context = [
            (item[0], item[1]) for item in snapshot.get("bilingual_context", [])
        ]
        self.state.asr_corrections = [
            (item[0], item[1]) for item in snapshot.get("asr_corrections", [])
        ]
        self._finalized = set(snapshot.get("finalized_ids", []))
        self._finalizing.clear()
        self._utterance_runtime.clear()
        self.segmenter.reset()

    def export_session_snapshot(self) -> dict:
        return {
            "config": self.state.config.model_dump(),
            "running": self.state.running,
            "utterance_id": self.state.utterance_id,
            "prior_context": self.state.prior_context,
            "bilingual_context": self.state.bilingual_context,
            "asr_corrections": self.state.asr_corrections,
            "finalized_ids": sorted(self._finalized),
        }

    def _build_segmenter(self, config: ConfigMessage) -> RMSGate:
        rms_threshold = config.rms_threshold or float(os.getenv("RMS_THRESHOLD", "0.01"))
        silero_threshold = min(max(config.silero_threshold or 0.5, 0.1), 0.95)
        speech_pad_ms = min(max(config.speech_pad_ms or 300, 0), 2000)
        min_silence_ms = min(max(config.min_silence_ms or 300, 100), 5000)
        max_utterance_seconds = min(max(config.max_utterance_seconds or 12.0, 5.0), 29.0)
        return make_segmenter(
            config.segmenter,
            rms_threshold,
            silero_threshold=silero_threshold,
            speech_pad_ms=speech_pad_ms,
            min_silence_ms=min_silence_ms,
            max_utterance_s=max_utterance_seconds,
        )

    def _max_tokens_for_ast(self, priority: str, audio: np.ndarray) -> int:
        duration_seconds = audio.shape[0] / 16_000
        if duration_seconds <= 8:
            return 80
        if duration_seconds <= 15:
            return 128
        return 192

    def _partial_interval_seconds(self) -> float:
        return self.state.config.partial_interval_seconds or DEFAULT_PARTIAL_INTERVAL_SECONDS

    def _active_utterance_runtime(self) -> UtteranceRuntime | None:
        if self.state.active_utterance_id is None:
            return None
        return self._utterance_runtime.get(self.state.active_utterance_id)

    def _active_utterance_has_new_speech_for_partial(self) -> bool:
        runtime = self._active_utterance_runtime()
        if runtime is None:
            return False

        now = time.monotonic()
        if (
            runtime.last_partial_wall_seconds > 0
            and now - runtime.last_partial_wall_seconds < self._partial_interval_seconds()
        ):
            return False

        voiced_samples = runtime.voiced_audio_samples
        if voiced_samples <= 0:
            return False

        if runtime.last_partial_audio_samples <= 0:
            return voiced_samples / 16_000 >= DEFAULT_PARTIAL_MIN_AUDIO_SECONDS

        new_speech_seconds = (
            voiced_samples - runtime.last_partial_audio_samples
        ) / 16_000
        return new_speech_seconds >= DEFAULT_PARTIAL_MIN_NEW_SPEECH_SECONDS

    def _early_commit_enabled(self) -> bool:
        if self.state.config.early_commit_enabled is not None:
            return self.state.config.early_commit_enabled
        return DEFAULT_EARLY_COMMIT_ENABLED

    def _early_commit_min_seconds(self) -> float:
        if self.state.config.early_commit_min_seconds is not None:
            return max(0.0, self.state.config.early_commit_min_seconds)
        return DEFAULT_EARLY_COMMIT_MIN_SECONDS

    def _early_commit_punctuation(self) -> bool:
        if self.state.config.early_commit_punctuation is not None:
            return self.state.config.early_commit_punctuation
        return DEFAULT_EARLY_COMMIT_PUNCTUATION

    def _early_commit_stability(self) -> bool:
        if self.state.config.early_commit_stability is not None:
            return self.state.config.early_commit_stability
        return DEFAULT_EARLY_COMMIT_STABILITY

    def _stability_window(self) -> int:
        if self.state.config.stability_window is not None:
            return max(2, self.state.config.stability_window)
        return DEFAULT_STABILITY_WINDOW

    def _begin_archive(self) -> None:
        if self._archive_dir is not None:
            return
        self._load_global_learning_profile()
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
        if payload.get("commit_reason") is not None:
            utterance["commit_reason"] = payload["commit_reason"]
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
        self._load_global_learning_profile()
        self._learn_asr_corrections_from_archive_events(events)
        self._learn_bilingual_context_from_archive_events(events)
        self._write_global_learning_profile()
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
            "bilingual_context": self.state.bilingual_context,
            "asr_corrections": self.state.asr_corrections,
        }
        await asyncio.to_thread(
            self._write_archive_files,
            archive_dir,
            utterances,
            events,
            meta,
        )

    async def _resume_archive_from_disk(self) -> None:
        archive_dir = await asyncio.to_thread(self._find_latest_archive_dir, self.session_id)
        if archive_dir is None:
            self._begin_archive()
            return

        self._archive_dir = archive_dir
        self._archive_events = self._load_archive_events(archive_dir)
        self._archive_utterances = self._utterances_from_events(self._archive_events)
        meta = self._load_archive_meta(archive_dir)
        self._load_global_learning_profile()
        self.state.bilingual_context = [
            (item[0], item[1]) for item in meta.get("bilingual_context", [])
        ]
        self.state.asr_corrections = [
            (item[0], item[1]) for item in meta.get("asr_corrections", [])
        ]
        started_at = meta.get("started_at")
        try:
            self._archive_started_at = datetime.fromisoformat(started_at)
        except (TypeError, ValueError):
            self._archive_started_at = datetime.now().astimezone()
        elapsed_seconds = max(
            [float(event.get("timestamp_seconds", 0.0)) for event in self._archive_events],
            default=0.0,
        )
        self._archive_started_at_monotonic = time.monotonic() - elapsed_seconds
        if self._archive_utterances:
            self.state.utterance_id = max(self.state.utterance_id, max(self._archive_utterances))
            self._finalized = {
                utterance["utterance_id"]
                for utterance in self._archive_utterances.values()
                if utterance.get("state") in {"final", "polished"}
            }
        if self._archive_autosave_task is None:
            self._archive_autosave_task = asyncio.create_task(
                self._run_archive_autosave(),
                name=f"archive-autosave-{self.session_id}",
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

    def _find_latest_archive_dir(self, session_id: str) -> Path | None:
        if not ARCHIVE_ROOT.exists():
            return None
        matches: list[Path] = []
        for meta_path in ARCHIVE_ROOT.glob("*/meta.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if meta.get("session_id") == session_id:
                matches.append(meta_path.parent)
        if not matches:
            return None
        return max(matches, key=lambda path: path.stat().st_mtime)

    def _load_archive_events(self, archive_dir: Path) -> list[dict]:
        try:
            raw_events = json.loads((archive_dir / "transcript.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        events: list[dict] = []
        seen_finals: set[int] = set()
        for event in raw_events:
            payload = event.get("payload", {})
            if payload.get("type") == "final":
                utterance_id = int(payload.get("utterance_id", 0))
                if utterance_id in seen_finals:
                    continue
                seen_finals.add(utterance_id)
            events.append(event)
        return events

    def _load_archive_meta(self, archive_dir: Path) -> dict:
        try:
            return json.loads((archive_dir / "meta.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _learn_asr_corrections_from_archive_events(self, events: list[dict]) -> None:
        if not self.state.config.transcript_learning_enabled:
            return
        first_final_by_id: dict[int, str] = {}
        latest_final_by_id: dict[int, str] = {}
        for event in events:
            payload = event.get("payload", {})
            if payload.get("type") != "final":
                continue
            utterance_id = payload.get("utterance_id")
            original = payload.get("original")
            if not isinstance(utterance_id, int) or not isinstance(original, str):
                continue
            first_final_by_id.setdefault(utterance_id, original)
            latest_final_by_id[utterance_id] = original
        for utterance_id, heard in first_final_by_id.items():
            corrected = latest_final_by_id.get(utterance_id, "")
            self._remember_asr_correction(heard, corrected)

    def _learn_bilingual_context_from_archive_events(self, events: list[dict]) -> None:
        if not self.state.config.bilingual_context_enabled:
            return
        latest_final_by_id: dict[int, str] = {}
        for event in events:
            payload = event.get("payload", {})
            if payload.get("type") != "final":
                continue
            utterance_id = payload.get("utterance_id")
            original = payload.get("original")
            if isinstance(utterance_id, int) and isinstance(original, str):
                latest_final_by_id[utterance_id] = original

        finals = [
            (utterance_id, text)
            for utterance_id, text in sorted(latest_final_by_id.items())
            if text.strip()
        ]
        for (_, first_text), (_, second_text) in zip(finals, finals[1:]):
            first_language = _language_hint(first_text)
            second_language = _language_hint(second_text)
            if first_language == second_language or not first_language or not second_language:
                continue
            if first_language == self.state.config.source_lang:
                self._remember_bilingual_context(first_text, second_text)
            elif second_language == self.state.config.source_lang:
                self._remember_bilingual_context(second_text, first_text)

    def _utterances_from_events(self, events: list[dict]) -> dict[int, dict]:
        utterances: dict[int, dict] = {}
        for event in events:
            elapsed_seconds = float(event.get("timestamp_seconds", 0.0))
            payload = event.get("payload", {})
            payload_type = payload.get("type")
            utterance_id = payload.get("utterance_id")
            if not isinstance(utterance_id, int):
                continue
            if payload_type == "speech_start":
                utterances.setdefault(
                    utterance_id,
                    {
                        "utterance_id": utterance_id,
                        "started_at": elapsed_seconds,
                        "ended_at": elapsed_seconds,
                        "original": "",
                        "translation": "",
                        "state": "partial",
                    },
                )
                continue
            if payload_type not in {"partial", "final", "polished"}:
                continue
            utterance = utterances.setdefault(
                utterance_id,
                {
                    "utterance_id": utterance_id,
                    "started_at": elapsed_seconds,
                    "ended_at": elapsed_seconds,
                    "original": "",
                    "translation": "",
                    "state": payload_type,
                },
            )
            utterance["original"] = payload.get("original", "")
            utterance["translation"] = payload.get("translation", "")
            utterance["state"] = payload_type
            if payload.get("commit_reason") is not None:
                utterance["commit_reason"] = payload["commit_reason"]
            if payload_type != "partial":
                utterance["ended_at"] = elapsed_seconds
        return utterances

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
