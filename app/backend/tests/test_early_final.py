"""The final decode starts early in a pause and is dropped if speech resumes."""
import asyncio
from types import SimpleNamespace

import numpy as np

from mlx_worker import ASTResult, MLXWorkerService
from protocol import ConfigMessage
from segmenter import RMSGate, SileroVAD
from session import SessionHub, TranscriptionSession

SPEECH = np.full(320, 0.1, dtype=np.float32)
SILENCE = np.zeros(320, dtype=np.float32)


class FakeSocket:
    def __init__(self):
        self.query_params = {}
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


class FakeWorker:
    """Final-priority decodes wait for release(); previews return nothing."""

    def __init__(self):
        self.finals = []
        self.cancelled = []
        self.release = asyncio.Event()
        self.is_busy_or_backlogged = False

    async def submit_ast(self, *, priority, utterance_id, audio_f32_16k, early=False, **_):
        if priority == "partial":
            return None
        call = SimpleNamespace(utterance_id=utterance_id, samples=audio_f32_16k.size, early=early)
        self.finals.append(call)
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.append(call)
            raise
        return ASTResult(f"said {call.samples}", f"dicho {call.samples}", True, False)

    def finish_partials(self, utterance_id):
        pass

    def cancel_active_partial(self, utterance_id):
        pass


def make_session(monkeypatch, early_ms="200"):
    monkeypatch.setenv("LIVETR3_EARLY_FINAL_MS", early_ms)
    monkeypatch.setattr("session.DEFAULT_PARTIAL_AST_ENABLED", False)
    socket = FakeSocket()
    session = TranscriptionSession(socket, FakeWorker(), SessionHub())
    session.state.config = ConfigMessage(polish_enabled=False)
    session.segmenter = RMSGate(trailing_silence_ms=600, min_utterance_ms=200, overlap_s=0)
    session.state.running = True
    return session, socket


async def feed(session, frame, count):
    for _ in range(count):
        await session._receive_frame(frame)
        await asyncio.sleep(0)


async def drain(session):
    while session._jobs:
        await asyncio.gather(*list(session._jobs))
        await asyncio.sleep(0)


def finals(socket):
    return [row for row in socket.sent if row["type"] == "final"]


def test_pause_starts_final_decode_and_end_of_speech_reuses_it(monkeypatch):
    async def run():
        session, socket = make_session(monkeypatch)
        worker = session.worker
        await feed(session, SPEECH, 50)
        await feed(session, SILENCE, 9)
        assert worker.finals == []
        await feed(session, SILENCE, 1)
        # 200 ms into the pause, before end-of-speech, the final decode is running.
        assert [(call.early, call.samples) for call in worker.finals] == [(True, 60 * 320)]
        await feed(session, SILENCE, 20)  # end-of-speech at 600 ms
        worker.release.set()
        await drain(session)
        assert len(worker.finals) == 1 and worker.cancelled == []
        assert [row["original"] for row in finals(socket)] == [f"said {60 * 320}"]
    asyncio.run(run())


def test_frames_batched_after_end_of_speech_keep_the_early_decode(monkeypatch):
    async def run():
        session, socket = make_session(monkeypatch)
        worker = session.worker
        await feed(session, SPEECH, 50)
        await feed(session, SILENCE, 10)
        # One audio message can carry many frames with no turn for the final task.
        for frame in [SILENCE] * 25 + [SPEECH] * 5:
            await session._receive_frame(frame)
        worker.release.set()
        await drain(session)
        assert worker.cancelled == []
        assert finals(socket)[0]["original"] == f"said {60 * 320}"
    asyncio.run(run())


def test_resumed_speech_cancels_early_decode_and_decodes_whole_sentence(monkeypatch):
    async def run():
        session, socket = make_session(monkeypatch)
        worker = session.worker
        await feed(session, SPEECH, 50)
        await feed(session, SILENCE, 12)
        assert len(worker.finals) == 1
        await feed(session, SPEECH, 1)
        assert worker.cancelled == worker.finals
        assert session._early_final is None
        await feed(session, SPEECH, 20)
        await feed(session, SILENCE, 30)
        worker.release.set()
        await drain(session)
        assert len(worker.finals) == 2
        whole = (50 + 12 + 1 + 20 + 10) * 320
        assert worker.finals[1].samples == whole
        # The final carries every word, including those after the brief pause.
        assert [row["original"] for row in finals(socket)] == [f"said {whole}"]
    asyncio.run(run())


def test_zero_waits_for_end_of_speech(monkeypatch):
    async def run():
        session, socket = make_session(monkeypatch, early_ms="0")
        worker = session.worker
        await feed(session, SPEECH, 50)
        await feed(session, SILENCE, 29)
        assert worker.finals == []
        await feed(session, SILENCE, 1)
        assert [(call.early, call.samples) for call in worker.finals] == [(False, 80 * 320)]
        worker.release.set()
        await drain(session)
        assert len(finals(socket)) == 1
    asyncio.run(run())


def test_changed_audio_is_decoded_again(monkeypatch):
    async def run():
        session, socket = make_session(monkeypatch)
        worker = session.worker
        await feed(session, SPEECH, 50)
        await feed(session, SILENCE, 10)
        # A commit that does not extend the early audio (e.g. a cut) re-decodes.
        await session._commit_utterance(
            session.state.active_utterance_id, session.segmenter.current_audio()[:-320],
            reason="max_utterance_cap", reset_segmenter=True,
        )
        worker.release.set()
        await drain(session)
        assert [call.early for call in worker.finals] == [True, False]
        assert worker.cancelled == worker.finals[:1]
        assert len(finals(socket)) == 1
    asyncio.run(run())


def test_pause_past_size_cap_is_left_to_the_cap_cut(monkeypatch):
    async def run():
        session, _ = make_session(monkeypatch)
        session.segmenter = RMSGate(trailing_silence_ms=600, max_utterance_s=1.0,
                                    overlap_s=0, cap_extend_s=2.0, cap_pause_ms=400)
        await feed(session, SPEECH, 60)
        await feed(session, SILENCE, 10)
        assert session.worker.finals == []
    asyncio.run(run())


def test_silero_quiet_counts_from_pending_end():
    vad = object.__new__(SileroVAD)
    RMSGate.__init__(vad)
    vad._silent_frames = 0
    vad._vad_iterator = SimpleNamespace(triggered=True, temp_end=16_000, current_sample=19_200)
    assert vad.trailing_quiet_ms == 0  # no utterance in progress
    vad._speech_active = True
    assert vad.trailing_quiet_ms == 200
    vad._vad_iterator.temp_end = 0  # speech returned
    assert vad.trailing_quiet_ms == 0
    vad._silent_frames = 5
    assert vad.trailing_quiet_ms == 100


def test_worker_stops_cancelled_early_decode_without_retiring_previews():
    async def run():
        service = MLXWorkerService()
        task = asyncio.create_task(service.submit_ast(
            priority="final", utterance_id=3, audio_f32_16k=np.zeros(320, dtype=np.float32),
            src="English", tgt="Spanish", prior_context=[], custom_vocab=[],
            code_switching_enabled=False, max_tokens=8, early=True,
        ))
        await asyncio.sleep(0)
        job = service._queue.get_nowait()
        assert job.cancellable
        service._active_job = job
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert service._cancelled_job_id.value == job.sequence
        assert 3 not in service._final_utterance_ids
    asyncio.run(run())
