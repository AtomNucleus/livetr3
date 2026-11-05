import asyncio
import sys
from types import SimpleNamespace

import mlx.core as mx
import mlx.nn as nn
import numpy as np
import pytest

import mlx_worker
from mlx_worker import GenerationCancelled, MLXWorker, MLXWorkerService, _install_cancel_hook
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
    calls, armed, flag = [], [], [False]
    def generate(*args, **kwargs):
        calls.append(kwargs)
        armed.append(worker._generation_cancelled)
        flag[0] = True  # the cancel arrives mid-prefill and the hook raises
        raise GenerationCancelled
        yield
    sys.modules["mlx_vlm"].stream_generate = generate
    worker = _worker(tmp_path)
    draft = worker._draft_model = object()
    cancelled = lambda: flag[0]
    assert worker.ast(np.ones(16000), "English", "Spanish", [], priority="partial",
                      cancelled=cancelled) is None
    assert armed == [cancelled] and worker._generation_cancelled is None
    assert worker._draft_model is draft and len(calls) == 1
    assert not list(tmp_path.glob("*.wav"))


def test_early_final_prefills_in_chunks_and_a_cancel_skips_the_retry(monkeypatch, tmp_path):
    # The early pause decode is a final the session can still drop when speech resumes.
    monkeypatch.setattr(mlx_worker, "CANCELLABLE_PREFILL_CHUNK", 32)
    _patch_mlx(monkeypatch, [])
    calls, flag = [], [False]
    def generate(*args, **kwargs):
        calls.append(kwargs)
        flag[0] = True  # speech resumes mid-prefill
        raise GenerationCancelled
        yield
    sys.modules["mlx_vlm"].stream_generate = generate
    worker = _worker(tmp_path)
    draft = worker._draft_model = object()
    assert worker.ast(np.ones(16000), "English", "Spanish", [], priority="final",
                      cancelled=lambda: flag[0]) is None
    assert [call.get("prefill_step_size") for call in calls] == [32]
    assert worker._draft_model is draft


def _ast_job(worker, priority, **extra):
    return asyncio.create_task(worker.submit_ast(
        priority=priority, utterance_id=7, audio_f32_16k=np.ones(16000, dtype=np.float32),
        src="English", tgt="Spanish", prior_context=[], custom_vocab=[],
        code_switching_enabled=False, max_tokens=128, **extra,
    ))


@pytest.mark.parametrize("early", [True, False])
def test_only_the_early_final_is_dispatched_cancellable(early):
    async def run():
        worker = MLXWorkerService()
        requests = []
        worker._request_queue = SimpleNamespace(put=requests.append)
        worker._response_queue = object()
        worker._process = SimpleNamespace(is_alive=lambda: True)
        async def respond(job, timeout_seconds):
            return {"type": "result", "job_id": job.sequence, "result": None}
        worker._wait_for_worker_response = respond
        runner = asyncio.create_task(worker._run())
        assert await _ast_job(worker, "final", early=early) is None
        runner.cancel()
        assert requests[0]["cancellable"] is early
    asyncio.run(run())


def test_cancelled_early_final_frees_the_worker_and_keeps_its_timing(monkeypatch):
    async def run():
        traced = []
        monkeypatch.setattr(mlx_worker, "trace", lambda stage, **fields: traced.append((stage, fields)))
        worker = MLXWorkerService()
        started = asyncio.Event()
        async def execute(job):
            started.set()
            while worker._cancelled_job_id.value != job.sequence:
                await asyncio.sleep(0.001)
            return None  # the child stops at the next prefill chunk
        worker._execute_job = execute
        runner = asyncio.create_task(worker._run())
        timing = {}
        early = _ast_job(worker, "final", early=True, timing=timing)
        await started.wait()
        worker.cancel_early_final(7)
        assert await early is None
        runner.cancel()
        [free] = [fields for stage, fields in traced if stage == "worker_cancel_free"]
        assert free["priority"] == "final" and free["cancelled_result"]
        assert set(timing) == {"queue_seconds", "inference_seconds"}
        assert 7 not in worker._early_jobs and not worker._cancel_requested_at
    asyncio.run(run())
