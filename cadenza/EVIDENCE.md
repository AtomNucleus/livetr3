# Cadenza validation — 2026-10-02

Cadenza proves a direct, one-generation-per-phrase path with frozen completed text and bounded audio collection. This private clip shows the same source error count as the existing app, with a longer wait for its first Spanish output. It does not establish faster inference, better accuracy, live acoustic performance, or projector behavior.

## Verified inputs

The isolated `codex/cadenza` worktree started from origin main `cbb766e5dfbc7b69998c49317852c223d477d1fc`. Primary-checkout context and packaging edits were left intact. The previously running translation-context candidate's identified engine was stopped with user authorization before model tests; no unrelated process was stopped. Tests ran serially, without competing loaded models.

Runtime: CPython 3.13.13, MLX 0.32.2, MLX-VLM 0.7.3, Transformers 5.17.0, SoundFile 0.13.1. Model: `mlx-community/gemma-4-e4b-it-8bit`, cached revision `4255b21bd9a9d3fc807ef7abd80373f5e3a52a73`. Cadenza uses temperature zero, ordinary decoding, Google's documented English → Spanish AST prompt, and a 512-token budget. No MTP, preview generation, previous-phrase context, or polish is enabled.

The local recording has 823,473 mono 16 kHz samples (51.467 seconds), and its human-provided English reference has 133 words. Audio, reference text, generated captions, detailed alignments, and caption screenshots remain local. This document includes aggregate measurements only.

## Bare and continuous backend replay

First, `raw_model.py` invoked the library directly on a six-second excerpt, without any LiveTR3 imports. Its cold first source/Spanish/final timings were 1.979 / 2.718 / 3.479 seconds after dispatch, with a normal model stop and both languages present.

Next, one loaded model completed an unscored real-phrase warmup, then the ordered **direct-before → continuous pipeline → direct-after** run. Each direct run used precisely the phrase WAVs that the continuous collector commits. All 12 raw bilingual answers were byte-identical across the three conditions.

| Condition | Complete phrases | Incomplete/failures | Source errors | Median inference |
| --- | ---: | ---: | ---: | ---: |
| Direct before | 12 | 0 | 5/133 | 1.413 s |
| Continuous pipeline | 12 | 0 | 5/133 | 1.782 s |
| Direct after | 12 | 0 | 5/133 | 1.557 s |

Continuous replay is paced against absolute 20 ms sample deadlines. From the beginning of audio collection, its first source characters appeared at **5.601 s**, and Spanish at **6.243 s**. The first phrase committed at about 4.9 seconds; collection time is separate from inference. Phrase last-voiced-frame → final delay was **2.282 s median / 3.114 s maximum**, including the 500 ms quiet wait. Maximum inference queue wait was **0.000109 s**, peak pending count was **1**, and there were **no overloads**. The retained capture was exactly equal to every input sample, with no duplicated or missing received audio. Twelve phrases covered 47.78 seconds; the remaining 3.687 seconds were energy-gated idle intervals and remained in the retained capture.

The gate is only an energy heuristic, not a learned VAD. A first unscored segmentation inspection at RMS 0.008 split this quiet recording too aggressively, so the initial gate was set to RMS 0.003 before scored model runs. The simple 500 ms pause and 8-second cap were not replaced with the old tuning stack. This clip does not establish quiet-speech robustness in another room or microphone.

## Existing LiveTR3 baseline

A separate serial run used the isolated worktree's existing session and worker implementation, with one full unscored warmup followed by one scored replay. It retained native-style settings: 6-second cap, 400 ms silence, 250 ms previews, 300 ms overlap, Silero threshold 0.5, and polish/code-switching/early-commit/MTP/phrase-bilingual experiments disabled. It used the same cached model, runtime, private audio, and English reference. This baseline ran after the ordered Cadenza comparison, rather than interleaved on the same loaded worker, so it is a practical behavioral comparison, not an inference-speed benchmark.

The baseline returned **13 nonempty complete finals, zero errors, and 5/133 source word errors**. First source characters arrived at **0.922 s**, first Spanish characters at **0.972 s**, and first final-retained Spanish word growth at **2.943 s**. Final-retained target-growth gaps had **1.565 s p95 / 3.119 s maximum**, with four gaps over two seconds; the final arrived **1.738 s after the original clip ended**. Retained growth compares previews with the model's eventual final answer; it does not score Spanish against a human reference.

Cadenza therefore avoids preview churn and repeated audio generations while matching this clip's final English error count, but the baseline gets text on screen sooner. It would be misleading to say the smaller architecture is faster or more accurate.

## Packaged native replay

The signed app launched normally without a shell environment launcher, loaded Gemma from its own resources, and displayed the real replay through its native pipe, collector, queue, and SwiftUI view. The bundled Python imports passed, and `codesign --verify --deep --strict` passed. The bundle has its own identifier, icon, preferences, and application-support directory.

An initial diagnostic used relative sleeps and accumulated replay pacing drift; that feed timing is excluded from latency comparisons. The diagnostic now uses absolute sample deadlines. Native cold and warmed results are recorded below after the final scroll-anchor fix. The cold framework/file setup and first inference are reported separately from warmed behavior.

| Native condition | First source / Spanish from first PCM | Last voice → final median / max | Maximum queue wait | Peak pending | Source errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| Cold diagnostic | 6.381 / 7.069 s | 2.280 / 3.256 s | 15.3 ms | 1 | 5/133 |
| Warmed second session, same child | 5.686 / 6.481 s | 2.448 / 3.366 s | 2.8 ms | 2, transient | 5/133 |

Both produced 12 complete phrases, zero failures/overloads, and byte-exact retention of all 823,473 input samples. The cold diagnostic took 12.337 seconds between session creation and the first PCM packet while initializing native file replay; the warmed session took 4.1 ms. Those setup delays are excluded from the first-PCM figures above, and model loading before session creation is also separate. Neither is a measured live-microphone startup time. Absolute pacing delivered the 51.467-second recording in 51.47 seconds after first PCM. No sustained inference backlog developed.

Actual UI inspection found that a growing last card could leave the final Spanish below the viewport. A bottom scroll anchor fixed it; the final translation was visibly present, the scroll bar reached the bottom, Start became available after drain, and a second replay started with the existing loaded child. Completed cards are guarded against subsequent partial/final events. The app does not animate a scroll for every token.

## Focused checks and remaining limits

Six focused tests passed: irregular-packet voiced-sample conservation across cap boundaries, inclusion of Stop's sub-frame tail, natural quiet commits, bounded overload with all captured samples and failed phrase files retained, drain/incomplete-answer/explicit-retry semantics, normal-stop-and-two-language completion checks, and disk-failure cleanup. Release build, bundled imports, and strict deep signature verification passed. Generated private data and app binaries are excluded from Git.

Spanish meaning was reviewed by the implementing assistant against the local source, without a human Spanish reference. The broad argument survives, but source mistakes propagate: one phrase changes singular “church” to plural, another changes a conjunction, and the opening remains awkward. Independent phrases also produce short Spanish fragments at pauses. There is no numerical Spanish accuracy claim.

Native file replay exercises the display path, not microphone permission, real-time hardware conversion, live acoustic segmentation, or physical projector presentation. Those remain unverified. A noisy or quiet room can challenge the fixed energy gate, and sustained slow inference intentionally stops capture once the bounded queue fills. All accepted audio remains on disk, and microphone audio is recorded before the bounded pipe; disk capacity is a practical limit. The local ad-hoc signature is not notarization or evidence of distribution to another Mac.

Local reproducibility artifacts are under ignored `dist/logs/cadenza/` (raw test, ordered replay, baseline, package/build/signature logs) and `~/Library/Application Support/Cadenza/` (native event log and retained recordings). The repo includes `validate.py` and the focused tests without private fixtures.
