# Chunk-limit comparison — 2026-10-01

Keep the native six-second cap. At native defaults, eight and twelve seconds did not produce a repeatable cadence improvement or recover any missing source words. No runtime settings were changed.

## Native-default backend replay

Main at `dba59dcf33a9abadd7a9541c0a900a017818acd0`, with the quiet-boundary fix enabled in every condition. One real Gemma worker was loaded, reported `Model worker ready`, performed its model warmup and a full unscored replay, then ran caps in the order **6, 8, 12, 12, 8, 6**. The retained private 51.467-second recording and human source reference were replayed at 20 ms/frame with two seconds of trailing silence. All audio, reference text and generated captions remain in ignored local artifacts.

Native `ClientConfig.default` was checked against the experiment: 250 ms previews, **150 ms silence**, 300 ms overlap, Silero threshold 0.5, polish/code switching/early commit disabled, English to Spanish, empty custom vocabulary. The earlier boundary-handoff replay used **400 ms silence**; its figures are not a native-default baseline. Model and prompt stayed fixed: `mlx-community/gemma-4-e4b-it-8bit`, cached revision `4255b21bd9a9d3fc807ef7abd80373f5e3a52a73`, `mlx-vlm 0.7.3`, `mlx 0.32.2`.

| Run/cap | Gaps >2 s | p95 gap (s) | Worst gap (s) | First target (s) | Drain after feed (s) | Last final after clip (s) | Forced / reused | Source errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 01-6s | 3 | 1.494 | 3.463 | 1.246 | 0.000 | 0.448 | 0 / 0 | 19 / 133 |
| 02-8s | 4 | 1.585 | 3.073 | 1.291 | 0.000 | 0.593 | 0 / 0 | 19 / 133 |
| 03-12s | 3 | 1.419 | 3.304 | 1.282 | 0.000 | 0.639 | 0 / 0 | 19 / 133 |
| 04-12s | 3 | 1.485 | 8.603 | 1.249 | 5.330 | 7.728 | 0 / 0 | 19 / 133 |
| 05-8s | 7 | 2.018 | 4.692 | 0.991 | 0.607 | 2.604 | 0 / 0 | 19 / 133 |
| 06-6s | 2 | 1.505 | 2.915 | 1.254 | 0.000 | 0.604 | 0 / 0 | 19 / 133 |

The primary cadence metric matches the earlier evidence: an event counts only when nonempty target text exceeds that utterance’s previous maximum character length. Repeated full hypotheses do not count. Rewrites, substitutions, inserted text and repeated overlap can still increase length, so this is **hypothesis growth**, not verified new useful Spanish words. Equal-length corrections are excluded. Initial source-only generation is represented by time to first target, not an inter-target gap.

A conservative secondary metric counts increasing whole-word counts, omitting the unfinished last word of a partial. It still measures hypothesis growth and can count rewritten or overlapping words.

| Run/cap | Word-growth gaps >2 s | Word-growth p95 (s) | Word-growth worst (s) | First whole-word growth (s) |
| --- | ---: | ---: | ---: | ---: |
| 01-6s | 3 | 1.545 | 3.506 | 3.063 |
| 02-8s | 4 | 1.670 | 3.153 | 3.057 |
| 03-12s | 3 | 1.587 | 3.304 | 3.210 |
| 04-12s | 3 | 1.504 | 8.603 | 2.982 |
| 05-8s | 8 | 2.076 | 4.692 | 3.088 |
| 06-6s | 2 | 1.532 | 2.965 | 4.077 |

Feed-end drain includes flushing the active chunk and waiting for every pending job after the padded input ends. Last-final-after-clip separately reports delay from the original recording’s end, so the two-second padding cannot hide a late final. All six runs produced 20 complete, nonempty finals with unique IDs and no error messages. Different runs use disjoint IDs because the shared worker remembers finalized IDs for preview cancellation.

## Why a larger cap did not help

Every commit was `silero_end`; the largest decoded audio chunk was 5.2 seconds. None reached even the six-second cap, and none reused a decoded prefix. Thus this recording at native silence settings does not exercise forced cap boundaries. All six runs produced identical source text, even though inference/preview timing varied. The twelve-second reverse run had an 8.603-second gap and 5.330-second drain, so selecting it from the slightly lower p95 in the forward run would hide a longer stall. Eight seconds also failed to improve both orders. These observations do not establish that the cap caused those timing differences.

Safe quiet-boundary reuse requires a complete preview covering at least half the cap: 3, 4 or 6 seconds respectively. Increasing the cap delays that eligibility and can remove beneficial early handoffs, even when it reduces forced final decodes on other recordings. At 150 ms silence the short chunks in this clip provided no such handoffs at any cap.

## Source coverage and limits

Word scoring matches the existing reference scorer: Unicode word tokens, case/punctuation ignored, contractions split, finals joined in order without overlap deduplication. Each run scored **8 substitutions, 11 deletions, 0 insertions / 133 reference tokens**. Eleven errors were within two hypothesis tokens of a final boundary; this proximity is diagnostic, not proof that segmentation caused every error. Alignment and per-final text are retained locally for inspection. There was no added overlap repetition scored as an insertion; the same dropped phrase words occurred under every cap. The source negation was retained. The recording has no explicit numeric quantities, so quantity preservation is untested. No human Spanish reference was available.

This is paced **backend replay**, including the real segmenter/session/model worker. It does not measure native socket delivery, visible SwiftUI caption cadence, live microphone behavior or a physical projector. Frame-conservation/rollover/preview/handoff checks passed (35 focused backend tests), as did known scoring edits, repeated-hypothesis exclusion and Python compilation. The user stopped capture before replay; the existing app/processes and untracked `app/backend/validation/` were preserved. A separate `livetra` model worker started at 02:15:47, after the last scored native-default event at 02:15:35; additional inference was held to avoid competition.

## Reproduction

Use the backend virtual environment, set `PYTHONPATH=app/backend`, and run `script/chunk_limit_replay.py` with `--audio`, `--reference` and an ignored `--output` directory. Its default order is `6,8,12,12,8,6`; native silence is 150 ms. `--silence-ms 400` reproduces the earlier replay configuration while holding the other settings constant. Stop live capture first; the harness refuses to run when a UDS or legacy server model worker exists and aborts if one appears during replay.

Raw scored events, traces, model/config metadata and private source alignments: `dist/logs/chunk-limit-2026-10-01/native-defaults/`. The preliminary top-level warmup artifacts are unscored and are not used above.

## Completed follow-up

The matched 150/300/400 ms and 400 ms cap comparisons, isolated native file replay, and opt-in 400 ms test build are documented in [silence-threshold-comparison-2026-10-01.md](silence-threshold-comparison-2026-10-01.md). The six-second cap remains preferred; 400 ms is a live-test candidate with a measured coverage versus pause-latency tradeoff, not a normal-default change.
