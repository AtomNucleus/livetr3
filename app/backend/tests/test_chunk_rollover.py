from collections import deque
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
    vad._speech_rms = deque(maxlen=1450)
    vad._end_event_pending = False
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


def test_quiet_speech_is_not_flushed_as_digital_silence():
    vad = fake_silero()
    vad.max_utterance_frames = 1000
    quiet_speech = np.full(320, 0.0005, dtype=np.float32)
    for _ in range(60):
        result = vad.ingest(quiet_speech)
    assert result.speech_active and not result.speech_ended
    silence = np.full(320, 0.00001, dtype=np.float32)
    for _ in range(20):
        result = vad.ingest(silence)
    assert result.speech_ended


def test_loud_speech_keeps_the_absolute_silence_flush_level():
    vad = fake_silero()
    vad.max_utterance_frames = 1000
    for _ in range(30):
        vad.ingest(np.full(320, 0.1, dtype=np.float32))
    for _ in range(20):
        result = vad.ingest(np.full(320, 0.0009, dtype=np.float32))
    assert result.speech_ended


def short_join_silero(events, join_frames=30, hold_frames=10):
    """events maps a frame index to the Silero event seen while ingesting it."""
    vad = fake_silero()
    vad.max_utterance_frames = vad.hard_max_utterance_frames = 1000
    vad.trailing_silence_frames = 5
    vad._base_trailing_silence_frames = 5
    vad.min_utterance_frames = 1
    vad._short_join_frames, vad._short_join_hold_frames, vad._holding = join_frames, hold_frames, False
    vad.frame, seen = 0, set()

    def iterator(*args, **kwargs):
        if vad.frame in seen:
            return None
        seen.add(vad.frame)
        return events.get(vad.frame)

    vad._vad_iterator.side_effect = iterator
    return vad


def run(vad, frames):
    results = []
    for index, frame in enumerate(frames):
        vad.frame = index
        vad._pending = np.zeros(512, dtype=np.float32)  # one detector step per frame
        results.append(vad.ingest(frame))
    return results


SPEECH = np.full(320, 0.1, dtype=np.float32)
QUIET = np.zeros(320, dtype=np.float32)


def test_short_utterance_waits_for_the_hold_then_commits_alone():
    vad = short_join_silero({0: {"start": 0}, 4: {"end": 0}})
    results = run(vad, [SPEECH] * 4 + [QUIET] * 14)
    ended = [i for i, r in enumerate(results) if r.speech_ended]
    assert ended == [4 + 9]  # the hold is 10 silent frames, counting the end-event frame
    assert results[ended[0]].audio.size == 14 * 320
    assert not vad._holding and vad.trailing_silence_frames == 5
    vad._vad_iterator.reset_states.assert_called()


def test_speech_resuming_in_the_hold_joins_the_same_utterance():
    vad = short_join_silero({0: {"start": 0}, 4: {"end": 0}, 8: {"start": 0}, 15: {"end": 0}},
                            join_frames=12)
    results = run(vad, [SPEECH] * 4 + [QUIET] * 4 + [SPEECH] * 7 + [QUIET] * 8)
    assert sum(r.speech_started for r in results) == 1
    ended = [i for i, r in enumerate(results) if r.speech_ended]
    # The joined utterance is past join_frames, so its end commits at once.
    assert ended == [15] and results[15].audio.size == 16 * 320
    assert not vad._holding and vad.trailing_silence_frames == 5


def test_long_utterance_ends_without_a_hold():
    vad = short_join_silero({0: {"start": 0}, 8: {"end": 0}}, join_frames=5)
    results = run(vad, [SPEECH] * 8 + [QUIET] * 3)
    assert [i for i, r in enumerate(results) if r.speech_ended] == [8]


def test_a_fragment_below_the_minimum_is_still_dropped_without_a_hold():
    vad = short_join_silero({0: {"start": 0}, 4: {"end": 0}})
    vad.min_utterance_frames = 10
    results = run(vad, [SPEECH] * 4 + [QUIET] * 14)
    assert not any(r.speech_ended for r in results)
    assert not vad._holding and not vad.speech_active
