# Herald

Live translated captions for a speaker at the mic. It's built for sermons and talks,
and it runs entirely on one Mac.

Herald used to be called LiveTR3, and that name is still used inside the code: the
Swift package, the executable and process (`LiveTR3`), the bundle ID
(`com.livetr3.mac`), settings keys and the data folders. That way settings and saved
sessions carry over.

The operator window shows what was said and its translation as they come in. A
second window puts large, easy-to-read captions on a projector or screen for the
room. Speech recognition and translation run locally on Apple Silicon. Nothing goes
to the cloud, and once the models are downloaded the app works offline.

- **Languages:** English, Spanish, French, German, Italian, Portuguese, Japanese,
  Korean, Mandarin and Arabic, in either direction. The default is English to Spanish.
  Right-to-left and unspaced scripts are supported on the projector.
- **Speed:** a final caption takes about 1.3 s median (2.4 s p95) after the speaker
  stops, with draft captions updating about every 250 ms while they talk.
- **Accuracy:** about 4.7% word error rate and 55.5 chrF++ on the replay scoreboard
  (FLEURS and recorded sermon clips).
- **Projector:** Roll-up, Split and Stack layouts with paged text, and fullscreen on
  any display.
- **Operator:** a pill transport bar with a session clock, a live level meter,
  pause (which ends the current line), an optional swear-word filter, and TXT, SRT
  and VTT transcript export.

## How it works

```
Mic ─► AVAudioEngine ─► 16 kHz mono PCM ─► Unix socket ─► Python engine (MLX)
                                                          │  Silero VAD splits utterances
                                                          │  Gemma transcribes + translates
SwiftUI operator window ◄─── partials + finals ◄──────────┘
SwiftUI projector window ◄── paced presentation
```

- **`macos/LiveTR3Mac`**: the native SwiftUI app (Swift package, macOS 14+). It
  captures audio, starts the engine and draws the operator and projector windows.
- **`app/backend`**: the Python engine. One Gemma call (`mlx-community/gemma-4-e4b-it-8bit`)
  does transcription and translation together, sped up with a multi-token-prediction
  assistant model. It talks to the app over a Unix socket (`uds_host.py`).

[app/README.md](app/README.md) has the full caption path: segmenting, partials,
finals and retries.

## Requirements

- An Apple Silicon Mac on macOS 14 or later. It's tuned on an M1 Pro with 32 GB.
- Xcode command-line tools (Swift 5.10+)
- Python 3.13 and [`uv`](https://docs.astral.sh/uv/)
- These models in the Hugging Face cache. The app loads models offline, so download
  them once while you're online:
  - `mlx-community/gemma-4-e4b-it-8bit`
  - `mlx-community/gemma-4-E4B-it-assistant-bf16`

## Build and run

```sh
cd app/backend && uv sync --extra test && cd ../..
./script/build_and_run.sh --verify
```

This builds a release app at `dist/Herald.app` and opens it. The development
bundle runs the engine from this checkout's `app/backend`. To build a standalone
app that can be moved to another Mac, use `script/package_share_app.py`.

**Where things are kept**

| What | Where |
|---|---|
| Session archives (captions, timings) | `~/Library/Application Support/LiveTR3/sessions/` |
| Engine log (dev build) | `dist/logs/backend-runtime.log` |
| Engine socket | `~/Library/Application Support/LiveTR3/Runtime/` |

## Checks

Speed and accuracy are protected. A change must not slow captions or make them
worse. [CLAUDE.md](CLAUDE.md) has the rules and the baselines.

| When | Command | Time |
|---|---|---|
| Every edit | `./script/quick_check.sh` | about 10 s |
| Before a PR with UI changes | `./script/ui_perf_check.py` (quit Herald first) | about 4 min |
| Before a PR with engine changes | `./script/validate.sh` and `python3 -I script/scoreboard.py` | longer |

`ui_perf_check.py` replays a recorded sermon clip through the whole app, comparing
the installed app with your branch. It reports app CPU and caption latency for both.
CI runs the backend tests and the Swift build and tests on every push.

To get back to the last known-good speed and accuracy, check out the
`known-good-2026-11-06` tag.

## Repository layout

```
macos/LiveTR3Mac/   SwiftUI app and its unit tests
app/backend/        Python engine, segmenter, socket host, tests, soak scripts
app/docs/           Validation notes, projector design, HIG findings
script/             Build, packaging, quick checks, replay and scoring tools
dist/               Build output and eval data (not in git)
```
