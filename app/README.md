# LiveTR3

Local-first live transcription and translation for a mic'd speaker on an Apple Silicon Mac.

The app captures microphone audio in the browser, sends 16 kHz mono float32 PCM frames to a local FastAPI WebSocket server, segments speech locally, and runs Gemma 4 E4B through `mlx-vlm` on Metal. The original-language caption appears in the top pane and the translation appears in the bottom pane.

## Requirements

- Apple M1 Pro with 32 GB unified memory
- macOS 14+
- Python 3.13
- `uv`
- Node.js 20+ and `yarn`
- Enough free disk for the MLX model download. Expect roughly 8 GB for `mlx-community/gemma-4-e4b-it-8bit`, plus cache overhead.

No cloud service or external API is used by the app. Internet is only needed for dependency and model download.

## Install

From this directory:

```bash
brew install uv
npm install -g yarn
```

```bash
cd app/backend
uv sync
```

Then install the frontend dependencies:

```bash
cd ../frontend
yarn install
```

The model is downloaded by `mlx-vlm` the first time the backend or smoke test loads:

```bash
cd ../backend
uv run python smoke_ast.py /path/to/ten-second-16khz-mono.wav --source English --target Spanish
```

The first run downloads the model and compiles/primes Metal kernels. On the target M1 Pro, expect a longer first run for download and cache setup; subsequent cold model loads should be under about 30 seconds, and warmup inference should be under about 5 seconds once dependencies and model cache are present.

## Start

Backend:

```bash
cd app/backend
uv run uvicorn server:app --host 127.0.0.1 --port 8765
```

Frontend:

```bash
cd app/frontend
yarn dev
```

Open the Vite URL, usually `http://127.0.0.1:5173`, grant mic access, and press Start.

For projector mode, use the operator window's `Open Projector Window` button. That opens
`/projector?session=<token>` in a second window that mirrors the same backend session as a
read-only audience view.

## CLI Smoke Test

Before testing the live app, confirm MLX audio inference works with a short WAV:

```bash
cd app/backend
uv run python smoke_ast.py ./sample.wav --source English --target Spanish
```

Input must be 16 kHz mono WAV. Keep it under 10 seconds for the smoke test. The script prints:

```text
<original transcript>
Spanish: <translation>
```

## Prerecorded WebSocket Test

With the backend running:

```bash
cd app/backend
uv run python stream_wav_client.py ./sample.wav --source English --target Spanish
```

This sends the WAV as 20 ms little-endian float32 frames over `ws://127.0.0.1:8765/` and prints server JSON messages.

## Runtime Behavior

- Audio up: binary little-endian float32, 16 kHz, mono, 320 samples per 20 ms frame.
- Text down: JSON only.
- Config contract: `ConfigMessage.version = 2`.
- Shared sessions: producer and viewer sockets join the same session with `?session=<id>`.
- Viewer handshake: read-only clients send `{"type":"join_viewer"}` after connect.
- Segmentation: Silero VAD at 16 kHz with 512-sample VAD frames.
- Partial inference: every about 2 seconds while speech is active by default, configurable per session.
- Final inference: on Silero utterance end or at the configured max-utterance cap.
- Context: last two committed utterances are inserted as text-only prior context.
- Custom vocabulary: injected before the AST prompt per session.
- Code-switch mode: optional prompt hint to let the model handle source/target language switching within one utterance.
- Polish pass: optional text-only cleanup after final output.
- MLX execution: single model worker with an `asyncio.PriorityQueue`; final jobs outrank partial jobs.
- Worker recovery: AST/final/polish jobs have configurable timeouts, and the model worker is reloaded after timeouts or fatal inference crashes.
- Maintenance: MLX cache clear + Silero reset run periodically by time or utterance count.
- Mid-session controls: pause/resume capture, commit-now flush, skip-next-polish, queued language-direction swap, and live mic hot-swap.
- Reconnect/resume: the operator client reconnects to the same session token and restores the utterance counter when the backend stays alive.

## Latency Expectations

On an M1 Pro with 32 GB RAM:

- Finalized caption latency after a pause: target under 3 seconds for typical 15 second utterances.
- Partial cadence: about every 2 seconds during speech.
- Model load: target under 30 seconds after the model is already downloaded.
- Warmup: target under 5 seconds after model cache exists.
- Sustained use: intended for 60 minute talks without raw audio persistence.

Actual latency depends on speech length, selected languages, thermal state, and whether polish is enabled. Disable polish for the lowest final-caption latency.

## Silero VAD

Silero VAD is the active segmenter for this build. RMS segmentation is not used as a fallback. The backend config is:

```json
{"type":"config","segmenter":"silero"}
```

The backend dependency list includes `silero-vad`. If Silero cannot load, the server sends an error instead of switching to another segmenter.

If captions start too late or cut off, adjust mic gain/placement first. Then tune the Silero parameters in `backend/segmenter.py`:

- probability threshold: default `0.5`
- speech pad: default `300 ms`
- min silence: default `400 ms`

The `level` WebSocket message still reports a loudness value named `rms` for the waveform meter. That value is not used to decide speech boundaries in this Silero-only build.

## Exports

The TXT, SRT, and VTT buttons download:

- `livetr3-transcript.txt`
- `livetr3-transcript.srt`
- `livetr3-transcript.vtt`

Keyboard shortcuts:

- Space: start/stop when focus is not in a form control
- Cmd+E: export TXT
- Cmd+,: open/close settings

## Projector View

- Route: `/projector?session=<id>`
- Transport: the operator window keeps the producer WebSocket; projector windows join as read-only viewers.
- Content: target-language captions only, with the last two utterances auto-fit to the largest readable font that fits the screen.
- Font control: the operator slider updates projector font size live across windows.

## Session Archive

Each started session is autosaved every 60 seconds and finalized on stop/disconnect under:

```text
~/Library/Application Support/LiveTR3/sessions/<ISO timestamp>/
```

Files written:

- `transcript.srt`
- `transcript.vtt`
- `transcript.json`
- `meta.json`

## Offline Use

After `uv sync`, `yarn install`, and the first successful model load, turn Wi-Fi off and start both local servers. The app uses only local WebSocket traffic and local MLX inference.

## Privacy

The backend keeps audio in memory and writes only short-lived temporary WAV files for the current inference call because `mlx-vlm` expects audio paths. Temp files are deleted immediately after generation, placed under a managed LiveTR3 temp directory, and stale files are swept periodically. Raw audio is not stored between chunks.
