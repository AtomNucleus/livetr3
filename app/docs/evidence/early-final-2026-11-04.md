# Early final decode at pauses — 2026-11-04

**Pause finals now start decoding 300 ms into the pause instead of after
Silero confirms it.** On the three-set scoreboard, pause finals (`silero_end`,
89% of live finals) come 0.06 s sooner at the median and 0.15 s sooner at
p95. WER, chrF++ and caption-growth gaps match the flag-off passes.
`LIVETR3_EARLY_FINAL=0` restores the old path.

## Why

Before this change a pause final waited for 600 ms of silence. Then the session
cancelled the running preview and decoded the whole utterance again, about
0.7–1.0 s at the median. The decoded-prefix shortcut covers only chunks near the
6 s cap: 0.2% of live finals.

Previews already decode trimmed audio: voiced frames (frame RMS ≥ 0.0006)
plus a 300 ms pad on each side. Once a pause reaches 300 ms, that trimmed
audio stops changing. Decoding is greedy, and MTP drafting doesn't change
the output, so a final decode started then gives the result the commit would
compute.

## What changed

- `session.py`:
  - Each speech frame updates a quiet-frame count. At 15 quiet frames (the
    trim pad), the session submits a final decode of the trimmed audio as an
    *early final*.
  - When Silero ends the utterance, the commit takes the early decode if its
    audio is bit-identical to the commit's trimmed audio and its result is
    complete. Otherwise it cancels the early decode and decodes as before.
  - A voiced frame before the commit (speech resumed) cancels the early decode.
  - Pause finals (`silero_end`, including Stop and Commit now) decode the
    trimmed audio, as previews and decoded-prefix finals already did. Cap
    finals still decode untrimmed audio.
  - Low-energy skips and decoded-prefix commits cancel any early decode.
  - Trace rows: `early_final` with event `start`, `used`, `resumed` or
    `mismatch`.
- `mlx_worker.py`:
  - An early final is a final-priority job that stays cancellable.
  - It replaces any queued preview of its utterance, but lets a running
    preview finish (see version D below).
  - The commit's `finish_partials` leaves it alone, and `cancel_early_final()`
    drops it.
- Tests: `tests/test_early_final.py`. `test_trailing_silence_does_not_start_preview_before_imminent_final`
  now expects the trimmed final audio.

## Scoreboard

The setup matches the 2026-10-27 baseline: `gemma-4-e4b-it-8bit` with MTP,
mlx-vlm 0.7.4, M1 Pro 32 GB, native defaults (6 s cap, 2 s / 200 ms extension,
600 ms silence). Outputs are in ignored `dist/logs/scoreboard/early-final-2026-11-04/`.
Passes ran in this order: A1 off, B1 on, B2 on, A2 off, C1, C2, D1, D2.

Three versions were tried:

- **B:** an early start cancels a running preview of the same utterance, and
  resumed speech cancels the early decode.
- **C:** like B, but a resumed early decode runs on as a preview.
- **D (shipped):** like B, but an early start lets a running preview finish.

Pooled rows. "Live" latency reweights finals to the live commit mix.

| Pass | WER | chrF++ | live lat med / p95 (s) | pause final med / p95 (s) | gaps > 2 s |
| --- | ---: | ---: | --- | --- | ---: |
| A1 off | 4.72% | 55.7 | 1.63 / 36.02 | 1.56 / 36.02 | 148 |
| A2 off | 4.69% | 55.4 | 1.54 / 2.46 | 1.48 / 2.38 | 139 |
| B1 | 4.69% | 55.4 | 1.40 / 2.27 | 1.33 / 2.14 | 162 |
| B2 | 4.69% | 55.4 | 1.40 / 2.30 | 1.34 / 2.14 | 162 |
| C1 | 4.69% | 55.8 | 1.51 / 2.56 | 1.38 / 2.41 | 153 |
| C2 | 4.69% | 55.8 | 1.50 / 2.58 | 1.42 / 2.45 | 147 |
| D1 | 4.66% | 55.3 | 1.51 / 2.34 | 1.43 / 2.23 | 136 |
| D2 | 4.69% | 55.4 | 1.49 / 2.44 | 1.41 / 2.24 | 138 |

"Pause final" is time from the last audio frame to the published
`silero_end` final, over all three sets. "Gaps > 2 s" counts waits over
2 s between additions of Spanish words the final keeps.

- **B** was fastest: pause finals came 0.15 s sooner at the median and 0.24 s at p95.
  But sermon-v2 gaps rose from 61 to 83, and gaps within one utterance from 9
  to 25–27. An early start cancelled the preview that was showing text. When
  speech resumed (122 of about 256 early starts), the early decode was dropped
  too, so the screen got nothing new until a later preview finished.
- **C** recovered only part of the gaps (sermon-v2: 74). It kept the worker
  busy with a stale prefix while speech went on, and pause-final p95 rose to
  2.41–2.45 s, worse than off.
- **D** brings gaps back to the flag-off level (sermon-v2: 61 and 65, within-utterance
  15 and 14). It keeps part of the gain: 1.48 → 1.41–1.43 s median, 2.38 →
  2.23–2.24 s p95. Cap and decoded-prefix finals are unchanged.

Early decodes in D, summed over the three sets per pass: 255–258 starts, 121–122
resumed, 128–129 used, 5 mismatched. That covers 62% of the 208–209
`silero_end` commits: 18/18 on sermon-v1, 94–95 of 143–144 on sermon-v2,
16/47 on FLEURS.

Text scores are unchanged, so trimming the pause finals' audio cost nothing.
WER is 4.69% in every pass except A1 (4.72%: one extra sermon-v2 error during
the stall below) and D1 (4.66%).

Time-of-run drift on this machine is about 0.1 s between passes. B and D were
not run in ABBA order against each other, so the B-to-D difference is
approximate. The D-to-off difference rests on A2 alone, the closer clean off
pass.

### The A1 stall

A1, flag off, so the old path, stalled for 64 s in sermon-v2 clip-03. A
preview was dispatched and nothing came back. The next `ast_decode` was a
warmup (token budget 8), so the worker was reloaded. Twenty finals then queued for
up to 63 s. That is a worker hang independent of this change, and the reason
A1 is left out of the comparison. The likely cause is an unrelated workload
running on the machine during that pass. Replays don't keep the engine's
stdout, so this can't be confirmed from the logs.

## Limits

- An early decode needs 15 frames below frame RMS 0.0006 in a row. A room whose noise
  floor sits above that never triggers one and gets the old behavior. On
  FLEURS only 16 of 47 pause commits used one: 30–31 of its 49 starts were
  cancelled by resumed speech, and the other pause commits had no early
  decode left at the commit. Live archives keep no audio, so the live noise
  floor is unknown.
- Pauses of 300–600 ms inside a sentence start an early decode that speech
  then cancels (about 47% of starts). Each costs up to one uncancellable
  prefill, about 0.4 s of worker time.
- Live gains need live data. After the everyday build is rebuilt, recompute
  final latency from the session archives against the 2026-10-27 baseline
  (1.3 s median, 2.42 s p95).
