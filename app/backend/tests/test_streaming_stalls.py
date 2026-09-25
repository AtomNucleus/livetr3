import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest

from mlx_worker import MLXWorkerService
from parakeet_worker import ASRResult, ParakeetASR, ParakeetASRService
from segmenter import RMSGate
from session import SessionHub, TranscriptionSession


def make_session(monkeypatch):
    monkeypatch.setattr(TranscriptionSession, "_build_segmenter", lambda *_: RMSGate())
    value = TranscriptionSession(
        SimpleNamespace(query_params={}), Mock(), SessionHub(),
        transcription_engine="parakeet", asr_worker=Mock(),
    )
    value._send = AsyncMock()
    value._send_and_broadcast = AsyncMock()
    return value


def test_pending_final_does_not_block_next_utterance_partials(monkeypatch):
    async def run():
        value = make_session(monkeypatch)
        value.state.utterance_id = 1
        value._finalizing[1] = "silero_end"
        value._schedule_ast = Mock()
        for _ in range(20):
            await value._receive_frame(np.full(320, 0.1, dtype=np.float32))
        assert value.state.active_utterance_id == 2
        assert any(call.args[:2] == ("partial", 2) for call in value._schedule_ast.call_args_list)
    asyncio.run(run())


@pytest.mark.parametrize("result", [None, ASRResult(text=""), TimeoutError("slow model")])
def test_empty_or_failed_final_releases_pending_commit(monkeypatch, result):
    async def run():
        value = make_session(monkeypatch)
        value._finalizing[1] = "silero_end"
        if isinstance(result, Exception):
            value.asr_worker.submit_asr = AsyncMock(side_effect=result)
        else:
            value.asr_worker.submit_asr = AsyncMock(return_value=result)
        await value._run_ast("final", 1, np.ones(16000, dtype=np.float32))
        assert 1 not in value._finalizing
    asyncio.run(run())


def test_final_translation_precedes_queued_previews():
    async def run():
        worker = MLXWorkerService()
        preview = asyncio.create_task(worker.submit_translate_text(
            "new preview", "English", "Spanish", priority="partial", utterance_id=2))
        final = asyncio.create_task(worker.submit_translate_text(
            "finished sentence", "English", "Spanish", priority="final", utterance_id=1))
        await asyncio.sleep(0)
        assert worker._queue.get_nowait().payload["text"] == "finished sentence"
        preview.cancel()
        final.cancel()
        await asyncio.gather(preview, final, return_exceptions=True)
    asyncio.run(run())


def test_partial_timeout_resets_ipc_without_retrying_stale_audio():
    async def run():
        worker = ParakeetASRService()
        worker._dispatch_job_once = AsyncMock(side_effect=TimeoutError("expired"))
        worker._stop_worker_process = AsyncMock()
        worker._start_worker_process = AsyncMock()
        result = await worker._dispatch_job(SimpleNamespace(payload={"priority": "partial"}))
        assert result.text == ""
        worker._stop_worker_process.assert_awaited_once_with(force=True)
        worker._start_worker_process.assert_awaited_once()
        worker._dispatch_job_once.assert_awaited_once()
    asyncio.run(run())


def test_parakeet_uses_in_memory_pcm(monkeypatch):
    import parakeet_mlx.audio
    captured = []
    def logmel(audio, config):
        captured.append(np.array(audio))
        return "mel"
    monkeypatch.setattr(parakeet_mlx.audio, "get_logmel", logmel)
    worker = object.__new__(ParakeetASR)
    worker.model = SimpleNamespace(
        preprocessor_config=SimpleNamespace(sample_rate=16000),
        generate=Mock(return_value=[SimpleNamespace(text="hello", timestamp=None)]),
    )
    audio = np.array([0.0000123, 0.5, -0.5], dtype=np.float32)
    assert worker.transcribe(audio).text == "hello"
    np.testing.assert_array_equal(captured[0], audio)
    worker.model.generate.assert_called_once_with("mel")


def test_final_timeout_resets_ipc_and_reports_failure_without_second_timeout():
    async def run():
        worker = ParakeetASRService()
        worker._dispatch_job_once = AsyncMock(side_effect=TimeoutError("expired"))
        worker._stop_worker_process = AsyncMock()
        worker._start_worker_process = AsyncMock()
        with pytest.raises(TimeoutError):
            await worker._dispatch_job(SimpleNamespace(payload={"priority": "final"}))
        worker._stop_worker_process.assert_awaited_once_with(force=True)
        worker._start_worker_process.assert_awaited_once()
        worker._dispatch_job_once.assert_awaited_once()
    asyncio.run(run())
