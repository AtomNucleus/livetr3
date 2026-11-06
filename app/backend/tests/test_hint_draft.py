"""Drafting from the previous decode: matching, and an exact round loop."""
from types import SimpleNamespace

import mlx.core as mx
import pytest

import hint_draft
from hint_draft import propose


def test_propose_continues_after_the_matching_tail():
    hint = [1, 2, 3, 4, 5, 6, 7, 8]
    assert propose([9, 2, 3, 4], hint, 0, 3) == ([5, 6, 7], 7)


def test_propose_uses_a_shorter_tail_at_the_start():
    assert propose([1], [1, 2, 3], 0, 4) == ([2, 3], 3)


def test_propose_prefers_the_match_after_the_cursor():
    hint = [1, 2, 3, 10, 1, 2, 3, 20]
    assert propose([1, 2, 3], hint, 0, 1) == ([10], 4)
    assert propose([1, 2, 3], hint, 5, 1) == ([20], 8)


def test_propose_needs_a_match():
    assert propose([4, 5, 6], [1, 2, 3, 7], 0, 3) == ([], 0)
    assert propose([1, 2, 3], [], 0, 3) == ([], 0)


class FakeTarget:
    """Greedy target that always continues TRUE from the committed position."""

    def __init__(self, true):
        self.true = true
        self.position = 0
        self.blocks = []

    def verify(self, lm, verify_input, prompt_cache, sampler, sample_target_tokens):
        width = verify_input.shape[1]
        self.blocks.append(width)
        start = self.position
        targets = [self.true[min(start + 1 + j, len(self.true) - 1)] for j in range(width)]
        target = self

        class Verify:
            hidden = mx.zeros((1, width, 1))
            shared_kv_states = {}
            target_tokens = mx.array([targets])

            def commit(self, model, caches, accepted, block_size):
                target.position += int(accepted) + 1

            def abort(self):
                pass

        return Verify()


@pytest.fixture
def fake_mtp(monkeypatch):
    from mlx_vlm.speculative import mtp as m

    true = [5, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]
    target = FakeTarget(true)
    monkeypatch.setattr(m, "_dflash_block_total", lambda draft, size: 3)
    monkeypatch.setattr(m, "_mtp_cache_offset_max", lambda cache: 0)
    monkeypatch.setattr(m, "_mtp_draft_hidden", lambda lm, hidden: hidden)
    monkeypatch.setattr(m, "_mtp_draft_kwargs", lambda *args: {})
    monkeypatch.setattr(m, "_sampler_supports_positioned_target", lambda sampler: False)
    monkeypatch.setattr(m, "_mtp_next_block_size", lambda draft, total, configured, remaining: min(3, remaining))
    monkeypatch.setattr(m, "_mtp_verify_target", target.verify)
    drafter = SimpleNamespace(
        config=SimpleNamespace(block_size=3),
        accept_lens=[],
        reset=lambda model: [],
        set_shared_kv=lambda *args, **kwargs: None,
        # A useless drafter: every MTP round accepts nothing.
        draft_block=lambda b, hidden, cache, size, sampler, dtype: mx.array([[0] * (size - 1)]),
    )
    return true, target, drafter


def run(true, drafter, hint, monkeypatch):
    monkeypatch.setattr(hint_draft, "_hint", tuple(hint))
    rounds = hint_draft._hinted_mtp_rounds(
        SimpleNamespace(), drafter, [], mx.zeros((1, 4, 1)), {},
        first_bonus=true[0], max_tokens=len(true), sampler=lambda logits: logits,
        greedy_sampling=True,
    )
    return [true[0]] + [token for token, _ in rounds]


def test_hint_rounds_emit_exactly_the_target_sequence(fake_mtp, monkeypatch):
    true, target, drafter = fake_mtp
    # The previous decode heard less audio and ended differently.
    hint = true[:9] + [99, 98]
    assert run(true, drafter, hint, monkeypatch) == true
    assert max(target.blocks) > 3  # the hint drafted more than MTP's block


def test_without_a_hint_the_loop_matches_mtp(fake_mtp, monkeypatch):
    true, target, drafter = fake_mtp
    assert run(true, drafter, [], monkeypatch) == true
    assert set(target.blocks) <= {2, 3}


def test_a_wrong_hint_cannot_change_the_output(fake_mtp, monkeypatch):
    true, target, drafter = fake_mtp
    hint = [5, 10, 11, 40, 41, 42, 43, 12, 13, 50]
    assert run(true, drafter, hint, monkeypatch) == true
