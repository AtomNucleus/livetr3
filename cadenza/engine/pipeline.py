"""Audio collection is independent of the single inference consumer."""
import base64
import json
from pathlib import Path
import queue
import threading
import time
import uuid

import numpy as np
import soundfile as sf

RATE = 16000
FRAME = 320
MAX_SAMPLES = 8 * RATE
QUIET_SAMPLES = RATE // 2


class Segmenter:
    """20 ms energy gate, 500 ms quiet, 8 s cap; no overlap or text policy."""
    def __init__(self, threshold=0.003):
        self.threshold = threshold
        self.pending = np.empty(0, dtype=np.float32)
        self.parts = []
        self.count = self.quiet = self.offset = self.start = 0
        self.speech = False
        self.last_voice = 0

    def feed(self, samples):
        self.pending = np.concatenate((self.pending, samples))
        result = []
        while len(self.pending) >= FRAME:
            frame, self.pending = self.pending[:FRAME], self.pending[FRAME:]
            phrase = self._frame(frame)
            if phrase is not None:
                result.append(phrase)
        return result

    def _frame(self, frame):
        loud = float(np.sqrt(np.mean(frame * frame))) >= self.threshold
        if self.count == 0:
            self.start = self.offset
        self.parts.append(frame.copy())
        self.count += len(frame)
        self.offset += len(frame)
        self.speech |= loud
        self.quiet = 0 if loud else self.quiet + len(frame)
        if loud:
            self.last_voice = self.offset
        if self.count >= MAX_SAMPLES or self.quiet >= QUIET_SAMPLES:
            return self._flush()
        return None

    def _flush(self):
        result = None
        if self.speech:
            result = (np.concatenate(self.parts), self.start, self.offset, self.last_voice)
        self.parts = []
        self.count = self.quiet = 0
        self.speech = False
        return result

    def stop(self):
        # Include the final sub-frame so Stop cannot lose the trailing audio.
        result = []
        if len(self.pending):
            phrase = self._frame(self.pending)
            self.pending = np.empty(0, dtype=np.float32)
            if phrase is not None:
                result.append(phrase)
        phrase = self._flush()
        if phrase is not None:
            result.append(phrase)
        return result


class Pipeline:
    def __init__(self, root, emit, capacity=3):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.emit = emit
        self.jobs = queue.Queue(maxsize=capacity)
        self.lock = threading.RLock()
        self.pending = 0
        self.recording = False
        self.overloaded = False
        self.received = 0
        self.segmenter = None
        self.capture = None
        self.phrases = {}

    def start(self):
        with self.lock:
            if self.recording or self.pending:
                raise ValueError("Wait for all queued phrases before restarting")
            self.session = self.root / (time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
            self.session.mkdir(mode=0o700)
            self.capture = sf.SoundFile(self.session / "capture.wav", mode="w", samplerate=RATE,
                                        channels=1, subtype="FLOAT")
            self.segmenter = Segmenter()
            self.received = 0
            self.overloaded = False
            self.recording = True
            self.emit(dict(type="capturing", recovery=str(self.session)))

    def audio(self, samples):
        with self.lock:
            if not self.recording:
                raise ValueError("Audio received outside an active capture")
            samples = np.asarray(samples, dtype=np.float32).reshape(-1)
            if len(samples) > RATE or not np.isfinite(samples).all():
                raise ValueError("Invalid or oversized audio packet")
            if self.received == 0:
                self.emit(dict(type="audio_started"))
            self.capture.write(samples)
            self.capture.flush()
            self.received += len(samples)
            for phrase in self.segmenter.feed(samples):
                self._commit(phrase)

    def _commit(self, phrase):
        samples, start, end, last_voice = phrase
        ident = uuid.uuid4().hex
        wav = self.session / f"{ident}.wav"
        sf.write(wav, samples, RATE, subtype="FLOAT")
        job = dict(id=ident, wav=str(wav), start=start, end=end, last_voice=last_voice,
                   audio_seconds=len(samples) / RATE, committed=time.monotonic())
        self.phrases[ident] = job
        self.emit(dict(type="queued", **job))
        self._enqueue(job)

    def _enqueue(self, job):
        try:
            job["state"] = "queued"
            self.jobs.put_nowait(job)
        except queue.Full:
            job["state"] = "failed"
            self.overloaded = True
            self.emit(dict(type="failed", id=job["id"],
                           message="Queue full. Capture stopped; audio retained. Retry after draining."))
            self.emit(dict(type="overload", message="Inference fell behind. Capture stopped; queued phrases will finish."))
        else:
            self.pending += 1
            self.emit(dict(type="backlog", pending=self.pending, queued=self.jobs.qsize()))

    def stop(self):
        with self.lock:
            if not self.recording:
                return
            try:
                for phrase in self.segmenter.stop():
                    self._commit(phrase)
            finally:
                try:
                    self.capture.close()
                finally:
                    self.capture = None
                    self.recording = False
            self.emit(dict(type="stopped", samples=self.received, recovery=str(self.session),
                           overloaded=self.overloaded))
            if not self.pending:
                self.emit(dict(type="drained"))

    def retry(self, ident):
        with self.lock:
            job = self.phrases[ident]
            if job.get("state") != "failed":
                raise ValueError("Only failed phrases can be retried")
            job["committed"] = time.monotonic()
            self._enqueue(job)

    def process(self, job, model):
        with self.lock:
            job["state"] = "running"
        wait = time.monotonic() - job["committed"]
        self.emit(dict(type="working", id=job["id"], queue_wait=wait))
        def progress(raw, source, spanish):
            self.emit(dict(type="partial", id=job["id"], source=source, spanish=spanish))
        try:
            result = model.phrase(job["wav"], progress)
            if not result["complete"]:
                raise ValueError(f"Incomplete model answer ({result['finish_reason']}); retained for Retry")
            job["state"] = "complete"
            self.emit(dict(type="final", id=job["id"], queue_wait=wait,
                           end_to_final=wait + result["inference"], **result))
        except Exception as error:
            job["state"] = "failed"
            self.emit(dict(type="failed", id=job["id"], message=str(error)))
        finally:
            with self.lock:
                self.pending -= 1
                self.jobs.task_done()
                self.emit(dict(type="backlog", pending=self.pending, queued=self.jobs.qsize()))
                if not self.recording and not self.pending:
                    self.emit(dict(type="drained"))


def decode_audio(message):
    return np.frombuffer(base64.b64decode(message["pcm"], validate=True), dtype="<f4").copy()
