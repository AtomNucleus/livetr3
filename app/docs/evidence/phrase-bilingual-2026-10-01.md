# Alternating bilingual phrase experiment — 2026-10-01

Keep the normal source-first output format. The opt-in candidate emits alternating Source/Target phrases within the same Gemma generation and flattens them into the existing source/translation caption fields. It genuinely interleaves some decodes, but the ordered replay does **not** establish more fluid sustained output. Both candidate runs have higher p95 useful-word gaps and more pauses than their paired baselines. Source errors fall from 5/133 to 4/133 by removing one overlap insertion, with the same four substitutions and no deletions; this is one-clip replay evidence, not a live accuracy result.

## Implementation

`LIVETR3_PHRASE_BILINGUAL=1` selects the experimental prompt per worker-service job. Normal launches retain the previous prompt and parser. Each Source line contains a natural phrase and the next Target line translates it before the next source phrase. The worker streams accumulated source and target through the existing canonical progress format; no protocol or SwiftUI changes are needed. Previous phrase translations remain present while the next source phrase grows. Roles remain distinct even when source and target languages are identical.

Finals require nonempty alternating source/target blocks, a translated final source block and nontruncated generation. Wrong-order, unlabeled preambles, empty blocks, incomplete labels and unmatched source blocks cannot become complete finals. The existing bounded retry, final priority, stale-preview cancellation, exact quiet-prefix handoff and audio buffering remain unchanged. A structurally complete response is not proof of acoustic word coverage; replay scoring remains necessary. The 400 ms silence threshold, six-second cap, 250 ms preview setting, 300 ms overlap, model and greedy decoding remain fixed. No preview-reuse code from rejected PR #9 is included.

The first prompt was rejected after real-model warmup produced an unlabelled full transcript before its labeled output, leading to rejected finals. Another prompt probe stopped after one phrase. The final simpler prompt completed all scored utterances; abandoned probes remain in local ignored artifacts and are not offered as test builds.

## Ordered real-Gemma replay

Baseline main `3b893301981c2b5e6bd0726cb6189047fc59660a`. One Gemma worker reported Model worker ready, performed startup warmup and one full unscored replay per format, then ran baseline/candidate/candidate/baseline with disjoint utterance IDs. All runs used the same private 51.467-second recording and human source reference, paced in 20 ms frames with two seconds of silence. Polish, vocabulary, code switching and early commit were disabled. Model `mlx-community/gemma-4-e4b-it-8bit`, revision `4255b21bd9a9d3fc807ef7abd80373f5e3a52a73`, mlx-vlm 0.7.3 and mlx 0.32.2.

Useful-word cadence uses final-retained order-preserving target-word growth, excluding unfinished partial words. It measures retained model hypotheses, not human Spanish correctness. First target characters can be unstable or wrong, so both startup measures are reported. End latency is relative to original clip end, not padded feed end.

| Run | First target characters (s) | First retained target word (s) | p95 useful gap (s) | Worst useful gap (s) | Gaps >2 s | Last final after clip (s) | Source errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 01-baseline | 0.966 | 3.731 | 1.516 | 2.453 | 4 | 1.653 | 5/133 |
| 02-candidate | 1.110 | 2.452 | 2.082 | 3.485 | 8 | 1.864 | 4/133 |
| 03-candidate | 1.129 | 7.436 | 1.847 | 2.831 | 6 | 1.881 | 4/133 |
| 04-baseline | 0.985 | 2.530 | 1.505 | 2.937 | 4 | 1.701 | 5/133 |

Every scored run produced 13 complete, nonempty, unique finals, zero inference errors and one existing quiet-prefix reuse. The first candidate's retained Spanish starts earlier, but the reverse candidate's starts later; neither startup measure establishes a repeatable improvement. A per-dispatch trace inspection found source growth after target progress in 5/35 and 6/30 candidate decodes with target progress, versus 0/44 and 0/41 baseline decodes. These counts include previews and finals and establish interleaving, not an accuracy or cadence benefit.

Word-level source alignment inspection found the same four substitutions in both candidates. The extra boundary repetition in both baselines was absent in both candidates. The reference clip's negation was retained in source and translation; the clip contains no explicit numeric quantities. Deterministic tests cover concatenation of negation/quantities, while acoustic quantity preservation is untested. No human Spanish reference was available, so no target accuracy score is claimed.

## Validation and test build

156 backend tests passed. Native tests executed 51 tests: 50 passed and one optional test skipped; release build passed. Python compilation, shell syntax, whitespace and signed bundle verification passed. Bundled worker/session hashes match the checkout. One isolated candidate native file replay produced 13 nonempty unique finals, zero errors and **4/133 source errors**. It used 48 kHz file injection through native conversion/framing, UDS, the real Gemma worker, caption stores and SwiftUI with the experiment enabled. This is a candidate smoke check, not a warmed native baseline/candidate cadence comparison; resampling can change boundaries, so its source score cannot be attributed solely to the format change. Bundle signing was verified after replay.

Test bundle: `dist/LiveTR3-phrase-bilingual.app`, bundle identifier `com.livetr3.phrase-bilingual-test`. `script/launch_phrase_bilingual.sh` enables the format with separate engine socket, archive and traces, and refuses to launch beside another active model worker. The bundle's Python shim uses the existing primary-checkout backend environment. The normal app and idle engine hosts are preserved. Start a live session manually to evaluate the test build.

No live microphone or physical projector result is claimed. Native view events are update proxies rather than physical presentation timestamps. All private audio, reference text, transcripts, source alignments, prompt probes and traces remain local under the primary checkout's ignored `dist/logs/phrase-bilingual-2026-10-01/`.

Reproduce backend comparison with the existing backend environment and `PYTHONPATH=app/backend`, running `script/phrase_bilingual_replay.py --audio <private-audio.wav> --reference <human-source.txt> --output <ignored-output>`. It records both prompts, evaluated worker source/hash, model/runtime metadata and all replay events. Do not run alongside live model inference.
