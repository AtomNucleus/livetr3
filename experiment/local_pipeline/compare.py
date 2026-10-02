#!/usr/bin/env python3
"""Serial B-C-C-B comparison; each process loads only its own pipeline."""
import argparse
from pathlib import Path
import subprocess
import sys
from replay import guard


def main(args):
    guard()
    here=Path(__file__).resolve().parent
    args.output.mkdir(parents=True,exist_ok=True)
    # Consecutive candidate trials share a warmed pair; reverse baseline is
    # independently warmed again. Cold load is never mixed into scored latency.
    for index,(condition,runs) in enumerate((('baseline',1),('candidate',2),('baseline',1)),1):
        guard()
        python=args.baseline_python if condition=='baseline' else Path(sys.executable)
        script='baseline.py' if condition=='baseline' else 'replay.py'
        output=args.output/f'{index:02d}-{condition}'
        command=[str(python),str(here/script),'--audio',str(args.audio.resolve()),
                 '--reference',str(args.reference.resolve()),'--output',str(output.resolve()),
                 '--runs',str(runs)]
        print(f'{condition}: {runs} scored run(s) after full warmup',flush=True)
        with (args.output/f'{index:02d}-{condition}.log').open('w') as log:
            subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True,cwd=here.parents[1])
    print('Finished serial B-C-C-B. Private summaries remain in the output directory.',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for flag in ('audio','reference','output','baseline-python'):
        p.add_argument('--'+flag,type=Path,required=True)
    main(p.parse_args())
