"""Instruction-prefix KV cache: keying, private copies and the embedding hand-off."""
import importlib
from contextlib import contextmanager
from types import SimpleNamespace

import mlx.core as mx
import pytest

from prefix_cache import PrefixKVCache

BOA = 9


class FakeCache:
    def __init__(self):
        self.state = (mx.zeros((1, 2)), mx.zeros((1, 2)))
        self.meta_state = ("0",)


class FakeLanguageModel:
    def __init__(self):
        self.prefills = []

    def __call__(self, inputs, cache, logits_to_keep):
        self.prefills.append(inputs[0].tolist())
        for entry in cache:
            entry.state = (mx.full((1, 2), float(sum(self.prefills[-1]))), mx.ones((1, 2)))
            entry.meta_state = (str(inputs.shape[1]),)
        return SimpleNamespace(logits=mx.zeros((1, 1, 4)))


class FakeModel:
    def __init__(self):
        self.config = SimpleNamespace(boa_token_id=BOA)
        self.language_model = FakeLanguageModel()

    def get_input_embeddings(self, input_ids, pixel_values, mask=None, **kwargs):
        return SimpleNamespace(inputs_embeds=mx.zeros((1, input_ids.shape[1], 3)), own=True)


@pytest.fixture
def model(monkeypatch):
    prompts = {}
    monkeypatch.setattr(importlib.import_module("mlx_vlm.generate.dispatch"),
                        "_prepare_generation_inputs",
                        lambda model, processor, prompt, *args: (
                            mx.array([prompts[prompt]]), None, None, {"input_features": "f"}))
    monkeypatch.setattr(importlib.import_module("mlx_vlm.models.cache"), "make_prompt_cache",
                        lambda lm: [FakeCache(), FakeCache()])
    fake = FakeModel()
    fake.prompts = prompts
    return fake


def test_prefix_built_once_per_distinct_prefix(model):
    model.prompts.update(a=[1, 2, 3, BOA, 7, 8], b=[1, 2, 3, BOA, 5], c=[1, 4, 3, BOA, 5])
    cache = PrefixKVCache(model)

    kwargs, prefix = cache.prepare(None, "a", "x.wav")
    assert prefix == 3
    assert kwargs["input_ids"][0].tolist() == [BOA, 7, 8]
    assert kwargs["input_features"] == "f"
    cache.prepare(None, "b", "x.wav")
    assert cache.builds == 1
    cache.prepare(None, "c", "x.wav")
    assert cache.builds == 2
    assert model.language_model.prefills == [[1, 2, 3], [1, 4, 3]]


def test_each_decode_gets_a_private_copy(model):
    model.prompts.update(a=[1, 2, 3, BOA, 7])
    cache = PrefixKVCache(model)
    first, _ = cache.prepare(None, "a", "x.wav")
    second, _ = cache.prepare(None, "a", "x.wav")

    keys = first["prompt_cache"][0].state[0]
    keys[0, 0] = 99.0
    assert second["prompt_cache"][0].state[0][0, 0].item() == 6.0
    assert first["prompt_cache"][0].meta_state == ("3",)


def test_no_prefix_without_audio_token(model):
    model.prompts.update(a=[1, 2, 3], b=[BOA, 1, 2])
    cache = PrefixKVCache(model)
    assert cache.prepare(None, "a", "x.wav") is None
    assert cache.prepare(None, "b", "x.wav") is None
    assert cache.builds == 0


def test_embeddings_served_once_then_restored(model):
    model.prompts.update(a=[1, 2, 3, BOA, 7, 8])
    cache = PrefixKVCache(model)
    kwargs, _ = cache.prepare(None, "a", "x.wav")
    with cache.embeddings(kwargs) as inputs:
        assert "_prefix_embedding" not in inputs
        served = model.get_input_embeddings(None, None)
        assert served.inputs_embeds.shape == (1, 3, 3)
        assert model.get_input_embeddings(mx.zeros((1, 6)), None).inputs_embeds.shape == (1, 6, 3)
    assert "get_input_embeddings" not in vars(model)


def test_embedding_override_removed_when_never_called(model):
    model.prompts.update(a=[1, 2, 3, BOA, 7])
    cache = PrefixKVCache(model)
    kwargs, _ = cache.prepare(None, "a", "x.wav")
    with pytest.raises(RuntimeError):
        with cache.embeddings(kwargs):
            raise RuntimeError
    assert "get_input_embeddings" not in vars(model)


def test_worker_flag_defaults_on():
    import mlx_worker

    assert mlx_worker.PREFIX_CACHE is True


class BrokenCache:
    """Fails in prepare() or, once its inputs are used, inside generation."""

    def __init__(self, where):
        self.where = where

    def prepare(self, processor, prompt, audio_path):
        if self.where == "prepare":
            raise ValueError("prepare broke")
        return {"input_ids": "suffix", "_prefix_embedding": None}, 77

    @contextmanager
    def embeddings(self, kwargs):
        kwargs.pop("_prefix_embedding")
        yield kwargs


RESPONSE = [SimpleNamespace(text="We cannot go\nSpanish: No podemos ir",
                            generation_tokens=8, finish_reason="stop")]


@pytest.mark.parametrize("where", ["prepare", "generate"])
def test_cache_failure_reruns_uncached_and_keeps_mtp(monkeypatch, tmp_path, where):
    import numpy as np

    import mlx_worker
    from test_ast_streaming import _patch_mlx, _worker

    traced = []
    monkeypatch.setattr(mlx_worker, "trace", lambda stage, **fields: traced.append(stage))
    _patch_mlx(monkeypatch, [])
    calls = []

    def generate(*args, **kwargs):
        calls.append(kwargs)
        if kwargs.get("input_ids") == "suffix":
            yield SimpleNamespace(text="We", generation_tokens=1, finish_reason=None)
            raise RuntimeError("cached generation broke")
        yield from RESPONSE

    import sys
    sys.modules["mlx_vlm"].stream_generate = generate
    worker = _worker(tmp_path)
    draft = worker._draft_model = object()
    worker._prefix_cache = BrokenCache(where)

    result = worker.ast(np.ones(16000), "English", "Spanish", [], priority="final")
    assert (result.original, result.translation) == ("We cannot go", "No podemos ir")
    assert worker._draft_model is draft and worker._prefix_cache is None
    assert "prefix_cache_failed" in traced and "mtp_fallback" not in traced
    assert "audio" in calls[-1] and calls[-1]["draft_model"] is draft

    worker.ast(np.ones(16000), "English", "Spanish", [], priority="final")
    assert "audio" in calls[-1] and "input_ids" not in calls[-1]


def test_cancel_in_the_cached_path_still_propagates(monkeypatch, tmp_path):
    import sys

    import numpy as np

    import mlx_worker
    from test_ast_streaming import _patch_mlx, _worker

    _patch_mlx(monkeypatch, [])

    def generate(*args, **kwargs):
        raise mlx_worker.GenerationCancelled
        yield

    sys.modules["mlx_vlm"].stream_generate = generate
    worker = _worker(tmp_path)
    worker._draft_model = object()
    cache = worker._prefix_cache = BrokenCache("generate")
    assert worker.ast(np.ones(16000), "English", "Spanish", [], priority="partial",
                      cancelled=lambda: False) is None
    assert worker._prefix_cache is cache
