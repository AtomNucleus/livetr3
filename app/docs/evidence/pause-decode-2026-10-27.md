# Pause decode — 2026-10-27

When an utterance ends in silence, the final waits for the full
`min_silence_ms` (600 ms) before the segmenter commits it, and only then does
the worker start decoding. The pause decode starts that same decode earlier:
as soon as Silero's non-speech run reaches the 300 ms speech pad, the worker
decodes the window the commit would decode. If the commit then arrives with an
identical window, its final is the pause decode's result. The hoped-for gain
was up to about 0.28 s per silence-ended final.

It is behind `LIVETR3_PAUSE_DECODE=1` and **stays off by default**. Silence-ended
finals did get faster, but the pooled gate fails: the median and p95 do not
improve, and gap p95 gets worse. Numbers are below.

## Trigger

The plan was to fire once 320 ms of frames fall below
`MIN_TRANSCRIBABLE_FRAME_RMS` (−64 dBFS). An offline run of the real segmenter
over every eval clip, using native defaults and the replays' 2 s of trailing
zeros, shows that this trigger misses too many pauses. On the stand-ins for
live sermons, it fires before only 47 of 73 silence-ended commits (64%):

- sermon-v1: 8 of 8
- sermon-v2 04–07: 39 of 65, with clip 07 at only 8 of 27

The reason is the noise floor. Pauses sit around −70 dBFS, but the clip-07
recording's pauses sit around −60 dBFS. FLEURS catches 16 of 44.

A trigger keyed on Silero fires before 100% of silence-ended commits in every
set. It fires once Silero's `temp_end` is one pad plus one 512-sample chunk in
the past. A separate window check compared the pause window, cut at Silero's
silence start plus the pad, with the audio each commit actually decoded:

- 162 of 162 silence-ended commits had a ready window that was byte-identical
  to the commit window.
- The lead before the commit had a median of 200 ms (p10: 120 ms). sermon-v1
  gains little, because the digital-silence flush commits only about 0.12 s
  after the trigger.
- 131 windows were discarded because speech resumed.
- Cap commit counts are unchanged.

The two scripts are `trigger_check.py` and `window_check.py`. Their output is in
`dist/logs/pause-decode-2026-10-27/`.

## Design

- **Segmenter.** `SileroVAD.pause_audio()` returns the utterance up to Silero's
  silence start plus the speech pad. It is ready once the non-speech run covers
  the pad. A silence-ended `SegmentResult` carries `pause_samples`, and the
  session decodes `audio[:pause_samples]`. That is the same window, so the
  final's audio now ends 300 ms into the silence instead of 600 ms. `RMSGate`
  has no pause window.
- **Session.**
  - Starts one pause decode per window.
  - Holds partial previews while it runs.
  - Discards the pause decode when speech resumes: the window changes, or a
    new window appears.
  - At a `silero_end` commit, reuses the pause decode only when both of these
    hold:
    - the request is equal: same languages, prior context, vocabulary and
      code-switching setting
    - the audio passes `np.array_equal`
  - Reuses the result only if it is complete and not truncated. Otherwise it
    decodes a fresh final from the same window, and the trace records
    `pause_decode_fallback`.
  - Cap and `decoded_prefix` commits discard the pause decode and behave as
    before.
  - A discarded pause decode's progress never reaches the client.
- **Worker.** A pause job is queued at final priority, but it is cancellable.
  - Later partials don't coalesce it.
  - `finish_partials` doesn't cancel it.
  - `cancel_pause_decode` retires it, whether it is queued or in flight.
  - Starting a pause decode cancels a stale in-flight preview through the new
    `cancel_partials`.
- **Protocol.** Finals carry `pause_decode_reused` (true or false) when the flag
  is on. The archive records it too. Swift's parser ignores unknown keys, and
  the new protocol test parses a final that has it.
- **Experiment flag.** `LIVETR3_PAUSE_DECODE_CANCEL_PREVIEW=0` keeps the
  in-flight preview running (pass C1).

## Screening

Each pass is one `script/scoreboard.py` run: real Gemma 4 E4B 8-bit with MTP,
cap 6 s, extend 2 s, cap pause 200 ms. Sets are FLEURS-8, sermon-v1 and
sermon-v2, pooled. No other worker was loaded during any pass. Latency is in
seconds. "First target" is the median time to the first caption; "infer med"
is the scoreboard's median inference time.

| Pass | Silence | Final latency median | p95 | First target | Gap p95 | Gaps over 2 s | Infer med | WER | chrF++ | Numbers / negation | Dropped |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| A1, flag off | 600 | 1.70 | 2.58 | 2.64 | 1.86 | 146 | 1.28 | 4.72% | 55.4 | 2/51, 1/55 | 0 |
| B1, flag on | 600 | 1.72 | 2.57 | 2.64 | 2.04 | 164 | 2.00 | 4.78% | 55.6 | 2/51, 1/55 | 0 |
| C1, on, keep preview | 600 | 1.71 | 2.58 | 2.60 | 1.96 | 145 | 2.01 | 4.78% | 55.5 | 2/51, 1/55 | 0 |
| D1, on, keep preview | 800 | 1.88 | 2.81 | 2.72 | 1.97 | 156 | 1.99 | 5.22% | 55.6 | 2/51, 1/55 | 0 |

Quality is within the gate in B1 and C1. WER changes by 0.06 points, which is
within pass-to-pass noise: sermon-v2 alone moves 2.46% ↔ 2.40%. Latency is not
within the gate.

### Final latency by commit reason (median s, finals)

| Set | Reason | A1 | B1 | C1 | D1 (800 ms) |
| --- | --- | --- | --- | --- | --- |
| FLEURS | silero_end | 1.66 (43) | **1.38** (43) | 1.43 (43) | 1.46 (36) |
| FLEURS | decoded_prefix | 1.58 (16) | 1.83 (13) | 1.62 (14) | 1.69 (18) |
| FLEURS | cap | 2.18 (49) | 2.21 (50) | 2.18 (50) | 2.27 (55) |
| sermon-v1 | silero_end | 1.71 (9) | 1.70 (9) | 1.65 (9) | 1.68 (4) |
| sermon-v2 | silero_end | 1.47 (118) | **1.33** (116) | 1.41 (116) | 1.25 (69) |
| sermon-v2 | decoded_prefix | 1.63 (34) | 1.92 (28) | 1.88 (31) | 1.98 (49) |
| sermon-v2 | cap | 2.22 (30) | 2.21 (34) | 2.28 (32) | 2.10 (48) |

### Pause decodes and queue time (worker dispatch, seconds med / p95 / max)

| Pass / set | Starts | Reused | Discarded: speech resumed / other | Fallbacks | Silence-ended finals reused | Final queue | Pause queue |
| --- | ---: | ---: | --- | ---: | ---: | --- | --- |
| A1 FLEURS | — | — | — | — | — | 0.04 / 1.02 / 1.84 | — |
| A1 sermon-v1 | — | — | — | — | — | 0.00 / 0.24 / 0.41 | — |
| A1 sermon-v2 | — | — | — | — | — | 0.02 / 0.31 / 1.10 | — |
| B1 FLEURS | 86 | 43 | 29 / 9 cap | 0 | 43/43 | 0.04 / 0.45 / 0.56 | 0.05 / 2.06 / 3.37 |
| B1 sermon-v1 | 11 | 9 | 2 / 0 | 0 | 9/9 | 0.12 / 0.23 / 0.24 | 0.00 / 0.06 / 0.06 |
| B1 sermon-v2 | 182 | 116 | 64 / 2 cap | 0 | 116/116 | 0.05 / 0.47 / 0.54 | 0.01 / 0.17 / 1.08 |
| C1 FLEURS | 87 | 42 | 30 / 9 cap, 1 prefix | 0 | 42/43 | 0.04 / 0.57 / 0.65 | 0.26 / 2.07 / 3.11 |
| C1 sermon-v1 | 11 | 9 | 2 / 0 | 0 | 9/9 | 0.12 / 0.15 / 0.15 | 0.00 / 0.18 / 0.18 |
| C1 sermon-v2 | 182 | 116 | 64 / 1 cap, 1 prefix | 0 | 116/116 | 0.06 / 0.41 / 0.44 | 0.04 / 0.34 / 1.05 |
| D1 FLEURS | 87 | 36 | 35 / 13 cap, 1 prefix | 0 | 36/36 | 0.04 / 0.47 / 0.60 | 0.24 / 2.28 / 3.22 |
| D1 sermon-v1 | 11 | 4 | 7 / 0 | 0 | 4/4 | 0.08 / 0.08 / 0.08 | 0.00 / 0.24 / 0.25 |
| D1 sermon-v2 | 185 | 69 | 111 / 4 cap, 1 prefix | 0 | 69/69 | 0.05 / 0.37 / 0.58 | 0.01 / 0.50 / 0.90 |

## Why the gain does not reach the pooled numbers

The mechanism works. Every silence-ended final reused its pause decode, with
no fallbacks. Publish time relative to the commit moved 0.17–0.23 s earlier,
close to the expected 0.28 s less the time already spent queued. Silence-ended
finals improved by 0.14–0.28 s on FLEURS and sermon-v2. Final queue p95
roughly halved on FLEURS.

The cost lands on the other commit reasons, through the worker:

1. **About a third of pause decodes are wasted.** About 35% of starts in B1
   and C1 were discarded because speech resumed, and 61% in D1. A discard can
   cancel the job between tokens, but prefill can't be interrupted. So each
   discarded pause decode still holds the single worker for a full audio
   prefill, right when the next utterance's previews and `decoded_prefix`
   commit need it. Median inference time rises from 1.28 to 2.0 s, and pause
   queue p95 on FLEURS is about 2 s.
2. **B1 cancels the in-flight preview.** Its tokens were feeding the
   stability-based `decoded_prefix` commit, so B1 had fewer decoded-prefix
   finals (FLEURS 16 → 13, sermon-v2 34 → 28) and they were 0.25–0.3 s slower.
   Keeping the preview (C1) mostly recovered FLEURS (1.62 s), but not
   sermon-v2 (1.88 s), where point 1 dominates.
3. **sermon-v1 barely gains.** Its utterances end through the digital-silence
   flush only about 0.12 s after the trigger.

## 600 vs 800 ms silence

The 800 ms pass (D1) has the same flags as C1. It moves silence-ended commits
200 ms later, which gives the pause decode a longer lead. sermon-v2's
silence-ended finals are then the fastest of any pass (1.25 s). But fewer
utterances end in silence (sermon-v2 116 → 69), and more become slower
decoded-prefix and cap commits. More pause decodes are wasted (111 of 185
discarded on sermon-v2), and WER rises to 5.22%. Pooled, the median goes to
1.88 s and p95 to 2.81 s, which is worse than A1 and C1. 600 ms stays.
Neither silence setting was a candidate for adoption, so no ABBA was run.

## Gate verdict

| Gate | B1 | C1 | D1 |
| --- | --- | --- | --- |
| Final latency median improves (A1 1.70) | no, 1.72 | no, 1.71 | no, 1.88 |
| Final latency p95 improves (A1 2.58) | flat, 2.57 | flat, 2.58 | no, 2.81 |
| First target not worse (A1 2.64) | yes | yes | no |
| Gap p95 not worse (A1 1.86) | no, 2.04 | no, 1.96 | no, 1.97 |
| Final queue not worse | yes | yes | yes |
| WER +≤0.3 pt, chrF++ −≤0.5 | yes | yes | no |
| No dropped finals, numbers or negation regressions | yes | yes | yes |

**Fails.** The flag stays off and the default behavior is unchanged. A pause
decode could pay off only if a discarded one didn't cost a full prefill. Two
routes would get there: an interruptible prefill, or a prefix KV cache that
lets the final reuse the prefill. The KV cache is already in Phase 3's spike
list, and it could also cut the waste from speech-resumed discards.

## Tests

`tests/test_pause_decode.py` covers:

- the decode fires exactly at the pad and publishes as the final
- reuse only on an equal request and an equal window
- speech after the pause discards it and its progress, and forces a fresh
  window
- truncated, incomplete and cancelled pause decodes fall back to a fresh final
- a cap commit discards it and decodes untrimmed audio
- flag off keeps untrimmed finals with no new field
- worker semantics: final priority, no coalescing, survives `finish_partials`,
  cancellable
- dispatch sends a pause job as a cancellable final

The existing suite covers `decoded_prefix` commits unchanged. Results: backend
175 passed, and Swift `LiveTR3ProtocolTests` passes with a final that carries
`pause_decode_reused`.
