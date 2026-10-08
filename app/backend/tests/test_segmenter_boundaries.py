import numpy as np

from segmenter import FRAME_SAMPLES, RMSGate


def test_max_utterance_is_limited_to_29_seconds_below_gemma_window():
    assert RMSGate(max_utterance_s=29.0).max_utterance_frames == 29 * 50
    segmenter = RMSGate(max_utterance_s=30.0)
    frame = np.full(FRAME_SAMPLES, 0.1, dtype=np.float32)

    assert segmenter.max_utterance_frames == 29 * 50
    for index in range(segmenter.max_utterance_frames):
        result = segmenter.ingest(frame)
        assert result.force_flushed is (index == segmenter.max_utterance_frames - 1)

    assert result.audio is not None
    assert result.audio.size == 29 * 16_000


def test_size_rollover_repeats_only_the_configured_overlap_and_loses_no_frames():
    frames = [
        np.full(FRAME_SAMPLES, amplitude, dtype=np.float32)
        for amplitude in (0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4)
    ]
    segmenter = RMSGate(max_utterance_s=0.1, overlap_s=0.04)

    first_audio = None
    for frame in frames[:5]:
        result = segmenter.ingest(frame)
        if result.force_flushed:
            first_audio = result.audio

    assert first_audio is not None
    np.testing.assert_array_equal(first_audio, np.concatenate(frames[:5]))

    for frame in frames[5:8]:
        result = segmenter.ingest(frame)

    assert result.force_flushed
    assert result.audio is not None
    expected_second_audio = np.concatenate(frames[3:8])
    np.testing.assert_array_equal(result.audio, expected_second_audio)

    # Removing the two-frame overlap reconstructs the input exactly once.
    reconstructed = np.concatenate([first_audio, result.audio[2 * FRAME_SAMPLES :]])
    np.testing.assert_array_equal(reconstructed, np.concatenate(frames[:8]))


def test_size_cap_cuts_at_a_quiet_gap_without_repeating_or_losing_frames():
    loud = [np.full(FRAME_SAMPLES, 0.1 + i / 1000, dtype=np.float32) for i in range(30)]
    quiet = [np.full(FRAME_SAMPLES, 0.001, dtype=np.float32) for _ in range(4)]
    frames = loud[:20] + quiet + loud[20:26]
    segmenter = RMSGate(max_utterance_s=0.6, overlap_s=0.1)

    for frame in frames:
        result = segmenter.ingest(frame)
    assert result.force_flushed
    # The cut lands inside the gap; the speech after it starts the next chunk.
    cut = result.audio.size // FRAME_SAMPLES
    assert 20 < cut < 24
    later = [np.full(FRAME_SAMPLES, 0.2, dtype=np.float32) for _ in range(3)]
    for frame in later:
        segmenter.ingest(frame)
    reconstructed = np.concatenate([result.audio, segmenter.current_audio()])
    np.testing.assert_array_equal(reconstructed, np.concatenate(frames + later))


def test_size_cap_without_a_pause_keeps_the_configured_overlap():
    frames = [np.full(FRAME_SAMPLES, 0.1, dtype=np.float32) for _ in range(30)]
    segmenter = RMSGate(max_utterance_s=0.6, overlap_s=0.1)
    for frame in frames:
        result = segmenter.ingest(frame)
    assert result.force_flushed and result.audio.size == 30 * FRAME_SAMPLES
    segmenter.ingest(frames[0])
    assert segmenter.current_audio().size == 6 * FRAME_SAMPLES


def test_extended_cap_waits_for_a_dip_after_the_soft_cap():
    loud = [np.full(FRAME_SAMPLES, 0.1, dtype=np.float32) for _ in range(40)]
    quiet = [np.full(FRAME_SAMPLES, 0.001, dtype=np.float32) for _ in range(4)]
    frames = loud[:35] + quiet + loud[35:]
    segmenter = RMSGate(max_utterance_s=0.6, overlap_s=0.1, cap_extend_s=0.2)

    flushed = []
    for frame in frames:
        result = segmenter.ingest(frame)
        if result.force_flushed:
            flushed.append(result)
    # No flush at the 30-frame soft cap; the cut lands in the dip at 35-38 instead.
    assert len(flushed) == 1
    cut = flushed[0].audio.size // FRAME_SAMPLES
    assert 35 < cut < 39
    reconstructed = np.concatenate([flushed[0].audio, segmenter.current_audio()])
    np.testing.assert_array_equal(reconstructed, np.concatenate(frames))


def test_extended_cap_forces_the_cut_at_the_hard_cap():
    frames = [np.full(FRAME_SAMPLES, 0.1, dtype=np.float32) for _ in range(50)]
    segmenter = RMSGate(max_utterance_s=0.6, overlap_s=0.1, cap_extend_s=0.2)
    for index, frame in enumerate(frames):
        result = segmenter.ingest(frame)
        assert result.force_flushed is (index == 39)
        if result.force_flushed:
            assert result.audio.size == 40 * FRAME_SAMPLES


def test_extended_cap_never_exceeds_the_gemma_window():
    assert RMSGate(max_utterance_s=28.0, cap_extend_s=5.0).hard_max_utterance_frames == 29 * 50


def test_pause_mode_skips_a_word_gap_and_cuts_at_a_phrase_pause():
    loud = [np.full(FRAME_SAMPLES, 0.1, dtype=np.float32) for _ in range(40)]
    gap = [np.full(FRAME_SAMPLES, 0.001, dtype=np.float32) for _ in range(3)]
    pause = [np.full(FRAME_SAMPLES, 0.001, dtype=np.float32) for _ in range(12)]
    frames = loud[:25] + gap + loud[25:32] + pause + loud[32:]
    segmenter = RMSGate(max_utterance_s=0.6, overlap_s=0.1, cap_extend_s=0.4, cap_pause_ms=200)

    flushed = [r for r in map(segmenter.ingest, frames) if r.force_flushed]
    # The 60 ms gap at 25-27 is inside the soft-cap window but too short.
    assert len(flushed) == 1
    cut = flushed[0].audio.size // FRAME_SAMPLES
    assert 35 < cut < 47
    np.testing.assert_array_equal(flushed[0].audio, np.concatenate(frames[:cut]))


def test_pause_mode_falls_back_to_the_quietest_point_at_the_hard_cap():
    loud = [np.full(FRAME_SAMPLES, 0.1, dtype=np.float32) for _ in range(50)]
    gap = [np.full(FRAME_SAMPLES, 0.001, dtype=np.float32) for _ in range(4)]
    frames = loud[:33] + gap + loud[33:]
    segmenter = RMSGate(max_utterance_s=0.6, overlap_s=0.1, cap_extend_s=0.2, cap_pause_ms=200)
    flushed = [r for r in map(segmenter.ingest, frames) if r.force_flushed]
    cut = flushed[0].audio.size // FRAME_SAMPLES
    assert 33 < cut < 37
