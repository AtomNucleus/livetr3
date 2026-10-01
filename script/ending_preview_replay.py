#!/usr/bin/env python3
"""Matched baseline/candidate ending reuse replay; private data stays in --output."""
import argparse
import asyncio
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from chunk_limit_replay import competing_workers, replay


async def main(args):
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for key, name in [('LIVETR3_TEMP_WAV_ROOT', 'temp-audio'), ('LIVETR3_ARCHIVE_ROOT', 'archives'),
                      ('LIVETR3_BACKEND_TRACE', 'backend.jsonl')]:
        os.environ[key] = str(output / name)
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['LIVETR3_ENGINE_SOCKET'] = str(output / 'engine.sock')
    from mlx_worker import AST_PROMPT, MLXWorkerService, MODEL_PATH
    from session import TranscriptionSession
    baseline_ref = subprocess.check_output(['git', 'rev-parse', args.baseline_ref], cwd=root, text=True).strip()
    source = subprocess.check_output(['git', 'show', f'{baseline_ref}:app/backend/session.py'], cwd=root)
    baseline_file = output / 'baseline_session.py'
    baseline_file.write_bytes(source)
    spec = importlib.util.spec_from_file_location('ending_replay_baseline', baseline_file)
    baseline = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = baseline
    spec.loader.exec_module(baseline)

    def instrument(base):
        class Instrumented(base):
            ending_reuses = 0
            final_decodes = 0

            def _schedule_ast(self, priority, utterance_id, audio):
                if priority == 'final': self.final_decodes += 1
                return super()._schedule_ast(priority, utterance_id, audio)

            async def _commit_utterance(self, *args, **kwargs):
                before = self.final_decodes
                accepted = await super()._commit_utterance(*args, **kwargs)
                if accepted and kwargs['reason'] == 'silero_end' and self.final_decodes == before:
                    self.ending_reuses += 1
                return accepted
        return Instrumented

    audio, rate = sf.read(args.audio, dtype='float32')
    if audio.ndim > 1: audio = audio.mean(axis=1)
    factor = math.gcd(rate, 16000)
    if rate != 16000: audio = resample_poly(audio, 16000 // factor, rate // factor)
    clip_seconds = audio.size / 16000
    audio = np.concatenate([audio, np.zeros(32000, dtype='float32')])
    reference = args.reference.read_text()
    metadata = dict(baseline_ref=baseline_ref, candidate_session_sha256=hashlib.sha256((root/'app/backend/session.py').read_bytes()).hexdigest(),
                    model=MODEL_PATH, prompt=AST_PROMPT, mlx=importlib.metadata.version('mlx'), mlx_vlm=importlib.metadata.version('mlx-vlm'),
                    cap_seconds=6, silence_ms=400, preview_seconds=.25, overlap_ms=300,
                    audio_sha256=hashlib.sha256(args.audio.read_bytes()).hexdigest(), reference_sha256=hashlib.sha256(args.reference.read_bytes()).hexdigest())
    revision = Path.home()/'.cache/huggingface/hub'/('models--'+MODEL_PATH.replace('/', '--'))/'refs/main'
    if revision.exists(): metadata['model_revision'] = revision.read_text().strip()
    (output/'metadata.json').write_text(json.dumps(metadata, indent=2))
    if competing_workers(): raise RuntimeError('Live inference exists; preserving it and refusing replay')
    worker = MLXWorkerService()
    results = {}
    try:
        await worker.start()
        print(json.dumps(dict(worker_status=worker._status.state, message=worker._status.message)), flush=True)
        await replay(6, 'warmup', worker, audio, output, reference, clip_seconds, 1000, 400)
        for i, (label, base) in enumerate([('baseline', baseline.TranscriptionSession), ('candidate', TranscriptionSession),
                                           ('candidate', TranscriptionSession), ('baseline', baseline.TranscriptionSession)], 1):
            captured = []
            cls = instrument(base)
            def create(*a, **k):
                value = cls(*a, **k)
                if label == "candidate": value._ending_preview_reuse_enabled = True
                captured.append(value)
                return value
            name = f'{i:02d}-{label}'
            result = await replay(6, name, worker, audio, output, reference, clip_seconds, (i+1)*1000, 400, create)
            result['ending_reuses'] = captured[0].ending_reuses
            result['final_decodes'] = captured[0].final_decodes
            results[name] = result
            (output/'summary.json').write_text(json.dumps(results, indent=2, ensure_ascii=False))
            print(json.dumps(dict(run=name, ending_reuses=result['ending_reuses'], final_decodes=result['final_decodes'])), flush=True)
    finally:
        await worker.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref', required=True)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
