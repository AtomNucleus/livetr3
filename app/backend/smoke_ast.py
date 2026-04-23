from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf

from mlx_worker import MLXWorker


def read_wav_16k_mono(path: Path) -> np.ndarray:
    audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    if sample_rate != 16_000:
        raise ValueError(
            f"{path} is {sample_rate} Hz. Convert to 16 kHz mono float32 before smoke testing."
        )
    if mono.shape[0] > 25 * 16_000:
        mono = mono[: 25 * 16_000]
    return np.clip(mono, -1.0, 1.0).astype(np.float32, copy=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gemma 4 E4B MLX audio smoke test")
    parser.add_argument("wav", type=Path, help="Path to a <=10s, 16 kHz mono WAV file")
    parser.add_argument("--source", default="English")
    parser.add_argument("--target", default="Spanish")
    parser.add_argument("--vocab", default="", help="Comma-separated custom vocabulary")
    args = parser.parse_args()

    custom_vocab = [item.strip() for item in args.vocab.split(",") if item.strip()]
    worker = MLXWorker()
    original, translation = worker.ast(
        read_wav_16k_mono(args.wav),
        args.source,
        args.target,
        prior_context=[],
        custom_vocab=custom_vocab,
        max_tokens=256,
    )
    print(original)
    print(f"{args.target}: {translation}")


if __name__ == "__main__":
    main()

