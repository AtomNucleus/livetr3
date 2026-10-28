"""Instruction-prefix KV cache for Gemma AST decodes.

Every AST prompt starts with the same instruction tokens before the audio
(boa) token. Their KV is computed once per distinct prefix and each decode
gets its own copy, so prefill runs only on the audio and the answer header.

mlx-vlm 0.7.4 (and 0.7.10) only reuse a cached prefix when the rest of the
prompt is text, so this feeds stream_generate caller-prepared inputs instead:
the suffix token ids, a copied prefix cache, and the full prompt's embedding
output with its token embeddings cut to the suffix. Gemma 4 slices its
per-layer inputs by cache offset, so those stay full length. MTP needs
nothing extra: its drafter reads the hidden state and shared KV of the
prefill's last step, which attends over the whole cache.
"""
from __future__ import annotations

from contextlib import contextmanager


class PrefixKVCache:
    def __init__(self, model) -> None:
        self._model = model
        self._key: tuple[int, ...] | None = None
        self._template: list[tuple[tuple, object]] | None = None
        self.builds = 0

    def prepare(self, processor, prompt: str, audio_path: str) -> tuple[dict, int] | None:
        """stream_generate kwargs for a cached-prefix decode and the cached
        token count, or None when the prompt has no cacheable prefix."""
        import mlx.core as mx
        from mlx_vlm.generate.dispatch import _prepare_generation_inputs

        model = self._model
        ids, pixel_values, mask, data = _prepare_generation_inputs(
            model, processor, prompt, None, [audio_path], None, {}
        )
        tokens = ids[0].tolist()
        boa = getattr(model.config, "boa_token_id", None)
        if boa not in tokens or pixel_values is not None:
            return None
        prefix = tokens.index(boa)
        if prefix < 2:
            return None
        key = tuple(tokens[:prefix])
        if key != self._key:
            self._build(ids[:, :prefix])
            self._key = key
        embedding = model.get_input_embeddings(ids, pixel_values, mask=mask, **data)
        embedding.inputs_embeds = embedding.inputs_embeds[:, prefix:]
        mx.eval(embedding.inputs_embeds)
        kwargs = dict(data, input_ids=ids[:, prefix:], prompt_cache=self._copy(),
                      _prefix_embedding=embedding)
        return kwargs, prefix

    @contextmanager
    def embeddings(self, kwargs: dict):
        """Serve the precomputed embedding output to generate_step's one
        get_input_embeddings call; later calls reach the model's own."""
        embedding = kwargs.pop("_prefix_embedding")
        model = self._model

        def serve(*args, **kw):
            model.__dict__.pop("get_input_embeddings", None)
            return embedding

        model.get_input_embeddings = serve
        try:
            yield kwargs
        finally:
            model.__dict__.pop("get_input_embeddings", None)

    def _build(self, prefix_ids) -> None:
        import mlx.core as mx
        from mlx_vlm.models import cache as cache_module

        language_model = self._model.language_model
        cache = cache_module.make_prompt_cache(language_model)
        output = language_model(inputs=prefix_ids, cache=cache, logits_to_keep=1)
        mx.eval(output.logits, [c.state for c in cache])
        self._template = [(tuple(mx.array(a) for a in c.state), c.meta_state) for c in cache]
        mx.eval([arrays for arrays, _ in self._template])
        self.builds += 1

    def _copy(self) -> list:
        """A private cache per decode: KVCache writes into its buffers in place."""
        import mlx.core as mx
        from mlx_vlm.models import cache as cache_module

        cache = cache_module.make_prompt_cache(self._model.language_model)
        for entry, (arrays, meta) in zip(cache, self._template):
            entry.state = tuple(mx.array(a) for a in arrays)
            entry.meta_state = meta
        return cache
