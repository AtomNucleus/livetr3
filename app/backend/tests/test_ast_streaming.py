import sys
from types import SimpleNamespace
from types import ModuleType
import asyncio

import numpy as np
import pytest

from mlx_worker import (
    ASTResult,
    AST_MAX_AUDIO_SECONDS,
    MLXWorker,
    MLXWorkerService,
    _generation_was_truncated,
    _parse_ast_response,
    _streaming_ast_progress_text,
)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("I cannot go\nSpanish: No puedo ir", ("I cannot go", "No puedo ir")),
        (
            "English: I cannot carry nine boxes\n**Translation (Spanish):** "
            "No puedo llevar nueve cajas",
            ("I cannot carry nine boxes", "No puedo llevar nueve cajas"),
        ),
        ("One two three\nSpanish - Uno dos tres", ("One two three", "Uno dos tres")),
        ("One two\nSpanish\nUno dos", ("One two", "Uno dos")),
    ],
)
def test_ast_parser_accepts_small_label_format_variants(response, expected):
    assert _parse_ast_response(response, "Spanish", "English") == expected


@pytest.mark.parametrize(
    "source",
    [
        "Spanish-speaking people arrived.",
        "Spanish",
        "Spanish\nis the language I speak.",
        "We cannot go\nS",
        "We cannot go\nSp",
        "We cannot go\nSpa",
        "I speak\nSpanish",
        "We cannot go\nTranslation (Spa",
    ],
)
def test_ast_parser_preserves_source_text_that_only_resembles_a_label(source):
    assert _parse_ast_response(source, "Spanish", "English") == (source, "")


@pytest.mark.parametrize("word", ["S", "Sp", "Spa", "Spanish"])
def test_final_parser_preserves_short_spoken_words_before_translation(word):
    assert _parse_ast_response(
        f"{word}\nSpanish: {word}", "Spanish", "English"
    ) == (word, word)


@pytest.mark.parametrize(
    "partial_label",
    [
        "S",
        "Sp",
        "Spa",
        "- S",
        "- Sp",
        "- Spa",
        "**S",
        "**Sp",
        "**Spa",
        "Translation (S",
        "Translation (Sp",
        "Translation (Spa",
        "- **Translation (S",
        "**Translation (Sp",
    ],
)
def test_streaming_parser_hides_progressive_target_label_prefixes(partial_label):
    response = f"We cannot go\n{partial_label}"

    assert _parse_ast_response(
        response, "Spanish", "English", streaming=True
    ) == ("We cannot go", "")
    assert _streaming_ast_progress_text(response, "Spanish", "English") == (
        "We cannot go"
    )


def test_streaming_parser_keeps_a_source_only_short_transcript_without_label_boundary():
    assert _parse_ast_response("S", "Spanish", "English", streaming=True) == (
        "S",
        "",
    )
    assert _streaming_ast_progress_text("Sp", "Spanish", "English") == "Sp"
    assert _parse_ast_response("Spanish", "Spanish", "English", streaming=True) == (
        "Spanish",
        "",
    )
    assert _streaming_ast_progress_text("Spanish", "Spanish", "English") == "Spanish"


def test_streaming_progress_canonicalizes_completed_translation():
    assert _streaming_ast_progress_text(
        "English: We cannot go\n**Translation (Spanish):** No podemos ir",
        "Spanish",
        "English",
    ) == "We cannot go\nSpanish: No podemos ir"


@pytest.mark.parametrize(
    ("metadata", "truncated"),
    [
        ({"generation_tokens": 384, "finish_reason": "stop"}, False),
        ({"generation_tokens": 385, "finish_reason": "STOP"}, False),
        ({"generation_tokens": 383, "finish_reason": "stop"}, False),
        ({"generation_tokens": 20, "finish_reason": "length"}, True),
        ({"generation_tokens": 20, "finish_reason": "max_tokens"}, True),
        ({"generation_tokens": 20, "finish_reason": "token_limit"}, True),
        ({"generation_tokens": 384}, True),
        ({"generation_tokens": 384, "finish_reason": None}, True),
        ({"generation_tokens": 383}, False),
    ],
)
def test_generation_completion_uses_token_limit_and_finish_reason(metadata, truncated):
    assert _generation_was_truncated(SimpleNamespace(**metadata), 384) is truncated


def _worker(tmp_path):
    worker = object.__new__(MLXWorker)
    worker._temp_wav_root = tmp_path
    worker.model = worker.processor = worker.config = object()
    return worker


def _patch_mlx(monkeypatch, streams):
    budgets = []
    stream_iterator = iter(streams)

    mlx_vlm = ModuleType("mlx_vlm")
    prompt_utils = ModuleType("mlx_vlm.prompt_utils")

    def stream_generate(*args, **kwargs):
        budgets.append(kwargs["max_tokens"])
        return iter(next(stream_iterator))

    mlx_vlm.stream_generate = stream_generate
    prompt_utils.apply_chat_template = lambda *args, **kwargs: "formatted"
    mlx_vlm.prompt_utils = prompt_utils
    monkeypatch.setitem(sys.modules, "mlx_vlm", mlx_vlm)
    monkeypatch.setitem(sys.modules, "mlx_vlm.prompt_utils", prompt_utils)
    return budgets


def test_ast_streams_source_then_translation_and_returns_complete_result(
    monkeypatch, tmp_path
):
    pieces = [
        SimpleNamespace(text="We cannot go", generation_tokens=3, finish_reason=None),
        SimpleNamespace(
            text="\nSpanish: No podemos ir",
            generation_tokens=9,
            finish_reason="stop",
        ),
    ]
    budgets = _patch_mlx(monkeypatch, [pieces])
    progress = []
    result = _worker(tmp_path).ast(
        np.ones(16_000, dtype=np.float32),
        "English",
        "Spanish",
        prior_context=[],
        max_tokens=192,
        priority="partial",
        on_progress=progress.append,
    )

    assert result == ASTResult("We cannot go", "No podemos ir", True, False)
    assert budgets == [192]
    assert progress == ["We cannot go", "We cannot go\nSpanish: No podemos ir"]


def test_truncated_final_retries_once_with_bounded_budget(monkeypatch, tmp_path):
    first = [
        SimpleNamespace(
            text="We cannot go\nSpanish: No podemos ir",
            generation_tokens=100,
            finish_reason="length",
        )
    ]
    second = [
        SimpleNamespace(
            text="We cannot go\nSpanish: No podemos ir",
            generation_tokens=20,
            finish_reason="stop",
        )
    ]
    budgets = _patch_mlx(monkeypatch, [first, second])
    result = _worker(tmp_path).ast(
        np.ones(16_000, dtype=np.float32),
        "English",
        "Spanish",
        prior_context=[],
        max_tokens=100,
        priority="final",
    )

    assert result == ASTResult("We cannot go", "No podemos ir", True, False)
    assert budgets == [100, 200]


def test_partial_ast_cancellation_closes_stream_and_returns_no_result(monkeypatch, tmp_path):
    cancelled = [False]
    closed = []

    def stream_generate(*args, **kwargs):
        try:
            yield SimpleNamespace(text="We can", generation_tokens=1)
            cancelled[0] = True
            yield SimpleNamespace(text=" go", generation_tokens=2)
        finally:
            closed.append(True)

    _patch_mlx(monkeypatch, [])
    mlx_vlm = sys.modules["mlx_vlm"]
    mlx_vlm.stream_generate = stream_generate
    result = _worker(tmp_path).ast(
        np.ones(16_000, dtype=np.float32),
        "English",
        "Spanish",
        prior_context=[],
        max_tokens=192,
        priority="partial",
        cancelled=lambda: cancelled[0],
    )

    assert result is None
    assert closed == [True]


def test_ast_rejects_audio_over_documented_limit_instead_of_trimming(tmp_path):
    worker = _worker(tmp_path)
    with pytest.raises(ValueError, match="30-second clip limit"):
        worker.ast(
            np.zeros((AST_MAX_AUDIO_SECONDS + 1) * 16_000, dtype=np.float32),
            "English",
            "Spanish",
            prior_context=[],
        )


def test_finish_partials_cancels_active_combined_ast_preview_only_for_same_utterance():
    worker = MLXWorkerService()
    worker._active_job = SimpleNamespace(
        kind="ast", sequence=17, payload={"priority": "partial", "utterance_id": 4}
    )

    worker.finish_partials(3)
    assert worker._cancelled_job_id.value == -1
    worker.finish_partials(4)
    assert worker._cancelled_job_id.value == 17

    worker._active_job = SimpleNamespace(
        kind="ast", sequence=18, payload={"priority": "final", "utterance_id": 5}
    )
    worker.finish_partials(5)
    assert worker._cancelled_job_id.value == 17


def test_service_forwards_streamed_ast_progress_before_final_result():
    class ResponseQueue:
        responses = iter(
            [
                {"type": "progress", "job_id": 12, "text": "We cannot"},
                {"type": "result", "job_id": 12, "result": "complete"},
            ]
        )

        def get(self, *args, **kwargs):
            return next(self.responses)

    async def run():
        worker = MLXWorkerService()
        worker._response_queue = ResponseQueue()
        worker._process = SimpleNamespace(is_alive=lambda: True)
        progress = []

        async def on_progress(text):
            progress.append(text)

        response = await worker._wait_for_worker_response(
            SimpleNamespace(sequence=12, on_progress=on_progress),
            timeout_seconds=1.0,
        )
        assert response == {"type": "result", "job_id": 12, "result": "complete"}
        assert progress == ["We cannot"]

    asyncio.run(run())


@pytest.mark.parametrize("label", ["Spanish:", "- Spanish:", "**Translation (Spanish):**"])
def test_ast_stream_progress_does_not_publish_partial_target_label_prefixes(
    monkeypatch, tmp_path, label
):
    pieces = [
        SimpleNamespace(text="We cannot go", generation_tokens=3, finish_reason=None),
        *[SimpleNamespace(text=char) for char in "\n" + label],
        SimpleNamespace(
            text=" No podemos ir",
            generation_tokens=40,
            finish_reason="stop",
        ),
    ]
    _patch_mlx(monkeypatch, [pieces])
    progress = []

    result = _worker(tmp_path).ast(
        np.ones(16_000, dtype=np.float32),
        "English",
        "Spanish",
        prior_context=[],
        max_tokens=192,
        priority="partial",
        on_progress=progress.append,
    )

    assert result == ASTResult("We cannot go", "No podemos ir", True, False)
    assert progress == ["We cannot go", "We cannot go\nSpanish: No podemos ir"]


def test_stop_at_exact_token_budget_does_not_retry(monkeypatch, tmp_path):
    stream = [
        SimpleNamespace(
            text="We cannot go\nSpanish: No podemos ir",
            generation_tokens=100,
            finish_reason="stop",
        )
    ]
    budgets = _patch_mlx(monkeypatch, [stream])

    result = _worker(tmp_path).ast(
        np.ones(16_000, dtype=np.float32),
        "English",
        "Spanish",
        prior_context=[],
        max_tokens=100,
        priority="final",
    )

    assert result == ASTResult("We cannot go", "No podemos ir", True, False)
    assert budgets == [100]


def test_long_final_retry_stays_inside_the_768_token_cap(monkeypatch, tmp_path):
    first = [
        SimpleNamespace(
            text="We cannot go\nSpanish: No podemos ir",
            generation_tokens=640,
            finish_reason="length",
        )
    ]
    second = [
        SimpleNamespace(
            text="We cannot go\nSpanish: No podemos ir",
            generation_tokens=32,
            finish_reason="stop",
        )
    ]
    budgets = _patch_mlx(monkeypatch, [first, second])

    result = _worker(tmp_path).ast(
        np.ones(29 * 16_000, dtype=np.float32),
        "English",
        "Spanish",
        prior_context=[],
        max_tokens=640,
        priority="final",
    )

    assert result == ASTResult("We cannot go", "No podemos ir", True, False)
    assert budgets == [640, 768]
    assert sum(budgets) == 1_408


@pytest.mark.parametrize(
    ("text", "reason", "expected"),
    [
        (
            "We cannot go\nSpanish: No podemos",
            "length",
            ASTResult("We cannot go", "No podemos", False, True),
        ),
        ("We cannot go", "stop", ASTResult("We cannot go", "", False, False)),
    ],
)
def test_final_stays_incomplete_after_one_failed_retry(
    monkeypatch, tmp_path, text, reason, expected
):
    streams = [
        [SimpleNamespace(text=text, generation_tokens=budget, finish_reason=reason)]
        for budget in (100, 200)
    ]
    budgets = _patch_mlx(monkeypatch, streams)

    result = _worker(tmp_path).ast(
        np.ones(16_000, dtype=np.float32),
        "English",
        "Spanish",
        prior_context=[],
        max_tokens=100,
        priority="final",
    )

    assert result == expected
    assert budgets == [100, 200]


def test_truncated_partial_does_not_retry(monkeypatch, tmp_path):
    budgets = _patch_mlx(monkeypatch, [[SimpleNamespace(
        text="We cannot go\nSpanish: No podemos", generation_tokens=100, finish_reason="length"
    )]])

    result = _worker(tmp_path).ast(
        np.ones(16_000, dtype=np.float32),
        "English",
        "Spanish",
        prior_context=[],
        max_tokens=100,
        priority="partial",
    )

    assert result == ASTResult("We cannot go", "No podemos", False, True)
    assert budgets == [100]


@pytest.mark.parametrize('priority,reason,budgets_expected', [
    ('final', 'length', [100, 200]),
    ('partial', 'length', [100]),
    ('final', 'stop', [100]),
])
def test_mtp_keeps_greedy_audio_completion_and_retry_policy(
    monkeypatch, tmp_path, priority, reason, budgets_expected
):
    _patch_mlx(monkeypatch, [])
    calls, closed, progress = [], [], []
    draft = SimpleNamespace()
    def generate(*args, **kwargs):
        calls.append(kwargs)
        try:
            yield SimpleNamespace(text='We cannot go', generation_tokens=3)
            yield SimpleNamespace(text='\nSpanish: No podemos ir', generation_tokens=100,
                                  finish_reason=reason if len(calls) == 1 else 'stop')
        finally:
            closed.append(True)
    sys.modules['mlx_vlm'].stream_generate = generate
    worker = _worker(tmp_path)
    worker._draft_model = draft
    result = worker.ast(np.ones(16000), 'English', 'Spanish', [], max_tokens=100,
                        priority=priority, on_progress=progress.append)
    assert [call['max_tokens'] for call in calls] == budgets_expected
    assert all(call['draft_model'] is draft and call['draft_kind'] == 'mtp'
               and call['temperature'] == 0 and len(call['audio']) == 1 for call in calls)
    assert len(closed) == len(calls)
    assert progress[0] == 'We cannot go'
    assert progress[-1] == 'We cannot go\nSpanish: No podemos ir'
    assert result.complete is (priority == 'final' or reason == 'stop')
    assert not list(tmp_path.glob('*.wav'))


def test_mtp_failure_discards_failed_hypothesis_disables_candidate_and_bounds_fallback(
    monkeypatch, tmp_path
):
    _patch_mlx(monkeypatch, [])
    calls, closed = [], []
    def generate(*args, **kwargs):
        calls.append(kwargs)
        try:
            if 'draft_model' in kwargs:
                yield SimpleNamespace(text='Incorrect partial', generation_tokens=1)
                raise ValueError('packed embedding cannot reshape')
            yield SimpleNamespace(text='We cannot go\nSpanish: No podemos ir',
                                  generation_tokens=100, finish_reason='length')
        finally:
            closed.append(True)
    sys.modules['mlx_vlm'].stream_generate = generate
    worker = _worker(tmp_path)
    worker._draft_model = object()
    result = worker.ast(np.ones(16000), 'English', 'Spanish', [], max_tokens=100)
    assert [call['max_tokens'] for call in calls] == [100, 100, 200]
    assert ['draft_model' in call for call in calls] == [True, False, False]
    assert worker._draft_model is None
    assert result.original == 'We cannot go'
    assert not result.complete and result.truncated
    assert len(closed) == 3
    assert not list(tmp_path.glob('*.wav'))


def test_mtp_cancellation_closes_stream_without_fallback(monkeypatch, tmp_path):
    _patch_mlx(monkeypatch, [])
    calls, closed, cancelled = [], [], [False]
    def generate(*args, **kwargs):
        calls.append(kwargs)
        try:
            yield SimpleNamespace(text='We cannot', generation_tokens=1)
            cancelled[0] = True
            yield SimpleNamespace(text=' go', generation_tokens=2)
        finally:
            closed.append(True)
    sys.modules['mlx_vlm'].stream_generate = generate
    worker = _worker(tmp_path)
    draft = worker._draft_model = object()
    assert worker.ast(np.ones(16000), 'English', 'Spanish', [],
                      cancelled=lambda: cancelled[0]) is None
    assert worker._draft_model is draft
    assert len(calls) == len(closed) == 1
    assert not list(tmp_path.glob('*.wav'))


@pytest.mark.parametrize('enabled,compatible', [(False, True), (True, True), (True, False)])
def test_mtp_load_is_opt_in_and_incompatibility_preserves_target(
    monkeypatch, tmp_path, enabled, compatible
):
    _patch_mlx(monkeypatch, [])
    target = SimpleNamespace(config=object())
    sys.modules['mlx_vlm'].load = lambda path: (target, object())
    module = ModuleType('mlx_vlm.speculative.drafters')
    draft, loads = object(), []
    def load(path, kind):
        loads.append(path)
        return draft, kind
    def validate(*args):
        if not compatible:
            raise ValueError('wrong architecture')
    module.load_drafter = load
    module.validate_drafter_compatibility = validate
    monkeypatch.setitem(sys.modules, 'mlx_vlm.speculative.drafters', module)
    monkeypatch.setenv('LIVETR3_GEMMA_MTP', '1' if enabled else '0')
    monkeypatch.setattr(MLXWorker, '_warmup', lambda self: None)
    worker = MLXWorker(tmp_path)
    assert worker.model is target
    assert len(loads) == int(enabled)
    assert worker._draft_model is (draft if enabled and compatible else None)


def test_mtp_does_not_treat_progress_callback_failure_as_decoder_failure(monkeypatch, tmp_path):
    _patch_mlx(monkeypatch, [[SimpleNamespace(text='We cannot', generation_tokens=1)]])
    worker = _worker(tmp_path)
    draft = worker._draft_model = object()
    def broken_callback(text):
        raise RuntimeError('consumer stopped')
    with pytest.raises(RuntimeError, match='consumer stopped'):
        worker.ast(np.ones(16000), 'English', 'Spanish', [], on_progress=broken_callback)
    assert worker._draft_model is draft
    assert not list(tmp_path.glob('*.wav'))
