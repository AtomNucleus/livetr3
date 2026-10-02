#!/usr/bin/env python3
"""Untuned origin/main Gemma pipeline, serial warmed replay with explicit defaults."""
import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'script'), str(ROOT/'app/backend')]
from replay import guard, read_audio, resource_snapshot
from policy import prefix_length, words


async def main(args):
    import numpy as np
    args.output.mkdir(parents=True, exist_ok=True)
    guard()
    for name in ('LIVETR3_GEMMA_MTP','LIVETR3_PHRASE_BILINGUAL'):
        os.environ[name] = '0'
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      MODEL_PATH='mlx-community/gemma-4-e4b-it-8bit',
                      LIVETR3_BACKEND_TRACE=str(args.output/'trace.jsonl'),
                      LIVETR3_TEMP_WAV_ROOT=str(args.output/'temp-audio'),
                      LIVETR3_ARCHIVE_ROOT=str(args.output/'archives'))
    import chunk_limit_replay as harness
    from mlx_worker import MLXWorkerService, MODEL_PATH, AST_PROMPT
    class Capture(harness.Capture):
        instances = {}
        def __init__(self,path):
            super().__init__(path)
            self.instances[path.stem] = self
    harness.Capture = Capture
    audio = read_audio(args.audio)
    duration = len(audio)/16000
    audio = np.concatenate([audio,np.zeros(32000,dtype='float32')])
    reference = args.reference.read_text()
    cached = Path.home()/'.cache/huggingface/hub'/('models--'+MODEL_PATH.replace('/','--'))/'refs/main'
    metadata = dict(commit=__import__('subprocess').check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                    model=MODEL_PATH, revision=cached.read_text().strip(), prompt=AST_PROMPT,
                    cap_seconds=6, silence_ms=400, preview_seconds=.25,
                    versions={p:importlib.metadata.version(p) for p in ('mlx','mlx-vlm','transformers')},
                    audio_sha256=hashlib.sha256(args.audio.read_bytes()).hexdigest(),
                    reference_sha256=hashlib.sha256(args.reference.read_bytes()).hexdigest())
    metadata['before_load'] = resource_snapshot()
    worker = MLXWorkerService()
    start = time.monotonic()
    try:
        await worker.start()
        metadata['load_seconds'] = time.monotonic()-start
        print(worker._status.message,flush=True)
        await harness.replay(6,'warmup',worker,audio,args.output,reference,duration,1000,400)
        metadata['warm_worker'] = resource_snapshot(worker._process.pid)
        results=[]
        for i in range(args.runs):
            guard()
            name=f'run-{i+1}'
            result=await harness.replay(6,name,worker,audio,args.output,reference,duration,(i+2)*1000,400)
            capture=Capture.instances[name]
            finals={r['utterance_id']:words(r['translation']) for r in capture.rows if r['type']=='final'}
            growth, high, rewrites, positions, old=[],{},0,0,{}
            for row in capture.rows:
                if row['type'] not in ('partial','final'): continue
                line=row['utterance_id']; current=words(row['translation'])
                if row['type']=='partial' and row['translation'] and not row['translation'][-1].isspace():
                    current=current[:-1]
                previous=old.get(line,[]); common=prefix_length(previous,current)
                if common<len(previous):
                    rewrites+=1; positions+=len(previous)-common
                old[line]=current
                retained=prefix_length(current,finals.get(line,[]))
                if retained>=3 and retained>high.get(line,0):
                    growth.append(row['elapsed']); high[line]=retained
            result.update(usable_final_prefix_growth=harness.gaps(growth),
                          first_source=next((r['elapsed'] for r in capture.rows if r['type'] in ('partial','final') and r['original']),None),
                          target_rewrite_events=rewrites,replaced_word_positions=positions,
                          replay_start_monotonic=capture.start)
            traces=[json.loads(s) for s in (args.output/'trace.jsonl').read_text().splitlines()]
            commits={r['utterance']:r for r in traces if r['stage']=='segment_commit'}
            result['commit_to_final']=[r['elapsed']+capture.start-commits[r['utterance_id']]['monotonic'] for r in result['finals'] if r['utterance_id'] in commits]
            result['max_queue_wait']=max((r['queue_seconds'] for r in traces if r['stage']=='worker_dispatch' and (i+2)*1000 <= (r.get('utterance') or 0) < (i+3)*1000),default=0)
            results.append(result)
            (args.output/'summary.json').write_text(json.dumps(results,indent=2,ensure_ascii=False))
            print(json.dumps({k:v for k,v in result.items() if k not in ('source','finals','alignment_errors','errors')},ensure_ascii=False),flush=True)
    finally:
        if worker._process:
            metadata['after_runs'] = resource_snapshot(worker._process.pid)
        await worker.stop()
        (args.output/'metadata.json').write_text(json.dumps(metadata,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for flag in ('audio','reference','output'):
        parser.add_argument('--'+flag,type=Path,required=True)
    parser.add_argument('--runs',type=int,default=1)
    asyncio.run(main(parser.parse_args()))
