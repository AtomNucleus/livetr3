from types import SimpleNamespace

from protocol import ConfigMessage
from session import TranscriptionSession, UtteranceRuntime


def session(source="English", code_switching=False):
    value = object.__new__(TranscriptionSession)
    value.transcription_engine = "parakeet"
    value.state = SimpleNamespace(config=ConfigMessage(
        source_lang=source, code_switching_enabled=code_switching))
    return value


def test_incomplete_or_changed_translation_is_not_promoted_to_final():
    value = session()
    runtime = UtteranceRuntime(latest_partial_original="We can go",
                               latest_translation_original="We can go",
                               latest_partial_translation="Podemos ir")
    assert value._promotable_partial_translation(runtime, "We can go tomorrow") is None
    assert value._promotable_partial_translation(runtime, "We cannot go") is None
    assert value._promotable_partial_translation(runtime, "We can go.") == "Podemos ir"


def test_unverified_model_corrections_are_opt_in():
    assert not ConfigMessage().asr_correction_enabled
    assert not ConfigMessage().transcript_learning_enabled


def test_native_asr_routes_unsupported_languages_and_code_switching_to_gemma():
    assert session("English")._should_use_parakeet_asr()
    assert session("Spanish")._should_use_parakeet_asr()
    assert not session("Japanese")._should_use_parakeet_asr()
    assert not session("English", True)._should_use_parakeet_asr()


def test_gemma_replaces_partial_instead_of_appending_or_retranslating():
    import asyncio
    from unittest.mock import AsyncMock
    import numpy as np

    async def run():
        value = session()
        value.worker = SimpleNamespace(submit_ast=AsyncMock(return_value=("We cannot go", "No podemos ir")))
        value.state.prior_context = []
        value._finalized = set()
        value._finalizing = {}
        value._utterance_runtime = {1: UtteranceRuntime(
            latest_partial_original="We can go", latest_partial_translation="Podemos ir")}
        value._send_and_broadcast = AsyncMock()
        value._maybe_commit_early = AsyncMock()
        await value._run_mlx_ast("partial", 1, np.zeros(16000, dtype=np.float32))
        payload = value._send_and_broadcast.call_args.args[0]
        assert payload["original"] == "We cannot go"
        assert payload["translation"] == "No podemos ir"

    asyncio.run(run())


def test_workers_do_not_share_temporary_audio_directories():
    from mlx_worker import MLXWorkerService
    from parakeet_worker import ParakeetASRService

    assert MLXWorkerService()._temp_wav_root != ParakeetASRService()._temp_wav_root
