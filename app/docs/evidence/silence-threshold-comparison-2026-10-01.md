# Matched silence and chunk-limit comparison — 2026-10-01

**Keep the six-second cap; use 400 ms as an opt-in live-test candidate.** It recovered omitted source words and shortened the longest target-growth stall in both orders, but increased the number of moderate pauses and end-of-speech latency. No threshold improved every cadence metric, so this experiment does not justify changing the normal native default. The focused change adds a test-only environment override and an isolated launcher.

## Promotion after live user testing

After trying the isolated 400 ms build, the user reported that it was better and requested merging it into main. The native default is now 400 ms, with saved nil/150 ms settings migrated to 400 ms; other explicit thresholds are preserved. The six-second cap remains. This live preference supports promotion, but does not establish continuous output or quantify live microphone accuracy. The replay tradeoffs below remain applicable.

## Matched real-model replay

Main `dba59dcf33a9abadd7a9541c0a900a017818acd0`; quiet-boundary reuse enabled throughout. One Gemma worker reported `Model worker ready`, completed its model warmup and an unscored full replay, then ran these conditions: **6s/150ms, 6s/300ms, 6s/400ms, 8s/400ms, 12s/400ms, 12s/400ms, 8s/400ms, 6s/400ms, 6s/300ms, 6s/150ms**. This gives forward and reverse threshold comparisons and forward/reverse cap comparisons on the same worker.

The private 51.467-second audio and human reference were identical across conditions, paced in 20 ms frames with two seconds of trailing silence. Fixed settings: English→Spanish, 250 ms previews, 300 ms overlap, Silero threshold 0.5, no vocabulary, polish/code switching/early commit off. Model `mlx-community/gemma-4-e4b-it-8bit`, cached revision `4255b21bd9a9d3fc807ef7abd80373f5e3a52a73`, `mlx-vlm 0.7.3`, `mlx 0.32.2`; prompt and decoding unchanged. All raw captions, audio, reference text and alignments remain local in ignored `dist/` artifacts.

The workspace `.env` specifies a two-second preview default and enables polish, but both experiments explicitly supply the client’s 250 ms preview interval and disable polish. Those fallback values therefore do not explain the 19-versus-5 error difference. Repeating 150 and 400 ms under the same current worker reproduced 19 and 5 source errors in both orders.

## Target updates and source coverage

“Final-retained word growth” is a conservative useful-update proxy: tokenize a target hypothesis, exclude the unfinished last partial word, and count the longest order-preserving match against that utterance’s eventual complete target. An update counts only when this matching-word count exceeds its previous maximum. Repeated full hypotheses and discarded rewrites do not count again; an early name/spelling change does not prevent later matching words from counting. This still uses Gemma’s final as a consistency check, not a human Spanish truth reference, and it does not deduplicate overlap across utterances.

| Cap / silence / order | Retained-word gaps >2 s | p95 gap (s) | Worst gap (s) | First retained target (s) | Last final after clip (s) | Forced / reused | Source errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 01-6s-150ms | 4 | 1.518 | 3.027 | 2.933 | 0.688 | 0 / 0 | 19 / 133 |
| 02-6s-300ms | 3 | 1.762 | 3.140 | 1.585 | 1.339 | 1 / 0 | 9 / 133 |
| 03-6s-400ms | 5 | 1.592 | 2.480 | 3.697 | 1.619 | 1 / 1 | 5 / 133 |
| 04-8s-400ms | 3 | 1.562 | 3.014 | 2.867 | 1.609 | 1 / 1 | 5 / 133 |
| 05-12s-400ms | 5 | 1.724 | 4.180 | 2.932 | 1.647 | 0 / 0 | 4 / 133 |
| 06-12s-400ms | 5 | 1.736 | 4.192 | 2.920 | 1.646 | 0 / 0 | 4 / 133 |
| 07-8s-400ms | 3 | 1.577 | 3.960 | 2.325 | 1.643 | 1 / 1 | 5 / 133 |
| 08-6s-400ms | 4 | 1.587 | 2.513 | 3.807 | 1.631 | 1 / 1 | 5 / 133 |
| 09-6s-300ms | 5 | 1.752 | 2.505 | 1.380 | 1.336 | 1 / 0 | 9 / 133 |
| 10-6s-150ms | 3 | 1.503 | 3.054 | 2.939 | 0.688 | 0 / 0 | 19 / 133 |

Every scored run had zero errors, empty finals or duplicate final IDs. Final counts were 20 at 150 ms, 18 at 300 ms, 13 at 400 ms with 6/8-second caps, and 11 at 400 ms with a 12-second cap. Drain after the padded feed finished was below 1 ms in every run; the table separately measures the last final against the original clip end so padding cannot hide delay. The first retained target word can be much later than the first target characters because early partial words were rewritten.

For direct comparison with the older evidence, character growth counts a nonempty target only when it exceeds the same utterance’s previous maximum character length. It rejects repeats but can count rewrites or unfinished words, so it must not be described as fresh useful words.

| Run | Character-growth gaps >2 s | p95 gap (s) | Worst gap (s) | First target characters (s) |
| --- | ---: | ---: | ---: | ---: |
| 01-6s-150ms | 3 | 1.460 | 2.981 | 0.969 |
| 02-6s-300ms | 3 | 1.707 | 3.174 | 1.584 |
| 03-6s-400ms | 5 | 1.537 | 2.513 | 1.176 |
| 04-8s-400ms | 3 | 1.507 | 3.071 | 0.978 |
| 05-12s-400ms | 5 | 1.652 | 4.282 | 0.973 |
| 06-12s-400ms | 4 | 1.666 | 4.294 | 0.975 |
| 07-8s-400ms | 2 | 1.547 | 4.027 | 0.979 |
| 08-6s-400ms | 5 | 1.537 | 2.513 | 0.977 |
| 09-6s-300ms | 2 | 1.713 | 2.539 | 1.378 |
| 10-6s-150ms | 3 | 1.451 | 3.007 | 1.104 |

At six seconds, 400 ms shortened the worst final-retained gap from **3.027/3.054 s to 2.480/2.513 s** (about 18%), while source errors fell from **19/133 to 5/133**. It did not reduce the number of retained-word gaps over two seconds: **4/3 became 5/4**. p95 increased from **1.518/1.503 to 1.592/1.587 s**, and the last final moved from **0.688 to 1.619/1.631 s** after clip end. This is a coverage and longest-stall benefit with more moderate pauses and roughly 0.94 s more end latency.

300 ms scored 9/133 errors in both orders and had a higher retained-word p95 than either alternative. Its longest gap improved only in the reverse run, so it is not a repeatable continuity winner. At 400 ms, the 12-second cap recovered one insertion compared with six seconds (4 rather than 5 errors), but produced 4.180/4.192-second retained-word stalls. Eight seconds preserved the same source score as six but worsened the longest gap to 3.014/3.960 seconds. Keep six seconds. Larger caps also shift quiet-boundary handoff eligibility from 3 seconds to 4 or 6 seconds: the 6/8-second runs reused one prefix; the 12-second runs reused none.

## Why the source error counts differed

An offline replay through the same real Silero segmenter, without model-dependent prefix handoffs, checked that every returned chunk exactly equaled its span of original raw frames. The 800 ms minimum utterance length and all energy thresholds stayed fixed.

| Silence | Accepted chunks before model handoffs | Discarded bursts below minimum | Above-threshold audio outside accepted chunks | Substitutions / deletions / insertions in matched 6s replay |
| --- | ---: | ---: | ---: | ---: |
| 150 ms | 20 | 6 | 2.40 s | 8 / 11 / 0 |
| 300 ms | 18 | 1 | 0.36 s | 6 / 2 / 1 |
| 400 ms | 13 | 0 | 0.06 s | 4 / 0 / 1 |

At 150 ms, short pauses end speech bursts before they reach the 800 ms minimum, and those bursts are discarded. Raising silence joins more of those bursts into accepted chunks. The matched model results then remove all eleven source deletions at 400 ms. Above-threshold frame RMS is an audio-energy proxy, not a human speech label; the 0.06 s remaining outside accepted chunks does not prove a spoken omission. This controlled comparison attributes the main coverage difference to segmentation rather than a different model, prompt, cap or preview cadence.

WER uses the existing scorer’s Unicode word tokens, ignores case/punctuation, splits contractions, and joins finals without removing overlap words. At 400 ms/6s there is one extra repeated source word near a forced boundary; it is retained and scored, not silently deduplicated. The 12-second cap avoids that insertion at the cost of longer stalls. Source and Spanish negation were retained in every condition. The recording has no explicit numeric quantities, so quantity preservation remains untested. No human Spanish reference was available. Private error alignments and every final are saved for inspection.

## Native file replay and visible-caption evidence

The isolated native app replayed the same file at 48 kHz through conversion, framing, UDS, the real worker, caption stores and SwiftUI in **150, 400, 400, 150 ms** order, always with six-second chunks. The worker remained loaded across runs and performed its model startup warmup; unlike the backend experiment, there was no extra full unscored native run before the first scored run. Native config traces verify each threshold and all other timing settings.

| Native run / silence | Source errors | Operator view-growth gaps >2 s | View p95 (s) | View worst (s) | First view target (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 / 150 ms | 19 / 133 | 3 | 1.621 | 2.966 | 1.099 |
| 2 / 400 ms | 4 / 133 | 4 | 1.665 | 2.790 | 1.252 |
| 3 / 400 ms | 4 / 133 | 4 | 1.724 | 2.796 | 1.290 |
| 4 / 150 ms | 19 / 133 | 2 | 1.631 | 3.020 | 1.288 |

All native runs had complete nonempty unique finals, no errors and no post-feed final-store drain. Native 400 ms scored 4/133 rather than backend 5/133; the boundary repetition was absent after native resampling, so the extra one-token improvement is not treated as a backend threshold effect. The 19-versus-4 native result independently confirms the coverage benefit.

View cadence counts increasing character lengths in `view_text_update_proxy` callbacks for the actual translation rows. The store, display-field and projector measurements are also saved. These callbacks are layout/update proxies; LazyVStack may materialize offscreen rows, and no physical presentation timestamps are recorded. AX and a screenshot confirmed translated text in the isolated audience window. This is native **file replay**, not live microphone evidence or a physical projector test. The native view’s longest gap improved modestly at 400 ms, while moderate-pause count and p95 again increased.

## Reviewable implementation and live test

`ClientConfig.diagnosticConfig` accepts only the comparison thresholds 150/300/400 through `LIVETR3_DIAGNOSTIC_MIN_SILENCE_MS`, preserving the other native defaults. Normal launches retain their saved configuration. The native replay harness accepts a threshold per run and checks for other active UDS/legacy model workers before starting and throughout replay. The backend harness supports ordered cap/threshold pairs, disjoint utterance IDs and all recorded metrics.

Build: `dist/LiveTR3-silence-comparison.app`, with a separate bundle identifier and preferences. Launcher: `script/launch_silence_comparison.sh`, defaulting to 400 ms; optional argument `150` or `300` selects a comparison. Each launch gets its own engine socket, archive and log directory, and refuses to start while another known model worker exists. It uses the existing workspace Python environment through a packaged shim. The signed bundle’s segmenter, session and model-worker hashes match the checkout.

Validation: 51 native tests executed: 50 passed and one optional test skipped; release build passed with existing compiler warnings. Thirty-two focused backend tests passed, known word-edit and retained-word matching checks passed, Python compilation/shell syntax/diff whitespace checks passed, and bundle signing verification passed. Existing running apps and unrelated processes were preserved. No default was changed, merge performed, correction learned or live microphone capture started.

Reproduction and local data: `dist/logs/chunk-limit-2026-10-01/matched-thresholds/` holds backend events, summaries, metadata and offline segmentation; `native-silence/` holds native traces/archives/cadence summaries; `packaged-smoke/` checks the final bundle/launcher startup path. A live test should judge the additional waiting at pauses against recovered words, with real negation and numeric quantities before choosing a normal default.

The final signed bundle and launcher also completed a separate full packaged-engine file replay: 400 ms silence, six-second cap, 13 complete finals and **4/133 source errors**. The packaged Python shim started the intended backend, model readiness was verified by native replay gating, signing verification still passed after execution, and only the newly launched app/engine were stopped. Original app and engine PIDs remained running.
