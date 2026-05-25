from __future__ import annotations

import asyncio
import itertools
import multiprocessing as mp
import os
import queue
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Literal

import numpy as np
import soundfile as sf
from dotenv import load_dotenv
from mlx.core import bfloat16

from mlx_worker import TEMP_WAV_ROOT, _safe_unlink, sweep_stale_temp_wavs

load_dotenv()

PARAKEET_MODEL = os.getenv("PARAKEET_MODEL", "mlx-community/parakeet-tdt-0.6b-v3")
PARAKEET_WORKER_START_TIMEOUT_SECONDS = max(
    10.0, float(os.getenv("PARAKEET_WORKER_START_TIMEOUT_SECONDS", "240"))
)
PARAKEET_PARTIAL_TIMEOUT_SECONDS = max(
    1.0, float(os.getenv("PARAKEET_PARTIAL_TIMEOUT_SECONDS", "8"))
)
PARAKEET_FINAL_TIMEOUT_SECONDS = max(
    1.0, float(os.getenv("PARAKEET_FINAL_TIMEOUT_SECONDS", "20"))
)


@dataclass(slots=True, frozen=True)
class ASRResult:
    text: str
    timestamps: dict | None = None


@dataclass(slots=True, frozen=True)
class ParakeetStatusEvent:
    state: Literal["starting", "ready", "recovering", "failed"]
    message: str


@dataclass(order=True)
class _QueuedASRJob:
    priority: int
    sequence: int
    future: asyncio.Future = field(compare=False)
    payload: dict = field(compare=False)


class ParakeetASR:
    def __init__(self, temp_wav_root: Path | None = None) -> None:
        from parakeet_mlx import from_pretrained

        self._temp_wav_root = temp_wav_root or TEMP_WAV_ROOT
        self._temp_wav_root.mkdir(parents=True, exist_ok=True)
        sweep_stale_temp_wavs(self._temp_wav_root, 0)
        self.model = from_pretrained(PARAKEET_MODEL)

    def transcribe(self, audio_f32_16k: np.ndarray) -> ASRResult:
        audio_f32_16k = np.asarray(audio_f32_16k, dtype=np.float32).reshape(-1)
        fd, wav_path_raw = tempfile.mkstemp(
            suffix=".wav",
            prefix="parakeet-",
            dir=self._temp_wav_root,
        )
        os.close(fd)
        wav_path = Path(wav_path_raw)
        try:
            sf.write(wav_path, audio_f32_16k, 16_000, subtype="PCM_16")
            first = self.model.transcribe(
                wav_path,
                dtype=bfloat16,
                chunk_duration=None,
            )
            text = getattr(first, "text", None)
            timestamps = getattr(first, "timestamp", None)
            return ASRResult(
                text=(text if isinstance(text, str) else str(first)).strip(),
                timestamps=timestamps if isinstance(timestamps, dict) else None,
            )
        finally:
            _safe_unlink(wav_path)


class ParakeetASRService:
    """Async facade around one synchronous Parakeet ASR worker process."""

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[_QueuedASRJob] = asyncio.PriorityQueue()
        self._sequence = itertools.count()
        self._runner: asyncio.Task | None = None
        self._closed = asyncio.Event()
        self._temp_wav_root = TEMP_WAV_ROOT
        self._process: mp.Process | None = None
        self._request_queue: mp.Queue | None = None
        self._response_queue: mp.Queue | None = None
        self._queued_partial_jobs: dict[int, _QueuedASRJob] = {}
        self._final_utterance_ids: set[int] = set()
        self._mp_context = mp.get_context("spawn")
        self._status = ParakeetStatusEvent(
            state="starting",
            message=f"Loading Parakeet ASR model {PARAKEET_MODEL}",
        )
        self._status_listeners: set[Callable[[ParakeetStatusEvent], Awaitable[None]]] = set()

    async def start(self) -> None:
        self._temp_wav_root.mkdir(parents=True, exist_ok=True)
        try:
            await self._start_worker_process()
        except Exception as exc:
            await self._emit_status(
                ParakeetStatusEvent(
                    state="failed",
                    message=(
                        "Parakeet ASR failed to start. Install backend extras with "
                        "`uv sync --extra parakeet` and verify parakeet-mlx: "
                        f"{exc}"
                    ),
                )
            )
            return
        self._runner = asyncio.create_task(self._run(), name="parakeet-asr-queue")

    async def stop(self) -> None:
        self._closed.set()
        if self._runner:
            self._runner.cancel()
            try:
                await self._runner
            except asyncio.CancelledError:
                pass
        await self._stop_worker_process(force=True)

    async def submit_asr(
        self,
        *,
        priority: Literal["partial", "final"],
        utterance_id: int | None,
        audio_f32_16k: np.ndarray,
    ) -> ASRResult | None:
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        job = _QueuedASRJob(
            priority=0 if priority == "final" else 10,
            sequence=next(self._sequence),
            future=future,
            payload={
                "priority": priority,
                "utterance_id": utterance_id,
                "audio_f32_16k": audio_f32_16k,
            },
        )
        if utterance_id is not None:
            previous = self._queued_partial_jobs.get(utterance_id)
            if priority == "partial":
                if utterance_id in self._final_utterance_ids:
                    future.set_result(None)
                    return await future
                if previous is not None and not previous.future.done():
                    previous.future.set_result(None)
                self._queued_partial_jobs[utterance_id] = job
            else:
                self._final_utterance_ids.add(utterance_id)
                if previous is not None:
                    self._queued_partial_jobs.pop(utterance_id, None)
                    if not previous.future.done():
                        previous.future.set_result(None)
        await self._queue.put(job)
        return await future

    async def add_status_listener(
        self, listener: Callable[[ParakeetStatusEvent], Awaitable[None]]
    ) -> None:
        self._status_listeners.add(listener)
        await listener(self._status)

    def remove_status_listener(
        self, listener: Callable[[ParakeetStatusEvent], Awaitable[None]]
    ) -> None:
        self._status_listeners.discard(listener)

    @property
    def is_busy_or_backlogged(self) -> bool:
        return self._queue.qsize() > 0

    @property
    def status(self) -> ParakeetStatusEvent:
        return self._status

    async def _run(self) -> None:
        while not self._closed.is_set():
            job = await self._queue.get()
            try:
                if job.future.done():
                    continue
                if self._should_skip_job(job):
                    if not job.future.done():
                        job.future.set_result(None)
                    continue
                result = await self._dispatch_job(job)
                if not job.future.cancelled():
                    job.future.set_result(result)
            except Exception as exc:
                if not job.future.cancelled():
                    job.future.set_exception(exc)
            finally:
                self._queue.task_done()

    def _should_skip_job(self, job: _QueuedASRJob) -> bool:
        if job.payload.get("priority") != "partial":
            return False
        utterance_id = job.payload.get("utterance_id")
        if not isinstance(utterance_id, int):
            return False
        if utterance_id in self._final_utterance_ids:
            return True
        queued_job = self._queued_partial_jobs.get(utterance_id)
        if queued_job is None:
            return False
        if queued_job.sequence != job.sequence:
            return True
        self._queued_partial_jobs.pop(utterance_id, None)
        return False

    async def _dispatch_job(self, job: _QueuedASRJob) -> ASRResult:
        if self._request_queue is None or self._response_queue is None or self._process is None:
            raise RuntimeError("Parakeet ASR worker process is not started")
        if not self._process.is_alive():
            raise RuntimeError("Parakeet ASR worker process exited unexpectedly")

        timeout_seconds = (
            PARAKEET_FINAL_TIMEOUT_SECONDS
            if job.payload.get("priority") == "final"
            else PARAKEET_PARTIAL_TIMEOUT_SECONDS
        )
        await asyncio.to_thread(
            self._request_queue.put,
            {
                "job_id": job.sequence,
                "payload": {
                    "audio_f32_16k": job.payload["audio_f32_16k"],
                },
            },
        )
        deadline = time.monotonic() + timeout_seconds
        while True:
            if not self._process.is_alive():
                raise RuntimeError("Parakeet ASR worker process exited unexpectedly")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Parakeet ASR timed out after {timeout_seconds:.1f}s")
            try:
                response = await asyncio.to_thread(
                    self._response_queue.get,
                    True,
                    min(0.25, remaining),
                )
            except queue.Empty:
                continue
            if response.get("type") == "result" and response.get("job_id") == job.sequence:
                result = response["result"]
                return ASRResult(
                    text=str(result.get("text", "")).strip(),
                    timestamps=result.get("timestamps"),
                )
            if response.get("type") == "fatal" and response.get("job_id") == job.sequence:
                raise RuntimeError(response.get("error", "Unknown Parakeet ASR error"))
            raise RuntimeError(f"Unexpected Parakeet worker response: {response!r}")

    async def _start_worker_process(self) -> None:
        await self._emit_status(
            ParakeetStatusEvent(state="starting", message=f"Loading Parakeet ASR model {PARAKEET_MODEL}")
        )
        request_queue: mp.Queue = self._mp_context.Queue()
        response_queue: mp.Queue = self._mp_context.Queue()
        process = self._mp_context.Process(
            target=_parakeet_process_main,
            args=(request_queue, response_queue, str(self._temp_wav_root)),
            daemon=True,
        )
        process.start()
        self._process = process
        self._request_queue = request_queue
        self._response_queue = response_queue
        try:
            response = await asyncio.to_thread(
                response_queue.get,
                True,
                PARAKEET_WORKER_START_TIMEOUT_SECONDS,
            )
        except queue.Empty as exc:
            await self._stop_worker_process(force=True)
            raise RuntimeError(
                f"Timed out loading Parakeet after {PARAKEET_WORKER_START_TIMEOUT_SECONDS:.1f}s"
            ) from exc

        if response.get("type") != "ready":
            await self._stop_worker_process(force=True)
            raise RuntimeError(response.get("error", "Parakeet ASR failed to report ready"))
        await self._emit_status(
            ParakeetStatusEvent(state="ready", message=f"Parakeet ASR model ready: {PARAKEET_MODEL}")
        )

    async def _stop_worker_process(self, force: bool) -> None:
        process = self._process
        request_queue = self._request_queue
        response_queue = self._response_queue
        self._process = None
        self._request_queue = None
        self._response_queue = None
        if process is None:
            return
        if request_queue is not None and not force:
            try:
                await asyncio.to_thread(request_queue.put, None)
            except Exception:
                pass
        await asyncio.to_thread(process.join, 1.0)
        if process.is_alive():
            process.terminate()
            await asyncio.to_thread(process.join, 2.0)
        if process.is_alive():
            process.kill()
            await asyncio.to_thread(process.join, 2.0)
        for ipc_queue in (request_queue, response_queue):
            if ipc_queue is None:
                continue
            try:
                ipc_queue.close()
                ipc_queue.join_thread()
            except Exception:
                pass

    async def _emit_status(self, event: ParakeetStatusEvent) -> None:
        self._status = event
        if not self._status_listeners:
            return
        await asyncio.gather(
            *(listener(event) for listener in list(self._status_listeners)),
            return_exceptions=True,
        )


def _parakeet_process_main(
    request_queue: mp.Queue,
    response_queue: mp.Queue,
    temp_wav_root: str,
) -> None:
    try:
        worker = ParakeetASR(Path(temp_wav_root))
    except Exception:
        response_queue.put({"type": "fatal", "error": traceback.format_exc()})
        return

    response_queue.put({"type": "ready"})

    while True:
        try:
            request = request_queue.get()
        except (EOFError, KeyboardInterrupt):
            return
        if request is None:
            return
        job_id = request["job_id"]
        try:
            result = worker.transcribe(**request["payload"])
        except Exception:
            response_queue.put(
                {
                    "type": "fatal",
                    "job_id": job_id,
                    "error": traceback.format_exc(),
                }
            )
            return
        response_queue.put(
            {
                "type": "result",
                "job_id": job_id,
                "result": {"text": result.text, "timestamps": result.timestamps},
            }
        )
