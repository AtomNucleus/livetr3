import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import numpy as np

from mlx_worker import ASTResult
from protocol import ConfigMessage
from segmenter import RMSGate
from session import SessionHub, TranscriptionSession

SPEECH = np.full(320, 0.1, dtype=np.float32)
# Above the frame RMS floor, below the gate: room noise in a pause.
NOISE = np.full(320, 0.005, dtype=np.float32)


def make_session(monkeypatch):
    monkeypatch.setattr(TranscriptionSession, "_build_segmenter", lambda *_: RMSGate())
    value = TranscriptionSession(SimpleNamespace(query_params={}), Mock(), SessionHub())
    value.state.config = ConfigMessage(polish_enabled=False)
    value.worker.is_busy_or_backlogged = True
    value._send = AsyncMock()
    value._send_and_broadcast = AsyncMock()
    value._send_error = AsyncMock()
    ingest = value.segmenter.ingest

    def ingest_with_silero(frame):
        result = ingest(frame)
        result.quiet = bool(np.max(frame) < 0.05)
        return result
    value.segmenter.ingest = ingest_with_silero
    return value


def test_noisy_pause_starts_the_early_decode_and_the_final_reuses_it(monkeypatch):
    async def run():
        value = make_session(monkeypatch)
        value.worker.submit_ast = AsyncMock(return_value=ASTResult(
            "Grace and peace.", "Gracia y paz.", True, False))
        for frame in [SPEECH] * 20 + [NOISE] * 15:
            await value._receive_frame(frame)
        await asyncio.sleep(0)
        early = value.worker.submit_ast.await_args.kwargs
        assert early["early"]
        np.testing.assert_array_equal(
            early["audio_f32_16k"], np.concatenate([SPEECH] * 20 + [NOISE] * 15))

        # The noise after the cut never reaches the final.
        for frame in [NOISE] * 5:
            await value._receive_frame(frame)
        await asyncio.gather(*list(value._jobs))
        value.worker.submit_ast.assert_awaited_once()
        [final] = [call.args[0] for call in value._send_and_broadcast.await_args_list
                   if call.args[0]["type"] == "final"]
        assert final["translation"] == "Gracia y paz."
    asyncio.run(run())


def test_session_start_runs_one_warm_decode(monkeypatch):
    async def run():
        value = make_session(monkeypatch)
        value.worker.start = AsyncMock()
        value.worker.submit_ast = AsyncMock(return_value=None)
        await value._warm_mlx_worker()
        warm = value.worker.submit_ast.await_args.kwargs
        assert warm["utterance_id"] is None and warm["max_tokens"] == 8
    asyncio.run(run())


def test_warm_decode_uses_the_captions_prompt_so_it_caches_their_prefix(monkeypatch):
    async def run():
        value = make_session(monkeypatch)
        value.state.config = ConfigMessage(polish_enabled=False, custom_vocab=["Ephesians"],
                                           code_switching_enabled=True)
        value.worker.start = AsyncMock()
        value.worker.submit_ast = AsyncMock(return_value=None)
        await value._warm_mlx_worker()
        warm = value.worker.submit_ast.await_args.kwargs
        # The vocabulary and code-switching lines sit before the audio token.
        assert warm["custom_vocab"] == ["Ephesians"] and warm["code_switching_enabled"]
    asyncio.run(run())


def test_empty_final_is_dropped_without_an_error(monkeypatch):
    async def run():
        value = make_session(monkeypatch)
        value.worker.submit_ast = AsyncMock(return_value=ASTResult("", "", False, False))
        await value._run_mlx_ast("final", 1, np.ones(16_000, dtype=np.float32))
        value._send_error.assert_not_awaited()

        value.worker.submit_ast = AsyncMock(return_value=ASTResult("We go", "", False, True))
        await value._run_mlx_ast("final", 2, np.ones(16_000, dtype=np.float32))
        value._send_error.assert_awaited_once()
    asyncio.run(run())
