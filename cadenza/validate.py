#!/usr/bin/env python3
"""Private ordered direct/pipeline/direct replay. Never commit its output."""
import argparse
import json
import queue
from pathlib import Path
import re
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).parent / "engine"))
import numpy as np
import soundfile as sf
from pipeline import Pipeline, Segmenter, RATE, FRAME
from raw_model import Gemma, PROMPT


def score(reference, hypothesis):
    a, b = [re.findall(r"\w+", text.casefold()) for text in [reference, hypothesis]]
    row = list(range(len(b)+1))
    for i, word in enumerate(a, 1):
        previous, row = row, [i]
        for j, other in enumerate(b, 1):
            row.append(min(previous[j]+1, row[j-1]+1, previous[j-1]+(word != other)))
    return dict(word_errors=row[-1], reference_words=len(a), wer=row[-1]/len(a))


def summary(events, reference):
    finals = [e for e in events if e["type"] == "final"]
    partials = [e for e in events if e["type"] == "partial"]
    starts = {e["id"]: e for e in events if e["type"] == "queued"}
    end_delays = [e["end_to_final"] + (starts[e["id"]]["end"]-starts[e["id"]]["last_voice"])/RATE for e in finals]
    first_source = next((e["elapsed"] for e in partials if e["source"]), None)
    first_spanish = next((e["elapsed"] for e in partials if e["spanish"]), None)
    return dict(finals=len(finals), failed=sum(e["type"] == "failed" for e in events),
                overloads=sum(e["type"] == "overload" for e in events),
                first_source=first_source, first_spanish=first_spanish,
                end_to_final_median=float(np.median(end_delays)) if end_delays else None,
                end_to_final_max=max(end_delays, default=None),
                queue_wait_max=max((e["queue_wait"] for e in finals), default=0),
                peak_pending=max((e["pending"] for e in events if e["type"] == "backlog"), default=0),
                **score(reference, " ".join(e["source"] for e in finals)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    audio, rate = sf.read(args.audio, dtype="float32")
    assert rate == RATE and audio.ndim == 1
    ref = args.reference.read_text()
    segmenter = Segmenter()
    phrases = []
    for offset in range(0, len(audio), FRAME):
        phrases.extend(segmenter.feed(audio[offset:offset+FRAME]))
    phrases.extend(segmenter.stop())
    paths = []
    for index, (samples, start, end, voice) in enumerate(phrases):
        path = args.output / f"phrase-{index:02d}.wav"
        sf.write(path, samples, RATE, subtype="FLOAT")
        paths.append(path)
    model = Gemma()
    model.phrase(paths[0])  # Warm-up uses the same real phrase, unscored.
    results = {}
    for name in ["direct-before", "pipeline", "direct-after"]:
        if name.startswith("direct"):
            rows = [dict(start=p[1], end=p[2], **model.phrase(path)) for p, path in zip(phrases, paths)]
            results[name] = dict(finals=sum(r["complete"] for r in rows),
                                 failed=sum(not r["complete"] for r in rows),
                                 inference_median=float(np.median([r["inference"] for r in rows])),
                                 **score(ref, " ".join(r["source"] for r in rows)))
        else:
            start = time.monotonic()
            rows = []
            def emit(event):
                rows.append(dict(event, elapsed=time.monotonic()-start))
            p = Pipeline(args.output / "pipeline-sessions", emit)
            def feed():
                p.start()
                for offset in range(0, len(audio), FRAME):
                    p.audio(audio[offset:offset+FRAME])
                    deadline = start + (offset + min(FRAME, len(audio)-offset))/RATE
                    time.sleep(max(0, deadline-time.monotonic()))
                    if p.overloaded:
                        break
                p.stop()
            producer = threading.Thread(target=feed)
            producer.start()
            while producer.is_alive() or p.pending:
                try:
                    job = p.jobs.get(timeout=.05)
                except queue.Empty:
                    continue
                p.process(job, model)
            producer.join()
            results[name] = summary(rows, ref)
            capture, _ = sf.read(p.session / "capture.wav", dtype="float32")
            results[name]["received_samples"] = len(capture)
            results[name]["input_samples"] = len(audio)
            results[name]["capture_exact"] = bool(np.array_equal(capture, audio))
        (args.output/f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
        (args.output/"summary.json").write_text(json.dumps(results, indent=2))
        print(name, results[name], flush=True)


if __name__ == "__main__":
    main()
