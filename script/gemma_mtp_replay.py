#!/usr/bin/env python3
"""Ordered, warmed MTP audio comparison; private data stays in ignored output.

Use the existing backend Python with PYTHONPATH=app/backend. Each condition
owns one worker, warms on the full clip, scores one paced replay, then stops.
"""
import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import subprocess

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from chunk_limit_replay import competing_workers, replay


async def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      LIVETR3_TEMP_WAV_ROOT=str(output / 'temp-audio'),
                      LIVETR3_ARCHIVE_ROOT=str(output / 'archives'),
                      LIVETR3_BACKEND_TRACE=str(output / 'backend.jsonl'),
                      LIVETR3_GEMMA_MTP='1' if args.mode == 'mtp' else '0')
    from mlx_worker import MLXWorkerService, AST_PROMPT, MODEL_PATH
    audio, rate = sf.read(args.audio, dtype='float32')
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    factor = math.gcd(rate, 16000)
    audio = resample_poly(audio, 16000 // factor, rate // factor)
    duration = audio.size / 16000
    audio = np.concatenate([audio, np.zeros(32000, dtype='float32')])
    reference = args.reference.read_text()
    metadata = dict(mode=args.mode, model=MODEL_PATH, prompt=AST_PROMPT,
                    drafter=os.getenv('LIVETR3_MTP_MODEL', 'mlx-community/gemma-4-E4B-it-assistant-bf16'),
                    draft_block_size=3, cap_seconds=6, silence_ms=400,
                    preview_seconds=.25, overlap_ms=300,
                    versions={k: importlib.metadata.version(k) for k in ('mlx', 'mlx-vlm')},
                    commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                    audio_sha256=hashlib.sha256(args.audio.read_bytes()).hexdigest(),
                    reference_sha256=hashlib.sha256(args.reference.read_bytes()).hexdigest())
    for key in ('model', 'drafter'):
        ref = Path.home() / '.cache/huggingface/hub' / ('models--' + metadata[key].replace('/', '--')) / 'refs/main'
        metadata[key + '_revision'] = ref.read_text().strip()
    (output / 'metadata.json').write_text(json.dumps(metadata, indent=2))
    if competing_workers():
        raise RuntimeError('Another engine has a resident worker')
    worker = MLXWorkerService()
    try:
        await worker.start()
        await replay(6, 'warmup', worker, audio, output, reference, duration, 1000, 400)
        await replay(6, args.mode, worker, audio, output, reference, duration, 2000, 400)
    finally:
        await worker.stop()
    if args.mode == 'mtp':
        rows = [json.loads(line) for line in (output / 'backend.jsonl').read_text().splitlines()]
        if any(row['stage'] == 'mtp_fallback' for row in rows):
            raise RuntimeError('MTP fell back; do not label this a candidate measurement')
        if not any(row.get('mtp') and row.get('drafted', 0) > 0 for row in rows):
            raise RuntimeError('No MTP proposals were verified')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=('baseline', 'mtp'), required=True)
    asyncio.run(run(parser.parse_args()))
