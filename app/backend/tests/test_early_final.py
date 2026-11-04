import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import numpy as np

from mlx_worker import ASTResult, MLXWorkerService
from protocol import ConfigMessage
from segmenter import RMSGate
from session import SessionHub, TranscriptionSession, UtteranceRuntime

SPEECH = np.full(320, 0.1, dtype=np.float32)
SILENCE = np.zeros(320, dtype=np.float32)


def make_session(monkeypatch):
    monkeypatch.setattr(TranscriptionSession, "_build_segmenter", lambda *_: RMSGate())
    value = TranscriptionSession(
        SimpleNamespace(query_params={}), Mock(), SessionHub(),
    )
    value.state.config = ConfigMessage(polish_enabled=False)
    value.worker.is_busy_or_backlogged = False
    value._send = AsyncMock()
    value._send_and_broadcast = AsyncMock()
    return value


def finals(value):
    return [call.args[0] for call in value._send_and_broadcast.await_args_list
            if call.args[0]["type"] == "final"]


def test_pause_final_reuses_the_early_decode(monkeypatch):
    async def run():
        value = make_session(monkeypatch)
        value.worker.submit_ast = AsyncMock(return_value=ASTResult(
            "Grace and peace.", "Gracia y paz.", True, False))
        # Previews stay busy, so only the early decode reaches the worker.
        value.worker.is_busy_or_backlogged = True
        for frame in [SPEECH] * 20 + [SILENCE] * 15:
            await value._receive_frame(frame)
        await asyncio.sleep(0)
        early = value.worker.submit_ast.await_args.kwargs
        assert early["early"] and early["priority"] == "final"
        np.testing.assert_array_equal(
            early["audio_f32_16k"], np.concatenate([SPEECH] * 20 + [SILENCE] * 15))

        for frame in [SILENCE] * 5:
            await value._receive_frame(frame)
        await asyncio.gather(*list(value._jobs))
        value.worker.submit_ast.assert_awaited_once()
        [final] = finals(value)
        assert final["commit_reason"] == "silero_end"
        assert final["translation"] == "Gracia y paz."
    asyncio.run(run())


def test_resumed_speech_drops_the_early_decode(monkeypatch):
    async def run():
        value = make_session(monkeypatch)
        value.worker.is_busy_or_backlogged = True

        async def infer(**kwargs):
            seconds = kwargs["audio_f32_16k"].size / 16_000
            return ASTResult(f"{seconds:.2f}", f"{seconds:.2f}", True, False)
        value.worker.submit_ast = AsyncMock(side_effect=infer)
        for frame in [SPEECH] * 20 + [SILENCE] * 15:
            await value._receive_frame(frame)
        value.worker.cancel_early_final.assert_not_called()

        await value._receive_frame(SPEECH)
        value.worker.cancel_early_final.assert_called_once_with(1)
        assert value._utterance_runtime[1].early_final_task is None

        for frame in [SILENCE] * 20:
            await value._receive_frame(frame)
        await asyncio.gather(*list(value._jobs))
        # The second pause's early decode covers all the speech and is the final.
        assert value.worker.submit_ast.await_count == 2
        [final] = finals(value)
        assert final["original"] == f"{(20 + 15 + 1 + 15) * 320 / 16_000:.2f}"
    asyncio.run(run())


def test_commit_with_other_audio_cancels_the_early_decode(monkeypatch):
    async def run():
        value = make_session(monkeypatch)
        task = asyncio.create_task(asyncio.sleep(0))
        value._utterance_runtime[1] = UtteranceRuntime(
            early_final_task=task, early_final_audio=np.ones(320, dtype=np.float32))
        assert value._claim_early_final(1, np.ones(640, dtype=np.float32)) is None
        value.worker.cancel_early_final.assert_called_once_with(1)
        assert value._utterance_runtime[1].early_final_task is None
        await task
    asyncio.run(run())


def test_early_final_retires_previews_and_survives_the_commit():
    async def run():
        worker = MLXWorkerService()

        def submit(priority, value, **extra):
            return asyncio.create_task(worker.submit_ast(
                priority=priority, utterance_id=7,
                audio_f32_16k=np.full(16000, value, dtype=np.float32),
                src="English", tgt="Spanish", prior_context=[], custom_vocab=[],
                code_switching_enabled=False, max_tokens=128, **extra,
            ))

        preview = submit("partial", 0.1)
        await asyncio.sleep(0)
        # Dispatch the preview as the queue runner does.
        running = worker._queue.get_nowait()
        assert not worker._should_skip_job(running)
        worker._active_job = running
        early = submit("final", 0.2, early=True)
        await asyncio.sleep(0)
        # A running preview finishes and shows its text.
        assert worker._cancelled_job_id.value != running.sequence and not preview.done()
        assert worker._early_jobs[7].early
        worker._active_job = None
        preview.cancel()

        # The commit retires previews but keeps the early decode queued.
        worker.finish_partials(7)
        assert not early.done() and 7 in worker._early_jobs
        worker.cancel_early_final(7)
        assert await early is None
        assert 7 not in worker._early_jobs
    asyncio.run(run())


def test_early_final_drops_a_queued_preview():
    async def run():
        worker = MLXWorkerService()

        def submit(priority, **extra):
            return asyncio.create_task(worker.submit_ast(
                priority=priority, utterance_id=7, audio_f32_16k=np.ones(16000, dtype=np.float32),
                src="English", tgt="Spanish", prior_context=[], custom_vocab=[],
                code_switching_enabled=False, max_tokens=128, **extra,
            ))

        preview = submit("partial")
        await asyncio.sleep(0)
        early = submit("final", early=True)
        await asyncio.sleep(0)
        assert await preview is None
        assert 7 not in worker._queued_partial_jobs
        early.cancel()
        await asyncio.gather(early, return_exceptions=True)
    asyncio.run(run())
