# Engine preload and 30-minute idle unload — 2026-10-27

**A Stop and Start across a pause no longer reloads Gemma.** A real-model reproduction of the Oct 8 live glitch:

- **Main:** the engine unloaded the worker 45 s after the producer disconnected. The next Start waited for a reload. Its first final queued 10.48 s, and the two finals behind it queued 5.00 s and 2.98 s.
- **This branch:** the same sequence kept the same worker process. After the gap no final queued more than 0.06 s, and the first final came 5.5 s after connecting instead of 16.1 s.

The engine also loads Gemma as soon as it opens its socket. So the first Start after the app opens no longer waits for a load, provided it comes after the load finishes (15–18 s here). The first-final queue for that Start was 14.22 s on main and 0.00 s on the branch.

The cost: an open LiveTR3 app now holds a loaded worker, about 9.6 GB physical footprint on this 32 GB M1 Pro, from launch until 30 minutes pass without a producer.

## What changed

- `app/backend/uds_host.py`:
  - After printing `engine_ready`, `EngineHost.start()` starts `worker.start()` as a background task. Neither the socket nor the ready line waits for it, and the app still only waits for the socket file.
  - A Start that arrives mid-load joins that load through the worker's `_start_lock` instead of starting a second one. A client that connects mid-load gets "starting", then "ready".
  - If the preload fails, the host prints `worker_preload_failed` and keeps serving. The worker reports "failed", and the next Start retries through `_schedule_worker_warmup`.
- Idle unload:
  - The default goes from 45 s to 1800 s. `MLX_WORKER_IDLE_UNLOAD_SECONDS` still overrides it, with the same 5 s minimum.
  - With no producer at all, the clock runs from engine start, so an unused preload is released 30 minutes after the app opens.
- `CaptureActivity.swift` and `SessionController.swift`:
  - Capture, live or file replay, holds a `[.userInitiated, .latencyCritical]` activity from Start until Stop.
  - A Start that fails goes through `stop()`, which ends the activity. Teardown ends it in `deinit`.
  - Pause and reconnects keep the activity, since capture is still running.
- `LiveTR3Runtime.swift` launches the engine with `qualityOfService = .userInitiated`.
- The replay guards in `script/fleurs_replay.py` and `script/chunk_limit_replay.py` now say to quit LiveTR3. An open app holds a worker, and they refuse to run beside one.

## Reproduction

| Setting | Value |
| --- | --- |
| Model | `mlx-community/gemma-4-e4b-it-8bit` revision `4255b21bd9a9d3fc807ef7abd80373f5e3a52a73` |
| MTP drafter | `mlx-community/gemma-4-E4B-it-assistant-bf16` |
| Libraries | mlx 0.32.2, mlx-vlm 0.7.4 |
| Machine | M1 Pro, 32 GB |
| Code compared | `app/backend` from `origin/main` (`d2ee293`) and from this branch |

Each side got its own `uds_host.py` on an isolated socket, with its own archive, temp-WAV and trace paths. The two ran one after the other, with no other LiveTR3 worker loaded.

A driver acted like the app:

1. It connected 60 s after the socket appeared. The app opens the engine at launch, and the operator presses Start later.
2. It sent hello, the native default config, and Start.
3. It fed the first 15 s of sermon-v2 clip-05 plus 2 s of silence, in real time as 20 ms frames.
4. It waited for the finals to settle, sent Stop and disconnected.
5. It waited 60 s with no producer. Main's unload fires 45 s after the disconnect.
6. It reconnected with the same session id and repeated steps 2 to 4.

| Run | Worker when Start arrived | Status after connecting | "ready" after connecting (s) | Final `queue_seconds` (s) | First final after connecting (s) |
| --- | --- | --- | ---: | --- | ---: |
| main, first Start | none loaded | starting → ready | 18.4 | 14.22 / 8.76 / 6.76 | 19.8 |
| main, Start after 60 s idle | none: pid 25343 was unloaded in the gap | ready (stale) → starting → ready | 14.6 | 10.48 / 5.00 / 2.98 | 16.1 |
| branch, first Start | preloaded: pid 25745, loaded since engine start | ready | 0.8 | 0.00 / 0.18 / 0.06 | 5.6 |
| branch, Start after 60 s idle | the same pid 25745, kept through the gap | ready | 0.0 | 0.00 / 0.06 / 0.00 | 5.5 |

`queue_seconds` is the backend trace's `worker_dispatch` time from enqueue to dispatch, listed for each final in the round. Each round produced three finals with no errors. On the branch, "ready" was the first status message, so that column there only shows when the session first replied. Main's load took 18.4 s after the first Start and 14.6 s after the second.

The Oct 8 live log showed the same backlog pattern: 5.97 s for the first final, then 2.26 s and 0.37 s.

## Memory

| Process | Physical footprint | RSS |
| --- | ---: | ---: |
| Worker, after load | 9,622 MB (main), 9,623 MB (branch) | 5,372 MB (main), 4,413 MB (branch) |
| Host | 175 MB (main), 177 MB (branch) | — |

Both were read after the first round. The footprint comes from `footprint <pid>`. It counts Metal buffers that RSS misses, so it is the number that matters for the rest of the machine.

## Benchmarking now needs the app quit

An open LiveTR3 app now always holds a loaded worker: from launch, and for 30 minutes after the last Stop. The replay scripts refuse to run beside one (`competing_workers()`). Quit LiveTR3 before benchmarking. The guard messages now say so.

## Capture activity and QoS

**Activity.** `pmset -g assertions` listed `PreventUserIdleSystemSleep named: "Live caption capture"` while the activity was held, and nothing after it ended. This was checked with a small Swift program making the same `beginActivity` call, not in the app itself.

**QoS.** `Process.qualityOfService` does reach the engine and the MLX worker it spawns, but `.userInitiated` does not raise their priority. Thread priorities were read with `ps -M` for the host and its spawned worker:

| `qualityOfService` | Priority of every thread, host and worker |
| --- | ---: |
| unset | 31 |
| `.userInitiated` | 31 |
| `.utility` | 20 |
| `.background` | 4 |

From a command-line parent, `.userInitiated` measured the same as unset. Lower values lower every thread, so the setting behaves as a ceiling, not a boost. This was not tested with the GUI app as the parent, which would mean launching a second copy of the app beside the user's. `taskinfo`, which would show effective QoS directly, needs root.

## Tests

**Backend.** `uv run --extra test python -m pytest tests -q` gave 169 passed. That includes four new tests in `tests/test_engine_host.py`:

- A Start during the preload joins it. There is one load, the client sees starting → ready, and the socket exists during the load.
- A failed preload keeps the host serving, and the next Start retries and loads.
- An unused preload is released after the idle timeout, with no client ever connecting.
- The default is 1800 s, and the env override still works.

Linux CI skips this file, like the other tests that import MLX modules.

**Swift.** `swift test --package-path macos/LiveTR3Mac` ran 64 tests with 0 failures and 1 skipped (the opt-in `testRenderAudienceLayouts`). That includes the new `CaptureActivityTests`.

## Left as is

After an idle unload, the worker's status still reads "ready" until the next Start begins the reload. Main's second round saw "ready", then "starting". `MLXWorkerService.stop()` does not change the status, and the protocol has no unloaded state. With the 30-minute default, this now shows only after 30 idle minutes.

## Raw outputs

These stay local, in the ignored `dist/logs/idle-reload-2026-10-27/`:

- `main/` and `branch/`: summaries, client event logs, backend traces and host logs.
- `idle_reload.py`: the driver. `rounds.py` prints the per-round numbers above.
- `main-src/`: main's exported backend.
