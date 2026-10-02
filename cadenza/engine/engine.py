"""Private NDJSON pipe child. No LiveTR3 session, worker, socket, or HTTP server."""
import fcntl
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

from pipeline import Pipeline, decode_audio
from raw_model import Gemma


def main():
    root = Path.home() / "Library/Application Support/Cadenza"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (root / "engine.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(json.dumps(dict(type="fatal", message="Another Cadenza engine is already running.")), flush=True)
        return
    # Refuse to compete with the existing app's engine; never terminate it.
    processes = subprocess.check_output(["/bin/ps", "-axo", "comm=,args="], text=True)
    if any(len(fields := line.split(None, 1)) == 2
           and Path(fields[0]).name.lower().startswith("python")
           and "uds_host.py" in fields[1] for line in processes.splitlines()):
        print(json.dumps(dict(type="fatal", message="Quit the running LiveTR3 engine before loading Cadenza's Gemma.")), flush=True)
        return
    output_lock = threading.Lock()
    log = (root / "events.jsonl").open("a", buffering=1)
    def emit(event):
        event = dict(event, time=time.monotonic())
        line = json.dumps(event, ensure_ascii=False)
        with output_lock:
            log.write(line + "\n")
            print(line, flush=True)
    emit(dict(type="loading"))
    model = Gemma(Path(__file__).parent.parent / "Model")
    emit(dict(type="ready"))
    pipeline = Pipeline(root / "Sessions", emit)
    quitting = threading.Event()
    def read():
        try:
            for line in sys.stdin:
                try:
                    if len(line) > 100000:
                        raise ValueError("Oversized command")
                    message = json.loads(line)
                    kind = message["type"]
                    if kind == "start":
                        pipeline.start()
                    elif kind == "audio":
                        pipeline.audio(decode_audio(message))
                    elif kind == "stop":
                        pipeline.stop()
                    elif kind == "retry":
                        pipeline.retry(message["id"])
                    elif kind == "quit":
                        break
                    else:
                        raise ValueError("Unknown command")
                except Exception as error:
                    emit(dict(type="error", message=str(error)))
                    try:
                        pipeline.stop()
                    except Exception as stop_error:
                        emit(dict(type="error", message=f"Could not flush captured audio: {stop_error}"))
        finally:
            try:
                pipeline.stop()
            except Exception as error:
                emit(dict(type="error", message=f"Could not flush captured audio: {error}"))
            finally:
                quitting.set()
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    while not quitting.is_set() or pipeline.pending:
        try:
            job = pipeline.jobs.get(timeout=0.1)
        except queue.Empty:
            continue
        pipeline.process(job, model)
    emit(dict(type="bye"))
    log.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps(dict(type="fatal", message=str(error))), flush=True)
        raise
