# LiveTR3

Native macOS live transcription and translation. SwiftUI renders the operator and
projector windows, AVAudioEngine captures the microphone, and a local Python/MLX
engine communicates over a Unix socket. No browser or web server is needed for the
Mac app. Inference stays on this Mac; model downloads need internet access.

## Build and run

Requires Apple Silicon, macOS 14+, Xcode command-line tools, Python 3.13+, and `uv`.
From the repository root:

```sh
cd app/backend
uv sync --extra test
cd ../..
./script/build_and_run.sh --verify
```

This creates and opens `dist/LiveTR3.app` using a release Swift build. The default
bundle contains the engine source and uses the repository's Python environment.
It is a development app, not yet a relocatable standalone distribution.
`script/package_engine.sh` supports a supplied standalone Python and wheelhouse
for packaging that runtime separately.

Download/cache these models before offline use:

- `mlx-community/parakeet-tdt-0.6b-v3`
- `mlx-community/gemma-4-e4b-it-8bit`

The native launcher sets offline model loading by default. Model files must
already be available in the Hugging Face cache. The engine log is
`dist/logs/backend-runtime.log`.

## Caption path

The native app defaults to Parakeet ASR for English, Spanish, French, German,
Italian, and Portuguese. Gemma handles translation, other source languages, and
code-switching sessions. Set `TRANSCRIPTION_ENGINE=gemma` in the app's inherited
environment to use Gemma ASR throughout.

- Apple's streaming audio converter produces 16 kHz mono PCM with continuous
  resampling and anti-alias filtering. Pausing discards captured audio.
- Silero detects utterance boundaries. Native defaults request partials every
  250 ms, a 12-second utterance cap, and a 150 ms silence threshold. Scheduling
  cadence is not a promise that inference finishes within 250 ms.
- Each partial decodes the complete utterance so far and replaces the previous
  hypothesis. Final ASR runs again on the completed utterance.
- Parakeet source finals appear before translation completes. A subsequent
  message updates the same caption with the translation.
- Gemma's audio path supplies both languages in one pass, without a redundant
  partial translation request. Generation uses greedy decoding.
- Automatic text-only ASR correction, transcript learning, polish, and speculative
  punctuation/stability commits default off. A language model's rewrite is not
  independent evidence of what was spoken.
- Final translations outrank previews. Finalizing one utterance does not stop
  partials for the next. Failed or empty finals release their pending state.
- Parakeet consumes PCM directly in memory. Gemma temporary audio directories
  are isolated by engine and host process.
- Slow jobs log queue and inference timing to the native engine log.

The native macOS app is the only UI. The browser client and alternative design
gallery have been removed.

## Validation

```sh
cd app/backend
uv run --extra test python -m pytest tests -q
uv run python -m scripts.check_imports
cd ../..
swift test --package-path macos/LiveTR3Mac
```

See `docs/NATIVE_VALIDATION.md` for the current test evidence and limits. Historical
browser/Gemma-only timing results do not characterize this native pipeline.
