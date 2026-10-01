#!/usr/bin/env python3
"""Compare source-first and alternating phrases on one warmed Gemma worker."""
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


async def main(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for key, name in [('LIVETR3_TEMP_WAV_ROOT', 'temp-audio'), ('LIVETR3_ARCHIVE_ROOT', 'archives'),
                      ('LIVETR3_BACKEND_TRACE', 'backend.jsonl')]:
        os.environ[key] = str(output / name)
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    from mlx_worker import AST_PROMPT, PHRASE_AST_PROMPT, MLXWorkerService, MODEL_PATH
    root = Path(__file__).resolve().parents[1]
    audio, rate = sf.read(args.audio, dtype='float32')
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    factor = math.gcd(rate, 16000)
    if rate != 16000:
        audio = resample_poly(audio, 16000 // factor, rate // factor)
    clip_seconds = audio.size / 16000
    audio = np.concatenate([audio, np.zeros(32000, dtype='float32')])
    metadata = dict(commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
        candidate_sha256=hashlib.sha256((root/'app/backend/mlx_worker.py').read_bytes()).hexdigest(),
        model=MODEL_PATH, baseline_prompt=AST_PROMPT, candidate_prompt=PHRASE_AST_PROMPT,
        mlx=importlib.metadata.version('mlx'), mlx_vlm=importlib.metadata.version('mlx-vlm'),
        cap_seconds=6, silence_ms=400, preview_seconds=.25, overlap_ms=300,
        audio_sha256=hashlib.sha256(args.audio.read_bytes()).hexdigest(),
        reference_sha256=hashlib.sha256(args.reference.read_bytes()).hexdigest())
    revision = Path.home()/'.cache/huggingface/hub'/('models--'+MODEL_PATH.replace('/', '--'))/'refs/main'
    if revision.exists():
        metadata['model_revision'] = revision.read_text().strip()
    (output/'metadata.json').write_text(json.dumps(metadata, indent=2))
    (output/'evaluated_mlx_worker.py').write_bytes((root/'app/backend/mlx_worker.py').read_bytes())
    if competing_workers():
        raise RuntimeError('Live inference exists; refusing competing replay')
    worker = MLXWorkerService()
    results = {}
    try:
        worker._phrase_bilingual_enabled = False
        await worker.start()
        print(json.dumps(dict(worker_status=worker._status.state, message=worker._status.message)), flush=True)
        await replay(6, 'warmup-baseline', worker, audio, output, args.reference.read_text(), clip_seconds, 1000, 400)
        worker._phrase_bilingual_enabled = True
        await replay(6, 'warmup-candidate', worker, audio, output, args.reference.read_text(), clip_seconds, 2000, 400)
        for index, enabled in enumerate([False, True, True, False], 1):
            worker._phrase_bilingual_enabled = enabled
            name = f'{index:02d}-' + ('candidate' if enabled else 'baseline')
            results[name] = await replay(6, name, worker, audio, output,
                args.reference.read_text(), clip_seconds, (index+2)*1000, 400)
            (output/'summary.json').write_text(json.dumps(results, indent=2, ensure_ascii=False))
    finally:
        await worker.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
