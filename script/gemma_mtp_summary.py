#!/usr/bin/env python3
"""Numerical summaries of gemma_mtp_replay outputs; no captions printed."""
import argparse
import json
from pathlib import Path

import numpy as np


def distribution(values):
    return dict(median=float(np.median(values)), p95=float(np.percentile(values, 95)),
                worst=float(max(values))) if values else None


def summarize(directory):
    metadata = json.loads((directory / 'metadata.json').read_text())
    mode = metadata['mode']
    summary = json.loads((directory / f'{mode}-summary.json').read_text())
    trace = [json.loads(line) for line in (directory / 'backend.jsonl').read_text().splitlines()]
    windows, current = [], None
    for row in trace:
        if row['stage'] == 'worker_dispatch':
            current = row
        elif row['stage'] == 'worker_complete' and current is not None:
            if row.get('utterance', 0) >= 2000 and row.get('kind') == 'ast':
                windows.append((current, row))
            current = None
    decodes = [row for row in trace if row['stage'] == 'ast_decode'
               and any(a['monotonic'] <= row['monotonic'] <= b['monotonic'] for a, b in windows)]
    finals = [row for row in decodes if row['priority'] == 'final' and row.get('finish_reason') == 'stop']
    proposed = sum(row['drafted'] for row in decodes)
    accepted = sum(row['accepted'] for row in decodes)
    generation_seconds = sum(row['generation_tokens'] / row['generation_tps'] for row in finals
                             if row.get('generation_tps', 0) > 0)
    return dict(run=directory.name, mode=mode,
                retained=summary['final_retained_word_growth'],
                first_target_characters=summary['character_growth']['first_translation_seconds'],
                last_final_after_clip=summary['last_final_after_clip_seconds'],
                word_errors=summary['word_errors'], reference_words=summary['reference_words'],
                error_kinds={kind: sum(e['kind'] == kind for e in summary['alignment_errors'])
                             for kind in ('substitution', 'deletion', 'insertion')},
                complete_finals=summary['final_count']-summary['empty_finals'],
                unique_final_ids=summary['unique_final_ids'], failures=len(summary['errors']),
                final_inference=distribution([b['inference_seconds'] for a, b in windows
                                              if b['priority'] == 'final']),
                final_queue=distribution([a['queue_seconds'] for a, b in windows
                                          if b['priority'] == 'final']),
                final_first_response=distribution([r['first_response_seconds'] for r in finals]),
                # mlx-vlm reports target prompt processing from its own timer;
                # this includes audio encoder/prefill, excludes prepare_inputs.
                final_target_prompt=distribution([r['prompt_tokens'] / r['prompt_tps'] for r in finals]),
                final_generation_tps=sum(r['generation_tokens'] for r in finals) / generation_seconds
                if generation_seconds else None,
                drafted=proposed, accepted=accepted,
                acceptance_fraction=accepted / proposed if proposed else None,
                fallback_count=sum(r['stage'] == 'mtp_fallback' for r in trace))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directories', type=Path, nargs='+')
    args = parser.parse_args()
    print(json.dumps([summarize(path) for path in args.directories], indent=2))
