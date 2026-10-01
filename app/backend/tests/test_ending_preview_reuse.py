import asyncio
from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest

from mlx_worker import ASTResult
from protocol import ConfigMessage
from session import CompletedPreview, SessionHub, TranscriptionSession, UtteranceRuntime, _trim_to_transcribable_audio


def fixture():
    value = TranscriptionSession(Mock(query_params={}), Mock(is_busy_or_backlogged=False), SessionHub())
    value._ending_preview_reuse_enabled = True
    value.state.running = True
    value.state.active_utterance_id = 7
    value.state.config = ConfigMessage(polish_enabled=False)
    value._send_and_broadcast = AsyncMock()
    value._maybe_run_maintenance = AsyncMock()
    value._maybe_commit_early = AsyncMock()
    value._schedule_ast = Mock()
    # Exact preview includes all speech and the same 300 ms trim padding.
    snapshot = np.concatenate([np.full(16000, .05, dtype=np.float32), np.zeros(4800, dtype=np.float32)])
    audio = np.concatenate([snapshot, np.zeros(1600, dtype=np.float32)])
    result = ASTResult('We cannot send 27 boxes', 'No podemos enviar 27 cajas', True, False)
    runtime = UtteranceRuntime(partial_audio_snapshot=snapshot.copy(), last_audio_frame_unix_seconds=123.)
    runtime.completed_preview = CompletedPreview(snapshot.copy(), snapshot.copy(), value.state.config.model_copy(deep=True), 0, result)
    value._utterance_runtime[7] = runtime
    return value, audio, runtime


def commit(value, audio, reason='silero_end'):
    return value._commit_utterance(7, audio, reason=reason, reset_segmenter=False)


def test_exact_input_reuses_once_preserving_negation_quantities_and_timestamp():
    async def run():
        value, audio, _ = fixture()
        original = audio.copy()
        assert await commit(value, audio)
        assert not await commit(value, audio)
        value._schedule_ast.assert_not_called()
        value.worker.finish_partials.assert_called_once_with(7)
        payload = value._send_and_broadcast.await_args.args[0]
        assert payload['original'] == 'We cannot send 27 boxes'
        assert payload['translation'] == 'No podemos enviar 27 cajas'
        assert payload['last_audio_frame_unix_seconds'] == 123.
        assert payload['commit_reason'] == 'silero_end'
        assert 7 not in value._utterance_runtime and 7 not in value._finalizing
        np.testing.assert_array_equal(audio, original)
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['new_speech', 'quiet_tail', 'changed_sample', 'padding', 'pending_config', 'config', 'revision', 'identity', 'stopped', 'incomplete', 'truncated', 'empty_source', 'empty_target', 'no_preview', 'cap'])
def test_unproven_preview_falls_back_without_dropping_audio(failure):
    async def run():
        value, audio, runtime = fixture()
        preview = runtime.completed_preview
        reason = 'silero_end'
        if failure == 'new_speech': audio[-320:] = .05
        elif failure == 'quiet_tail': audio[-320:] = .0001
        elif failure == 'changed_sample': audio[500] += .001
        elif failure == 'padding':
            preview.snapshot = preview.snapshot[:-320]
            preview.decoded_audio = preview.decoded_audio[:-320]
        elif failure == 'pending_config': value._pending_config = value.state.config.model_copy()
        elif failure == 'config': value.state.config.target_lang = 'French'
        elif failure == 'revision': value._config_revision += 2  # Changed away and back.
        elif failure == 'identity': value.state.active_utterance_id = 8
        elif failure == 'stopped': value.state.running = False
        elif failure in ('incomplete', 'truncated', 'empty_source', 'empty_target'):
            preview.result = ASTResult('' if failure == 'empty_source' else 'No 27', '' if failure == 'empty_target' else 'No 27', failure != 'incomplete', failure == 'truncated')
        elif failure == 'no_preview': runtime.completed_preview = None
        elif failure == 'cap': reason = 'max_utterance_cap'
        assert await commit(value, audio, reason)
        value._schedule_ast.assert_called_once()
        priority, uid, submitted = value._schedule_ast.call_args.args
        assert (priority, uid) == ('final', 7)
        np.testing.assert_array_equal(submitted, audio)
        value._send_and_broadcast.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('outcome', ['late', 'cancelled', 'config_changed', 'runtime_replaced', 'completed'])
def test_inflight_completion_cannot_race_final_or_cache_stale_result(outcome):
    async def run():
        value, audio, runtime = fixture()
        runtime.completed_preview = None
        entered, release = asyncio.Event(), asyncio.Event()
        result = ASTResult('We cannot send 27 boxes', 'No podemos enviar 27 cajas', True, False)
        async def submit(**kwargs):
            entered.set()
            await release.wait()
            return result
        value.worker.submit_ast = AsyncMock(side_effect=submit)
        value._commit_decoded_prefix = AsyncMock(return_value=False)
        task = asyncio.create_task(value._run_mlx_ast('partial', 7, _trim_to_transcribable_audio(runtime.partial_audio_snapshot)))
        await entered.wait()
        if outcome == 'late':
            assert await commit(value, audio)
            value._schedule_ast.assert_called_once()
        elif outcome == 'cancelled': task.cancel()
        elif outcome == 'config_changed': value._config_revision += 2
        elif outcome == 'runtime_replaced': value._utterance_runtime[7] = UtteranceRuntime()
        release.set()
        await asyncio.gather(task, return_exceptions=outcome == 'cancelled')
        if outcome == 'completed':
            assert runtime.completed_preview is not None
            assert await commit(value, audio)
            value._schedule_ast.assert_not_called()
        else:
            assert runtime.completed_preview is None
            assert not any(c.args[0]['type'] == 'final' for c in value._send_and_broadcast.await_args_list)
    asyncio.run(run())


def test_real_configuration_change_invalidates_completed_cache_even_when_values_return():
    async def run():
        value, audio, _ = fixture()
        original = value.state.config.model_copy(deep=True)
        await value._apply_config(original.model_copy(update={"target_lang": "French"}))
        await value._apply_config(original)
        assert await commit(value, audio)
        value._schedule_ast.assert_called_once()
    asyncio.run(run())


def test_explicit_flush_can_reuse_and_resets_segmenter():
    async def run():
        value, audio, _ = fixture()
        value.segmenter = Mock()
        assert await value._commit_utterance(7, audio, reason="silero_end", reset_segmenter=True)
        value.segmenter.reset.assert_called_once()
        value._schedule_ast.assert_not_called()
    asyncio.run(run())


def test_disabled_experiment_keeps_normal_final_decode():
    async def run():
        value, audio, _ = fixture()
        value._ending_preview_reuse_enabled = False
        assert await commit(value, audio)
        value._schedule_ast.assert_called_once()
        value._send_and_broadcast.assert_not_awaited()
    asyncio.run(run())
