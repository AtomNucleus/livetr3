#!/usr/bin/env python3
"""Replay FLEURS-8, sermon-v1 and sermon-v2 with real Gemma and print one scoreboard.

Stop live capture first. Each set replays at native defaults in its own engine
process (fleurs_replay.py, backend venv) into OUTPUT/<set>, then
fleurs_score.py prints every set plus a pooled row. Engine flags pass through
the environment:
  LIVETR3_MTP_BLOCK=4 python3 -I script/scoreboard.py dist/logs/mtp-block/B1-block4
Finished sets are kept, so rerunning resumes; --score-only rescores. Give
several outputs to compare passes, e.g. a baseline/candidate/candidate/baseline run:
  python3 -I script/scoreboard.py --score-only dist/logs/mtp-block/{A1,B1,B2,A2}-*
"""
import argparse
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SETS = ('fleurs-v1', 'sermon-v1', 'sermon-v2')


def main(args):
    # Eval data lives in the main checkout's ignored dist/, also from a worktree.
    common = subprocess.check_output(['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                                     cwd=ROOT, text=True).strip()
    eval_root = args.eval_root or Path(common).parent / 'dist/eval'
    sets = args.sets.split(',')
    if not args.score_only:
        for output in args.outputs:
            for name in sets:
                run = output.resolve() / name
                if (run / 'complete').exists():
                    continue
                if run.exists():
                    raise SystemExit(f'{run} holds an unfinished replay; move it aside first')
                subprocess.run([str(ROOT / 'app/backend/.venv/bin/python'), str(ROOT / 'script/fleurs_replay.py'),
                                '--eval-dir', str(eval_root / name), '--mode', 'mtp',
                                '--conditions', args.conditions, '--output', str(run)],
                               env=dict(os.environ, PYTHONPATH=str(ROOT / 'app/backend')), cwd=ROOT, check=True)
                (run / 'complete').touch()
    runs = [output / name for output in args.outputs for name in sets if (output / name / 'complete').exists()]
    if not runs:
        raise SystemExit('No finished replays to score')
    subprocess.run(['uv', 'run', '--quiet', '--no-project', '--with', 'sacrebleu', '--with', 'whisper-normalizer',
                    'python', '-I', str(ROOT / 'script/fleurs_score.py'), '--pool', *map(str, runs)],
                   cwd=ROOT, check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('outputs', type=Path, nargs='+', help='One directory per pass')
    parser.add_argument('--sets', default=','.join(SETS))
    parser.add_argument('--conditions', default='6:600', help='fleurs_replay.py conditions; default native')
    parser.add_argument('--eval-root', type=Path, help="Default: the main checkout's dist/eval")
    parser.add_argument('--score-only', action='store_true')
    main(parser.parse_args())
