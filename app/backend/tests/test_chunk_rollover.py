import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from mlx_worker import MLXWorkerService
from segmenter import RMSGate, SileroVAD


def fake_silero():
    vad = object.__new__(SileroVAD)
    RMSGate.__init__(vad, max_utterance_s=0.1, overlap_s=0.02)
    vad._torch = SimpleNamespace(from_numpy=lambda value: value)
    # Silero emits a start once, then stays active until an end event.
    events = iter([{"start": 0}])
    vad._vad_iterator = Mock(side_effect=lambda *args, **kwargs: next(events, None))
    vad._pending = np.zeros(0, dtype=np.float32)
    vad._silero_active = False
    vad._silent_frames = 0
    vad._silence_flush_frames = 20
    return vad


def test_size_cap_continues_speech_on_next_frame_without_resetting_silero():
    vad = fake_silero()
    frame = np.full(320, 0.1, dtype=np.float32)
    for _ in range(10):
        result = vad.ingest(frame)
        if result.force_flushed:
            break
    assert result.force_flushed
    vad._vad_iterator.reset_states.assert_not_called()
    next_result = vad.ingest(frame)
    assert next_result.speech_started
    assert next_result.speech_active
    # The next chunk retains the previous tail and the first new frame.
    np.testing.assert_array_equal(vad.current_audio(), np.concatenate([frame, frame]))


def test_end_of_speech_at_size_cap_still_resets_silero():
    vad = fake_silero()
    frame = np.full(320, 0.1, dtype=np.float32)
    vad._speech_active = True
    vad._silero_active = True
    vad._current = [frame.copy() for _ in range(4)]
    vad._pending = frame.copy()
    vad._vad_iterator.side_effect = None
    vad._vad_iterator.return_value = {"end": 0}
    result = vad.ingest(frame)
    assert result.force_flushed
    assert not vad._silero_active
    vad._vad_iterator.reset_states.assert_called_once()


def test_audio_commit_discards_previews_before_final_asr_has_completed():
    async def run():
        worker = MLXWorkerService()
        preview = asyncio.create_task(worker.submit_translate_text(
            "unfinished", "English", "Spanish", priority="partial", utterance_id=1))
        await asyncio.sleep(0)
        worker.finish_partials(1)
        assert await preview is None
        # A preview task that was waiting for model startup cannot rejoin the queue.
        assert await worker.submit_translate_text(
            "late preview", "English", "Spanish", priority="partial", utterance_id=1) is None
        final = asyncio.create_task(worker.submit_translate_text(
            "finished", "English", "Spanish", priority="final", utterance_id=1))
        await asyncio.sleep(0)
        assert worker._queue.get_nowait().payload["text"] == "finished"
        final.cancel()
        await asyncio.gather(final, return_exceptions=True)
    asyncio.run(run())


def test_commit_cancels_only_active_preview_for_that_utterance():
    worker = MLXWorkerService()
    worker._active_job = SimpleNamespace(
        kind="translate", sequence=17, payload={"priority": "partial", "utterance_id": 4})
    worker.finish_partials(3)
    assert worker._cancelled_job_id.value == -1
    worker.finish_partials(4)
    assert worker._cancelled_job_id.value == 17
    worker._active_job = SimpleNamespace(
        kind="translate", sequence=18, payload={"priority": "final", "utterance_id": 5})
    worker.finish_partials(5)
    assert worker._cancelled_job_id.value == 17


def test_cancelled_translation_returns_no_truncated_text_and_closes_stream(monkeypatch):
    import mlx_vlm
    import mlx_vlm.prompt_utils
    from mlx_worker import MLXWorker

    closed = []
    cancelled = [False]
    def tokens(*args, **kwargs):
        try:
            yield SimpleNamespace(text="partial")
            cancelled[0] = True
            yield SimpleNamespace(text=" unfinished")
        finally:
            closed.append(True)
    monkeypatch.setattr(mlx_vlm, "stream_generate", tokens)
    monkeypatch.setattr(mlx_vlm.prompt_utils, "apply_chat_template", lambda *a, **k: "prompt")
    worker = object.__new__(MLXWorker)
    worker.model = worker.processor = worker.config = None
    assert worker.translate_text("source", "English", "Spanish", cancelled=lambda: cancelled[0]) is None
    assert closed == [True]


def test_uncancelled_preview_returns_complete_streamed_translation(monkeypatch):
    import mlx_vlm
    import mlx_vlm.prompt_utils
    from mlx_worker import MLXWorker

    def tokens(*args, **kwargs):
        yield SimpleNamespace(text="Hola")
        yield SimpleNamespace(text=" mundo")
    monkeypatch.setattr(mlx_vlm, "stream_generate", tokens)
    monkeypatch.setattr(mlx_vlm.prompt_utils, "apply_chat_template", lambda *a, **k: "prompt")
    worker = object.__new__(MLXWorker)
    worker.model = worker.processor = worker.config = None
    progress = []
    assert worker.translate_text("hello world", "English", "Spanish", cancelled=lambda: False, on_progress=progress.append) == "Hola mundo"
    assert progress == ["Hola", "Hola mundo"]
