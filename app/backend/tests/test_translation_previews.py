import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np

from parakeet_worker import ASRResult
from protocol import ConfigMessage
from session import TranscriptionSession, UtteranceRuntime


def make_session(current="We can go tomorrow"):
    session = object.__new__(TranscriptionSession)
    session.state = SimpleNamespace(config=ConfigMessage())
    session._finalizing = {}
    session._finalized = set()
    session._utterance_runtime = {1: UtteranceRuntime(latest_partial_original=current)}
    session._translate_partial = AsyncMock(return_value="Podemos ir")
    session._send_and_broadcast = AsyncMock()
    return session


def test_translation_of_still_valid_prefix_is_published_without_rewinding_source():
    async def run():
        session = make_session()
        await session._run_partial_translation_update(1, "We can go")
        payload = session._send_and_broadcast.call_args.args[0]
        assert payload["original"] == "We can go tomorrow"
        assert payload["translation"] == "Podemos ir"
        runtime = session._utterance_runtime[1]
        assert runtime.latest_translation_original == "We can go"
        assert session._promotable_partial_translation(runtime, "We can go tomorrow") is None
    asyncio.run(run())


def test_asr_correction_invalidates_translation_of_old_words():
    async def run():
        session = make_session("We cannot go")
        await session._run_partial_translation_update(1, "We can go")
        session._send_and_broadcast.assert_not_awaited()
    asyncio.run(run())


def test_word_fragment_is_not_treated_as_complete_matching_prefix():
    async def run():
        session = make_session("We cannot go")
        await session._run_partial_translation_update(1, "We can")
        session._send_and_broadcast.assert_not_awaited()
    asyncio.run(run())


def test_late_shorter_translation_cannot_overwrite_newer_preview():
    async def run():
        session = make_session()
        runtime = session._utterance_runtime[1]
        runtime.latest_translation_original = "We can go tomorrow"
        runtime.latest_partial_translation = "Podemos ir mañana"
        await session._run_partial_translation_update(1, "We can go")
        session._send_and_broadcast.assert_not_awaited()
        assert runtime.latest_partial_translation == "Podemos ir mañana"
    asyncio.run(run())


def test_source_growth_keeps_spanish_preview_visible():
    async def run():
        session = make_session("We can go")
        runtime = session._utterance_runtime[1]
        runtime.latest_translation_original = "We can go"
        runtime.latest_partial_translation = "Podemos ir"
        session.asr_worker = SimpleNamespace(submit_asr=AsyncMock(return_value=ASRResult("We can go tomorrow")))
        session._jobs = set()
        session._run_partial_translation_update = AsyncMock()
        session._maybe_commit_early = AsyncMock()
        await session._run_parakeet_asr("partial", 1, np.zeros(16000, dtype=np.float32))
        assert session._send_and_broadcast.call_args.args[0]["translation"] == "Podemos ir"
        await asyncio.gather(*session._jobs)
    asyncio.run(run())


def test_generated_words_are_visible_but_cannot_be_promoted_until_complete():
    async def run():
        session = make_session("We can go")
        await session._publish_translation_preview(1, "We can go", "Podemos")
        assert session._send_and_broadcast.call_args.args[0]["translation"] == "Podemos"
        assert session._promotable_partial_translation(session._utterance_runtime[1], "We can go") is None
        await session._run_partial_translation_update(1, "We can go")
        assert session._promotable_partial_translation(session._utterance_runtime[1], "We can go") == "Podemos ir"
        session._finalized.add(1)
        session._send_and_broadcast.reset_mock()
        await session._publish_translation_preview(1, "We can go", "stale")
        session._send_and_broadcast.assert_not_awaited()
    asyncio.run(run())


def test_worker_delivers_progress_before_result():
    import queue
    from mlx_worker import MLXWorkerService, _QueuedJob

    async def run():
        worker = MLXWorkerService()
        worker._process = SimpleNamespace(is_alive=lambda: True)
        worker._response_queue = queue.Queue()
        worker._response_queue.put({"type": "progress", "job_id": 3, "text": "Podemos"})
        worker._response_queue.put({"type": "result", "job_id": 3, "result": "Podemos ir"})
        progress = AsyncMock()
        job = _QueuedJob(20, 3, "translate", asyncio.get_running_loop().create_future(), {}, on_progress=progress)
        result = await worker._wait_for_worker_response(job, 1)
        progress.assert_awaited_once_with("Podemos")
        assert result["result"] == "Podemos ir"
    asyncio.run(run())


def test_next_decode_does_not_erase_existing_translation_prefix():
    async def run():
        session = make_session("We can go tomorrow")
        runtime = session._utterance_runtime[1]
        runtime.latest_translation_original = "We can go"
        runtime.latest_partial_translation = "Podemos ir"
        await session._publish_translation_preview(1, "We can go tomorrow", "Podemos")
        session._send_and_broadcast.assert_not_awaited()
        assert runtime.latest_partial_translation == "Podemos ir"
        await session._publish_translation_preview(1, "We can go tomorrow", "Podemos ir mañana")
        assert session._send_and_broadcast.call_args.args[0]["translation"] == "Podemos ir mañana"
        assert runtime.translation_incomplete
    asyncio.run(run())
