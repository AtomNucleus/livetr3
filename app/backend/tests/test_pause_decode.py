import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

import session as session_module
from mlx_worker import ASTResult, MLXWorkerService
from segmenter import FRAME_SAMPLES, RMSGate
from session import SessionHub, TranscriptionSession

SPEECH = np.full(FRAME_SAMPLES, 0.1, dtype=np.float32)
QUIET = np.zeros(FRAME_SAMPLES, dtype=np.float32)
PAD = 4  # The pause window ends this many frames into the silence, like Silero's pad.
DONE = ASTResult("Hello there.", "Hola.", complete=True, truncated=False)


class PauseGate(RMSGate):
    """RMSGate with a Silero-like pause window: it ends PAD frames into the
    silence, is ready one frame later, and the commit comes at 20 quiet frames."""

    def __init__(self):
        super().__init__(trailing_silence_ms=400)

    def _quiet(self):
        quiet = 0
        for frame in reversed(self._current):
            if float(np.sqrt(np.mean(np.square(frame)))) > self.threshold:
                break
            quiet += 1
        return quiet

    def pause_audio(self):
        quiet = self._quiet()
        if not self.speech_active or quiet <= PAD:
            return None
        return self.current_audio()[:(len(self._current) - quiet + PAD) * FRAME_SAMPLES]

    def ingest(self, frame):
        result = super().ingest(frame)
        if result.speech_ended and not result.force_flushed:
            result.pause_samples = result.audio.size - (self.trailing_silence_frames - PAD) * FRAME_SAMPLES
        return result


class FakeWorker:
    is_busy_or_backlogged = False

    def __init__(self):
        self.jobs = []
        self.cancelled_pauses = []
        self.cancelled_partials = []

    async def submit_ast(self, *, priority, utterance_id, audio_f32_16k, max_tokens, on_progress=None, **request):
        job = SimpleNamespace(priority=priority, utterance_id=utterance_id, audio=audio_f32_16k.copy(),
                              max_tokens=max_tokens, request=request, on_progress=on_progress,
                              future=asyncio.get_running_loop().create_future())
        self.jobs.append(job)
        return await job.future

    def finish_partials(self, utterance_id):
        pass

    def cancel_partials(self, utterance_id):
        self.cancelled_partials.append(utterance_id)

    def cancel_pause_decode(self, utterance_id):
        self.cancelled_pauses.append(utterance_id)
        for job in self.jobs:
            if job.priority == "pause" and job.utterance_id == utterance_id and not job.future.done():
                job.future.set_result(None)

    def of(self, priority):
        return [job for job in self.jobs if job.priority == priority]


@pytest.fixture
def make_session(monkeypatch):
    monkeypatch.setenv("LIVETR3_PAUSE_DECODE", "1")
    monkeypatch.setattr(session_module, "DEFAULT_PARTIAL_AST_ENABLED", False)
    monkeypatch.setattr(TranscriptionSession, "_build_segmenter", lambda *_: PauseGate())

    def make():
        value = TranscriptionSession(SimpleNamespace(query_params={}), FakeWorker(), SessionHub())
        value._send = AsyncMock()
        value._send_and_broadcast = AsyncMock()
        return value
    return make


async def feed(value, frames):
    for frame in frames:
        await value._receive_frame(frame)
        await asyncio.sleep(0)


async def settle(value):
    for _ in range(5):
        await asyncio.sleep(0)


def finals(value):
    return [call.args[0] for call in value._send_and_broadcast.await_args_list
            if call.args[0]["type"] == "final"]


def test_pause_decode_starts_at_the_pad_and_publishes_as_the_final(make_session):
    async def run():
        value = make_session()
        await feed(value, [SPEECH] * 20 + [QUIET] * PAD)
        assert value.worker.jobs == []
        await feed(value, [QUIET])
        [pause] = value.worker.of("pause")
        expected = np.concatenate([SPEECH] * 20 + [QUIET] * PAD)
        np.testing.assert_array_equal(pause.audio, expected)
        # The same request a final would make.
        assert pause.max_tokens == value._max_tokens_for_ast("final", expected)
        assert pause.request == value._ast_request()
        assert value.worker.cancelled_partials == [1]

        await feed(value, [QUIET] * (20 - PAD - 1))  # The commit.
        await settle(value)
        assert value.worker.of("final") == []
        pause.future.set_result(DONE)
        await asyncio.gather(*value._jobs)
        [final] = finals(value)
        assert (final["original"], final["commit_reason"], final["pause_decode_reused"]) == (
            "Hello there.", "silero_end", True)
    asyncio.run(run())


def test_speech_after_the_pause_discards_it_and_its_progress(make_session):
    async def run():
        value = make_session()
        await feed(value, [SPEECH] * 20 + [QUIET] * (PAD + 2))
        [stale] = value.worker.of("pause")
        await feed(value, [SPEECH] * 5)
        assert value.worker.cancelled_pauses == [1]
        assert stale.future.result() is None
        await stale.on_progress("<transcript>Hello</transcript>")
        assert value._send_and_broadcast.await_count == 1  # Only speech_start.

        await feed(value, [QUIET] * 20)
        await settle(value)
        stale_window, fresh = value.worker.of("pause")
        assert fresh.audio.size == (20 + PAD + 2 + 5 + PAD) * FRAME_SAMPLES
        fresh.future.set_result(DONE)
        await asyncio.gather(*value._jobs)
        assert value.worker.of("final") == []
        assert finals(value)[0]["pause_decode_reused"] is True
    asyncio.run(run())


@pytest.mark.parametrize("pause_result", [
    ASTResult("Hello", "", complete=False, truncated=True),
    ASTResult("Hello there.", "Hola.", complete=False, truncated=False),
    None,  # Cancelled or failed.
])
def test_unusable_pause_decode_falls_back_to_a_fresh_final(make_session, pause_result):
    async def run():
        value = make_session()
        await feed(value, [SPEECH] * 20 + [QUIET] * 20)
        [pause] = value.worker.of("pause")
        pause.future.set_result(pause_result)
        await settle(value)
        [final] = value.worker.of("final")
        np.testing.assert_array_equal(final.audio, pause.audio)
        final.future.set_result(DONE)
        await asyncio.gather(*value._jobs)
        assert finals(value)[0]["pause_decode_reused"] is False
    asyncio.run(run())


def test_reuse_needs_the_same_window_and_request(make_session):
    async def run():
        value = make_session()
        await feed(value, [SPEECH] * 20 + [QUIET] * (PAD + 1))
        value.state.config = value.state.config.model_copy(update={"custom_vocab": ["Corinthians"]})
        await feed(value, [QUIET] * (20 - PAD - 1))
        await settle(value)
        assert value.worker.cancelled_pauses == [1]
        [final] = value.worker.of("final")
        assert final.request["custom_vocab"] == ["Corinthians"]
    asyncio.run(run())


def test_cap_commit_discards_the_pause_decode_and_decodes_untrimmed(make_session):
    async def run():
        value = make_session()
        await feed(value, [SPEECH] * 20 + [QUIET] * (PAD + 1))
        audio = value.segmenter.current_audio()
        await value._commit_utterance(1, audio, reason="max_utterance_cap", reset_segmenter=True)
        await settle(value)
        assert value.worker.cancelled_pauses == [1]
        [final] = value.worker.of("final")
        np.testing.assert_array_equal(final.audio, audio)
        final.future.set_result(DONE)
        await asyncio.gather(*value._jobs)
        assert finals(value)[0]["pause_decode_reused"] is False
    asyncio.run(run())


def test_flag_off_keeps_untrimmed_finals(make_session, monkeypatch):
    async def run():
        monkeypatch.setenv("LIVETR3_PAUSE_DECODE", "0")
        value = make_session()
        await feed(value, [SPEECH] * 20 + [QUIET] * 20)
        await settle(value)
        [final] = value.worker.jobs
        assert final.priority == "final" and final.audio.size == 40 * FRAME_SAMPLES
        final.future.set_result(DONE)
        await asyncio.gather(*value._jobs)
        assert "pause_decode_reused" not in finals(value)[0]
    asyncio.run(run())


def test_worker_queues_pause_jobs_like_finals_but_cancellable():
    async def run():
        worker = MLXWorkerService()
        submit = lambda priority: asyncio.create_task(worker.submit_ast(
            priority=priority, utterance_id=3, audio_f32_16k=np.zeros(320, dtype=np.float32),
            src="English", tgt="Spanish", prior_context=[], custom_vocab=[],
            code_switching_enabled=False, max_tokens=384))
        pause = submit("pause")
        await asyncio.sleep(0)
        job = worker._pause_jobs[3]
        assert job.priority == 0 and not worker._should_skip_job(job)
        # Neither a later preview nor the commit retires it.
        partial = submit("partial")
        await asyncio.sleep(0)
        worker.finish_partials(3)
        assert await partial is None
        await asyncio.sleep(0)
        assert not pause.done()
        worker.cancel_pause_decode(3)
        assert await pause is None and 3 not in worker._pause_jobs
    asyncio.run(run())


def test_worker_sends_pause_jobs_as_cancellable_finals():
    async def run():
        worker = MLXWorkerService()
        sent = []
        worker._request_queue = SimpleNamespace(put=sent.append)
        worker._response_queue = object()
        worker._process = SimpleNamespace(is_alive=lambda: True)
        worker._wait_for_worker_response = AsyncMock(return_value={"type": "result", "job_id": 5, "result": DONE})
        job = SimpleNamespace(sequence=5, kind="ast", payload={"priority": "pause", "utterance_id": 3})
        assert await worker._dispatch_job(job, 1.0) is DONE
        assert sent[0]["payload"] == {"priority": "final"} and sent[0]["cancellable"] is True
    asyncio.run(run())
