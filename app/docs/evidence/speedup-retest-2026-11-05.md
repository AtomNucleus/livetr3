# Speed-up retest on the noisy-room branch — 2026-11-05

**The speed-ups still pay on top of the early pause decode.** The stack
(#26 interruptible prefill, #27 prefix cache, #28 docs) was rebased onto
`claude/noisy-room-fixes`, which is main plus #29, #30 and #31. Against that
branch, live-weighted final latency drops by **0.17 s at the median and
0.15 s at p95** on the three-set scoreboard, and by 0.16 / 0.14 s on the noisy
sermon window. Quality is flat. #29 does not hide the prefill: the pause
decode itself prefills 0.08 s faster.

- **A** is `claude/noisy-room-fixes` at 3b58702, which is what the everyday
  app runs.
- **B** is the rebased stack at 3ea718f.

Outputs are in `dist/logs/speedup-retest-2026-11-05/`. Only one model worker
ran at a time, and no LiveTR3 engine was loaded during any pass.

## Rebase

Each PR's own commits were replayed with `git rebase --onto`.

There were two conflicts, both additive:
- `mlx_worker.py`: #30's per-job queue and inference timing and #26's
  `worker_cancel_free` trace now sit side by side after `worker_complete`.
- `tests/conftest.py`: both sides' Darwin-only test files are kept.

#29's truncation-only final retry merged cleanly into #27's
cache/MTP fallback `attempt()`.

## Interplay

- **The early pause decode is a cancellable job.** The service already sends
  it as cancellable (#29), so on B it gets the 32-token prefill chunk and the
  cancel hook.
  - When speech resumes, the cancel lands between chunks: cancel-to-free p95
    is 0.07 s.
  - The decode returns no result, and the session decodes the final again.
  - Fixed: `cancel_early_final` didn't record the cancel time, so cancelled
    pause decodes were missing from `worker_cancel_free`. It now records it.
- **The prefix cache covers the pause decode.** Its prompt drops from 156
  tokens to 75.
  - A cancel during `prepare()` or the prefix build propagates as a cancel. It
    doesn't count as a cache fault, and nothing half-built is kept.
- **Start warm-up.** #31's warm decode at Start goes through the same cached,
  chunked path.
  - Fixed: it used no custom vocabulary or code-switching. Those lines sit
    before the audio token, so with a vocabulary set, the first caption
    rebuilt the one-entry prefix. The warm decode now uses the session's
    prompt options. The replays use no vocabulary, so this doesn't touch the
    numbers below.
- **#30 timing.** Queue and inference seconds are recorded the same way with
  the cache on. A cache fault's uncached rerun is in the same job, so its
  inference seconds include both attempts.
- **Cost:** a pause decode that the final reuses still prefills in chunks of
  32. That is why its prefill drops by 0.08 s, while a final's drops by
  0.12 s.
- **Note: the first decode after worker start is about 0.3 s slower on B in
  the noisy replays** (first token at 0.85 / 0.90 s vs 0.52 / 0.56 s).
  - The worker's load-time warm-up isn't cancellable, so it doesn't run the
    chunked path.
  - Live, #31's Start warm decode is cancellable and runs that path before
    the first caption.
  - Not changed here.

## Test

ABBA in the order A1, B1, B2, A2. Each pass ran:
- `script/scoreboard.py`: FLEURS-8, sermon-v1 and sermon-v2, real Gemma 4 E4B
  8-bit with MTP, cap 6 s, silence 600 ms
- the noisy sermon window from #31: the same 22 minutes (660–1980 s) of the
  licensed live recording, streamed in real time through
  `TranscriptionSession` by the local `stream_replay.py`. The audio and its
  harness stay outside the repo.

**The Mac rebooted for a macOS update during B2.** So pair 1 (A1, B1) and
pair 2 (B2, A2) ran in two machine sessions.
- The partial B2 (6 of 7 sermon-v2 clips) is kept as `B2-partial-reboot`.
- B2 was rerun in full, from fresh worktrees at the same commits.
- After the update, Spotlight indexing and Photos conversion were running.
  The one-minute load average was 18 → 10 during B2 and 5 → 3 during A2
  (`load.log`), so pair 2 is biased against B.

Latencies are in seconds. Each cell is the mean of the two passes, with the
two values in brackets.

| Set | Arm | Live-weighted median | Live-weighted p95 | Pooled median | Pooled p95 | WER | chrF++ | First target | Gap p95 | Numbers / negation | Dropped |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| FLEURS-8 | A | 1.52 (1.49, 1.56) | 2.56 (2.67, 2.46) | 1.86 (1.96, 1.77) | 2.67 (2.75, 2.59) | 8.00% (8.00, 8.00) | 54.8 | 2.88 (2.95, 2.81) | 2.01 (1.98, 2.05) | 1/23, 1/22 | 0 |
| | B | **1.27** (1.26, 1.28) | **2.26** (2.26, 2.27) | **1.56** (1.56, 1.55) | **2.42** (2.41, 2.42) | 8.11% (8.07, 8.14) | 54.7 | **2.57** (2.53, 2.61) | **1.86** (1.87, 1.85) | 1/23, 1/22 | 0 |
| sermon-v1 | A | 1.58 (1.62, 1.55) | 2.36 (2.61, 2.11) | 1.60 (1.63, 1.57) | 2.10 (2.20, 2.01) | 3.01% | — | 3.17 (2.63, 3.72) | 1.50 (1.50, 1.50) | 0/0, 0/1 | 0 |
| | B | **1.52** (1.57, 1.46) | **2.06** (2.12, 2.00) | **1.48** (1.51, 1.46) | **1.91** (1.95, 1.86) | 3.01% | — | **2.63** (2.65, 2.62) | **1.45** (1.49, 1.41) | 0/0, 0/1 | 0 |
| sermon-v2 | A | 1.31 (1.30, 1.33) | 2.38 (2.35, 2.41) | 1.62 (1.63, 1.62) | 2.46 (2.46, 2.46) | 2.43% (2.46, 2.40) | 56.6 | 2.21 (2.21, 2.22) | 1.89 (1.91, 1.86) | 1/28, 0/32 | 0 |
| | B | **1.22** (1.20, 1.24) | **2.34** (2.32, 2.36) | **1.47** (1.47, 1.47) | **2.35** (2.32, 2.38) | 2.46% (2.46, 2.46) | 56.9 | **2.12** (2.15, 2.08) | **1.79** (1.81, 1.77) | 1/28, 0/32 | 0 |
| **All, pooled** | A | 1.42 (1.42, 1.43) | 2.42 (2.44, 2.39) | 1.69 (1.72, 1.67) | 2.54 (2.61, 2.47) | 4.71% (4.72, 4.69) | 55.4 | 2.61 (2.61, 2.61) | 1.92 (1.92, 1.93) | 2/51, 1/55 | 0 |
| | B | **1.26** (1.23, 1.29) | **2.27** (2.26, 2.28) | **1.52** (1.52, 1.51) | **2.37** (2.34, 2.40) | 4.77% (4.75, 4.78) | 55.5 | **2.38** (2.37, 2.38) | **1.81** (1.82, 1.79) | 2/51, 1/55 | 0 |

sermon-v1 has no Spanish reference, so it has no chrF++. A2's sermon-v1
first target of 3.72 s is the same one-clip wording drift as in Phase 4.

All sets pooled, by pair:

| Pair | Live median | Live p95 | Pooled median | Pooled p95 | WER | chrF++ | First target | Gap p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B1 − A1 | −0.19 | −0.18 | −0.20 | −0.27 | +0.03 pt | +0.1 | −0.24 | −0.10 |
| B2 − A2 | −0.14 | −0.11 | −0.16 | −0.07 | +0.09 pt | +0.1 | −0.23 | −0.14 |

Every B pass beats both A passes on the pooled live-weighted median and p95,
first target and gap p95.

Per set, three cells fail that test, each by 0.01–0.02 s:
- sermon-v1 live p95: B1 2.12 vs A2 2.11
- sermon-v1 first target: B1 2.65 vs A1 2.63
- sermon-v2 live p95: B2 2.36 vs A1 2.35

All three are well inside the ±0.08 s pass-to-pass noise.

### Noisy sermon window

267 finals in every pass, no errors. This set has no references, so it has no
WER.

| Pass | Live-weighted median / p95 | Pooled median / p95 | Pause finals (`silero_end`) median / p95 | Cap finals median / p95 | Pause finals from the early decode | Gaps > 3 s with ≥ 1 s speech |
| --- | --- | --- | --- | --- | ---: | ---: |
| A1 | 1.32 / 2.28 | 1.60 / 2.37 | 1.22 / 2.12 | 1.95 / 2.65 | 155 of 157 | 23 |
| B1 | **1.13 / 2.12** | **1.38 / 2.18** | **1.09 / 2.04** | **1.75 / 2.27** | 157 of 157 | **14** |
| B2 | **1.19 / 2.11** | **1.42 / 2.14** | **1.06 / 2.05** | **1.75 / 2.38** | 157 of 157 | **16** |
| A2 | 1.32 / 2.24 | 1.53 / 2.33 | 1.21 / 2.12 | 1.88 / 2.57 | 156 of 157 | 23 |

By pair, B − A on the live-weighted median / p95 is −0.19 / −0.16 in pair 1
and −0.13 / −0.13 in pair 2.

### Per-decode prefill (`ast_decode`, time to first response)

Medians and p95s are in seconds, with the median prompt tokens in brackets.
"Pause" means the early pause decodes, whether used or dropped. "Final" means
the finals decoded after the commit: cap, decoded-prefix and fallback finals.

| Pass | Previews | Pause decodes | Finals | Final and pause queue p95 | Previews run |
| --- | --- | --- | --- | ---: | ---: |
| A1, 3 sets | 0.379 / 0.562 (137) | 0.390 / 0.537 (156) | 0.585 / 0.710 (241) | 0.460 | 1,135 |
| B1, 3 sets | 0.242 / 0.439 (58) | 0.309 / 0.463 (75) | 0.454 / 0.528 (164) | 0.366 | 1,394 |
| B2, 3 sets | 0.248 / 0.455 (58) | 0.311 / 0.467 (75) | 0.460 / 0.541 (164) | 0.373 | 1,385 |
| A2, 3 sets | 0.374 / 0.541 (137) | 0.388 / 0.511 (156) | 0.569 / 0.633 (241) | 0.457 | 1,176 |
| A1, noisy | 0.379 / 0.512 (142) | 0.390 / 0.511 (156) | 0.561 / 0.624 (240) | 0.490 | 925 |
| B1, noisy | 0.250 / 0.463 (62) | 0.312 / 0.464 (76) | 0.454 / 0.515 (163) | 0.435 | 1,114 |
| B2, noisy | 0.256 / 0.474 (62) | 0.318 / 0.476 (76) | 0.459 / 0.530 (163) | 0.411 | 1,090 |
| A2, noisy | 0.373 / 0.524 (142) | 0.389 / 0.509 (156) | 0.558 / 0.626 (240) | 0.493 | 945 |

Prefill falls by about **0.13 s per preview, 0.08 s per pause decode and
0.12 s per final**. Faster previews mean about 20% more of them run.

Traces in every pass:
- `prefix_cache_failed`: 0
- `mtp_fallback`: 0
- B's `worker_cancel_free` p95: 0.065–0.075 s

## Gate

| Check | Result |
| --- | --- |
| WER ≤ +0.3 pt | +0.06 pt (4.71 → 4.77%): **pass** |
| chrF++ ≥ −0.5 | +0.1: **pass** |
| No dropped finals, no number or negation regressions | 0 dropped; 2/51 and 1/55 in every pass: **pass** |
| Live-weighted median and p95 improve | −0.17 / −0.15 s; every B beats both A: **pass** |
| First target and gap p95 no worse | −0.23 / −0.11 s: **pass** |

**Passes.** The gain is about what the stack showed against d2ee293 before
#29 (−0.15 / −0.12 s), and it holds in the noisy room.

## Tests

- 199 backend tests pass on the top branch.
- 64 Swift tests pass, with one skipped.

New tests:
- `test_cancellable_prefill.py`:
  - the early pause decode is dispatched cancellable and a plain final isn't
  - a cancel mid-prefill returns no result, with no truncation retry
  - cancelling it while it runs frees the worker with a `worker_cancel_free`
    trace and keeps its #30 timing
- `test_prefix_cache.py`:
  - a cancel during the prefix build caches nothing
  - a cancel while the early decode prepares keeps the cache on
- `test_noisy_room.py`: the Start warm decode uses the captions' prompt
  options
