import asyncio
import importlib
import json
import shutil
import tempfile
from pathlib import Path

import pytest

import session
import uds_host
from mlx_worker import WorkerStatusEvent
from transport import FRAME_TEXT, HEADER


def fake_loads(host, outcomes):
    """Replace the model load: each call follows the next outcome once released."""
    calls = []
    release = asyncio.Event()

    async def load():
        calls.append(outcomes[len(calls)])
        await host.worker._emit_status(WorkerStatusEvent(state="starting", message="Loading"))
        await release.wait()
        if calls[-1] == "fail":
            raise RuntimeError("load failed")
        await host.worker._emit_status(WorkerStatusEvent(state="ready", message="Ready"))

    host.worker._start_worker_process = load
    return calls, release


def count_starts(host):
    starts = []
    start = host.worker.start

    async def counted():
        starts.append(1)
        await start()

    host.worker.start = counted
    return starts


async def connect_and_start(socket_path):
    reader, writer = await asyncio.open_unix_connection(str(socket_path))
    for payload in ({"type": "hello", "session": "host-test"}, {"type": "start"}):
        data = json.dumps(payload).encode()
        writer.write(HEADER.pack(FRAME_TEXT, len(data)) + data)
    await writer.drain()
    return reader, writer


async def next_status(reader):
    while True:
        frame_type, length = HEADER.unpack(await reader.readexactly(HEADER.size))
        payload = json.loads(await reader.readexactly(length))
        if frame_type == FRAME_TEXT and payload.get("type") == "status":
            return payload["state"]


async def wait_for(condition):
    async with asyncio.timeout(5):
        while not condition():
            await asyncio.sleep(0.01)


@pytest.fixture
def socket_path():
    # macOS caps AF_UNIX paths at 104 bytes, shorter than pytest's tmp_path.
    root = Path(tempfile.mkdtemp(prefix="lt3-", dir="/tmp"))
    yield root / "engine.sock"
    shutil.rmtree(root, ignore_errors=True)


def isolate_session_files(monkeypatch, tmp_path):
    monkeypatch.setattr(session, "ARCHIVE_ROOT", tmp_path / "sessions")
    monkeypatch.setattr(session, "LEARNING_PROFILE_PATH", tmp_path / "profile.json")


def test_start_during_preload_joins_it_instead_of_loading_again(monkeypatch, tmp_path, socket_path):
    isolate_session_files(monkeypatch, tmp_path)

    async def run():
        host = uds_host.EngineHost()
        calls, release = fake_loads(host, ["ready"])
        starts = count_starts(host)
        serving = asyncio.create_task(host.start(socket_path))
        try:
            await wait_for(lambda: calls)
            assert socket_path.exists()  # The socket does not wait for the load.
            reader, writer = await connect_and_start(socket_path)
            assert await next_status(reader) == "starting"
            await wait_for(lambda: len(starts) == 2)  # Preload, then the Start warmup.
            release.set()
            assert await asyncio.wait_for(next_status(reader), 5) == "ready"
            await wait_for(lambda: host.worker._started)
            assert calls == ["ready"]
            writer.close()
        finally:
            host.stop()
            await asyncio.wait_for(serving, 5)

    asyncio.run(run())


def test_failed_preload_keeps_the_host_and_start_retries(monkeypatch, tmp_path, socket_path, capsys):
    isolate_session_files(monkeypatch, tmp_path)

    async def run():
        host = uds_host.EngineHost()
        calls, release = fake_loads(host, ["fail", "ready"])
        release.set()
        serving = asyncio.create_task(host.start(socket_path))
        try:
            await wait_for(lambda: host.worker.status.state == "failed")
            assert not serving.done()
            reader, writer = await connect_and_start(socket_path)
            states = [await asyncio.wait_for(next_status(reader), 5) for _ in range(3)]
            assert states == ["failed", "starting", "ready"]
            assert calls == ["fail", "ready"]
            writer.close()
        finally:
            host.stop()
            await asyncio.wait_for(serving, 5)

    asyncio.run(run())
    assert "worker_preload_failed" in capsys.readouterr().out


def test_unused_preload_is_released_after_the_idle_timeout(monkeypatch, socket_path):
    monkeypatch.setattr(uds_host, "IDLE_UNLOAD_SECONDS", 0.2)
    monkeypatch.setattr(uds_host, "IDLE_POLL_SECONDS", 0.05)

    async def run():
        host = uds_host.EngineHost()
        _, release = fake_loads(host, ["ready"])
        release.set()
        serving = asyncio.create_task(host.start(socket_path))
        try:
            await wait_for(lambda: host.worker._started)
            # No client ever connects: the idle clock runs from engine start.
            await wait_for(lambda: not host.worker._started)
        finally:
            host.stop()
            await asyncio.wait_for(serving, 5)

    asyncio.run(run())


def test_idle_unload_defaults_to_thirty_minutes(monkeypatch):
    monkeypatch.delenv("MLX_WORKER_IDLE_UNLOAD_SECONDS", raising=False)
    try:
        assert importlib.reload(uds_host).IDLE_UNLOAD_SECONDS == 1800
        monkeypatch.setenv("MLX_WORKER_IDLE_UNLOAD_SECONDS", "120")
        assert importlib.reload(uds_host).IDLE_UNLOAD_SECONDS == 120
    finally:
        monkeypatch.undo()
        importlib.reload(uds_host)
