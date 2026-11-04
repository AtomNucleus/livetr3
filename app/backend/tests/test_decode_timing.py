import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import numpy as np

from mlx_worker import ASTResult, MLXWorkerService
from protocol import ConfigMessage
from segmenter import RMSGate
from session import SessionHub, TranscriptionSession


def test_worker_reports_queue_and_inference_seconds():
    async def run():
        worker = MLXWorkerService()

        async def execute(job):
            await asyncio.sleep(0.02)
            return ASTResult("Hi.", "Hola.", True, False)
        worker._execute_job = execute
        runner = asyncio.create_task(worker._run())
        timing = {}
        result = await worker.submit_ast(
            priority="final", utterance_id=1, audio_f32_16k=np.ones(160, dtype=np.float32),
            src="English", tgt="Spanish", prior_context=[], custom_vocab=[],
            code_switching_enabled=False, max_tokens=64, timing=timing,
        )
        runner.cancel()
        assert result.translation == "Hola."
        assert set(timing) == {"queue_seconds", "inference_seconds"}
        assert timing["inference_seconds"] >= 0.02
    asyncio.run(run())


def test_each_decode_is_archived_with_its_timing(monkeypatch, tmp_path):
    async def run():
        monkeypatch.setattr(TranscriptionSession, "_build_segmenter", lambda *_: RMSGate())
        value = TranscriptionSession(SimpleNamespace(query_params={}), Mock(), SessionHub())
        value.state.config = ConfigMessage(polish_enabled=False)
        value._archive_dir = tmp_path

        async def submit(**kwargs):
            kwargs["timing"].update(queue_seconds=0.25, inference_seconds=1.5)
            return None if kwargs["priority"] == "partial" else ASTResult("Hi.", "Hola.", True, False)
        value.worker.submit_ast = AsyncMock(side_effect=submit)
        audio = np.ones(32_000, dtype=np.float32)
        await value._submit_ast("partial", 3, audio)
        await value._submit_ast("final", 3, audio, early=True)

        decodes = [event["payload"] for event in value._archive_events]
        assert [(d["priority"], d["early"], d["outcome"]) for d in decodes] == [
            ("partial", False, "dropped"), ("final", True, "complete")]
        assert decodes[1]["audio_seconds"] == 2.0
        assert decodes[1]["queue_seconds"] == 0.25 and decodes[1]["inference_seconds"] == 1.5
        # Resuming a session from its archive skips decode events.
        assert value._utterances_from_events(value._archive_events) == {}
    asyncio.run(run())
