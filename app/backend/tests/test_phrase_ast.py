import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from mlx_worker import ASTResult, MLXWorkerService, _parse_phrase_ast_response, _canonical_ast_progress, _parse_ast_response
from test_ast_streaming import _patch_mlx, _worker


def test_phrases_keep_negation_quantities_and_source_target_separate():
    raw = "Source: We cannot carry nine boxes.\nTarget: No podemos llevar nueve cajas.\nSource: Only three fit.\nTarget: Solo caben tres."
    assert _parse_phrase_ast_response(raw) == (
        "We cannot carry nine boxes. Only three fit.",
        "No podemos llevar nueve cajas. Solo caben tres.", True,
    )


def test_every_token_prefix_hides_headers_and_keeps_previous_translation():
    raw = "Source: We cannot go.\nTarget: No podemos ir.\nSource: Bring nine boxes.\nTarget: Traigan nueve cajas."
    previous = ""
    for size in range(1, len(raw) + 1):
        source, target, _ = _parse_phrase_ast_response(raw[:size], streaming=True)
        assert "Source:" not in source + target
        assert "Target:" not in source + target
        assert target.startswith(previous)
        previous = target
        canonical = _canonical_ast_progress(source, target, "Spanish")
        if canonical:
            assert _parse_ast_response(canonical, "Spanish", "English") == (source, target)


@pytest.mark.parametrize("raw", [
    "Target: No podemos ir.",
    "Source: We cannot go.\nSource: Bring nine boxes.",
    "Source: We cannot go.\nTarget:",
    "Source: We cannot go.\nTarget: No podemos ir.\nSource: Bring nine boxes.",
    "Source: We cannot go.\nTarget: No podemos ir.\nSou",
    "Here is the transcription.\nSource: We cannot go.\nTarget: No podemos ir.",
    "Source:\nTarget: No podemos ir.",
])
def test_malformed_or_unpaired_output_is_never_a_complete_final(raw):
    assert _parse_phrase_ast_response(raw)[2] is False


def test_role_labels_work_when_source_and_target_languages_match():
    assert _parse_phrase_ast_response("Source: Hola.\nTarget: Hola.") == ("Hola.", "Hola.", True)


def test_phrase_worker_streams_first_translation_before_second_source(monkeypatch, tmp_path):
    raw = ["Source: We cannot go.", "\nTarget: No podemos ir.",
           "\nSource: Bring nine boxes.", "\nTarget: Traigan nueve cajas."]
    pieces = [SimpleNamespace(text=text, generation_tokens=i + 1,
                              finish_reason="stop" if i == len(raw) - 1 else None)
              for i, text in enumerate(raw)]
    budgets = _patch_mlx(monkeypatch, [pieces])
    progress = []
    result = _worker(tmp_path).ast(np.ones(16000, dtype=np.float32), "English", "Spanish",
        prior_context=[], priority="partial", on_progress=progress.append, phrase_bilingual=True)
    assert result == ASTResult("We cannot go. Bring nine boxes.", "No podemos ir. Traigan nueve cajas.", True, False)
    assert len(budgets) == 1
    assert progress[1] == "We cannot go.\nSpanish: No podemos ir."
    assert progress[2] == "We cannot go. Bring nine boxes.\nSpanish: No podemos ir."


def test_untranslated_last_phrase_retries_instead_of_publishing_incomplete_final(monkeypatch, tmp_path):
    first = "Source: We cannot go.\nTarget: No podemos ir.\nSource: Bring nine boxes."
    second = first + "\nTarget: Traigan nueve cajas."
    budgets = _patch_mlx(monkeypatch, [[SimpleNamespace(text=text, generation_tokens=40, finish_reason="stop")]
                                       for text in (first, second)])
    result = _worker(tmp_path).ast(np.ones(16000, dtype=np.float32), "English", "Spanish",
        prior_context=[], max_tokens=100, phrase_bilingual=True)
    assert result.complete
    assert budgets == [100, 200]


def test_truncated_paired_partial_is_not_complete(monkeypatch, tmp_path):
    _patch_mlx(monkeypatch, [[SimpleNamespace(text="Source: We cannot go.\nTarget: No podemos ir.",
        generation_tokens=192, finish_reason="length")]])
    result = _worker(tmp_path).ast(np.ones(16000, dtype=np.float32), "English", "Spanish",
        prior_context=[], max_tokens=192, priority="partial", phrase_bilingual=True)
    assert result.truncated and not result.complete


@pytest.mark.parametrize("setting,enabled", [(None, False), ("0", False), ("1", True)])
def test_service_captures_experimental_format_in_each_job(monkeypatch, setting, enabled):
    if setting is None:
        monkeypatch.delenv("LIVETR3_PHRASE_BILINGUAL", raising=False)
    else:
        monkeypatch.setenv("LIVETR3_PHRASE_BILINGUAL", setting)

    async def run():
        worker = MLXWorkerService()
        request = asyncio.create_task(worker.submit_ast(priority="partial", utterance_id=1,
            audio_f32_16k=np.ones(16000, dtype=np.float32), src="English", tgt="Spanish",
            prior_context=[], custom_vocab=[], code_switching_enabled=False, max_tokens=192))
        await asyncio.sleep(0)
        job = await worker._queue.get()
        assert job.payload["phrase_bilingual"] is enabled
        job.future.set_result(None)
        assert await request is None
    asyncio.run(run())
