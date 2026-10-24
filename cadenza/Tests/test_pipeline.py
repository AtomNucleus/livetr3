import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import soundfile as sf
from pipeline import Pipeline, Segmenter, MAX_SAMPLES, RATE
from raw_model import completed, split_text


class PipelineTests(unittest.TestCase):
    def test_cap_and_stop_cover_every_voiced_sample(self):
        audio = np.ones(2 * MAX_SAMPLES + 157, np.float32) * .1
        segmenter = Segmenter()
        phrases = []
        # Irregular native packets must not create gaps or duplicated boundaries.
        for start in range(0, len(audio), 777):
            phrases.extend(segmenter.feed(audio[start:start+777]))
        phrases.extend(segmenter.stop())
        np.testing.assert_array_equal(np.concatenate([p[0] for p in phrases]), audio)
        self.assertEqual([(p[1], p[2]) for p in phrases],
                         [(0, MAX_SAMPLES), (MAX_SAMPLES, 2*MAX_SAMPLES), (2*MAX_SAMPLES, len(audio))])
        self.assertTrue(all(len(p[0]) <= MAX_SAMPLES for p in phrases))

    def test_natural_pause_and_idle_silence(self):
        segmenter = Segmenter()
        phrases = segmenter.feed(np.r_[np.ones(RATE)*.1, np.zeros(RATE)])
        self.assertEqual(len(phrases), 1)
        self.assertEqual(phrases[0][3], RATE)
        self.assertEqual(phrases[0][2], RATE + RATE//2)
        self.assertEqual(segmenter.stop(), [])

    def test_overload_retains_audio_and_exposes_failed_phrase(self):
        with tempfile.TemporaryDirectory() as root:
            events = []
            p = Pipeline(root, events.append, capacity=1)
            p.start()
            for _ in range(17):
                p.audio(np.ones(RATE, np.float32)*.1)
            p.stop()
            capture, rate = sf.read(p.session / "capture.wav")
            self.assertEqual(len(capture), 17*RATE)
            self.assertEqual(p.jobs.qsize(), 1)
            self.assertTrue(any(e["type"] == "overload" for e in events))
            failed = [e for e in events if e["type"] == "failed"]
            self.assertEqual(len(failed), 2)
            for event in failed:
                self.assertTrue(Path(p.phrases[event["id"]]["wav"]).exists())
            self.assertFalse(p.recording)

    def test_stop_drains_and_incomplete_result_requires_retry(self):
        class Model:
            def phrase(self, wav, progress):
                progress("hello", "hello", "")
                return dict(complete=False, finish_reason="length")
        with tempfile.TemporaryDirectory() as root:
            events = []
            p = Pipeline(root, events.append)
            p.start()
            p.audio(np.ones(153, np.float32)*.1)
            p.stop()
            job = p.jobs.get_nowait()
            p.process(job, Model())
            self.assertEqual(p.pending, 0)
            self.assertEqual(events[-1]["type"], "drained")
            self.assertFalse(any(e["type"] == "final" for e in events))
            p.retry(job["id"])
            self.assertEqual(p.pending, 1)
            with self.assertRaises(ValueError):
                p.retry(job["id"])

    def test_stop_cleans_up_after_phrase_disk_failure(self):
        with tempfile.TemporaryDirectory() as root:
            p = Pipeline(root, lambda event: None)
            p.start()
            p.audio(np.ones(RATE, np.float32)*.1)
            with patch("pipeline.sf.write", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    p.stop()
            self.assertFalse(p.recording)
            self.assertIsNone(p.capture)
            p.stop()  # Cleanup remains idempotent after a failed flush.

    def test_completion_requires_model_stop_and_both_languages(self):
        self.assertFalse(completed("hello\nSpanish: hola", "length"))
        self.assertFalse(completed("hello\nSpanish:", "stop"))
        self.assertFalse(completed("hello", None))
        self.assertTrue(completed("hello\nSpanish: hola", "stop"))
        self.assertEqual(split_text("hello\nSpanish: hola"), ("hello", "hola"))


if __name__ == "__main__":
    unittest.main()
