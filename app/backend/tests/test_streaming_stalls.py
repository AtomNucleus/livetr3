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
        priority, utterance_id, audio = value._schedule_ast.call_args.args[:3]
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


def test_complete_snapshot_handoff_keeps_newer_audio_and_avoids_second_decode(monkeypatch):
    from session import UtteranceRuntime
    from protocol import ConfigMessage

    async def run():
        value = make_session(monkeypatch)
        value.segmenter = RMSGate(max_utterance_s=6, overlap_s=0.3)
        value.state.running = True
        value.state.utterance_id = value.state.active_utterance_id = 1
        value.state.config = ConfigMessage(polish_enabled=False)
        frames = [np.full(320, .05 + i / 1000, dtype=np.float32) for i in range(200)]
        frames[142:150] = [np.zeros(320, dtype=np.float32) for _ in range(8)]
        for frame in frames[:150]:
            value.segmenter.ingest(frame)
        snapshot = value.segmenter.current_audio().copy()
        value._utterance_runtime[1] = UtteranceRuntime(
            partial_audio_snapshot=snapshot, partial_last_audio_unix_seconds=10,
            last_audio_frame_unix_seconds=10,
        )
        # One combined inference starts at three seconds. Another second of
        # speech arrives while Gemma produces the source and target text.
        async def infer(**kwargs):
            np.testing.assert_array_equal(kwargs['audio_f32_16k'], snapshot)
            for frame in frames[150:]:
                value.segmenter.ingest(frame)
            value._utterance_runtime[1].last_audio_frame_unix_seconds = 11
            return ASTResult('We cannot spend nineteen dollars.',
                             'No podemos gastar diecinueve dólares.', True, False)
        value.worker.submit_ast = AsyncMock(side_effect=infer)
        value._schedule_ast = Mock()
        await value._run_mlx_ast('partial', 1, snapshot)
        value.worker.submit_ast.assert_awaited_once()
        value._schedule_ast.assert_not_called()
        final, start = [call.args[0] for call in value._send_and_broadcast.await_args_list]
        assert final['type'] == 'final' and final['commit_reason'] == 'decoded_prefix'
        assert final['original'] == 'We cannot spend nineteen dollars.'
        assert final['translation'] == 'No podemos gastar diecinueve dólares.'
        assert final['last_audio_frame_unix_seconds'] == 10
        assert start['type'] == 'speech_start' and start['utterance_id'] == 2
        assert value.state.active_utterance_id == 2
        assert value._utterance_runtime[2].last_audio_frame_unix_seconds == 11
        tail = value.segmenter.current_audio()
        np.testing.assert_array_equal(tail, np.concatenate(frames[135:]))
        np.testing.assert_array_equal(np.concatenate([snapshot, tail[15 * 320:]]),
                                      np.concatenate(frames))
        assert 1 in value._finalized and 1 not in value._finalizing
    asyncio.run(run())


@pytest.mark.parametrize('invalid', [
    'incomplete', 'truncated', 'empty_source', 'empty_target', 'no_pause', 'config',
    'pending_config', 'stopped', 'stale_id', 'finalizing', 'mutated_prefix',
    'decoded_audio_mismatch', 'short_snapshot', 'no_new_audio', 'silence_end',
])
def test_decoded_prefix_falls_back_when_result_or_coverage_is_invalid(monkeypatch, invalid):
    from session import UtteranceRuntime
    from protocol import ConfigMessage

    async def run():
        value = make_session(monkeypatch)
        value.segmenter = RMSGate(max_utterance_s=6, overlap_s=.3)
        value.state.running = True
        value.state.utterance_id = value.state.active_utterance_id = 1
        value.state.config = ConfigMessage(polish_enabled=False)
        for i in range(150):
            value.segmenter.ingest(np.full(320, .1 if i < 142 else 0, dtype=np.float32))
        snapshot = value.segmenter.current_audio().copy()
        if invalid != 'no_new_audio':
            value.segmenter.ingest(np.full(320, .2, dtype=np.float32))
        value._utterance_runtime[1] = UtteranceRuntime(partial_audio_snapshot=snapshot)
        config = value.state.config.model_copy(deep=True)
        result = ASTResult('Do not go.', 'No vayas.', True, False)
        decoded = snapshot.copy()
        if invalid == 'incomplete':
            result = ASTResult(result.original, result.translation, False, False)
        elif invalid == 'truncated':
            result = ASTResult(result.original, result.translation, True, True)
        elif invalid == 'empty_source':
            result = ASTResult('', result.translation, True, False)
        elif invalid == 'empty_target':
            result = ASTResult(result.original, '', True, False)
        elif invalid == 'no_pause':
            snapshot[-8 * 320:] = .1
            decoded = snapshot.copy()
        elif invalid == 'config':
            value.state.config.target_lang = 'French'
        elif invalid == 'pending_config':
            value._pending_config = ConfigMessage(target_lang='French')
        elif invalid == 'stopped':
            value.state.running = False
        elif invalid == 'stale_id':
            value.state.active_utterance_id = 2
        elif invalid == 'finalizing':
            value._finalizing[1] = 'silero_end'
        elif invalid == 'mutated_prefix':
            value.segmenter._current[0] = np.full(320, .3, dtype=np.float32)
        elif invalid == 'decoded_audio_mismatch':
            decoded[-1] = .5
        elif invalid == 'short_snapshot':
            snapshot = snapshot[:320]
            decoded = snapshot.copy()
        elif invalid == 'silence_end':
            value.segmenter.reset()
        before = value.segmenter.current_audio().copy()
        assert not await value._commit_decoded_prefix(1, snapshot, decoded, config, result, None)
        np.testing.assert_array_equal(before, value.segmenter.current_audio())
        value.worker.finish_partials.assert_not_called()
        value._send_and_broadcast.assert_not_called()
    asyncio.run(run())


def test_preview_uses_recent_pause_only_near_cap_and_keeps_tail_buffered(monkeypatch):
    from session import UtteranceRuntime

    value = make_session(monkeypatch)
    value.segmenter = RMSGate(max_utterance_s=6, overlap_s=.3)
    value.state.active_utterance_id = 1
    value._utterance_runtime[1] = UtteranceRuntime()
    frames = [np.full(320, .1, dtype=np.float32) for _ in range(200)]
    frames[152:160] = [np.zeros(320, dtype=np.float32) for _ in range(8)]
    for frame in frames:
        value.segmenter.ingest(frame)
    full = value.segmenter.current_audio()
    snapshot = value._partial_audio_snapshot(full)
    np.testing.assert_array_equal(snapshot, np.concatenate(frames[:160]))
    np.testing.assert_array_equal(value.segmenter.current_audio(), full)
    # A fast decode should not repeatedly choose the same older pause.
    value._utterance_runtime[1].partial_audio_snapshot = snapshot
    np.testing.assert_array_equal(value._partial_audio_snapshot(full), full)
    value._utterance_runtime[1].partial_audio_snapshot = None
    np.testing.assert_array_equal(value._partial_audio_snapshot(full[:100 * 320]),
                                  full[:100 * 320])
    # A seven-frame quiet interval is too short to retire the boundary.
    full[152 * 320:153 * 320] = .1
    np.testing.assert_array_equal(value._partial_audio_snapshot(full), full)


def test_pause_snapshot_timestamp_tracks_last_spoken_frame(monkeypatch):
    async def run():
        value = make_session(monkeypatch)
        value.segmenter = RMSGate(max_utterance_s=6, overlap_s=.3)
        value.worker.is_busy_or_backlogged = True
        value._schedule_ast = Mock()
        monkeypatch.setattr('session.time.time', lambda: 100)
        frames = [np.full(320, .1, dtype=np.float32) for _ in range(200)]
        frames[152:160] = [np.zeros(320, dtype=np.float32) for _ in range(8)]
        for frame in frames[:199]:
            await value._receive_frame(frame)
        value.worker.is_busy_or_backlogged = False
        await value._receive_frame(frames[-1])
        runtime = value._utterance_runtime[1]
        assert runtime.partial_audio_snapshot.size == 160 * 320
        # Both the 160ms pause and the 800ms newer speech are outside the
        # timestamp of the last spoken frame in the decoded snapshot.
        assert runtime.partial_last_audio_unix_seconds == pytest.approx(99.04)
    asyncio.run(run())
