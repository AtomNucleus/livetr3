#!/usr/bin/env python3
"""Paced real-Gemma chunk-cap comparison. Private captions stay in --output.

Run with the backend venv and PYTHONPATH=app/backend, after stopping live capture.
Uses one warmed worker, native defaults, and no production engine socket.
"""
import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


def words(text):
    # Match scripts.recorded_validation and previous replay evidence exactly.
    return re.findall(r"\w+", text.casefold(), flags=re.UNICODE)


def score(reference, hypothesis):
    """Exact word edit alignment, with error locations for boundary inspection."""
    ref, hyp = words(reference), words(hypothesis)
    costs = [[0] * (len(hyp) + 1) for _ in range(len(ref) + 1)]
    for i in range(len(ref) + 1):
        costs[i][0] = i
    for j in range(len(hyp) + 1):
        costs[0][j] = j
    for i, a in enumerate(ref, 1):
        for j, b in enumerate(hyp, 1):
            costs[i][j] = min(costs[i-1][j-1] + (a != b),
                              costs[i-1][j] + 1, costs[i][j-1] + 1)
    i, j = len(ref), len(hyp)
    errors = []
    while i or j:
        if i and j and costs[i][j] == costs[i-1][j-1] + (ref[i-1] != hyp[j-1]):
            if ref[i-1] != hyp[j-1]:
                errors.append(dict(kind='substitution', reference_index=i-1,
                                   hypothesis_index=j-1, reference=ref[i-1], hypothesis=hyp[j-1]))
            i, j = i-1, j-1
        elif i and costs[i][j] == costs[i-1][j] + 1:
            errors.append(dict(kind='deletion', reference_index=i-1,
                               hypothesis_index=j, reference=ref[i-1], hypothesis=''))
            i -= 1
        else:
            errors.append(dict(kind='insertion', reference_index=i,
                               hypothesis_index=j-1, reference='', hypothesis=hyp[j-1]))
            j -= 1
    return dict(reference_words=len(ref), word_errors=costs[-1][-1],
                wer=costs[-1][-1] / len(ref), alignment_errors=list(reversed(errors)))


def competing_workers(exclude_host_pids=()):
    rows = subprocess.check_output(['ps', '-axo', 'pid,ppid,command'], text=True).splitlines()
    hosts = {int(row.split(None, 2)[0]) for row in rows
             if ('uds_host.py' in row or 'uvicorn server:app' in row)
             and len(row.split(None, 2)) == 3} - set(exclude_host_pids)
    return [row.strip() for row in rows if len(row.split(None, 2)) == 3
            and row.split(None, 2)[1].isdigit()
            and int(row.split(None, 2)[1]) in hosts and 'spawn_main' in row]


class Capture:
    query_params = {}

    def __init__(self, path):
        self.start = time.monotonic()
        self.rows = []
        self.file = path.open('w')

    async def send_json(self, payload):
        if payload['type'] in {'partial', 'final', 'error', 'speech_start'}:
            row = dict(elapsed=time.monotonic() - self.start, **payload)
            self.rows.append(row)
            self.file.write(json.dumps(row, ensure_ascii=False) + '\n')
            self.file.flush()


def gaps(times):
    values = np.diff(times)
    return dict(updates=len(times), first_translation_seconds=times[0] if times else None,
                p95_seconds=float(np.percentile(values, 95)) if len(values) else None,
                worst_seconds=float(max(values)) if len(values) else None,
                over_two_seconds=int(np.count_nonzero(values > 2)))


def retained_word_count(tokens, final_tokens):
    """Longest order-preserving word match, without counting rewritten words."""
    previous = [0] * (len(final_tokens) + 1)
    for a in tokens:
        current = [0]
        for j, b in enumerate(final_tokens, 1):
            current.append(previous[j-1] + 1 if a == b else max(previous[j], current[-1]))
        previous = current
    return previous[-1]


def summarize(rows, reference, clip_seconds, feed_seconds, drain_seconds):
    high_chars, high_words, char_times, word_times = {}, {}, [], []
    finals = []
    for row in rows:
        if row['type'] not in {'partial', 'final'}:
            continue
        key, target = row['utterance_id'], row['translation']
        # Per-utterance high water rejects repeated full hypotheses. This is
        # hypothesis growth, not proof of newly spoken or correct target words.
        if len(target) > high_chars.get(key, 0):
            char_times.append(row['elapsed'])
            high_chars[key] = len(target)
        count = len(words(target))
        if row['type'] == 'partial' and target and not target[-1].isspace():
            count = max(0, count - 1)
        if count > high_words.get(key, 0):
            word_times.append(row['elapsed'])
            high_words[key] = count
        if row['type'] == 'final':
            finals.append(row)
    source = ' '.join(row['original'] for row in finals)
    final_targets = {row['utterance_id']: words(row['translation']) for row in finals}
    confirmed, confirmed_times, retained, retained_times = {}, [], {}, []
    for row in rows:
        if row['type'] not in {'partial', 'final'}:
            continue
        key = row['utterance_id']
        tokens = words(row['translation'])
        if row['type'] == 'partial' and row['translation'] and not row['translation'][-1].isspace():
            tokens = tokens[:-1]
        count = 0
        for a, b in zip(tokens, final_targets.get(key, [])):
            if a != b:
                break
            count += 1
        if count > confirmed.get(key, 0):
            confirmed_times.append(row['elapsed'])
            confirmed[key] = count
        count = retained_word_count(tokens, final_targets.get(key, []))
        if count > retained.get(key, 0):
            retained_times.append(row['elapsed'])
            retained[key] = count
    scoring = score(reference, source)
    boundaries, offset = [], 0
    for row in finals[:-1]:
        offset += len(words(row['original']))
        boundaries.append(offset)
    for error in scoring['alignment_errors']:
        error['near_final_boundary'] = any(abs(error['hypothesis_index'] - b) <= 2 for b in boundaries)
    return dict(character_growth=gaps(char_times), word_growth=gaps(word_times),
                final_prefix_growth=gaps(confirmed_times),
                final_retained_word_growth=gaps(retained_times),
                clip_seconds=clip_seconds, feed_seconds=feed_seconds,
                final_drain_seconds=drain_seconds,
                last_final_after_clip_seconds=max((r['elapsed'] for r in finals), default=0)-clip_seconds,
                forced_finals=sum(r.get('commit_reason') == 'max_utterance_cap' for r in finals),
                reused_boundaries=sum(r.get('commit_reason') == 'decoded_prefix' for r in finals),
                final_count=len(finals), unique_final_ids=len({r['utterance_id'] for r in finals}),
                empty_finals=sum(not r['original'] or not r['translation'] for r in finals),
                errors=[r for r in rows if r['type'] == 'error'],
                source=source, finals=finals, **scoring)


async def replay(cap, name, worker, audio, output, reference, clip_seconds, id_base, silence_ms=150, session_type=None):
    from protocol import ConfigMessage
    from session import SessionHub, TranscriptionSession
    if competing_workers():
        raise RuntimeError('Live engine worker exists; stop capture before replay')
    capture = Capture(output / f'{name}.jsonl')
    value = (session_type or TranscriptionSession)(capture, worker, SessionHub())
    value.state.config = ConfigMessage(max_utterance_seconds=cap,
        partial_interval_seconds=.25, polish_enabled=False, min_silence_ms=silence_ms,
        speech_pad_ms=300, silero_threshold=.5, early_commit_enabled=False,
        early_commit_min_seconds=1, early_commit_punctuation=True,
        early_commit_stability=True, stability_window=2)
    value.segmenter = value._build_segmenter(value.state.config)
    value.state.running = True
    # The shared worker retains finalized IDs to cancel obsolete previews.
    # Different replay sessions must never reuse them.
    value.state.utterance_id = id_base
    start = time.monotonic()
    capture.start = start
    try:
        for offset in range(0, audio.size, 320):
            await asyncio.sleep(max(0, start + offset / 16000 - time.monotonic()))
            if offset % 16000 == 0 and competing_workers():
                raise RuntimeError('Live capture worker resumed; comparison aborted')
            frame = audio[offset:offset+320]
            if frame.size < 320:
                frame = np.pad(frame, (0, 320-frame.size))
            await value._receive_frame(frame)
        feed = time.monotonic() - start
        await value._flush_active_final()
        while value._jobs:
            await asyncio.gather(*list(value._jobs))
        result = summarize(capture.rows, reference, clip_seconds, feed,
                           time.monotonic() - start - feed)
        result['cap_seconds'] = cap
        result['silence_ms'] = silence_ms
        (output / f'{name}-summary.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(json.dumps(dict(run=name, **{k:v for k,v in result.items()
                    if k not in {'source', 'finals', 'alignment_errors', 'errors'}})), flush=True)
        return result
    finally:
        # A live-capture guard failure must leave no session jobs publishing
        # into a closed output file while main shuts down our worker.
        for task in list(value._jobs):
            task.cancel()
        if value._jobs:
            await asyncio.gather(*list(value._jobs), return_exceptions=True)
        capture.file.close()


async def main(args):
    conditions = ([tuple(map(int, item.split(':'))) for item in args.conditions.split(',')]
                  if args.conditions else [(int(cap), args.silence_ms) for cap in args.order.split(',')])
    if any(len(pair) != 2 or pair[0] not in (6, 8, 12) or pair[1] not in (150, 300, 400)
           for pair in conditions):
        raise ValueError('Comparison conditions must use caps 6/8/12 and silence 150/300/400 ms')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ['LIVETR3_TEMP_WAV_ROOT'] = str(output / 'temp-audio')
    os.environ['LIVETR3_ARCHIVE_ROOT'] = str(output / 'archives')
    os.environ['LIVETR3_BACKEND_TRACE'] = str(output / 'backend.jsonl')
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    from mlx_worker import MLXWorkerService, MODEL_PATH, AST_PROMPT
    root = Path(__file__).resolve().parents[1]
    native = (root / 'macos/LiveTR3Mac/Sources/LiveTR3Mac/LiveTR3Protocol.swift').read_text()
    for key, expected in dict(partial_interval_seconds='0.25', max_utterance_seconds='6',
                              min_silence_ms='150', speech_pad_ms='300', silero_threshold='0.5',
                              early_commit_enabled='false', polish_enabled='false',
                              code_switching_enabled='false', early_commit_min_seconds='1.0',
                              early_commit_punctuation='true', early_commit_stability='true').items():
        assert re.search(rf'{key}: {re.escape(expected)}\s*,', native), f'Native default changed: {key}'
    metadata = dict(commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
                    model=MODEL_PATH, prompt=AST_PROMPT, conditions=conditions,
                    warmup_silence_ms=args.silence_ms, preview_interval_seconds=.25, overlap_ms=300,
                    mlx_vlm=importlib.metadata.version('mlx-vlm'), mlx=importlib.metadata.version('mlx'),
                    audio_sha256=hashlib.sha256(args.audio.read_bytes()).hexdigest(),
                    reference_sha256=hashlib.sha256(args.reference.read_bytes()).hexdigest())
    revision = Path.home() / '.cache/huggingface/hub' / ('models--' + MODEL_PATH.replace('/', '--')) / 'refs/main'
    if revision.exists():
        metadata['cached_model_revision'] = revision.read_text().strip()
    (output / 'metadata.json').write_text(json.dumps(metadata, indent=2))
    audio, rate = sf.read(args.audio, dtype='float32')
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if rate != 16000:
        factor = math.gcd(rate, 16000)
        audio = resample_poly(audio, 16000//factor, rate//factor)
    clip_seconds = audio.size / 16000
    audio = np.concatenate([audio, np.zeros(32000, dtype='float32')])
    reference = args.reference.read_text()
    if competing_workers():
        raise RuntimeError('Live engine worker exists; wait for idle unload after stopping capture')
    worker = MLXWorkerService()
    try:
        await worker.start()  # Includes model load and its warmup; waits for actual worker readiness.
        print(json.dumps(dict(worker_status=worker._status.state,
                              message=worker._status.message)), flush=True)
        await replay(6, 'warmup', worker, audio, output, reference, clip_seconds, 1000, args.silence_ms)
        results = {}
        for i, (cap, silence_ms) in enumerate(conditions, 1):
            name = f'{i:02d}-{cap}s-{silence_ms}ms' if args.conditions else f'{i:02d}-{cap}s'
            results[name] = await replay(cap, name, worker, audio, output, reference, clip_seconds,
                                         (i + 1) * 1000, silence_ms)
            (output / 'summary.json').write_text(json.dumps(results, indent=2, ensure_ascii=False))
    finally:
        await worker.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--order', default='6,8,12,12,8,6')
    parser.add_argument('--conditions', help='Optional ordered cap:silence-ms pairs; overrides --order')
    parser.add_argument('--silence-ms', type=int, choices=(150, 300, 400), default=150,
                        help='Use 150 for native defaults; 400 reproduces the earlier replay settings')
    asyncio.run(main(parser.parse_args()))
