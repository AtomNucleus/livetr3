#!/usr/bin/env python3
"""Same-audio greedy equivalence, preprocessing profile and cancellation probe.

Run only with no other resident inference. Captions are written only to --output.
"""
import argparse
import cProfile
import json
import math
import os
from pathlib import Path
import time

import soundfile as sf
from scipy.signal import resample_poly
from chunk_limit_replay import competing_workers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if competing_workers():
        raise RuntimeError('Another engine has a resident worker')
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', LIVETR3_GEMMA_MTP='1',
                      LIVETR3_TEMP_WAV_ROOT=str(args.output / 'temp-audio'))
    from mlx_worker import MLXWorker
    worker = MLXWorker()
    draft = worker._draft_model
    if draft is None:
        raise RuntimeError('MTP warmup fell back')
    audio, rate = sf.read(args.audio, dtype='float32')
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    factor = math.gcd(rate, 16000)
    audio = resample_poly(audio, 16000 // factor, rate // factor)
    clips = [audio[:96000], audio[16 * 16000:22 * 16000], audio[-96000:]]
    reports = []
    for index, clip in enumerate(clips):
        # Warm both paths on this exact clip before profiling ABBA.
        for enabled in (False, True):
            worker._draft_model = draft if enabled else None
            worker.ast(clip, 'English', 'Spanish', [])
        outputs = []
        for enabled in (False, True, True, False):
            worker._draft_model = draft if enabled else None
            profiler = cProfile.Profile()
            started = time.monotonic()
            profiler.enable()
            result = worker.ast(clip, 'English', 'Spanish', [])
            profiler.disable()
            elapsed = time.monotonic() - started
            preprocessing = sum(entry.totaltime for entry in profiler.getstats()
                                if not isinstance(entry.code, str)
                                and entry.code.co_name == '_prepare_generation_inputs')
            outputs.append(dict(mtp=enabled, elapsed_seconds=elapsed,
                                audio_input_preprocessing_seconds=preprocessing,
                                original=result.original, translation=result.translation,
                                complete=result.complete, truncated=result.truncated))
        reports.append(dict(clip=index, outputs=outputs,
                            exact_bilingual_match=len({(x['original'], x['translation']) for x in outputs}) == 1))
    worker._draft_model = draft
    progress = []
    cancelled = worker.ast(clips[0], 'English', 'Spanish', [], priority='partial',
                           cancelled=lambda: bool(progress), on_progress=progress.append)
    after_cancel = worker.ast(clips[0], 'English', 'Spanish', [])
    report = dict(clips=reports, cancelled_returned_none=cancelled is None,
                  progress_before_cancel=bool(progress), complete_after_cancel=after_cancel.complete,
                  candidate_still_active=worker._draft_model is draft,
                  after_cancel_matches_first=after_cancel.original == reports[0]['outputs'][0]['original']
                  and after_cancel.translation == reports[0]['outputs'][0]['translation'])
    (args.output / 'summary.json').write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in report.items() if k != 'clips'}), flush=True)
    assert all(x['exact_bilingual_match'] for x in reports)
    assert cancelled is None and after_cancel.complete and worker._draft_model is draft


if __name__ == '__main__':
    main()
