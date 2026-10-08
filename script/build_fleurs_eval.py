#!/usr/bin/env python3
"""Build paced English clips with English and Spanish references from FLEURS.

FLEURS (CC BY 4.0) pairs English read speech with professional Spanish
translations of the same FLORES sentence. Each clip joins several sentences
from one speaker gender with seeded pauses, so the live segmenter sees real
boundaries, some shorter than the 400 ms silence threshold. Every clip mixes
sentences with numbers, negation and neither.

Needs pyarrow and soundfile (not part of the backend environment):
  python -I script/build_fleurs_eval.py --fleurs <snapshot dir> --output dist/eval/fleurs-v1
"""
import argparse
import csv
import io
import json
import random
import re
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import soundfile as sf

RATE = 16_000
FRAME = 320
# Levels match the retained live recording: speech p95 frame RMS about 0.022
# over a room-noise floor of about 0.0003, below the backend's 0.0006 voiced
# frame threshold.
SPEECH_P95_RMS = 0.022
NOISE_RMS = 0.0003
TRIM_RMS = 0.002
TRIM_PAD_SECONDS = 0.15
NUMERIC = re.compile(r"\d")
NEGATION = re.compile(r"\b(not|no|never|nor|none|nothing|without|cannot)\b|n't\b", re.I)


def frame_rms(audio):
    frames = audio[: audio.size // FRAME * FRAME].reshape(-1, FRAME)
    return np.sqrt(np.mean(np.square(frames), axis=1))


def prepare(audio):
    # Level first, so quiet recordings trim against the same speech level.
    p95 = float(np.percentile(frame_rms(audio), 95))
    if p95 < 1e-5:
        return None
    audio = np.clip(audio * (SPEECH_P95_RMS / p95), -1, 1).astype(np.float32)
    levels = frame_rms(audio)
    voiced = np.flatnonzero(levels >= TRIM_RMS)
    pad = int(TRIM_PAD_SECONDS * RATE / FRAME)
    start, end = max(0, voiced[0] - pad), min(levels.size, voiced[-1] + pad + 1)
    return audio[start * FRAME : end * FRAME]


def main(args):
    rows = pq.read_table(args.fleurs / "parquet-data/en_us/test-00000-of-00001.parquet",
                         columns=["id", "audio", "raw_transcription", "gender"]).to_pylist()
    spanish = {}
    with open(args.fleurs / "data/es_419/test.tsv", newline="") as handle:
        for row in csv.reader(handle, delimiter="\t", quoting=csv.QUOTE_NONE):
            spanish.setdefault(int(row[0]), row[2])
    recordings = {}
    for row in rows:
        if row["id"] in spanish:
            recordings.setdefault(row["id"], []).append(row)

    rng = random.Random(args.seed)
    ids = sorted(recordings)
    rng.shuffle(ids)
    numeric = [i for i in ids if NUMERIC.search(recordings[i][0]["raw_transcription"])]
    negation = [i for i in ids if i not in numeric
                and NEGATION.search(recordings[i][0]["raw_transcription"])]
    other = [i for i in ids if i not in numeric and i not in negation]

    args.output.mkdir(parents=True, exist_ok=True)
    manifest = dict(source="google/fleurs en_us + es_419 test", license="CC BY 4.0",
                    seed=args.seed, clips=[])
    noise = np.random.default_rng(args.seed)
    for clip in range(args.clips):
        gender = clip % 2
        chosen = ([numeric.pop() for _ in range(2)] + [negation.pop() for _ in range(2)]
                  + [other.pop() for _ in range(args.sentences - 4)])
        rng.shuffle(chosen)
        pieces, sentences, offset = [np.zeros(int(0.5 * RATE), np.float32)], [], 0.5
        for index, sentence_id in enumerate(chosen):
            options = recordings[sentence_id]
            match = [row for row in options if row["gender"] == gender] or options
            row = rng.choice(match)
            audio, rate = sf.read(io.BytesIO(row["audio"]["bytes"]), dtype="float32")
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            if rate != RATE:
                raise ValueError(f"Unexpected FLEURS rate {rate}")
            audio = prepare(audio)
            if audio is None:
                raise ValueError(f"Silent FLEURS recording for sentence {sentence_id}")
            text = row["raw_transcription"]
            sentences.append(dict(
                id=sentence_id, start_seconds=round(offset, 3),
                end_seconds=round(offset + audio.size / RATE, 3), gender=row["gender"],
                numeric=bool(NUMERIC.search(text)), negation=bool(NEGATION.search(text)),
                english=text, spanish=spanish[sentence_id]))
            pieces.append(audio)
            offset += audio.size / RATE
            if index < len(chosen) - 1:
                pause = rng.uniform(args.min_pause, args.max_pause)
                sentences[-1]["pause_after_seconds"] = round(pause, 3)
                pieces.append(np.zeros(int(pause * RATE), np.float32))
                offset += int(pause * RATE) / RATE
        pieces.append(np.zeros(int(0.5 * RATE), np.float32))
        audio = np.concatenate(pieces)
        audio += noise.normal(0, NOISE_RMS, audio.size).astype(np.float32)
        name = f"clip-{clip + 1:02d}"
        sf.write(args.output / f"{name}.wav", audio, RATE, subtype="PCM_16")
        (args.output / f"{name}.en.txt").write_text(" ".join(s["english"] for s in sentences) + "\n")
        (args.output / f"{name}.es.txt").write_text(" ".join(s["spanish"] for s in sentences) + "\n")
        manifest["clips"].append(dict(name=name, seconds=round(audio.size / RATE, 3),
                                      gender=gender, sentences=sentences))
        print(f"{name}: {audio.size / RATE:.1f} s, {len(sentences)} sentences")
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fleurs", type=Path, required=True, help="google/fleurs snapshot directory")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--clips", type=int, default=8)
    parser.add_argument("--sentences", type=int, default=7)
    parser.add_argument("--min-pause", type=float, default=0.3)
    parser.add_argument("--max-pause", type=float, default=1.3)
    parser.add_argument("--seed", type=int, default=7)
    main(parser.parse_args())
