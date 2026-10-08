#!/usr/bin/env python3
"""Paced real-Gemma replay of the FLEURS clip set for one decoding mode.

Run with the backend venv and PYTHONPATH=app/backend after stopping live
capture. One worker loads with --mode, warms on the last clip, then replays
every clip under each --conditions pair in order. Score the output
directory afterwards with script/fleurs_score.py.
"""
import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import time

import numpy as np
import soundfile as sf

from chunk_limit_replay import Capture, competing_workers, summarize


class WallCapture(Capture):
    """Adds wall time, so finals can be timed against their last voiced frame."""

    async def send_json(self, payload):
        if payload['type'] in {'partial', 'final', 'error', 'speech_start'}:
            row = dict(elapsed=time.monotonic() - self.start, wall=time.time(), **payload)
            self.rows.append(row)
            self.file.write(json.dumps(row, ensure_ascii=False) + '\n')
            self.file.flush()


async def replay(name, worker, audio, output, reference, id_base, cap, silence_ms):
    from protocol import ConfigMessage
    from session import SessionHub, TranscriptionSession
    if competing_workers():
        raise RuntimeError('Live engine worker exists; stop capture before replay')
    clip_seconds = audio.size / 16000
    audio = np.concatenate([audio, np.zeros(32000, dtype='float32')])
    capture = WallCapture(output / f'{name}.jsonl')
    value = TranscriptionSession(capture, worker, SessionHub())
    # Native ClientConfig.default, except the cap and silence under test.
    value.state.config = ConfigMessage(max_utterance_seconds=cap,
        partial_interval_seconds=.25, polish_enabled=False, min_silence_ms=silence_ms,
        speech_pad_ms=300, silero_threshold=.5, early_commit_enabled=False,
        early_commit_min_seconds=1, early_commit_punctuation=True,
        early_commit_stability=True, stability_window=2)
    value.segmenter = value._build_segmenter(value.state.config)
    value.state.running = True
    value.state.utterance_id = id_base
    start = time.monotonic()
    capture.start = start
    try:
        for offset in range(0, audio.size, 320):
            await asyncio.sleep(max(0, start + offset / 16000 - time.monotonic()))
            if offset % 16000 == 0 and competing_workers():
                raise RuntimeError('Live capture worker resumed; comparison aborted')
            frame = audio[offset:offset + 320]
            if frame.size < 320:
                frame = np.pad(frame, (0, 320 - frame.size))
            await value._receive_frame(frame)
        feed = time.monotonic() - start
        await value._flush_active_final()
        while value._jobs:
            await asyncio.gather(*list(value._jobs))
            await asyncio.sleep(0)
        result = summarize(capture.rows, reference, clip_seconds, feed,
                           time.monotonic() - start - feed)
        result['final_latency_seconds'] = [
            row['wall'] - row['last_audio_frame_unix_seconds'] for row in capture.rows
            if row['type'] == 'final' and row.get('last_audio_frame_unix_seconds')]
        result['cap_seconds'] = cap
        result['silence_ms'] = silence_ms
        (output / f'{name}-summary.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
        latency = result['final_latency_seconds']
        print(json.dumps(dict(run=name, finals=result['final_count'],
                              last_final_after_clip=round(result['last_final_after_clip_seconds'], 3),
                              median_final_latency=round(float(np.median(latency)), 3) if latency else None,
                              errors=len(result['errors']))), flush=True)
        return result
    finally:
        for task in list(value._jobs):
            task.cancel()
        if value._jobs:
            await asyncio.gather(*list(value._jobs), return_exceptions=True)
        capture.file.close()


def load(path):
    audio, rate = sf.read(path, dtype='float32')
    if rate != 16000 or audio.ndim != 1:
        raise ValueError(f'{path} must be mono 16 kHz')
    return audio


async def main(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      LIVETR3_TEMP_WAV_ROOT=str(output / 'temp-audio'),
                      LIVETR3_ARCHIVE_ROOT=str(output / 'archives'),
                      LIVETR3_BACKEND_TRACE=str(output / 'backend.jsonl'),
                      LIVETR3_GEMMA_MTP='1' if args.mode == 'mtp' else '0')
    from mlx_worker import MLXWorkerService, AST_PROMPT, MODEL_PATH
    root = Path(__file__).resolve().parents[1]
    clips = sorted(args.eval_dir.glob('clip-*.wav'))
    if args.clips:
        clips = [path for path in clips if path.stem in args.clips.split(',')]
    git = lambda *cmd: subprocess.check_output(['git', *cmd], cwd=root, text=True)
    metadata = dict(mode=args.mode, model=MODEL_PATH, prompt=AST_PROMPT,
                    conditions=args.conditions, clips=[path.stem for path in clips],
                    commit=git('rev-parse', 'HEAD').strip(),
                    worktree_diff_sha256=hashlib.sha256(git('diff', 'HEAD').encode()).hexdigest(),
                    manifest_sha256=hashlib.sha256((args.eval_dir / 'manifest.json').read_bytes()).hexdigest(),
                    versions={k: importlib.metadata.version(k) for k in ('mlx', 'mlx-vlm')})
    (output / 'metadata.json').write_text(json.dumps(metadata, indent=2))
    if competing_workers():
        raise RuntimeError('Another engine has a resident worker')
    worker = MLXWorkerService()
    id_base = 1000
    try:
        await worker.start()
        warm = sorted(args.eval_dir.glob('clip-*.wav'))[-1]
        await replay('warmup', worker, load(warm), output,
                     warm.with_suffix('.en.txt').read_text(), id_base, *args.conditions[0])
        for index, (cap, silence_ms) in enumerate(args.conditions, 1):
            for path in clips:
                id_base += 1000
                await replay(f'{index:02d}-{cap}s-{silence_ms}ms-{path.stem}', worker, load(path),
                             output, path.with_suffix('.en.txt').read_text(), id_base, cap, silence_ms)
    finally:
        await worker.stop()
    if args.mode == 'mtp':
        rows = [json.loads(line) for line in (output / 'backend.jsonl').read_text().splitlines()]
        if any(row['stage'] == 'mtp_fallback' for row in rows):
            raise RuntimeError('MTP fell back; do not label this a candidate measurement')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--eval-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=('baseline', 'mtp'), required=True)
    parser.add_argument('--conditions', default=[(6, 400)],
                        type=lambda s: [tuple(int(v) for v in item.split(':')) for item in s.split(',')],
                        help='Ordered cap-seconds:silence-ms pairs, e.g. 6:400,8:400')
    parser.add_argument('--clips', help='Comma-separated clip names; default all')
    asyncio.run(main(parser.parse_args()))
