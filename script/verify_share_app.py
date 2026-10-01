#!/usr/bin/env python3
"""Private, offline native file replay using a bundle's own Python and models.

No microphone capture. Only stops the app/backend this script creates.
"""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import time

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from chunk_limit_replay import competing_workers, score, gaps


def events(path):
    return [json.loads(row) for row in path.read_text().splitlines()] if path.exists() else []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if competing_workers():
        raise RuntimeError('Another engine has a resident worker')
    bundle = args.bundle.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True)
    audio, rate = sf.read(args.audio, dtype='float32')
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    factor = math.gcd(rate, 48000)
    audio = resample_poly(audio, 48000 // factor, rate // factor)
    fixture = output / 'private-replay.wav'
    sf.write(fixture, np.concatenate([audio, np.zeros(96000, dtype='float32')]), 48000, subtype='FLOAT')
    empty_home = output / 'empty-home'
    empty_home.mkdir()
    native = output / 'native.jsonl'
    backend = output / 'backend.jsonl'
    socket = f'/tmp/livetr3-share-verify-{os.getpid()}.sock'
    env = dict(PATH='/usr/bin:/bin', HOME=str(empty_home),
               LIVETR3_ENGINE_SOCKET=socket, LIVETR3_ARCHIVE_ROOT=str(output / 'archives'),
               LIVETR3_RUNTIME_LOG=str(output / 'runtime.log'), LIVETR3_BACKEND_TRACE=str(backend),
               LIVETR3_NATIVE_TRACE=str(native), LIVETR3_NATIVE_REPLAY=str(fixture),
               LIVETR3_TEMP_WAV_ROOT=str(output / 'temp-audio'), LIVETR3_DIAGNOSTIC_MIN_SILENCE_MS='400')
    hosts = set()
    with (output / 'app.log').open('w') as log:
        app = subprocess.Popen([str(bundle / 'Contents/MacOS/LiveTR3')], env=env,
                               cwd=empty_home, stdout=log, stderr=log)
        try:
            deadline, ended = time.monotonic() + 180, None
            while time.monotonic() < deadline:
                processes = subprocess.check_output(['ps', '-axo', 'pid,ppid,command'], text=True).splitlines()
                hosts.update(int(row.split(None, 2)[0]) for row in processes
                             if len(row.split(None, 2)) == 3 and row.split(None, 2)[1] == str(app.pid)
                             and 'uds_host.py' in row)
                if competing_workers(exclude_host_pids=hosts):
                    raise RuntimeError('Other live model inference resumed')
                if app.poll() is not None:
                    raise RuntimeError(f'App exited: {app.returncode}')
                if any(row['stage'] == 'replay_end' for row in events(native)):
                    ended = ended or time.monotonic()
                    if time.monotonic() - ended > 15:
                        break
                time.sleep(.25)
            else:
                raise RuntimeError('Native replay timed out')
            assert len(hosts) == 1
            cwd = subprocess.check_output(['lsof', '-a', '-p', str(next(iter(hosts))), '-d', 'cwd', '-Fn'], text=True)
            assert str(bundle / 'Contents/Resources/Engine/backend') in cwd
        finally:
            app.terminate()
            app.wait(timeout=10)
            for pid in hosts:
                subprocess.run(['kill', '-TERM', str(pid)], check=False)
    rows = events(native)
    archive = next((output / 'archives').glob('*/transcript.json'))
    payloads = [row['payload'] for row in json.loads(archive.read_text())]
    finals = [row for row in payloads if row['type'] == 'final']
    errors = [row for row in payloads if row['type'] == 'error']
    start = next(row['unix'] for row in rows if row['stage'] == 'replay_start')
    high, times = {}, []
    for row in rows:
        if row['stage'] == 'view_text_update_proxy' and row.get('surface') == 'operator' and row['field'] == 'translation':
            if row['chars'] > high.get(row['utterance'], 0):
                times.append(row['unix'] - start)
                high[row['utterance']] = row['chars']
    back = events(backend)
    report = dict(final_count=len(finals), unique_final_ids=len({row['utterance_id'] for row in finals}),
                  empty_finals=sum(not row['original'] or not row['translation'] for row in finals),
                  errors=errors, mtp_decodes=sum(row.get('mtp', False) for row in back),
                  mtp_fallbacks=sum(row['stage'] == 'mtp_fallback' for row in back),
                  source_score=score(args.reference.read_text(), ' '.join(row['original'] for row in finals)),
                  operator_view_character_growth=gaps(times), packaged_backend=True)
    (output / 'summary.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({key: value for key, value in report.items() if key != 'source_score'}), flush=True)
    print('source errors', report['source_score']['word_errors'], flush=True)
    native_finals = {row['utterance'] for row in rows if row['stage'] == 'store_caption'
                     and row.get('surface', 'operator') == 'operator' and row['type'] == 'final'}
    assert {row['utterance_id'] for row in finals} == native_finals
    assert len(finals) == report['unique_final_ids'] and len(finals) > 0
    assert not errors and not report['empty_finals'] and not report['mtp_fallbacks'] and report['mtp_decodes'] > 0
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)


if __name__ == '__main__':
    main()
