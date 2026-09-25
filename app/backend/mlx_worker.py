from __future__ import annotations

import asyncio
import itertools
import logging
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

load_dotenv()

logger = logging.getLogger("uvicorn.error")

MODEL_PATH = os.getenv("MODEL_PATH", "mlx-community/gemma-4-e4b-it-8bit")
TEMP_WAV_ROOT = Path(
    os.getenv("LIVETR3_TEMP_WAV_ROOT", os.path.join(tempfile.gettempdir(), "livetr3-mlx"))
)
TEMP_WAV_STALE_SECONDS = max(60, int(os.getenv("TEMP_WAV_STALE_SECONDS", "1800")))
TEMP_WAV_SWEEP_INTERVAL_SECONDS = max(
    30, int(os.getenv("TEMP_WAV_SWEEP_INTERVAL_SECONDS", "300"))
)
PARTIAL_TIMEOUT_SECONDS = max(1.0, float(os.getenv("PARTIAL_TIMEOUT_SECONDS", "8")))
FINAL_TIMEOUT_SECONDS = max(1.0, float(os.getenv("FINAL_TIMEOUT_SECONDS", "15")))
POLISH_TIMEOUT_SECONDS = max(1.0, float(os.getenv("POLISH_TIMEOUT_SECONDS", "10")))
TRANSLATE_TIMEOUT_SECONDS = max(1.0, float(os.getenv("TRANSLATE_TIMEOUT_SECONDS", "12")))
MAINTENANCE_TIMEOUT_SECONDS = max(1.0, float(os.getenv("MAINTENANCE_TIMEOUT_SECONDS", "5")))
MLX_WORKER_START_TIMEOUT_SECONDS = max(
    10.0, float(os.getenv("MLX_WORKER_START_TIMEOUT_SECONDS", "180"))
)
MLX_WORKER_RECOVERY_BACKOFF_SECONDS = max(
    0.0, float(os.getenv("MLX_WORKER_RECOVERY_BACKOFF_SECONDS", "2"))
)

AST_PROMPT = (
    "Transcribe the following speech segment in {src}, "
    "then translate it into {tgt}. When formatting the answer, "
    "first output the transcription in {src}, then one newline, "
    "then output the string '{tgt}: ', then the translation in {tgt}."
)

POLISH_PROMPT = (
    "You will receive a rough transcription. Remove filler words "
    "(um, uh, er, you know, like), fix punctuation, fix capitalization, "
    "and keep the exact meaning and wording. Return ONLY the cleaned text "
    "with no preamble.\n\nTranscription: {text}"
)

TRANSLATE_PROMPT = (
    "Translate the following text from {src} to {tgt}. Return ONLY the translation "
    "with no preamble.\n\nText: {text}"
)

CONTEXTUAL_TRANSLATE_PROMPT = (
    "Translate the following text from {src} to {tgt}. Return ONLY the translation "
    "with no preamble.\n\n"
    "Use these recent bilingual reference pairs only to preserve names, recurring "
    "church terms, scripture wording, tone, and phrase choices when they clearly "
    "apply. Do not copy a reference pair unless it matches the text being translated.\n\n"
    "{context}\n\nText: {text}"
)

ASR_CORRECTION_PROMPT = (
    "You will receive a finalized ASR transcript in {src}. Correct likely speech "
    "recognition errors, punctuation, capitalization, and spacing. Preserve the "
    "speaker's wording and meaning. Do not summarize, translate, add commentary, "
    "or censor. Never translate the transcript; if the transcript is actually in "
    "another language, keep that language and only fix recognition mistakes. "
    "Use the optional context only when it plausibly matches what was "
    "said. Return ONLY the corrected {src} transcript.\n\n{context}Transcript: {text}"
)


class MLXWorker:
    def __init__(self, temp_wav_root: Path | None = None) -> None:
        from mlx_vlm import load

        self._temp_wav_root = temp_wav_root or TEMP_WAV_ROOT / f"gemma-{os.getpid()}"
        self._temp_wav_root.mkdir(parents=True, exist_ok=True)
        sweep_stale_temp_wavs(self._temp_wav_root, TEMP_WAV_STALE_SECONDS)
        self.model, self.processor = load(MODEL_PATH)
        self.config = self.model.config
        self._warmup()

    def _warmup(self) -> None:
        silent = np.zeros(16_000, dtype=np.float32)
        self.ast(silent, "English", "Spanish", prior_context=[], max_tokens=8)

    def ast(
        self,
        audio_f32_16k: np.ndarray,
        src: str,
        tgt: str,
        prior_context: list[tuple[str, str]],
        custom_vocab: list[str] | None = None,
        code_switching_enabled: bool = False,
        max_tokens: int = 256,
    ) -> tuple[str, str]:
        from mlx_vlm import generate
        from mlx_vlm.prompt_utils import apply_chat_template

        audio_f32_16k = np.asarray(audio_f32_16k, dtype=np.float32).reshape(-1)
        if audio_f32_16k.shape[0] > 25 * 16_000:
            audio_f32_16k = audio_f32_16k[: 25 * 16_000]

        fd, wav_path_raw = tempfile.mkstemp(
            suffix=".wav",
            prefix="ast-",
            dir=self._temp_wav_root,
        )
        os.close(fd)
        wav_path = Path(wav_path_raw)

        try:
            sf.write(wav_path, audio_f32_16k, 16_000, subtype="FLOAT")
            prompt_text = AST_PROMPT.format(src=src, tgt=tgt)
            if custom_vocab:
                prompt_text = (
                    f"The speaker frequently uses these terms: {', '.join(custom_vocab)}. "
                    "Prefer them when acoustically ambiguous.\n\n"
                    + prompt_text
                )
            if code_switching_enabled:
                prompt_text = (
                    f"Speaker may code-switch between {src} and {tgt}; "
                    f"transcribe in the spoken language, translate to {tgt}.\n\n"
                    + prompt_text
                )
            if prior_context:
                ctx = "\n".join(f"Previous: {o} / {t}" for o, t in prior_context[-2:])
                prompt_text = ctx + "\n\n" + prompt_text

            # mlx-vlm expands num_audios before the prompt text; do not hand-roll templates.
            formatted = apply_chat_template(
                self.processor,
                self.config,
                prompt_text,
                num_audios=1,
            )
            out = _generation_text(
                generate(
                    self.model,
                    self.processor,
                    formatted,
                    audio=[str(wav_path)],
                    max_tokens=max_tokens,
                    temperature=0.0,
                    top_p=0.95,
                    top_k=64,
                    verbose=False,
                )
            )
            marker = f"\n{tgt}: "
            if marker in out:
                original, translation = out.split(marker, 1)
            else:
                original, translation = out, ""
            return original.strip(), translation.strip()
        finally:
            _safe_unlink(wav_path)

    def polish(self, text: str, max_tokens: int = 256) -> str:
        from mlx_vlm import generate
        from mlx_vlm.prompt_utils import apply_chat_template

        prompt = POLISH_PROMPT.format(text=text)
        formatted = apply_chat_template(self.processor, self.config, prompt, num_audios=0)
        out = _generation_text(
            generate(
                self.model,
                self.processor,
                formatted,
                max_tokens=max_tokens,
                temperature=0.0,
                top_p=0.95,
                top_k=64,
                verbose=False,
            )
        )
        return out.strip()

    def translate_text(
        self,
        text: str,
        src: str,
        tgt: str,
        max_tokens: int = 256,
        bilingual_context: list[tuple[str, str]] | None = None,
        cancelled: Callable[[], bool] | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> str | None:
        from mlx_vlm import generate
        from mlx_vlm.prompt_utils import apply_chat_template

        context = _format_bilingual_context(bilingual_context or [])
        if context:
            prompt = CONTEXTUAL_TRANSLATE_PROMPT.format(
                text=text,
                src=src,
                tgt=tgt,
                context=context,
            )
        else:
            prompt = TRANSLATE_PROMPT.format(text=text, src=src, tgt=tgt)
        formatted = apply_chat_template(self.processor, self.config, prompt, num_audios=0)
        if cancelled is not None:
            from mlx_vlm import stream_generate

            if cancelled():
                return None
            stream = stream_generate(
                self.model, self.processor, formatted, max_tokens=max_tokens,
                temperature=0.0, top_p=0.95, top_k=64,
            )
            pieces: list[str] = []
            try:
                for response in stream:
                    if cancelled():
                        return None
                    pieces.append(response.text)
                    if on_progress is not None:
                        on_progress("".join(pieces).strip())
            finally:
                stream.close()
            return "".join(pieces).strip()
        out = _generation_text(
            generate(
                self.model,
                self.processor,
                formatted,
                max_tokens=max_tokens,
                temperature=0.0,
                top_p=0.95,
                top_k=64,
                verbose=False,
            )
        )
        return out.strip()

    def correct_asr_text(
        self,
        text: str,
        src: str,
        custom_vocab: list[str] | None = None,
        prior_context: list[tuple[str, str]] | None = None,
        learned_corrections: list[tuple[str, str]] | None = None,
        code_switching_enabled: bool = False,
        max_tokens: int = 192,
    ) -> str:
        from mlx_vlm import generate
        from mlx_vlm.prompt_utils import apply_chat_template

        context_parts: list[str] = []
        if custom_vocab:
            context_parts.append(
                "Known names, terms, or phrases: "
                + ", ".join(item.strip() for item in custom_vocab if item.strip())
                + "."
            )
        if prior_context:
            recent = "\n".join(
                f"- {original}" for original, _ in prior_context[-3:] if original.strip()
            )
            if recent:
                context_parts.append("Recent transcript context:\n" + recent)
        learned = _format_learned_corrections(learned_corrections or [])
        if learned:
            context_parts.append(
                "Previously corrected ASR mistakes. If a similar mistake appears, "
                "prefer the corrected wording when it plausibly matches the audio:\n"
                + learned
            )
        if code_switching_enabled:
            context_parts.append(
                f"The speaker may code-switch while primarily speaking {src}."
            )
        context = "\n\n".join(context_parts)
        if context:
            context += "\n\n"
        prompt = ASR_CORRECTION_PROMPT.format(text=text, src=src, context=context)
        formatted = apply_chat_template(self.processor, self.config, prompt, num_audios=0)
        out = _generation_text(
            generate(
                self.model,
                self.processor,
                formatted,
                max_tokens=max_tokens,
                temperature=0.2,
                top_p=0.9,
                top_k=32,
                verbose=False,
            )
        )
        return out.strip()

    def clear_caches(self) -> None:
        import gc

        gc.collect()
        try:
            import mlx.core as mx

            mx.metal.clear_cache()
        except Exception:
            return


def _generation_text(result: object) -> str:
    if isinstance(result, str):
        return result
    text = getattr(result, "text", None)
    if isinstance(text, str):
        return text
    return str(result)


def _translation_max_tokens(text: str, priority: Literal["partial", "final"]) -> int:
    word_count = len(text.split())
    buffer = 18 if priority == "partial" else 28
    minimum = 32 if priority == "partial" else 48
    maximum = 96 if priority == "partial" else 160
    return min(maximum, max(minimum, word_count * 3 + buffer))


def _format_bilingual_context(pairs: list[tuple[str, str]]) -> str:
    lines: list[str] = []
    for original, translation in pairs[-5:]:
        original = " ".join(original.strip().split())
        translation = " ".join(translation.strip().split())
        if not original or not translation:
            continue
        lines.append(f"- Source: {original}\n  Translation: {translation}")
    return "\n".join(lines)


def _format_learned_corrections(pairs: list[tuple[str, str]]) -> str:
    lines: list[str] = []
    for heard, corrected in pairs[-8:]:
        heard = " ".join(heard.strip().split())
        corrected = " ".join(corrected.strip().split())
        if not heard or not corrected or heard == corrected:
            continue
        lines.append(f"- Heard: {heard}\n  Corrected: {corrected}")
    return "\n".join(lines)


class InferenceTimeoutError(RuntimeError):
    pass


class WorkerProcessError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class WorkerStatusEvent:
    state: Literal["starting", "ready", "recovering", "failed"]
    message: str


@dataclass(order=True)
class _QueuedJob:
    priority: int
    sequence: int
    kind: Literal["ast", "polish", "translate", "correct", "maintenance"] = field(compare=False)
    future: asyncio.Future = field(compare=False)
    payload: dict = field(compare=False)
    enqueued_at: float = field(default_factory=time.monotonic, compare=False)
    on_progress: Callable[[str], Awaitable[None]] | None = field(default=None, compare=False)


class MLXWorkerService:
    """Async facade around one synchronous MLXWorker and one Metal context."""

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[_QueuedJob] = asyncio.PriorityQueue()
        self._sequence = itertools.count()
        self._runner: asyncio.Task | None = None
        self._sweeper: asyncio.Task | None = None
        self._start_lock = asyncio.Lock()
        self._started = False
        self._closed = asyncio.Event()
        self._temp_wav_root = TEMP_WAV_ROOT / f"gemma-{os.getpid()}"
        self._process: mp.Process | None = None
        self._request_queue: mp.Queue | None = None
        self._response_queue: mp.Queue | None = None
        self._active_job_kind: Literal["ast", "polish", "translate", "correct", "maintenance"] | None = None
        self._queued_partial_jobs: dict[int, _QueuedJob] = {}
        self._queued_partial_translation_jobs: dict[int, _QueuedJob] = {}
        self._final_utterance_ids: set[int] = set()
        self._mp_context = mp.get_context("spawn")
        self._cancelled_job_id = self._mp_context.Value("q", -1)
        self._active_job: _QueuedJob | None = None
        self._status = WorkerStatusEvent(state="starting", message="Loading Gemma model worker")
        self._status_listeners: set[Callable[[WorkerStatusEvent], Awaitable[None]]] = set()

    async def start(self) -> None:
        async with self._start_lock:
            if self._started:
                return
            self._closed.clear()
            self._temp_wav_root.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(
                sweep_stale_temp_wavs, self._temp_wav_root, TEMP_WAV_STALE_SECONDS
            )
            try:
                await self._start_worker_process()
            except Exception as exc:
                await self._emit_status(
                    WorkerStatusEvent(state="failed", message=f"Model worker failed to start: {exc}")
                )
                raise
            self._runner = asyncio.create_task(self._run(), name="mlx-worker-queue")
            self._sweeper = asyncio.create_task(
                self._run_temp_wav_sweeper(), name="mlx-temp-wav-sweeper"
            )
            self._started = True

    async def stop(self) -> None:
        self._closed.set()
        if self._sweeper:
            self._sweeper.cancel()
            try:
                await self._sweeper
            except asyncio.CancelledError:
                pass
        if self._runner:
            self._runner.cancel()
            try:
                await self._runner
            except asyncio.CancelledError:
                pass
        await self._stop_worker_process(force=True)
        await asyncio.to_thread(sweep_stale_temp_wavs, self._temp_wav_root, 0)
        self._started = False

    async def submit_ast(
        self,
        *,
        priority: Literal["partial", "final"],
        utterance_id: int | None,
        audio_f32_16k: np.ndarray,
        src: str,
        tgt: str,
        prior_context: list[tuple[str, str]],
        custom_vocab: list[str],
        code_switching_enabled: bool,
        max_tokens: int,
    ) -> tuple[str, str] | None:
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        job = _QueuedJob(
            priority=1 if priority == "partial" else 0,
            sequence=next(self._sequence),
            kind="ast",
            future=future,
            payload={
                "priority": priority,
                "utterance_id": utterance_id,
                "audio_f32_16k": audio_f32_16k,
                "src": src,
                "tgt": tgt,
                "prior_context": prior_context,
                "custom_vocab": custom_vocab,
                "code_switching_enabled": code_switching_enabled,
                "max_tokens": max_tokens,
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

    async def submit_polish(self, text: str) -> str:
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        await self._queue.put(
            _QueuedJob(
                priority=20,
                sequence=next(self._sequence),
                kind="polish",
                future=future,
                payload={"text": text},
            )
        )
        return await future

    def finish_partials(self, utterance_id: int) -> None:
        """Retire queued previews immediately when audio commits, before final ASR finishes."""
        self._final_utterance_ids.add(utterance_id)
        active = self._active_job
        if (active is not None and active.kind == "translate"
                and active.payload.get("priority") == "partial"
                and active.payload.get("utterance_id") == utterance_id):
            self._cancelled_job_id.value = active.sequence
        for queued in (self._queued_partial_jobs, self._queued_partial_translation_jobs):
            job = queued.pop(utterance_id, None)
            if job is not None and not job.future.done():
                job.future.set_result(None)

    async def submit_translate_text(
        self,
        text: str,
        src: str,
        tgt: str,
        *,
        priority: Literal["partial", "final"] = "final",
        utterance_id: int | None = None,
        bilingual_context: list[tuple[str, str]] | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str | None:
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        job = _QueuedJob(
            priority=1 if priority == "final" else 20,
            sequence=next(self._sequence),
            kind="translate",
            on_progress=on_progress,
            future=future,
            payload={
                "priority": priority,
                "utterance_id": utterance_id,
                "text": text,
                "src": src,
                "tgt": tgt,
                "max_tokens": _translation_max_tokens(text, priority),
                "bilingual_context": bilingual_context or [],
            },
        )
        if utterance_id is not None:
            previous = self._queued_partial_translation_jobs.get(utterance_id)
            if priority == "partial":
                if utterance_id in self._final_utterance_ids:
                    future.set_result(None)
                    return await future
                if previous is not None and not previous.future.done():
                    previous.future.set_result(None)
                self._queued_partial_translation_jobs[utterance_id] = job
            else:
                self._final_utterance_ids.add(utterance_id)
                if previous is not None:
                    self._queued_partial_translation_jobs.pop(utterance_id, None)
                    if not previous.future.done():
                        previous.future.set_result(None)
        await self._queue.put(job)
        return await future

    async def submit_correct_asr_text(
        self,
        text: str,
        src: str,
        *,
        custom_vocab: list[str] | None = None,
        prior_context: list[tuple[str, str]] | None = None,
        learned_corrections: list[tuple[str, str]] | None = None,
        code_switching_enabled: bool = False,
    ) -> str:
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        await self._queue.put(
            _QueuedJob(
                priority=4,
                sequence=next(self._sequence),
                kind="correct",
                future=future,
                payload={
                    "text": text,
                    "src": src,
                    "custom_vocab": custom_vocab or [],
                    "prior_context": prior_context or [],
                    "learned_corrections": learned_corrections or [],
                    "code_switching_enabled": code_switching_enabled,
                },
            )
        )
        return await future

    async def submit_maintenance(self) -> None:
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        await self._queue.put(
            _QueuedJob(
                priority=30,
                sequence=next(self._sequence),
                kind="maintenance",
                future=future,
                payload={},
            )
        )
        await future

    async def add_status_listener(
        self, listener: Callable[[WorkerStatusEvent], Awaitable[None]]
    ) -> None:
        self._status_listeners.add(listener)
        await listener(self._status)

    def remove_status_listener(
        self, listener: Callable[[WorkerStatusEvent], Awaitable[None]]
    ) -> None:
        self._status_listeners.discard(listener)

    @property
    def is_busy_or_backlogged(self) -> bool:
        return self._active_job_kind is not None or self._queue.qsize() > 0

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
                self._active_job_kind = job.kind
                self._active_job = job
                dispatched_at = time.monotonic()
                result = await self._execute_job(job)
                finished_at = time.monotonic()
                if finished_at - job.enqueued_at >= 1.0:
                    logger.warning(
                        "slow_inference engine=gemma priority=%s utterance_id=%s queue_seconds=%.3f inference_seconds=%.3f",
                        job.payload.get("priority"), job.payload.get("utterance_id"),
                        dispatched_at - job.enqueued_at, finished_at - dispatched_at,
                    )
                if not job.future.cancelled():
                    job.future.set_result(result)
            except Exception as exc:
                if not job.future.cancelled():
                    job.future.set_exception(exc)
            finally:
                self._active_job_kind = None
                self._active_job = None
                self._queue.task_done()

    def _should_skip_job(self, job: _QueuedJob) -> bool:
        if job.payload.get("priority") != "partial":
            return False
        utterance_id = job.payload.get("utterance_id")
        if not isinstance(utterance_id, int):
            return False
        if utterance_id in self._final_utterance_ids:
            return True
        if job.kind == "ast":
            queued_job = self._queued_partial_jobs.get(utterance_id)
            queued_jobs = self._queued_partial_jobs
        elif job.kind == "translate":
            queued_job = self._queued_partial_translation_jobs.get(utterance_id)
            queued_jobs = self._queued_partial_translation_jobs
        else:
            return False
        if queued_job is None:
            return False
        if queued_job.sequence != job.sequence:
            return True
        queued_jobs.pop(utterance_id, None)
        return False

    async def _run_temp_wav_sweeper(self) -> None:
        while not self._closed.is_set():
            await asyncio.to_thread(
                sweep_stale_temp_wavs,
                self._temp_wav_root,
                TEMP_WAV_STALE_SECONDS,
            )
            try:
                await asyncio.wait_for(
                    self._closed.wait(),
                    timeout=TEMP_WAV_SWEEP_INTERVAL_SECONDS,
                )
            except asyncio.TimeoutError:
                continue

    async def _execute_job(self, job: _QueuedJob) -> object:
        timeout_seconds = self._job_timeout_seconds(job)
        try:
            return await self._dispatch_job(job, timeout_seconds)
        except InferenceTimeoutError:
            await self._recover_worker(
                f"{job.kind.upper()} timed out after {timeout_seconds:.1f}s; reloading model worker"
            )
            raise
        except WorkerProcessError as exc:
            recovered = await self._recover_worker(
                f"Model worker crashed during {job.kind}; reloading once"
            )
            if recovered:
                return await self._dispatch_job(job, timeout_seconds)
            raise RuntimeError(f"Inference failed after worker recovery attempt: {exc}") from exc

    async def _dispatch_job(self, job: _QueuedJob, timeout_seconds: float) -> object:
        if self._request_queue is None or self._response_queue is None or self._process is None:
            raise WorkerProcessError("MLX worker process is not started")
        if not self._process.is_alive():
            raise WorkerProcessError("MLX worker process exited unexpectedly")

        payload = job.payload
        if job.kind in {"ast", "translate"}:
            payload = {
                key: value
                for key, value in job.payload.items()
                if key not in {"priority", "utterance_id"}
            }
        request = {
            "job_id": job.sequence,
            "kind": job.kind,
            "cancellable": job.kind == "translate" and job.payload.get("priority") == "partial",
            "payload": payload,
        }
        await asyncio.to_thread(self._request_queue.put, request)
        response = await self._wait_for_worker_response(job, timeout_seconds)

        if response.get("type") == "result" and response.get("job_id") == job.sequence:
            return response["result"]
        if response.get("type") == "fatal" and response.get("job_id") == job.sequence:
            await self._stop_worker_process(force=True)
            raise WorkerProcessError(response.get("error", "Unknown worker error"))
        raise WorkerProcessError(f"Unexpected worker response: {response!r}")

    async def _wait_for_worker_response(
        self,
        job: _QueuedJob,
        timeout_seconds: float,
    ) -> dict:
        if self._response_queue is None or self._process is None:
            raise WorkerProcessError("MLX worker process is not started")

        deadline = time.monotonic() + timeout_seconds
        while True:
            if not self._process.is_alive():
                raise WorkerProcessError("MLX worker process exited unexpectedly")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                await self._stop_worker_process(force=True)
                raise InferenceTimeoutError(
                    f"{job.kind.upper()} timed out after {timeout_seconds:.1f}s"
                )
            try:
                response = await asyncio.to_thread(
                    self._response_queue.get,
                    True,
                    min(0.25, remaining),
                )
                if response.get("type") == "progress" and response.get("job_id") == job.sequence:
                    if job.on_progress is not None:
                        await job.on_progress(response["text"])
                    continue
                return response
            except queue.Empty:
                continue

    async def _recover_worker(self, message: str) -> bool:
        if self._closed.is_set():
            return False
        await self._emit_status(WorkerStatusEvent(state="recovering", message=message))
        await self._stop_worker_process(force=True)
        if MLX_WORKER_RECOVERY_BACKOFF_SECONDS:
            await asyncio.sleep(MLX_WORKER_RECOVERY_BACKOFF_SECONDS)
        try:
            await self._start_worker_process()
            return True
        except Exception as exc:
            await self._emit_status(
                WorkerStatusEvent(state="failed", message=f"Model worker recovery failed: {exc}")
            )
            return False

    async def _start_worker_process(self) -> None:
        await self._emit_status(WorkerStatusEvent(state="starting", message="Loading Gemma model worker"))
        request_queue: mp.Queue = self._mp_context.Queue()
        response_queue: mp.Queue = self._mp_context.Queue()
        process = self._mp_context.Process(
            target=_worker_process_main,
            args=(request_queue, response_queue, str(self._temp_wav_root), self._cancelled_job_id),
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
                MLX_WORKER_START_TIMEOUT_SECONDS,
            )
        except queue.Empty as exc:
            await self._stop_worker_process(force=True)
            raise RuntimeError(
                f"Timed out loading MLX worker after {MLX_WORKER_START_TIMEOUT_SECONDS:.1f}s"
            ) from exc

        if response.get("type") != "ready":
            await self._stop_worker_process(force=True)
            raise RuntimeError(response.get("error", "MLX worker failed to report ready"))
        await self._emit_status(WorkerStatusEvent(state="ready", message="Model worker ready"))

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

    async def _emit_status(self, event: WorkerStatusEvent) -> None:
        self._status = event
        if not self._status_listeners:
            return
        results = await asyncio.gather(
            *(listener(event) for listener in list(self._status_listeners)),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                continue

    def _job_timeout_seconds(self, job: _QueuedJob) -> float:
        if job.kind == "maintenance":
            return MAINTENANCE_TIMEOUT_SECONDS
        if job.kind == "correct":
            return POLISH_TIMEOUT_SECONDS
        if job.kind == "polish":
            return POLISH_TIMEOUT_SECONDS
        if job.kind == "translate":
            return TRANSLATE_TIMEOUT_SECONDS
        if job.kind == "ast" and job.payload.get("priority") == "partial":
            return PARTIAL_TIMEOUT_SECONDS
        return FINAL_TIMEOUT_SECONDS


def _worker_process_main(
    request_queue: mp.Queue,
    response_queue: mp.Queue,
    temp_wav_root: str,
    cancelled_job_id,
) -> None:
    try:
        worker = MLXWorker(Path(temp_wav_root))
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
            if request["kind"] == "ast":
                result = worker.ast(**request["payload"])
            elif request["kind"] == "maintenance":
                result = worker.clear_caches()
            elif request["kind"] == "polish":
                result = worker.polish(**request["payload"])
            elif request["kind"] == "correct":
                result = worker.correct_asr_text(**request["payload"])
            else:
                cancelled = (
                    (lambda: cancelled_job_id.value == job_id)
                    if request.get("cancellable") else None
                )
                result = worker.translate_text(
                    **request["payload"], cancelled=cancelled,
                    on_progress=lambda text: response_queue.put(
                        {"type": "progress", "job_id": job_id, "text": text}
                    ),
                )
        except Exception:
            response_queue.put(
                {
                    "type": "fatal",
                    "job_id": job_id,
                    "error": traceback.format_exc(),
                }
            )
            return

        response_queue.put({"type": "result", "job_id": job_id, "result": result})


def sweep_stale_temp_wavs(temp_wav_root: Path, stale_after_seconds: float) -> int:
    temp_wav_root.mkdir(parents=True, exist_ok=True)
    now = time.time()
    removed = 0
    for wav_path in temp_wav_root.glob("*.wav"):
        try:
            age_seconds = now - wav_path.stat().st_mtime
        except FileNotFoundError:
            continue
        if age_seconds < stale_after_seconds:
            continue
        _safe_unlink(wav_path)
        removed += 1
    return removed


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
