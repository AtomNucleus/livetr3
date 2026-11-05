# Noisy-room early decode, warm-up and empty finals — 2026-11-05

**Pause finals in a noisy room now come 0.17 s sooner at the median.** The
early final decode (2026-11-04) starts on 99% of pause finals instead of 47%.
Pooled WER on the three-set scoreboard is 4.69%, the same as main.

## Test

A licensed 22-minute sermon window (live recording with room noise; the
audio stays local) streamed in real time through `TranscriptionSession`, one
fresh engine per pass, ABBA: main (ad19cc0) vs this branch, 6 s cap, 600 ms
silence.

| | main A1 / A2 | branch B1 / B2 |
|---|---|---|
| Final latency, median | 1.65 / 1.64 s | 1.58 / 1.58 s |
| Final latency, p95 | 2.43 / 2.38 s | 2.39 / 2.36 s |
| Live-mix weighted median | 1.44 / 1.43 s | 1.32 / 1.31 s |
| Pause finals (`silero_end`), median | 1.38 / 1.39 s | 1.21 / 1.21 s |
| Early decode used | 73 / 73 of 156 | 156 / 155 of 156 |
| Caption gaps > 3 s with ≥ 1 s of speech | 23 / 22 | 28 / 27 |
| Errors | 0 / 0 | 0 / 0 |

Cap finals are unchanged. The gaps over 3 s rise slightly because the early
decode now runs twice as often (300 starts vs 143, 133 cancelled when speech
resumed). Gap causes match in both arms: about 70 of 90 gaps fall while a
final decodes. B1's 9.8 s gap is a page-turn pause; its finals are identical
to A1's.

## What changed

- **Quiet means Silero quiet.** Room noise kept frame RMS above 0.0006, so
  the quiet-frame count that starts the early decode rarely reached 300 ms.
  `SileroVAD` now marks a frame quiet once Silero's speech probability has
  dropped below threshold − 0.15 (`temp_end` set) or a silent frame was
  counted. The session treats a frame as quiet on either signal.
- **Deterministic cut.** At 300 ms of quiet the session records the
  utterance length. The pause final decodes the trimmed audio up to that
  point, so the early decode's audio and the commit's audio match even when
  noise keeps arriving until Silero ends the utterance.
- **Warm-up at Start.** After the worker starts, one 1 s silent decode with
  8 tokens runs, so the first real caption after a long idle doesn't pay the
  GPU clock ramp. On the replay the first decode was already warm, so this
  doesn't show in the table above.
- **Empty finals.** A final that stops (not truncated) with no English text
  is logged and dropped, not retried and shown as an error. Finals are only
  retried when truncated: decoding is greedy, so a stopped final would come
  out the same.

## 5 s cap: not adopted

The same sermon ABBA at 5 s vs 6 s cap: final latency 1.52 vs 1.66 s median,
2.17 vs 2.41 s p95, gaps over 3 s 13 vs 21, cut points no choppier. But the
scoreboard at 5 s raised pooled WER from 4.69% to 5.46%, worse on every set
(FLEURS 7.92 → 9.02%, sermon-v1 3.01 → 3.76%, sermon-v2 2.46 → 2.99%), with
more errors near cuts (92 → 110). The cap stays at 6 s.
