"""Draft from the previous decode's output, verified exactly by the target.

Consecutive decodes of one utterance hear mostly the same audio, so the last
preview's tokens predict about 90% of the final's. When the newest emitted
tokens match a run in that hint, the next hint tokens are proposed as one
verify block instead of a short MTP draft. The target model's greedy choice
decides every token either way, so the hint changes speed, never the caption
(up to the float differences any verify block size already has). Rounds
without a match use the MTP drafter as before.
"""
from __future__ import annotations

import os
from collections.abc import Callable, Generator, Sequence
from typing import Any

import mlx.core as mx

HINT_DRAFT_ENABLED = os.getenv("LIVETR3_HINT_DRAFT", "1").lower() not in {"0", "false", "no", "off"}
# Drafted hint tokens per verify block. On sermon audio 24 beat 8, 16 and 32 (each round costs more,
# but far fewer rounds are needed).
HINT_DRAFT_MAX = max(2, int(os.getenv("LIVETR3_HINT_DRAFT_MAX", "24")))
# Emitted tokens that must match the hint before it is trusted.
HINT_MATCH_TOKENS = 3

_hint: tuple[int, ...] = ()
stats = {"rounds": 0, "accepted": 0, "drafted": 0}


def set_hint(tokens: Sequence[int]) -> None:
    global _hint
    _hint = tuple(int(token) for token in tokens)


def propose(emitted: Sequence[int], hint: Sequence[int], cursor: int, limit: int) -> tuple[list[int], int]:
    """Return (hint tokens to draft, hint index after them) for the emitted tail.

    The match nearest after ``cursor`` (where the last proposal ended) wins,
    so repeated phrases follow the hint in order.
    """
    n = min(HINT_MATCH_TOKENS, len(emitted))
    if n == 0 or limit < 1 or len(hint) <= n:
        return [], cursor
    tail = list(emitted[-n:])
    best = None
    for start in range(0, len(hint) - n):
        if list(hint[start:start + n]) == tail:
            if start + n >= cursor:
                best = start
                break
            if best is None:
                best = start
    if best is None:
        return [], cursor
    begin = best + n
    tokens = list(hint[begin:begin + limit])
    return tokens, begin + len(tokens)


def install() -> bool:
    """Route mlx-vlm's single-row MTP loop through the hinted loop."""
    if not HINT_DRAFT_ENABLED:
        return False
    from mlx_vlm.speculative import utils

    if getattr(utils._mtp_rounds, "_livetr3_hinted", False):
        return True
    utils._mtp_rounds = _hinted_mtp_rounds
    return True


def _hinted_mtp_rounds(
    model: Any,
    draft_model: Any,
    prompt_cache: list[Any],
    hidden: mx.array,
    shared_kv_states: dict,
    *,
    prompt_tokens: mx.array | None = None,
    first_bonus: int,
    max_tokens: int,
    sampler: Callable[[mx.array], mx.array],
    draft_block_size: int | None = None,
    token_dtype: mx.Dtype = mx.int32,
    greedy_sampling: bool = False,
) -> Generator[tuple[int, None], None, None]:
    # Mirrors mlx_vlm.speculative.mtp._mtp_rounds (0.7.4); only the source of
    # each round's draft tokens differs.
    from mlx_vlm.speculative import mtp as m

    lm = model.language_model if hasattr(model, "language_model") else model
    hint = _hint
    # Hints are exact only under greedy verification.
    use_hint = bool(hint) and greedy_sampling

    block_total = m._dflash_block_total(draft_model, draft_block_size)
    configured_block_total = int(getattr(draft_model.config, "block_size", block_total))
    draft_model.reset(model)
    sampler_rng = m._SpeculativeSamplerRNG(
        draft_model,
        enabled=not greedy_sampling and not m._sampler_supports_positioned_target(sampler),
    )

    prefill_draft = getattr(draft_model, "prefill_from_target_hidden", None)
    if callable(prefill_draft) and prompt_tokens is not None:
        sampler_rng.draft_call(
            prefill_draft, prompt_tokens, hidden, first_bonus, sampler, token_dtype,
            **m._mtp_draft_kwargs(draft_model, greedy_sampling, sampler),
        )

    if hidden.shape[1] > 1:
        hidden = hidden[:, -1:, :]
    hidden = m._mtp_draft_hidden(lm, hidden)

    kv_offset = m._mtp_cache_offset_max(prompt_cache)
    draft_model.set_shared_kv(
        shared_kv_states, kv_offset,
        position=m._mtp_draft_position(kv_offset), kv_valid_len=kv_offset,
    )

    b = first_bonus
    emitted = 1
    history = [first_bonus]
    cursor = 0

    while emitted < max_tokens:
        proposal: list[int] = []
        if use_hint:
            proposal, next_cursor = propose(history, hint, cursor, min(HINT_DRAFT_MAX, max_tokens - emitted))
        if len(proposal) >= 2:
            bs = len(proposal) + 1
            from_hint = True
        else:
            bs = m._mtp_next_block_size(draft_model, block_total, configured_block_total, max_tokens - emitted + 1)
            if bs <= 1:
                break
            from_hint = False

        verify = None
        try:
            if from_hint:
                draft_tokens = mx.array([proposal], dtype=token_dtype)
            else:
                draft_tokens = sampler_rng.draft_tokens(
                    draft_model.draft_block, b, hidden, None, bs, sampler, token_dtype,
                    **m._mtp_draft_kwargs(draft_model, greedy_sampling, sampler),
                )

            with mx.stream(m.generation_stream):
                verify_input = mx.concatenate([mx.array([[b]], dtype=token_dtype), draft_tokens], axis=1)
                verify = m._mtp_verify_target(
                    lm, verify_input, prompt_cache, sampler, sample_target_tokens=greedy_sampling,
                )
            accepted, new_tokens = m._mtp_acceptance_walk(
                lm, verify, draft_tokens, sampler, max_tokens - emitted,
                row_id=0, base_position=emitted,
            )
            sampler_rng.target_sampled(sync_draft=not m._sampler_supports_positioned_target(sampler))
            if from_hint:
                stats["rounds"] += 1
                stats["accepted"] += int(accepted)
                stats["drafted"] += bs - 1
                cursor = next_cursor - len(proposal) + int(accepted)
            else:
                m._record_speculative_round(draft_model, accepted, bs - 1)

            accept_verified = getattr(draft_model, "accept_verified_tokens", None)
            if callable(accept_verified):
                sampler_rng.draft_call(
                    accept_verified, verify.hidden, draft_tokens, accepted, new_tokens,
                    sampler, token_dtype,
                    **m._mtp_draft_kwargs(draft_model, greedy_sampling, sampler),
                )

            verify.commit(lm, prompt_cache, accepted, bs)
        except BaseException:
            if verify is not None:
                verify.abort()
            abort_draft = getattr(draft_model, "abort_draft_round", None)
            if callable(abort_draft):
                abort_draft()
            raise

        for tok in new_tokens:
            yield tok, None
            history.append(int(tok))
            emitted += 1
            if emitted >= max_tokens:
                return

        hidden = m._mtp_draft_hidden(lm, verify.hidden[:, accepted:accepted + 1, :])
        b = new_tokens[-1] if new_tokens else b

        next_shared_kv = m._slice_shared_kv_after_reject(verify.shared_kv_states, bs - (accepted + 1))
        kv_offset += accepted + 1
        draft_model.set_shared_kv(
            next_shared_kv, kv_offset,
            position=m._mtp_draft_position(kv_offset), kv_valid_len=kv_offset,
        )

        if emitted % 256 == 0:
            mx.clear_cache()


_hinted_mtp_rounds._livetr3_hinted = True  # type: ignore[attr-defined]
