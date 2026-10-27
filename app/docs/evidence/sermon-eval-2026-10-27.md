# Sermon replay set and three-set scoreboard — 2026-10-27

FLEURS (see `fleurs-eval-2026-10-07.md`) is read sentences with synthetic
pauses, and sermon-v1 is one private 51-second clip. This adds sermon-v2, 12
minutes of licensed preaching and scripture reading with human references, and
one command that replays and scores all three sets. The baseline below is what
the latency and quality changes that follow are measured against.

## sermon-v2

`script/build_sermon_eval.py` downloads, cuts and levels seven clips (12.3
minutes, 1,835 reference words) into ignored `dist/eval/sermon-v2/`, with a
manifest of source URLs, licenses and sha256 hashes. The audio files and the
extracted reference texts are pinned by hash, so an upstream change fails the
build. Downloads total about 200 MB; nothing is committed.

| Clip | Audio | License | Length | Words | Spanish |
| --- | --- | --- | ---: | ---: | --- |
| 01 | Matthew 18:21–35, World English Bible, read by Michael Paul Johnson (eBible.org) | public domain | 99.8 s | 319 | BLL |
| 02 | Psalm 90, WEB, read by Sibella Denton (LibriVox) | public domain | 98.7 s | 305 | BLL |
| 03 | 1 Corinthians 13, WEB, read by William Healey (LibriVox) | public domain | 120.5 s | 275 | BLL |
| 04 | Andy Davis, sermon *The Secret of Christian Contentment, Part 1* (Two Journeys, 2004) | non-commercial, with credit | 107.0 s | 296 | — |
| 05 | Andy Davis, sermon *Healthy Churches Are Full of Love* (Two Journeys, 2021) | non-commercial, with credit | 91.8 s | 264 | — |
| 06 | John Piper, *Ask Pastor John* 2294, *The Gospel Before Jesus Died* (Desiring God, 2026) | personal or non-commercial | 110.2 s | 227 | — |
| 07 | President Obama, eulogy for the Reverend Clementa Pinckney (White House, 2015) | public domain | 108.1 s | 149 | — |

Scripture references are the 2005 WEB text (Project Gutenberg #8294). The
readers follow it ("reconcile accounts", "number our days"), and LibriVox's
New Testament lists it as its source; today's eBible.org text has since been
revised. The Spanish reference is the public-domain Santa Biblia libre
Latinoamericano. It is an independent translation rather than a translation
of this English, so scripture chrF++ is best read as a relative measure.
Preaching references are the publishers' own transcripts. Two
Journeys and Desiring God refuse scripted requests, so those come from fixed
Wayback Machine snapshots. Bracketed words are kept; parenthesized stage
directions and citations such as "(Applause.)" are dropped.

Cuts sit inside pauses chosen once from Parakeet TDT 0.6b word timings and the
audio level. Clips are leveled like FLEURS: speech p95 frame RMS 0.022, with
seeded noise raising each recording's floor to 0.0003.

Parakeet TDT 0.6b v3 in 30-second chunks, scored the same way, is within
0.3–4.8% WER of every reference (1.9% over the set, 0.8% on sermon-v1), so the
references are sound. Known departures are kept as published:

- clip-03: the reader departs from the 2005 text in five places, about 7 word
  errors: "of men and angels", "and I know all mysteries", "bestow" for "dole
  out", "For I know in part", "But now remain faith, hope, and love".
- clip-04: the transcript writes "versus" for "verses" and "Philippians
  4:10-13" for "chapter 4 verse 10 through 13".
- clip-06: Desiring God lightly edits its transcripts, for example "Isaiah
  52:7" where Piper says "Isaiah 52".
- clip-07 opens in applause and has congregation responses.

## Scoreboard

`script/scoreboard.py OUTPUT` replays FLEURS-8, sermon-v1 and sermon-v2 at
native defaults, each in its own engine process, into `OUTPUT/<set>`. It then
prints one table with a row per set and a pooled row:

    python3 -I script/scoreboard.py dist/logs/scoreboard/baseline-2026-10-27

Engine flags pass through the environment and are recorded in each run's
metadata with its eval set. Finished sets are kept, so an interrupted pass
resumes, and `--score-only A1 B1 B2 A2` scores several passes in one table,
for example in ABBA order. `fleurs_score.py` now leaves clips without a
Spanish reference out of chrF++ and BLEU, so sermon-v1 shows none and the
pooled figures cover the 11 clips that have one.

Three Whisper-normalizer artifacts are now handled before scoring, on both
sides:
- Typographic apostrophes are split ("don’t" becomes "don t"), so they are
  straightened first.
- An ellipsis leaves a "." word, so it is dropped.
- "1 Corinthians" becomes "one corinthians" but "First Corinthians" becomes
  "1st corinthians", so numbered books are spelled out.

Only the apostrophes touch FLEURS, where two references have them.
Rescoring the 2026-10-08 flexible-cap outputs moves FLEURS WER from 8.14% to
8.00% (near-cut errors 62 to 61), with every other figure unchanged. On
sermon-v2 the other two fixes remove four false errors.

## Baseline

The engine code is main at d2ee293; this branch changes only scripts. Model
`mlx-community/gemma-4-e4b-it-8bit` with MTP, mlx-vlm 0.7.4, MLX 0.32.2, at
native defaults: 6 s cap with the 2 s / 200 ms pause extension, 600 ms
silence. First target is the time from clip start to the first Spanish word
the final keeps. Gap p95 is the 95th-percentile wait between additions of
kept Spanish words. Outputs are in ignored
`dist/logs/scoreboard/baseline-2026-10-27/`.

| Set | WER | near-cut errors | numbers | negation | chrF++ | BLEU | dropped finals | final latency median / p95 (s) | first target (s) | gap p95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| FLEURS-8 | 8.00% | 61 | 1/23 | 1/22 | 54.7 | 21.2 | 0 | 1.91 / 2.63 | 2.82 | 1.96 |
| sermon-v1 | 3.01% | 2 | 0/0 | 0/1 | — | — | 0 | 1.74 / 2.07 | 2.19 | 1.60 |
| sermon-v2 | 2.40% | 29 | 1/28 | 0/32 | 56.9 | 26.1 | 0 | 1.61 / 2.49 | 2.16 | 1.90 |
| pooled | 4.69% | 92 | 2/51 | 1/55 | 55.5 | 23.1 | 0 | 1.69 / 2.54 | 2.49 | 1.91 |

FLEURS text scores reproduce the 2026-10-08 outputs exactly. Its final
latency median moved from 1.81–1.83 s to 1.91 s with no backend change since,
so latency differences near 0.1 s need ABBA-ordered passes to show.

sermon-v2 sits near its reference floor. Gemma scores 2.40% against
Parakeet's 1.9%, and Parakeet also misses 17 of the 32 reference words Gemma
misses, mostly the departures listed above. Gemma's own errors are mostly
single words: sound-alikes ("reigns" → "rains", "rancor" → "ranker") and one
reversal ("inappropriately" → "appropriately"). Seven of them are in clip-07,
a live recording with applause and congregation responses. FLEURS therefore remains the set that shows WER gains, and
sermon-v2 guards against regressions on preaching. Scripture scores 1.32% WER
and preaching 3.43%.

Final latency on the preached clips is 1.39 s median and 2.46 s p95. That is
close to the live session archives measured the same day: 1.3 s and 2.42 s
over 1,032 finals. Denser FLEURS speech runs about 0.5 s slower at the median.

## Limits

A word error is 0.05 points on sermon-v2 but 0.75 points on sermon-v1 (133
words), so sermon-v1 alone cannot resolve a fraction-of-a-point change; judge
by error counts there and by the pooled row. Scripture is read, not preached,
and preaching has no Spanish reference, so translation quality on preaching is
not measured. Two Journeys and Desiring God permit non-commercial use only; the
set is built locally for private evaluation and never committed or
redistributed.
