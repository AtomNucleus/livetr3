import sys

import mlx.core as mx
import mlx.nn as nn
import numpy as np
import pytest

import mlx_worker
from mlx_worker import GenerationCancelled, MLXWorker, _install_cancel_hook
from test_ast_streaming import _patch_mlx, _worker


class Language(nn.Module):
    def __init__(self):
        super().__init__()
        self.scale = mx.array(2.0)

    def __call__(self, inputs, cache=None):
        return inputs * self.scale


def test_cancel_hook_raises_from_the_forward_call_only_while_cancelled():
    model = nn.Module()
    model.language_model = Language()
    cancelled = [None]
    _install_cancel_hook(model, lambda: cancelled[0])
    language = model.language_model
    assert isinstance(language, Language) and type(language).__name__ == "Language"
    assert "scale" in dict(language.parameters())
    assert language(mx.array(3.0)).item() == 6.0  # no job armed
    cancelled[0] = lambda: False
    assert language(mx.array(3.0)).item() == 6.0
    cancelled[0] = lambda: True
    with pytest.raises(GenerationCancelled):
        language(mx.array(3.0))


@pytest.mark.parametrize("cancellable,expected", [(True, 32), (False, None)])
def test_only_cancellable_jobs_get_the_small_prefill_chunk(monkeypatch, tmp_path, cancellable, expected):
    monkeypatch.setattr(mlx_worker, "CANCELLABLE_PREFILL_CHUNK", 32)
    _patch_mlx(monkeypatch, [])
    calls = []
    def generate(*args, **kwargs):
        calls.append(kwargs)
        yield from ()
    sys.modules["mlx_vlm"].stream_generate = generate
    worker = _worker(tmp_path)
    worker.ast(np.ones(16000), "English", "Spanish", [], priority="partial",
               cancelled=(lambda: False) if cancellable else None)
    assert calls[0].get("prefill_step_size") == expected


def test_cancel_during_prefill_returns_no_result_and_keeps_mtp(monkeypatch, tmp_path):
    monkeypatch.setattr(mlx_worker, "CANCELLABLE_PREFILL_CHUNK", 32)
    _patch_mlx(monkeypatch, [])
    calls, armed = [], []
    def generate(*args, **kwargs):
        calls.append(kwargs)
        armed.append(worker._generation_cancelled)
        raise GenerationCancelled  # what the hook raises mid-prefill
        yield
    sys.modules["mlx_vlm"].stream_generate = generate
    worker = _worker(tmp_path)
    draft = worker._draft_model = object()
    cancelled = lambda: True
    assert worker.ast(np.ones(16000), "English", "Spanish", [], priority="partial",
                      cancelled=cancelled) is None
    assert armed == [cancelled] and worker._generation_cancelled is None
    assert worker._draft_model is draft and len(calls) == 1
    assert not list(tmp_path.glob("*.wav"))
