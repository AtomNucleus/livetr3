from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

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


def test_decoded_prefix_split_retains_silero_state_pending_samples_and_every_tail_frame():
    vad = fake_silero()
    vad.max_utterance_frames = 300
    frames = [np.full(320, .05 + i / 100, dtype=np.float32) for i in range(8)]
    for frame in frames[:5]:
        vad.ingest(frame)
    snapshot = vad.current_audio().copy()
    for frame in frames[5:]:
        vad.ingest(frame)
    pending = vad._pending.copy()
    silent_frames = vad._silent_frames
    assert vad.split_decoded_prefix(snapshot)
    np.testing.assert_array_equal(vad.current_audio(), np.concatenate(frames[4:]))
    np.testing.assert_array_equal(vad._pending, pending)
    assert vad._silero_active and vad.speech_active
    assert vad._silent_frames == silent_frames
    vad._vad_iterator.reset_states.assert_not_called()
    reconstructed = np.concatenate([snapshot, vad.current_audio()[320:]])
    np.testing.assert_array_equal(reconstructed, np.concatenate(frames))
