# FLEURS replay set, 600 ms silence and cap-cut repeats — 2026-10-07

The earlier tuning evidence used one private 51-second clip with a 133-word
English reference and no Spanish reference. This adds a public, larger set and
uses it to move the native silence default from 400 to 600 ms and to remove
words repeated across six-second cap cuts.

## Replay set

`script/build_fleurs_eval.py` builds eight clips (about ten minutes, 56
sentences, 1,363 reference words) from the FLEURS `en_us` test split (CC BY 4.0).
Each clip has seven sentences from one speaker gender, two with numbers and two
with negation, separated by seeded 0.3–1.3 s pauses. Levels match the retained
live recording (speech p95 frame RMS 0.022 over a 0.0003 noise floor). The
Spanish reference is FLEURS `es_419`, the professional FLORES translation of the
same sentences. Output lives in ignored `dist/eval/fleurs-v1/`.

`script/fleurs_replay.py` paces every clip through the real segmenter, session
and Gemma worker at native defaults, with `--conditions cap:silence` pairs.
`script/fleurs_score.py` reports English WER after Whisper's English normalizer,
errors on reference number and negation words and near final boundaries,
corpus chrF++/BLEU against the Spanish reference with one segment per clip,
and final latency from each final's last voiced frame.

## Results

Model `mlx-community/gemma-4-e4b-it-8bit`, mlx-vlm 0.7.4, MLX 0.32.2.

| Condition | WER | near-cut errors | numbers | negation | chrF++ | BLEU | final latency median / p95 (s) | last final after clip (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| ordinary decoding, 6 s / 400 ms | 10.56% | 99 | 1/23 | 1/22 | 54.0 | 20.5 | 1.90 / 2.75 | 1.09 |
| MTP, 6 s / 400 ms | 10.56% | 99 | 1/23 | 1/22 | 54.1 | 20.5 | 1.66 / 2.39 | 0.87 |
| MTP, 8 s / 400 ms | 9.24% | 78 | 0/23 | 1/22 | 54.6 | 21.5 | 1.87 / 2.94 | 1.54 |
| MTP, 10 s / 400 ms | 8.73% | 68 | 1/23 | 1/22 | 55.1 | 22.8 | 1.87 / 3.20 | 1.84 |
| MTP, 6 s / 600 ms | 9.24% | 83 | 1/23 | 1/22 | 54.7 | 21.2 | 1.71 / 2.41 | 0.98 |
| MTP, 8 s / 600 ms | 8.36% | 59 | 0/23 | 1/22 | 54.8 | 21.6 | 2.03 / 2.91 | 1.63 |
| **MTP, 6 s / 600 ms, repeat removal** | **8.88%** | 77 | 1/23 | 1/22 | **54.7** | **21.2** | **1.74 / 2.40** | 1.04 |

An ordered baseline/MTP/MTP/baseline run reproduced identical source and
Spanish scores in every MTP and baseline pass; MTP finals were about 0.25 s
faster in both orders, confirming the existing MTP default on public audio.

About 37% of finals at the six-second cap are forced cuts on continuous read
speech, and most source errors sit within two words of a final boundary. A
600 ms pause threshold merges more phrase pauses into one decode for about
0.05 s of added final latency. Longer caps were more accurate but added 0.5–0.8 s
at p95, which is too much for live captions.

When a cap cut finds no quiet frame it repeats the 300 ms overlap, so the next
caption can start with the previous caption's last word ("banned from | from
the Games"; Spanish "prohibidos de | de los Juegos"). After a cap cut, an exact
repeat of up to three leading words is now removed from each line separately,
never the whole caption.

## Limits

FLEURS is read speech with synthetic pauses, not a live room. WER includes
normalization artifacts (km/kilometers, wilful/willful) common to every
condition. Remaining errors are mainly at cap cuts and on names. A short live
check should confirm the 600 ms default, as was done for 400 ms.
