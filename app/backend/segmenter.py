from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import sqrt

import numpy as np

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 320
MAX_UTTERANCE_SECONDS = 29.0
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE
# A size cap is not a pause. Cut at the quietest point in the last second instead,
# so neither side of the seam re-transcribes (duplicates) or splits a word.
CAP_CUT_SEARCH_FRAMES = 50
CAP_CUT_QUIET_RATIO = 0.25
# The digital-silence flush is relative to the speaker so quiet speech is not
# mistaken for a pause; it never exceeds the original absolute level.
SILENCE_FLUSH_MAX_RMS = 0.001
SILENCE_FLUSH_LEVEL_RATIO = 0.1


@dataclass(slots=True)
class SegmentResult:
    rms: float
    speech_active: bool
    speech_started: bool = False
    speech_ended: bool = False
    force_flushed: bool = False
    audio: np.ndarray | None = None


class RMSGate:
    """Zero-dependency streaming utterance segmenter for 20 ms 16 kHz float32 frames."""

    def __init__(
        self,
        threshold: float = 0.01,
        trailing_silence_ms: int = 400,
        min_utterance_ms: int = 800,
        max_utterance_s: float = 25.0,
        overlap_s: float = 0.5,
        cap_extend_s: float = 0.0,
        cap_pause_ms: int = 0,
    ) -> None:
        self.threshold = threshold
        self.trailing_silence_frames = max(1, trailing_silence_ms // 20)
        self.min_utterance_frames = max(1, min_utterance_ms // 20)
        # Gemma's audio window is 30 seconds; keep segment boundaries below it so
        # no caller can hand the worker a chunk that needs to be silently trimmed.
        safe_max_utterance_s = min(float(max_utterance_s), MAX_UTTERANCE_SECONDS)
        self.max_utterance_frames = max(1, int(safe_max_utterance_s / FRAME_SECONDS))
        # Past the cap, wait up to cap_extend_s for a brief dip before forcing a
        # cut through continuous speech, which splits or repeats a word.
        safe_hard_cap_s = min(safe_max_utterance_s + max(0.0, float(cap_extend_s)), MAX_UTTERANCE_SECONDS)
        self.hard_max_utterance_frames = max(self.max_utterance_frames, int(safe_hard_cap_s / FRAME_SECONDS))
        self.overlap_frames = max(0, int(overlap_s / 0.02))
        self.cap_pause_frames = max(0, int(cap_pause_ms) // 20) if cap_extend_s > 0 else 0
        self._pre_roll: deque[np.ndarray] = deque(maxlen=self.overlap_frames)
        self._current: list[np.ndarray] = []
        self._speech_active = False
        self._below_threshold_frames = 0

    @property
    def speech_active(self) -> bool:
        return self._speech_active

    def current_audio(self) -> np.ndarray:
        if not self._current:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self._current).astype(np.float32, copy=False)

    def split_decoded_prefix(self, prefix: np.ndarray) -> bool:
        """Retire an exact decoded prefix, retaining overlap and all newer audio.

        This is a chunk boundary during speech, so detector state, pending VAD
        samples and trailing-silence counters must survive it.
        """
        if not self._speech_active or not prefix.size or prefix.size % FRAME_SAMPLES:
            return False
        current = self.current_audio()
        if prefix.size > current.size or not np.array_equal(prefix, current[:prefix.size]):
            return False
        boundary = prefix.size // FRAME_SAMPLES
        self._current = self._current[max(0, boundary - self.overlap_frames):]
        return True

    def _cap_cut(self) -> tuple[int, int] | None:
        """Frames to flush at the size cap and frames of overlap to repeat, or
        None to keep listening for a pause until the hard cap."""
        frames = len(self._current)
        if self._cap_is_end_of_speech():
            return frames, 0
        rms = np.sqrt(np.mean(np.square(np.stack(self._current)), axis=1))
        quiet = CAP_CUT_QUIET_RATIO * float(np.median(rms))
        start = max(frames // 2, frames - CAP_CUT_SEARCH_FRAMES)
        if self.cap_pause_frames and frames < self.hard_max_utterance_frames:
            # Before the hard cap, only a phrase pause will do: a gap between
            # words still splits the sentence the model needs to translate.
            run = 0
            for index in range(frames - 1, start - 1, -1):
                run = run + 1 if rms[index] <= quiet else 0
                if run >= self.cap_pause_frames:
                    end = index + run
                    while end < frames and rms[end] <= quiet:
                        end += 1
                    return (index + end) // 2, 0
            return None
        local = lambda cut: float(np.mean(rms[max(0, cut - 2):cut + 2]))
        if frames > self.max_utterance_frames and not self.cap_pause_frames:
            # Already searched up to the soft cap; only the newest cut point is new.
            cut = frames - 2
        else:
            # Ties keep the latest cut, i.e. the longest chunk.
            cut = min(range(frames, start - 1, -1), key=local)
        if local(cut) <= quiet:
            return cut, 0
        if frames < self.hard_max_utterance_frames:
            return None
        return frames, self.overlap_frames

    def _cap_is_end_of_speech(self) -> bool:
        return False

    def reset(self) -> None:
        tail = self._current[-self.overlap_frames :] if self.overlap_frames else []
        self._pre_roll = deque((x.copy() for x in tail), maxlen=self.overlap_frames)
        self._current = []
        self._speech_active = False
        self._below_threshold_frames = 0

    def _rollover(self) -> None:
        self.reset()

    def ingest(self, frame: np.ndarray) -> SegmentResult:
        frame = _coerce_frame(frame)
        rms = float(sqrt(float(np.mean(np.square(frame)))))
        is_speech = rms > self.threshold
        speech_started = False
        speech_ended = False
        force_flushed = False
        audio: np.ndarray | None = None

        if not self._speech_active:
            if is_speech:
                speech_started = True
                self._speech_active = True
                self._below_threshold_frames = 0
                self._current = [x.copy() for x in self._pre_roll]
                self._current.append(frame)
            else:
                self._pre_roll.append(frame)
            return SegmentResult(
                rms=rms,
                speech_active=self._speech_active,
                speech_started=speech_started,
            )

        self._current.append(frame)
        if is_speech:
            self._below_threshold_frames = 0
        else:
            self._below_threshold_frames += 1

        cap_cut = self._cap_cut() if len(self._current) >= self.max_utterance_frames else None
        if cap_cut is not None:
            cut, overlap = cap_cut
            audio = np.concatenate(self._current[:cut]).astype(np.float32, copy=False)
            carry = self._current[max(0, cut - overlap):]
            force_flushed = True
            speech_ended = True
            self._rollover()
            self._pre_roll = deque(carry, maxlen=max(self.overlap_frames, len(carry)))
        elif self._below_threshold_frames >= self.trailing_silence_frames:
            if len(self._current) >= self.min_utterance_frames:
                audio = self.current_audio()
                speech_ended = True
            self.reset()

        return SegmentResult(
            rms=rms,
            speech_active=self._speech_active,
            speech_started=speech_started,
            speech_ended=speech_ended,
            force_flushed=force_flushed,
            audio=audio,
        )


class SileroVAD(RMSGate):
    """Silero-backed VAD with the same streaming output contract as RMSGate."""

    def __init__(
        self,
        threshold: float = 0.5,
        speech_pad_ms: int = 300,
        min_silence_ms: int = 400,
        min_utterance_ms: int = 800,
        max_utterance_s: float = 25.0,
        cap_extend_s: float = 0.0,
        cap_pause_ms: int = 0,
    ) -> None:
        super().__init__(
            threshold=0.01,
            trailing_silence_ms=min_silence_ms,
            min_utterance_ms=min_utterance_ms,
            max_utterance_s=max_utterance_s,
            overlap_s=speech_pad_ms / 1000,
            cap_extend_s=cap_extend_s,
            cap_pause_ms=cap_pause_ms,
        )
        try:
            import torch
            from silero_vad import VADIterator, load_silero_vad
        except Exception as exc:  # pragma: no cover - only hit when optional deps are absent
            raise RuntimeError(
                "Silero VAD requested, but silero-vad/torch is not available. "
                "Install backend dependencies with uv sync."
            ) from exc

        self._torch = torch
        self._vad_iterator = VADIterator(
            load_silero_vad(),
            threshold=threshold,
            sampling_rate=SAMPLE_RATE,
            min_silence_duration_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
        )
        self._pending = np.zeros(0, dtype=np.float32)
        self._silero_active = False
        self._silence_flush_frames = max(1, min_silence_ms // 20)
        self._silent_frames = 0
        self._speech_rms: deque[float] = deque(maxlen=int(MAX_UTTERANCE_SECONDS / FRAME_SECONDS))
        self._end_event_pending = False

    def reset(self) -> None:
        super().reset()
        self._silero_active = False
        self._silent_frames = 0
        self._speech_rms.clear()
        try:
            self._vad_iterator.reset_states()
        except AttributeError:
            pass

    def _cap_is_end_of_speech(self) -> bool:
        # Nothing follows a real end of speech, so carry nothing past it.
        return self._end_event_pending

    def _rollover(self) -> None:
        # A size limit is not end-of-speech. Carry the detector state and pending
        # samples into the next chunk; RMSGate.ingest then sets the carried audio.
        RMSGate.reset(self)

    def ingest(self, frame: np.ndarray) -> SegmentResult:
        frame = _coerce_frame(frame)
        rms = float(sqrt(float(np.mean(np.square(frame)))))
        self._pending = np.concatenate([self._pending, frame])
        event: dict | None = None
        while self._pending.shape[0] >= 512:
            chunk = self._pending[:512]
            self._pending = self._pending[512:]
            tensor = self._torch.from_numpy(chunk)
            maybe_event = self._vad_iterator(tensor, return_seconds=False)
            if maybe_event:
                event = maybe_event

        parent_threshold = self.threshold
        if event and "start" in event:
            self._silero_active = True
            self._silent_frames = 0
        if self._silero_active:
            self._speech_rms.append(rms)
            level = float(np.percentile(self._speech_rms, 90))
            silence = min(SILENCE_FLUSH_MAX_RMS, SILENCE_FLUSH_LEVEL_RATIO * level)
            self._silent_frames = self._silent_frames + 1 if rms <= silence else 0
        else:
            self._silent_frames = 0
        end_event = bool(event and "end" in event) or (
            self._silero_active and self._silent_frames >= self._silence_flush_frames
        )
        active_for_parent = self._silero_active
        self.threshold = -1.0 if active_for_parent else 2.0
        self._end_event_pending = end_event
        try:
            result = super().ingest(frame)
        finally:
            self.threshold = parent_threshold
            self._end_event_pending = False
        if end_event and result.force_flushed:
            # Real end-of-speech on the cap frame still resets the detector.
            self.reset()
        if end_event and not result.speech_ended:
            audio = self.current_audio()
            speech_ended = len(self._current) >= self.min_utterance_frames
            self.reset()
            return SegmentResult(
                rms=result.rms,
                speech_active=False,
                speech_started=result.speech_started,
                speech_ended=speech_ended,
                audio=audio if speech_ended else None,
            )
        return result


def make_segmenter(
    name: str,
    rms_threshold: float = 0.01,
    *,
    silero_threshold: float = 0.5,
    speech_pad_ms: int = 300,
    min_silence_ms: int = 400,
    max_utterance_s: float = 25.0,
    cap_extend_s: float = 0.0,
    cap_pause_ms: int = 0,
) -> RMSGate:
    if name == "silero":
        return SileroVAD(
            threshold=silero_threshold,
            speech_pad_ms=speech_pad_ms,
            min_silence_ms=min_silence_ms,
            max_utterance_s=max_utterance_s,
            cap_extend_s=cap_extend_s,
            cap_pause_ms=cap_pause_ms,
        )
    raise ValueError("Only the Silero VAD segmenter is enabled for this build.")


def _coerce_frame(frame: np.ndarray) -> np.ndarray:
    frame = np.asarray(frame, dtype=np.float32).reshape(-1)
    if frame.shape[0] != FRAME_SAMPLES:
        raise ValueError(f"Expected {FRAME_SAMPLES} samples per frame, got {frame.shape[0]}")
    return np.clip(frame, -1.0, 1.0).astype(np.float32, copy=False)
