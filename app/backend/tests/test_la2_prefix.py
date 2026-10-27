import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

from mlx_worker import ASTResult
from session import SessionHub, TranscriptionSession, UtteranceRuntime, _agreed_source_prefix
from test_ast_streaming import _patch_mlx, _worker


@pytest.mark.parametrize("previous,latest,expected", [
    ("We cannot go to", "We cannot go to the", "We cannot go"),  # shared end of one hypothesis held back
    ("We cannot go there.", "we CANNOT go home", "we CANNOT go"),
    ("We cannot", "We cannot go", ""),  # one word after holding back is too little
    ("They will", "We will", ""),
    ("", "We cannot go", ""),
])
def test_agreement_is_the_shared_word_prefix_short_of_an_end(previous, latest, expected):
    assert _agreed_source_prefix(previous, latest) == expected


def test_worker_continues_the_forced_prefix(monkeypatch, tmp_path):
    _patch_mlx(monkeypatch, [])
    prompts = []
    def generate(model, processor, prompt, **kwargs):
        prompts.append(prompt)
        yield SimpleNamespace(text=" go home\nSpanish: No podemos ir a casa", generation_tokens=9,
                              finish_reason="stop")
    sys.modules["mlx_vlm"].stream_generate = generate
    progress = []
    result = _worker(tmp_path).ast(np.ones(16000), "English", "Spanish", [], priority="partial",
                                   on_progress=progress.append, source_prefix="We cannot")
    assert prompts == ["formattedWe cannot"]
    assert (result.original, result.translation, result.complete) == (
        "We cannot go home", "No podemos ir a casa", True)
    assert progress[-1].startswith("We cannot go home")


class Worker:
    is_busy_or_backlogged = False

    def __init__(self):
        self.calls = []

    async def submit_ast(self, **kwargs):
        self.calls.append(kwargs)
        text = ["We cannot go there", "We cannot go home now", "We cannot go home today",
                "We cannot go home today."][len(self.calls) - 1]
        return ASTResult(text, "x", complete=True, truncated=False)

    def finish_partials(self, utterance_id):
        pass


@pytest.mark.parametrize("mode,partial_prefix,final_prefix", [
    ("off", None, None), ("previews", "We cannot go", None), ("all", "We cannot go", "We cannot go home")])
def test_session_forces_agreement_only_where_the_mode_says(monkeypatch, mode, partial_prefix, final_prefix):
    monkeypatch.setenv("LIVETR3_LA2_PREFIX", mode)
    async def run():
        value = TranscriptionSession(SimpleNamespace(query_params={}), Worker(), SessionHub())
        value._send_and_broadcast = AsyncMock()
        value._utterance_runtime[3] = UtteranceRuntime()
        for _ in range(3):
            await value._run_mlx_ast("partial", 3, np.ones(16000, dtype=np.float32))
        await value._run_mlx_ast("final", 3, np.ones(16000, dtype=np.float32))
        calls = value.worker.calls
        assert "source_prefix" not in calls[0] and "source_prefix" not in calls[1]
        assert calls[2].get("source_prefix") == partial_prefix
        assert calls[3].get("source_prefix") == final_prefix
    asyncio.run(run())
