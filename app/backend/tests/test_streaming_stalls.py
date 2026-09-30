import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest

from mlx_worker import ASTResult
from segmenter import RMSGate
from session import SessionHub, TranscriptionSession


def make_session(monkeypatch):
    monkeypatch.setattr(TranscriptionSession, "_build_segmenter", lambda *_: RMSGate())
    value = TranscriptionSession(
        SimpleNamespace(query_params={}), Mock(), SessionHub(),
    )
    value.worker.is_busy_or_backlogged = False
    value._send = AsyncMock()
    value._send_and_broadcast = AsyncMock()
    return value


def test_pending_final_defers_next_preview_but_keeps_capturing_speech(monkeypatch):
    async def run():
        value = make_session(monkeypatch)
        value.state.utterance_id = 1
        value._finalizing[1] = "silero_end"
        value._schedule_ast = Mock()
        for _ in range(20):
            await value._receive_frame(np.full(320, 0.1, dtype=np.float32))
        assert value.state.active_utterance_id == 2
        value._schedule_ast.assert_not_called()
        assert value.segmenter.current_audio().size == 20 * 320
        value._finalizing.clear()
        await value._receive_frame(np.full(320, 0.1, dtype=np.float32))
        assert any(call.args[:2] == ("partial", 2) for call in value._schedule_ast.call_args_list)
    asyncio.run(run())


def test_trailing_silence_does_not_start_preview_before_imminent_final(monkeypatch):
    async def run():
        value = make_session(monkeypatch)
        value.worker.is_busy_or_backlogged = True
        value._schedule_ast = Mock()
        speech = np.full(320, 0.1, dtype=np.float32)
        silence = np.zeros(320, dtype=np.float32)
        for _ in range(20):
            await value._receive_frame(speech)

        # An earlier job finishes after the last spoken frame. A new preview
        # would waste its prefill, then be cancelled at the silence boundary.
        value.worker.is_busy_or_backlogged = False
        for _ in range(20):
            await value._receive_frame(silence)

        value._schedule_ast.assert_called_once()
        priority, utterance_id, audio = value._schedule_ast.call_args.args
        assert (priority, utterance_id) == ("final", 1)
        np.testing.assert_array_equal(
            audio, np.concatenate([speech] * 20 + [silence] * 20)
        )
    asyncio.run(run())


def test_deferred_preview_keeps_new_speech_for_next_voiced_frame(monkeypatch):
    async def run():
        value = make_session(monkeypatch)
        value.worker.is_busy_or_backlogged = True
        value._schedule_ast = Mock()
        speech = np.full(320, 0.1, dtype=np.float32)
        for _ in range(20):
            await value._receive_frame(speech)
        value.worker.is_busy_or_backlogged = False
        await value._receive_frame(np.zeros(320, dtype=np.float32))
        value._schedule_ast.assert_not_called()
        assert value._utterance_runtime[1].last_partial_audio_samples == 0

        await value._receive_frame(speech)
        priority, utterance_id, audio = value._schedule_ast.call_args.args
        assert (priority, utterance_id) == ("partial", 1)
        assert audio.size == 22 * 320
    asyncio.run(run())


@pytest.mark.parametrize("result", [None, ASTResult("", "", False, False), TimeoutError("slow model")])
def test_empty_or_failed_final_releases_pending_commit(monkeypatch, result):
    async def run():
        value = make_session(monkeypatch)
        value._finalizing[1] = "silero_end"
        if isinstance(result, Exception):
            value.worker.submit_ast = AsyncMock(side_effect=result)
        else:
            value.worker.submit_ast = AsyncMock(return_value=result)
        await value._run_ast("final", 1, np.ones(16000, dtype=np.float32))
        assert 1 not in value._finalizing
    asyncio.run(run())
