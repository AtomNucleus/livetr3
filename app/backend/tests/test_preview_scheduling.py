import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

from mlx_worker import MLXWorkerService
from protocol import ConfigMessage
from session import TranscriptionSession, UtteranceRuntime


def make_session(*, interval=0.25):
    value = object.__new__(TranscriptionSession)
    value.state = SimpleNamespace(
        config=ConfigMessage(partial_interval_seconds=interval),
        active_utterance_id=7,
    )
    value._utterance_runtime = {7: UtteranceRuntime()}
    value._finalizing = {}
    value._finalized = set()
    value._partial_ast_task = None
    value.worker = SimpleNamespace(is_busy_or_backlogged=False)
    return value


def test_busy_worker_defers_preview_without_consuming_new_audio():
    session = make_session()
    runtime = session._utterance_runtime[7]
    runtime.voiced_audio_samples = 16_000
    session.worker.is_busy_or_backlogged = True
    assert not session._active_utterance_has_new_speech_for_partial()
    assert runtime.last_partial_audio_samples == 0
    session.worker.is_busy_or_backlogged = False
    assert session._active_utterance_has_new_speech_for_partial()


def test_batched_frames_schedule_only_one_preview_before_task_starts():
    async def run():
        session = make_session()
        session._jobs = set()
        session._run_ast = AsyncMock()
        audio = np.ones(16000, dtype=np.float32)
        session._schedule_ast("partial", 7, audio)
        session._schedule_ast("partial", 7, audio)
        assert len(session._jobs) == 1
        # A required final still enters the queue immediately.
        session._schedule_ast("final", 7, audio)
        assert len(session._jobs) == 2
        await asyncio.gather(*session._jobs)
        assert [call.args[:2] for call in session._run_ast.await_args_list] == [
            ("partial", 7), ("final", 7),
        ]
    asyncio.run(run())


def test_partial_interval_respects_configured_floor():
    session = make_session(interval=0.75)
    assert session._partial_interval_seconds() == 0.75

    session.state.config.partial_interval_seconds = 2.8
    assert session._partial_interval_seconds() == 2.8


def test_partial_preview_waits_for_both_cadence_and_new_speech(monkeypatch):
    session = make_session(interval=1.5)
    runtime = session._utterance_runtime[7]
    runtime.last_partial_wall_seconds = 99.0
    runtime.last_partial_audio_samples = 16_000
    runtime.voiced_audio_samples = 19_200
    now = [100.0]
    monkeypatch.setattr("session.time", SimpleNamespace(monotonic=lambda: now[0]))

    assert not session._active_utterance_has_new_speech_for_partial()
    now[0] = 101.0
    runtime.voiced_audio_samples = 17_600
    assert not session._active_utterance_has_new_speech_for_partial()

    runtime.voiced_audio_samples = 19_200
    assert session._active_utterance_has_new_speech_for_partial()


def test_cold_preview_does_not_throttle_later_fast_previews(monkeypatch):
    async def run():
        session = make_session()
        session._jobs = set()
        runtime = session._utterance_runtime[7]
        now = [100.0]
        monkeypatch.setattr(
            "session.time", SimpleNamespace(monotonic=lambda: now[0])
        )
        completed = asyncio.Event()
        release = asyncio.Event()
        durations = iter([4.0, 0.6, 0.5])

        async def decode(*_):
            await release.wait()
            release.clear()
            now[0] += next(durations)
            runtime.voiced_audio_samples += 16_000
            completed.set()

        session._run_mlx_ast = decode

        for expected_finish in [104.0, 104.6, 105.1]:
            runtime.voiced_audio_samples += 4_000
            assert session._active_utterance_has_new_speech_for_partial()
            runtime.last_partial_wall_seconds = now[0]
            runtime.last_partial_audio_samples = runtime.voiced_audio_samples
            session._schedule_ast("partial", 7, np.ones(16000, dtype=np.float32))
            # The next voiced frames can't enqueue a stale preview while this
            # one is in flight, even though the configured cadence has elapsed.
            assert not session._active_utterance_has_new_speech_for_partial()
            release.set()
            await completed.wait()
            completed.clear()
            await session._partial_ast_task
            assert now[0] == pytest.approx(expected_finish)
            assert session._active_utterance_has_new_speech_for_partial()

    asyncio.run(run())


def test_queued_ast_previews_coalesce_and_final_keeps_priority():
    async def run():
        worker = MLXWorkerService()

        async def submit(priority, audio):
            return await worker.submit_ast(
                priority=priority,
                utterance_id=7,
                audio_f32_16k=np.full(16000, audio, dtype=np.float32),
                src="English",
                tgt="Spanish",
                prior_context=[],
                custom_vocab=[],
                code_switching_enabled=False,
                max_tokens=128,
            )

        first_preview = asyncio.create_task(submit("partial", 0.1))
        await asyncio.sleep(0)
        latest_preview = asyncio.create_task(submit("partial", 0.2))
        await asyncio.sleep(0)

        assert await first_preview is None
        queued_preview = worker._queued_partial_jobs[7]
        np.testing.assert_array_equal(
            queued_preview.payload["audio_f32_16k"],
            np.full(16000, 0.2, dtype=np.float32),
        )

        final = asyncio.create_task(submit("final", 0.3))
        await asyncio.sleep(0)
        assert await latest_preview is None
        assert worker._queue.get_nowait().payload["priority"] == "final"

        final.cancel()
        await asyncio.gather(final, return_exceptions=True)
        assert await submit("partial", 0.4) is None

    asyncio.run(run())
