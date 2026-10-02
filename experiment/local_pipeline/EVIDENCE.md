# Local two-model benchmark status — 2026-10-02

There is no measured candidate-versus-baseline result yet, so this experiment does not establish that Moonshine → TranslateGemma beats LiveTR3. The PR is a draft pending real-model replay and semantic inspection.

## Completed

- Isolated managed worktree and `codex/moonshine-translategemma` branch from verified `origin/main`, `cbb766e5dfbc7b69998c49317852c223d477d1fc`. The primary checkout's uncommitted work and Cadenza PR #13 were preserved.
- Candidate and baseline dependencies installed in separate pinned environments. Both candidate models were downloaded and cached outside Git; exact identity and ASR asset hashes are in `models.json`.
- The actual downloaded TranslateGemma tokenizer accepted the official structured `en` → `es` text message and produced its documented English-to-Spanish prompt without loading model weights.
- Eight focused tests passed, covering stability/cadence, final negation corrections, short/empty finals, names/quantities, bounded coalescing without final eviction, correct template shape, truncated/empty translation rejection, context overflow, and a simulated replay that preserves a sub-frame tail and drains exactly one translation final.
- Python compilation passed. The real CLI preflight correctly refused to load competing models.

These tests validate the policy and harness plumbing with controlled doubles. They do not validate model inference, acoustic recognition or translation quality.

## Specific replay blocker

The running Cadenza app owned its engine at PID 70002, launched from its existing app bundle. `vmmap -summary` measured approximately 9.5 GB resident in that engine; ordinary RSS showed only about 470–503 MB, illustrating why RSS is insufficient for this MLX workload. The app had a loaded Gemma audio model and was idle after a recorded session. It was left untouched because authorization to build this isolated experiment does not authorize stopping that app.

A user-input request to quit Cadenza normally is pending. The benchmark's process-owner guard fails before either candidate inference model loads. No scored candidate or fresh baseline replay was run alongside the loaded Cadenza model.

## Required before a recommendation

Run the documented serial warmed baseline/candidate/candidate/baseline comparison, inspect final source alignment against the private 133-word human reference, and review Spanish against the source with assistant-review limits stated. Publish only aggregate timings/error counts, queue/memory behavior and a concise semantic assessment; keep private text, recordings and generated output out of Git.

The earlier Cadenza evidence reports a separate LiveTR3 baseline at 5/133 English source errors, first Spanish characters at 0.972 seconds, and first final-retained Spanish word growth at 2.943 seconds. Those are historical read-only references, not measurements from this task, and the three-word prefix proxy here differs from that older retained-word metric. They cannot establish candidate improvement.

Cold load, paced file replay, live microphone and physical projector results must remain separate. No UI or app packaging was created, and no default pipeline was changed.
