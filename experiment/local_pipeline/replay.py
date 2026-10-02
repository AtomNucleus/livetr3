#!/usr/bin/env python3
"""Paced local Moonshine -> TranslateGemma replay. Outputs contain private text."""
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import subprocess
import threading
import time

from policy import CommitPolicy, Mailbox, prefix_length, words
from runtime import Translator, MODEL, REVISION

ROOT = Path(__file__).resolve().parents[2]


def guard():
    rows = subprocess.check_output(['ps', '-axo', 'pid,command'], text=True).splitlines()
    competing = [r for r in rows if any(s in r for s in
                 ('Contents/Resources/engine/engine.py', 'uds_host.py', 'mlx_lm.server', 'mlx_vlm.server'))
                 and 'ps -axo' not in r and '/bin/zsh -c' not in r]
    if competing:
        raise RuntimeError('Competing engine remains running: ' + '\n'.join(competing))


def resource_snapshot(pid=None):
    """Take snapshots between runs; RSS alone misses Metal allocations."""
    return {name: subprocess.run(command, capture_output=True, text=True).stdout
            for name, command in {
                'pressure': ['memory_pressure', '-Q'],
                'swap': ['sysctl', 'vm.swapusage'],
                'process_vm': ['vmmap', '-summary', str(pid or os.getpid())],
            }.items()}


def read_audio(path):
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    audio, rate = sf.read(path, dtype='float32')
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if rate != 16000:
        divisor = math.gcd(rate, 16000)
        audio = resample_poly(audio, 16000 // divisor, rate // divisor)
    if not len(audio) or not np.isfinite(audio).all():
        raise ValueError('Audio must be nonempty and finite')
    return audio


class Log:
    def __init__(self, path):
        self.file, self.rows, self.lock = path.open('w'), [], threading.Lock()
        self.start = time.monotonic()

    def emit(self, kind, **fields):
        with self.lock:
            row = dict(type=kind, elapsed=time.monotonic() - self.start, **fields)
            self.rows.append(row)
            self.file.write(json.dumps(row, ensure_ascii=False) + '\n')
            self.file.flush()
            return row


def replay(translator, asr, audio, path):
    import numpy as np
    from moonshine_voice import TranscriptEventListener
    log, policy, mailbox = Log(path), CommitPolicy(), Mailbox()
    errors = []
    done = set()
    stream = asr.create_stream(update_interval=.25)

    class Listener(TranscriptEventListener):
        def handle(self, event, final=False):
            line = event.line
            now = time.monotonic() - log.start
            end = line.start_time + line.duration
            log.emit('asr_final' if final else 'asr_partial', line=line.line_id,
                     text=line.text, acoustic_start=line.start_time, acoustic_end=end,
                     asr_latency_ms=line.last_transcription_latency_ms)
            if final:
                done.add(line.line_id)
            span = policy.update(line.line_id, line.text, final, now, end)
            if span:
                log.emit('commit', **span.__dict__)
                try:
                    mailbox.put(span)
                except Exception as exc:
                    errors.append(str(exc))
                    log.emit("error", message=str(exc), line=span.line)

        def on_line_started(self, event): self.handle(event)
        # Moonshine emits Updated and TextChanged for the SAME pass.
        # Process Updated once, so one pass cannot manufacture agreement.
        def on_line_text_changed(self, event): pass
        def on_line_updated(self, event): self.handle(event)
        def on_line_completed(self, event): self.handle(event, True)
        def on_error(self, event):
            errors.append(str(event.error))
            log.emit('error', message=str(event.error))

    def translate():
        cached = {}
        try:
            while (span := mailbox.get()) is not None:
                dispatched = time.monotonic() - log.start
                log.emit('dispatch', **span.__dict__, queue_wait=dispatched-span.committed)
                def publish(text):
                    log.emit('spanish_partial', line=span.line, text=text, source=span.text,
                             final_job=span.final, committed=span.committed,
                             dispatched=dispatched, acoustic_end=span.acoustic_end)
                try:
                    if not span.text:
                        raise RuntimeError('Empty ASR final is not translatable')
                    if span.final and cached.get(span.line, (None,))[0] == span.text:
                        result = cached[span.line][1]
                    else:
                        result = translator.translate(span.text, publish)
                    cached[span.line] = (span.text, result)
                    log.emit('spanish_final' if span.final else 'spanish_snapshot',
                             line=span.line, text=result, source=span.text,
                             committed=span.committed, dispatched=dispatched,
                             acoustic_end=span.acoustic_end,
                             inference=time.monotonic()-log.start-dispatched)
                except Exception as exc:
                    errors.append(str(exc))
                    log.emit('error', line=span.line, message=str(exc), source=span.text,
                             final_job=span.final)
        except Exception as exc:
            errors.append(str(exc))
            log.emit('error', message=str(exc))

    stream.add_listener(Listener())
    thread = threading.Thread(target=translate, name='local-translation')
    thread.start()
    lag, call_times = [], []
    samples = np.concatenate([audio, np.zeros(32000, dtype='float32')])
    log.start = time.monotonic()
    try:
        stream.start()
        for offset in range(0, len(samples), 320):
            if offset % 16000 == 0:
                guard()
            if errors:
                raise RuntimeError("ASR/translation failure: " + errors[-1])
            deadline = log.start + offset / 16000
            time.sleep(max(0, deadline-time.monotonic()))
            lag.append(max(0, time.monotonic()-deadline))
            started = time.monotonic()
            stream.add_audio(samples[offset:offset+320].tolist(), 16000)
            call_times.append(time.monotonic()-started)
        stream.stop()
        log.emit('feed_done', samples=len(audio), feed_seconds=time.monotonic()-log.start,
                 padding_seconds=2, max_feed_lag=max(lag), max_asr_call=max(call_times))
    finally:
        stream.close()
        mailbox.close()
        thread.join(timeout=90)
        if thread.is_alive():
            # No competing MLX access or unsafe thread cancellation.
            log.emit('error', message='Translation drain exceeded 90 seconds')
            log.file.flush()
            os._exit(2)
        log.emit('drained', peak_pending=mailbox.peak, coalesced=mailbox.coalesced)
        log.file.close()
    return log.rows


def summarize(rows, reference, clip_seconds):
    import sys
    sys.path.insert(0, str(ROOT / 'script'))
    from chunk_limit_replay import score, gaps
    finals = [r for r in rows if r['type'] == 'spanish_final']
    asr = {r['line']: r for r in rows if r['type'] == 'asr_final'}
    targets = {r['line']: words(r['text']) for r in finals}
    high, times, rewrites, positions, old = {}, [], 0, 0, {}
    for row in rows:
        if not row['type'].startswith('spanish_'):
            continue
        line, current = row['line'], words(row['text'])
        if row['type'] == 'spanish_partial' and row['text'] and not row['text'][-1].isspace():
            current = current[:-1]  # Unfinished final token is not a usable word.
        previous = old.get(line, [])
        common = prefix_length(previous, current)
        if common < len(previous):
            rewrites += 1
            positions += len(previous)-common
        old[line] = current
        retained = prefix_length(current, targets.get(line, []))
        if retained >= 3 and retained > high.get(line, 0):
            times.append(row['elapsed'])
            high[line] = retained
    source = ' '.join(r['text'] for r in sorted(asr.values(), key=lambda r:r['acoustic_start']))
    final_source = ' '.join(r['source'] for r in finals)
    ends = [r['elapsed']-r['acoustic_end'] for r in finals]
    return dict(asr_score=score(reference, source), translated_source_score=score(reference, final_source),
                clip_seconds=clip_seconds, asr_finals=len(asr), translation_finals=len(finals),
                missing_translation_lines=sorted(set(asr)-set(targets)),
                duplicated_final_count=len(finals)-len(targets),
                first_source=next((r['elapsed'] for r in rows if r['type'].startswith('asr_') and r['text']), None),
                first_spanish_characters=next((r['elapsed'] for r in rows if r['type'].startswith('spanish_') and r['text']), None),
                usable_final_prefix_growth=gaps(times), target_rewrite_events=rewrites,
                replaced_word_positions=positions, phrase_end_to_final=ends,
                max_queue_wait=max((r['queue_wait'] for r in rows if r['type']=='dispatch'), default=0),
                last_final_after_clip=max((r['elapsed'] for r in finals), default=0)-clip_seconds,
                errors=[r for r in rows if r['type']=='error'],
                feed=next((r for r in rows if r['type']=='feed_done'), None),
                queue=rows[-1], finals=finals)


def main(args):
    from huggingface_hub import snapshot_download
    from moonshine_voice import get_model_for_language, ModelArch, Transcriber
    args.output.mkdir(parents=True, exist_ok=True)
    guard()
    # Downloads belong to explicit setup, not timed replay. Offline execution
    # uses already pinned files; no audio or captions leave this process.
    path = snapshot_download(MODEL, revision=REVISION, local_files_only=True)
    asr_path, arch = get_model_for_language('en', ModelArch.MEDIUM_STREAMING)
    metadata = dict(model=MODEL, revision=REVISION, precision='4-bit, group size 64',
                    asr_path=asr_path, asr_arch=arch.name,
                    versions={p:importlib.metadata.version(p) for p in ('moonshine-voice','mlx-lm','mlx','transformers')},
                    audio_sha256=hashlib.sha256(args.audio.read_bytes()).hexdigest(),
                    reference_sha256=hashlib.sha256(args.reference.read_bytes()).hexdigest(),
                    asr_files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(asr_path).iterdir() if p.is_file()},
                    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
    expected = json.loads((Path(__file__).parent/'models.json').read_text())['asr']['sha256']
    if any(metadata['asr_files'].get(name) != digest for name, digest in expected.items()):
        raise RuntimeError('Moonshine asset identity differs from pinned models.json')
    (args.output/'metadata.json').write_text(json.dumps(metadata,indent=2))
    audio = read_audio(args.audio)
    metadata['before_load'] = resource_snapshot()
    start = time.monotonic()
    translator = Translator(path)
    asr = Transcriber(asr_path, arch, options={'identify_speakers':'false'})
    metadata['load_seconds'] = time.monotonic()-start
    translator.translate('Do not send twenty-three books to Maria.', lambda _:None)
    replay(translator, asr, audio, args.output/'warmup.jsonl')
    metadata['both_models_warm'] = resource_snapshot()
    results = []
    try:
        for index in range(args.runs):
            rows = replay(translator, asr, audio, args.output/f'run-{index+1}.jsonl')
            result = summarize(rows, args.reference.read_text(), len(audio)/16000)
            results.append(result)
            (args.output/'summary.json').write_text(json.dumps(results,indent=2,ensure_ascii=False))
            print(json.dumps({k:v for k,v in result.items() if k not in ('finals','errors')},ensure_ascii=False),flush=True)
        diagnostics = []
        for text in ('We did not send twenty-three books to Maria.',
                     'Paul received twenty-two books, not twenty-three.',
                     'The church is one body, even when its members disagree.'):
            began = time.monotonic()
            target = translator.translate(text, lambda _:None)
            diagnostics.append(dict(source=text,spanish=target,seconds=time.monotonic()-began))
        (args.output/'text-only-diagnostic.json').write_text(json.dumps(diagnostics,indent=2,ensure_ascii=False))
    finally:
        import mlx.core as mx
        metadata['mlx_peak_bytes'] = mx.get_peak_memory()
        metadata['after_runs'] = resource_snapshot()
        asr.close()
        (args.output/'metadata.json').write_text(json.dumps(metadata,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('audio','reference','output'):
        parser.add_argument('--'+flag,type=Path,required=True)
    parser.add_argument('--runs',type=int,default=1)
    main(parser.parse_args())
