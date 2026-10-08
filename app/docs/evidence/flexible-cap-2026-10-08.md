# Flexible chunk cap that waits for a phrase pause — 2026-10-08

On the FLEURS replay set (see `fleurs-eval-2026-10-07.md`), most remaining
English errors sit near final boundaries, and a flat 8 s cap fixed many of
them by cutting less often, at 0.5 s more p95 latency. This change keeps the
6 s cap as a soft limit. Past it, the segmenter waits up to 2 s for a quiet
run of at least 200 ms (each frame at or below a quarter of the chunk's median
level) and cuts in its middle. At the 8 s hard cap it falls back to the old
rule: the quietest point in the last second, else a cut with the 300 ms
overlap. `LIVETR3_CAP_EXTEND_SECONDS` and `LIVETR3_CAP_PAUSE_MS` (defaults 2
and 200) control it; either at 0 restores the plain cap.

## Results

Model `mlx-community/gemma-4-e4b-it-8bit` with MTP, mlx-vlm 0.7.4, MLX 0.32.2,
600 ms silence, cap-repeat removal on. Conditions are `cap:silence:extend:pause`.

| Condition | WER | near-cut errors | chrF++ | BLEU | dropped finals | final latency median / p95 (s) |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 6 s, no extension (control) | 8.88% | 77 | 54.7 | 21.2 | 1 | 1.67 / 2.29 |
| +1 s, cut at any 80 ms dip | 8.80% | 69 | 54.7 | 21.7 | 1 | 1.69 / 2.32 |
| +2 s, cut at any 80 ms dip | 8.73% | 70 | 54.4 | 21.4 | 0 | 1.65 / 2.29 |
| +1 s, 200 ms pause | 8.88% | 69 | 54.2 | 20.7 | 1 | 1.81 / 2.34 |
| **+2 s, 200 ms pause** | **8.14%** | 62 | 54.7 | 21.2 | 0 | 1.83 / 2.79 |
| +2 s, 300 ms pause | 8.14% | 60 | 54.6 | 21.3 | 0 | 1.85 / 2.80 |
| flat 8 s cap (2026-10-07 sweep) | 8.36% | 59 | 54.8 | 21.6 | 0 | 2.03 / 2.91 |

Only 14 of 55 control cap cuts were forced through continuous speech; the rest
already found an 80 ms dip, which is often a gap between words inside a
sentence. Accepting any dip past the cap therefore changed little. Requiring a
200 ms pause moved 30 of 49 cap cuts past 6.1 s (6 reached the hard cap) and
gave the lowest WER of any condition, including the flat 8 s cap, at lower
median latency than that cap. A 1 s extension did not help.

## Limits

FLEURS is read speech with synthetic sentence pauses. The p95 cost (+0.5 s)
may be smaller on live preaching with frequent phrase pauses; a short live
check should confirm it before this reaches the main build. Outputs are in
ignored `dist/logs/fleurs/flexcap*`.
