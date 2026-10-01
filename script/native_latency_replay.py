#!/usr/bin/env python3
"""Repeat native file replay through converter, framing, UDS, store and SwiftUI.

Never opens the microphone. Only terminates child processes created by this script.
The baseline route is selected with LIVETR3_AUDIO_MAIN_ACTOR=1; model/settings match.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from chunk_limit_replay import competing_workers


def events(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--routes', default='main,direct,direct,main')
    parser.add_argument('--projector-modes', default='live,live,live,live')
    parser.add_argument('--silence-ms', help='Comma-separated 150/300/400 ms settings, one per route')
    args = parser.parse_args()
    routes = args.routes.split(',')
    silence_values = args.silence_ms.split(',') if args.silence_ms else ['150'] * len(routes)
    if len(silence_values) != len(routes) or any(value not in {'150', '300', '400'} for value in silence_values):
        raise ValueError('--silence-ms must supply one 150/300/400 value per route')
    if competing_workers():
        raise RuntimeError('Stop live model inference before native file replay')
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    audio, rate = sf.read(root / 'app/backend/validation/sermon-clip.wav', dtype='float32')
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    import math
    factor = math.gcd(rate, 48000)
    audio = resample_poly(audio, 48000 // factor, rate // factor)
    audio = np.concatenate([audio, np.zeros(2 * 48000, dtype='float32')])
    fixture = output / 'replay-48k.wav'
    sf.write(fixture, audio, 48000, subtype='FLOAT')
    socket = f'/tmp/livetr3-native-{os.getpid()}.sock'
    env = {**os.environ, 'LIVETR3_ENGINE_SOCKET': socket,
           'LIVETR3_BACKEND_TRACE': str(output / 'backend.jsonl'),
           'LIVETR3_ARCHIVE_ROOT': str(output / 'archives'),
           'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'PYTHONNOUSERSITE': '1'}
    with (output / 'backend.log').open('w') as log:
        host = subprocess.Popen([str(root / 'app/backend/.venv/bin/python'), 'uds_host.py'],
                                cwd=root / 'app/backend', env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 30
            while not Path(socket).exists():
                if host.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Diagnostic backend did not start')
                time.sleep(.1)
            for index, route in enumerate(routes, 1):
                mode = args.projector_modes.split(',')[index-1]
                path = output / f'{index}-{route}.jsonl'
                app_env = {**env, 'LIVETR3_DIAGNOSTIC_EXTERNAL_ENGINE': '1',
                           'LIVETR3_NATIVE_TRACE': str(path), 'LIVETR3_NATIVE_REPLAY': str(fixture),
                           'LIVETR3_DIAGNOSTIC_MIN_SILENCE_MS': silence_values[index-1],
                           'LIVETR3_AUDIO_MAIN_ACTOR': '1' if route == 'main' else '0',
                           'LIVETR3_PROJECTOR_READING_QUEUE': '1' if mode == 'reading' else '0'}
                with (output / f'{index}-{route}.log').open('w') as app_log:
                    app = subprocess.Popen([str(args.bundle.resolve() / 'Contents/MacOS/LiveTR3')],
                                           cwd=root, env=app_env, stdout=app_log, stderr=app_log)
                    try:
                        deadline = time.monotonic() + 180
                        ended_at = None
                        while time.monotonic() < deadline:
                            if competing_workers(exclude_host_pids=(host.pid,)):
                                raise RuntimeError('Other live model inference resumed; native replay aborted')
                            if app.poll() is not None:
                                raise RuntimeError(f'Diagnostic app exited: {app.returncode}')
                            rows = events(path)
                            if any(row['stage'] == 'replay_end' for row in rows):
                                ended_at = ended_at or time.monotonic()
                                # Fixed drain window retains late finals and avoids inferring completion from a quiet stream.
                                if time.monotonic() - ended_at >= 15:
                                    break
                            time.sleep(.25)
                        else:
                            raise RuntimeError('Diagnostic replay timed out')
                        print(json.dumps({'run': index, 'route': route, 'events': len(rows), 'trace': str(path)}), flush=True)
                    finally:
                        app.terminate()
                        app.wait(timeout=10)
        finally:
            host.terminate()
            host.wait(timeout=15)


if __name__ == '__main__':
    main()
