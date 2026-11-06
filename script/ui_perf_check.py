#!/usr/bin/env python3
"""Per-PR check that a UI change doesn't slow captions. No microphone, no talking.

Builds this checkout's app, then replays one recorded clip through the full native
path (converter, socket, store, operator view, projector) into a single shared engine
started from this checkout's app/backend. It runs the installed app (A, main) and the
branch build (B) one after the other, so the only difference is the UI code. Reports
app CPU and final-caption latency for each and fails on a clear regression.

    ./script/ui_perf_check.py              # B then A, about 4 minutes
    ./script/ui_perf_check.py --order ABBA # cancels warm-up order effects, about 6 minutes

Quit LiveTR3 first: two engines on one GPU skew both. This script never quits it.
"""
import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / 'app/backend/.venv/bin/python'

try:
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
except ImportError:
    if Path(sys.executable).resolve() != VENV_PY.resolve() and VENV_PY.exists():
        os.execv(str(VENV_PY), [str(VENV_PY), '-I', __file__, *sys.argv[1:]])
    raise

DRAIN_SECONDS = 15
# Fail thresholds for B against A. Replay passes differ by about 0.1 s on their own.
MAX_MEDIAN_DELTA = 0.3
MAX_P95_DELTA = 0.5
MAX_CPU_RATIO = 1.25
CPU_SLACK = 5.0


def running(pattern, exact=False):
    args = ['pgrep', '-x' if exact else '-f', pattern]
    return subprocess.run(args, capture_output=True, text=True).stdout.split()


def cpu_seconds(pid):
    out = subprocess.run(['ps', '-o', 'time=', '-p', str(pid)], capture_output=True, text=True).stdout.strip()
    if not out:
        return None
    total = 0.0
    for part in out.split(':'):
        total = total * 60 + float(part)
    return total


def cpu_percent(pid):
    out = subprocess.run(['ps', '-o', '%cpu=', '-p', str(pid)], capture_output=True, text=True).stdout.strip()
    return float(out) if out else None


def trace_rows(path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # the app may be mid-write
    return rows


def build_bundle(dest, template):
    pkg = ROOT / 'macos/LiveTR3Mac'
    subprocess.run(['swift', 'build', '-c', 'release'], cwd=pkg, check=True)
    bin_dir = subprocess.run(['swift', 'build', '-c', 'release', '--show-bin-path'], cwd=pkg,
                             check=True, capture_output=True, text=True).stdout.strip()
    shutil.rmtree(dest, ignore_errors=True)
    (dest / 'Contents/MacOS').mkdir(parents=True)
    (dest / 'Contents/Resources').mkdir()
    shutil.copy2(Path(bin_dir) / 'LiveTR3', dest / 'Contents/MacOS/LiveTR3')
    shutil.copy2(template / 'Contents/Info.plist', dest / 'Contents/Info.plist')
    return dest


def percentile(values, q):
    if not values:
        return math.nan
    return float(np.percentile(values, q))


def analyze_archive(archive_dir):
    meta = json.loads((archive_dir / 'meta.json').read_text())
    started = dt.datetime.fromisoformat(meta['started_at']).timestamp()
    events = json.loads((archive_dir / 'transcript.json').read_text())
    lat, final_times = [], []
    reloads = errors = 0
    for event in events:
        p = event['payload']
        if p['type'] == 'final' and p.get('last_audio_frame_unix_seconds'):
            lat.append(started + event['timestamp_seconds'] - p['last_audio_frame_unix_seconds'])
            final_times.append(event['timestamp_seconds'])
        elif p['type'] == 'status' and 'reload' in p.get('message', '').lower():
            reloads += 1
        elif p['type'] == 'error':
            errors += 1
    gaps = [b - a for a, b in zip(final_times, final_times[1:])]
    return dict(finals=len(lat), median=statistics.median(lat) if lat else math.nan,
                p95=percentile(lat, 95), worst=max(lat, default=math.nan),
                longest_final_gap=max(gaps, default=0.0), reloads=reloads, errors=errors,
                archive=str(archive_dir))


def run_once(label, bundle, env, out, index):
    trace = out / f'{index}-{label}.jsonl'
    app_env = {**env, 'LIVETR3_DIAGNOSTIC_EXTERNAL_ENGINE': '1',
               'LIVETR3_NATIVE_TRACE': str(trace), 'LIVETR3_NATIVE_REPLAY': str(out / 'replay-48k.wav')}
    began = time.time()
    with (out / f'{index}-{label}.log').open('w') as log:
        app = subprocess.Popen([str(bundle / 'Contents/MacOS/LiveTR3')], cwd=ROOT, env=app_env,
                               stdout=log, stderr=log)
        samples, cpu_start, t_start, ended_at = [], None, None, None
        try:
            deadline = time.monotonic() + 300
            while True:
                if time.monotonic() > deadline:
                    raise RuntimeError(f'{label}: replay timed out')
                if app.poll() is not None:
                    raise RuntimeError(f'{label}: app exited with {app.returncode}; see {log.name}')
                stages = {row.get('stage') for row in trace_rows(trace)}
                if cpu_start is None and 'replay_start' in stages:
                    cpu_start, t_start = cpu_seconds(app.pid), time.monotonic()
                if cpu_start is not None:
                    pct = cpu_percent(app.pid)
                    if pct is not None:
                        samples.append(pct)
                if 'replay_end' in stages:
                    ended_at = ended_at or time.monotonic()
                    if time.monotonic() - ended_at >= DRAIN_SECONDS:
                        break
                time.sleep(0.5)
            cpu_avg = 100 * (cpu_seconds(app.pid) - cpu_start) / (time.monotonic() - t_start)
        finally:
            app.terminate()
            try:
                app.wait(timeout=10)
            except subprocess.TimeoutExpired:
                app.kill()
    pinned = sum(1 for s in samples if s >= 95) * 0.5
    return dict(label=label, began=began, ended=time.time(), cpu_avg=cpu_avg,
                cpu_p95=percentile(samples, 95), cpu_max=max(samples, default=math.nan),
                pinned_seconds=pinned)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--baseline', type=Path, default=Path('/Applications/LiveTR3.app'),
                        help='A bundle (default: the installed app, which tracks main)')
    parser.add_argument('--bundle', type=Path, help='B bundle; default builds this checkout')
    parser.add_argument('--order', default='BA', help='Run order of A and B, e.g. BA or ABBA')
    parser.add_argument('--audio', type=Path, default=ROOT / 'dist/eval/sermon-v1/clip-09.wav')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if set(args.order) - {'A', 'B'} or not {'A', 'B'} <= set(args.order):
        parser.error('--order must contain both A and B, e.g. BA or ABBA')
    if running('LiveTR3', exact=True) or running('uds_host.py'):
        sys.exit('LiveTR3 or a caption engine is running. Quit it first; this check needs the GPU to itself.')

    out = (args.output or ROOT / 'dist/logs/ui-check' / time.strftime('%Y-%m-%dT%H-%M-%S')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    bundle_b = args.bundle or build_bundle(ROOT / 'dist/ui-check/LiveTR3.app', args.baseline)
    bundles = {'A': args.baseline, 'B': bundle_b}

    audio, rate = sf.read(args.audio, dtype='float32')
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    g = math.gcd(rate, 48000)
    audio = resample_poly(audio, 48000 // g, rate // g).astype('float32')
    audio = np.concatenate([audio, np.zeros(2 * 48000, dtype='float32')])
    sf.write(out / 'replay-48k.wav', audio, 48000, subtype='FLOAT')

    socket = f'/tmp/livetr3-uicheck-{os.getpid()}.sock'
    env = {**os.environ, 'LIVETR3_ENGINE_SOCKET': socket, 'LIVETR3_ARCHIVE_ROOT': str(out / 'archives'),
           'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'PYTHONNOUSERSITE': '1'}
    runs = []
    with (out / 'engine.log').open('w') as log:
        host = subprocess.Popen([str(VENV_PY), 'uds_host.py'], cwd=ROOT / 'app/backend', env=env,
                                stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 60
            while not Path(socket).exists():
                if host.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError(f'Engine did not start; see {out / "engine.log"}')
                time.sleep(0.1)
            for i, label in enumerate(args.order, 1):
                print(f'==> pass {i}/{len(args.order)}: {label} ({bundles[label]})', flush=True)
                runs.append(run_once(label, bundles[label], env, out, i))
        finally:
            host.terminate()
            try:
                host.wait(timeout=15)
            except subprocess.TimeoutExpired:
                host.kill()

    archives = sorted((out / 'archives').glob('*/meta.json'))
    for run in runs:
        for meta in archives:
            started = dt.datetime.fromisoformat(json.loads(meta.read_text())['started_at']).timestamp()
            if run['began'] <= started <= run['ended']:
                run.update(analyze_archive(meta.parent))
        if 'finals' not in run:
            raise RuntimeError(f'No session archive found for pass {run["label"]}')

    def pooled(label, key, fn):
        return fn([r[key] for r in runs if r['label'] == label])

    summary = {label: dict(cpu_avg=pooled(label, 'cpu_avg', statistics.mean),
                           cpu_max=pooled(label, 'cpu_max', max),
                           pinned_seconds=pooled(label, 'pinned_seconds', max),
                           median=pooled(label, 'median', statistics.mean),
                           p95=pooled(label, 'p95', statistics.mean),
                           longest_final_gap=pooled(label, 'longest_final_gap', max),
                           finals=pooled(label, 'finals', min),
                           reloads=pooled(label, 'reloads', sum), errors=pooled(label, 'errors', sum))
               for label in 'AB'}
    a, b = summary['A'], summary['B']
    problems = []
    if b['median'] > a['median'] + MAX_MEDIAN_DELTA:
        problems.append(f'median latency {b["median"]:.2f}s vs {a["median"]:.2f}s')
    if b['p95'] > a['p95'] + MAX_P95_DELTA:
        problems.append(f'p95 latency {b["p95"]:.2f}s vs {a["p95"]:.2f}s')
    if b['cpu_avg'] > a['cpu_avg'] * MAX_CPU_RATIO + CPU_SLACK:
        problems.append(f'app CPU {b["cpu_avg"]:.0f}% vs {a["cpu_avg"]:.0f}%')
    if b['pinned_seconds'] >= 3:
        problems.append(f'app CPU at 95%+ for {b["pinned_seconds"]:.0f}s')
    if b['reloads'] or b['errors']:
        problems.append(f'{b["reloads"]} model reloads, {b["errors"]} errors')
    if b['finals'] < a['finals'] * 0.8:
        problems.append(f'only {b["finals"]} finals vs {a["finals"]}')

    print('\n            A (installed)   B (this branch)')
    for key, fmt in [('median', '{:.2f} s'), ('p95', '{:.2f} s'), ('cpu_avg', '{:.0f}%'), ('cpu_max', '{:.0f}%'),
                     ('longest_final_gap', '{:.1f} s'), ('finals', '{}'), ('reloads', '{}'), ('errors', '{}')]:
        print(f'{key:<18}{fmt.format(a[key]):<16}{fmt.format(b[key])}')
    report = dict(order=args.order, audio=str(args.audio), baseline=str(args.baseline), branch=str(bundle_b),
                  runs=runs, summary=summary, problems=problems)
    (out / 'report.json').write_text(json.dumps(report, indent=2))
    print(f'\nReport: {out / "report.json"}')
    if problems:
        print('UI perf check FAILED: ' + '; '.join(problems))
        sys.exit(1)
    print('UI perf check passed.')


if __name__ == '__main__':
    main()
