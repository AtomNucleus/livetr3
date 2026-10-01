# Ordinary-ending preview reuse experiment — 2026-10-01

Keep the experiment default-off. A warmed real-Gemma forward/reverse comparison reused **zero ordinary endings** in both candidate runs, so it establishes no reuse-driven latency improvement. Source coverage stayed unchanged, but cadence varied and the first candidate had a higher p95 and more pauses than its baseline. The focused implementation remains available with `LIVETR3_ENDING_PREVIEW_REUSE=1`; it is not a promoted fluidity improvement.

## Exact coverage and race handling

Each utterance can retain one complete, nontruncated bilingual preview with its raw snapshot, decoded input, deep-copied configuration and configuration revision. At an ordinary ending or explicit flush, reuse requires the same active utterance, running session, no pending configuration, current configuration/revision, nonempty source and target, an exact raw prefix and decoded-input equality with the committed audio's existing transcribable window. Newer nonzero samples require a fresh decode even when their energy is below the speech threshold. This last conservative guard protects quiet speech beyond the trim window; only digital silence can extend the raw snapshot without fallback.

The finalization lock protects cache insertion and the decision to publish. An ending does not wait for an in-flight preview: it retires previews and schedules the existing final decode, and a late result cannot populate the cache or replace that final. Configuration changes away and back invalidate results by revision. Reuse uses the normal final publisher once, retaining the committed utterance's last-voiced-frame timestamp, archival behavior and optional polish path. No punctuation-based coverage inference, prompt/parser redesign, target fabrication or correction learning is introduced.

The one-call Gemma contract, native 400 ms silence default, six-second cap, model/prompt, preview cadence, overlap and UI draft policy remain unchanged. The 400 ms promotion in `silence-threshold-comparison-2026-10-01.md` supersedes its original opt-in recommendation and older memory notes.

## Ordered real-Gemma replay

Baseline: main `3b893301981c2b5e6bd0726cb6189047fc59660a`. One worker reported **Model worker ready**, performed startup warmup and one unscored full replay, then ran baseline, candidate, candidate, baseline. All runs used the same private 51.467-second recording and human source reference, paced in 20 ms frames plus two seconds of silence. Settings: English→Spanish, 400 ms silence, six-second cap, 250 ms previews, 300 ms overlap, Silero 0.5; vocabulary, polish, code switching and early commit disabled. Model `mlx-community/gemma-4-e4b-it-8bit`, revision `4255b21bd9a9d3fc807ef7abd80373f5e3a52a73`, mlx-vlm 0.7.3, mlx 0.32.2; decoding and prompt unchanged.

Useful retained-word growth uses the existing longest order-preserving match between a target update and that utterance's eventual final, excluding unfinished last partial words. This measures retained hypothesis growth, not human target-language correctness. Pauses count intervals over two seconds; final latency is relative to original clip end, not padded feed end.

| Order | p95 useful gap (s) | Worst useful gap (s) | Pauses >2 s | Last final after clip (s) | Ending reuse | Prefix reuse | Source errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 01-baseline | 1.640 | 2.627 | 4 | 1.630 | 0 | 1 | 5/133 |
| 02-candidate | 1.762 | 2.529 | 5 | 1.643 | 0 | 1 | 5/133 |
| 03-candidate | 1.602 | 2.532 | 4 | 1.790 | 0 | 1 | 5/133 |
| 04-baseline | 1.643 | 2.913 | 5 | 1.648 | 0 | 1 | 5/133 |

Every run produced 13 nonempty unique finals, 12 final decodes, one existing quiet-prefix reuse, no inference errors and no duplicate final IDs. All four word-level alignments had four substitutions, one overlap insertion and zero deletions. Reference-based alignment inspection found no new source error or lost negation. The clip has no explicit numeric quantities; quantity and negation preservation are covered by deterministic tests, while real acoustic quantity coverage remains untested. No human Spanish reference was available.

Neither candidate reused an ordinary ending. The existing scheduler submits previews during speech and suppresses them during trailing silence; a snapshot ending at the last spoken frame generally lacks the 300 ms of padding included in the committed transcribable window. Waiting for a partial or treating quiet samples as proof of coverage would weaken the requested safety or final-priority behavior, so this experiment does neither. Timing differences cannot be attributed to saved final inference when none was saved. The default-off gate avoids promoting the mixed cadence result.

The measured enabled candidate predates the final default-off gate and stricter digital-silence-tail rejection. Its exact source and SHA-256 are preserved locally in `evaluated_session.py` and `metadata.json`. The final gate preserves its enabled behavior, and the tail guard only narrows eligibility; because measured ending reuse was zero, neither change converts these results into evidence of a win.

## Validation and evidence boundaries

Backend: 164 tests passed, including exact coverage, new/quiet speech, changed samples, insufficient padding, stale/pending configuration, changed-away-and-back configuration, wrong identity, stopped session, incomplete/truncated/empty results, cancellation, late completion, runtime replacement, duplicate commits, explicit-flush reset, disabled-mode fallback and preservation of negation/quantities. Native: 51 tests executed, 50 passed and one optional test skipped; release build passed with existing compiler warnings. Python compilation and diff whitespace checks passed.

Two separate candidate-only native file replays used a separate signed test bundle, external isolated engine socket and `LIVETR3_ENDING_PREVIEW_REUSE=1`. Both produced 13 complete nonempty unique finals, zero errors, zero ordinary-ending reuses and **4/133 source errors**. The second run included the final stricter tail guard. Audio passed through 48 kHz file injection, native conversion/framing, UDS, the real Gemma worker, caption stores and SwiftUI. Native source scoring differs from backend replay because resampling/segmentation eliminated the overlap insertion, as in the earlier silence experiment; it is not an improvement caused by ordinary-ending reuse. These are candidate smoke checks, not a warmed native baseline/candidate performance comparison. Bundle signing verification passed afterward.

No live microphone capture or physical projector test was performed. Native view callbacks are update proxies, not physical presentation timestamps; no physical readability or live acoustic result is claimed.

The primary checkout's unrelated `app/backend/validation/` remains intact. Three existing idle engine hosts and their sockets were identified and preserved; no competing model worker existed at replay start. Both harnesses continuously checked for resumed live inference. Only the workers/apps launched for this experiment were stopped. Test bundle: worktree `dist/LiveTR3-ending-preview.app`, separate bundle identifier and isolated UDS socket. Raw audio, source reference, transcripts, alignments and traces remain local under the primary checkout's ignored `dist/logs/ending-preview-2026-10-01/`.

Reproduce backend comparison with the existing backend environment and `PYTHONPATH=app/backend`, running `script/ending_preview_replay.py --baseline-ref 3b89330 --audio <private-audio.wav> --reference <human-source.txt> --output <ignored-output>`. The harness explicitly enables the candidate and uses disjoint utterance IDs on one warmed worker. Do not run alongside live model inference.
