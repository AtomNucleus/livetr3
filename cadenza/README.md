# Cadenza

Cadenza is a separate native macOS English → Spanish caption app. A complete short phrase goes through one ordinary Gemma generation, and its completed text stays unchanged. It is a small alternative speech-to-display path, with its own `org.atomnucleus.cadenza` identity, icon, preferences, child process, and logs. It does not change LiveTR3.

Double-click **Cadenza.app**, click **Start**, and allow microphone access. Start first loads Gemma; after that, Stop finishes the captured phrases and leaves the model loaded for another session. Quit drains accepted jobs before exiting. The first release requires Apple silicon and macOS 14 or newer. The delivered bundle contains Python, the verified MLX runtime, and the cached Gemma weights, so it needs no environment-variable launcher, Python installation, or model download. It is signed ad hoc for local use, not Developer ID signed or notarized for public distribution. Gemma use is subject to [Google's terms](https://ai.google.dev/gemma/terms).

The path deliberately waits for a phrase. In the warmed private replay, Spanish first appeared at 6.24 seconds; the existing preview-based LiveTR3 baseline appeared sooner. Both scored 5/133 source word errors. See [the validation evidence](EVIDENCE.md) for timings, coverage, and limits.

## Why these components exist

- `AudioCapture.swift` uses the native microphone and AVAudioConverter to send mono 16 kHz float samples. It saves microphone input before transport, so a pipe overflow has a recovery recording.
- `EnginePipe.swift` owns one private Python child and a serial, bounded writer. Audio packets and Stop stay ordered, with at most 64 unsent audio packets; no server or shared socket is needed.
- `Cadenza.swift` owns the minimal Start/Stop state and phrase history. Pending and failed answers stay visibly provisional; only a normal model stop with both languages creates a completed phrase. Retry is an explicit user action after failure.
- `pipeline.py` separates collection from inference. A 20 ms energy gate at RMS 0.003 commits after 500 ms of quiet or an 8-second cap. It keeps three waiting phrases plus one running phrase, stops capture visibly on overload, and retains rejected phrases for Retry. Stop includes a partial final audio frame and drains queued work.
- `raw_model.py` loads the pinned cached model and calls `mlx_vlm.stream_generate` once per phrase at temperature zero, with a 512-token limit. It uses [Google's documented AST prompt](https://ai.google.dev/gemma/docs/capabilities/audio) with English and Spanish filled in. It separates the documented `Spanish:` label without polishing, deduplicating, or rewriting the returned words.
- `engine.py` handles the private command/event pipe and session files. Its inference loop keeps Gemma loaded; its reader continues collecting audio during generation. It refuses to load beside another Cadenza child or a detected LiveTR3 engine, and never kills another app.

The 8-second cap is comfortably below Google's 30-second audio limit. A cap can split a word, and the simple energy gate can mistake quiet speech or noise for silence or speech. All received samples remain in `capture.wav` even when idle intervals are excluded from inference. This first version has no projector, vocabulary tuning, preview calls, cancellation, prefix reuse, context history, agreement rules, polish pass, separate recognizer, or separate translation model.

## Build and focused tests

Run these from the repository root using the installed Python 3.13 MLX environment. The packager verifies MLX 0.32.2, MLX-VLM 0.7.3, and Transformers 5.17.0, copies the installed dependency closure recorded in `requirements.lock`, and materializes cached model revision `4255b21bd9a9d3fc807ef7abd80373f5e3a52a73`. It requires a standalone Python 3.13.13 prefix; `--python-runtime` can select its location. APFS cloning saves build-machine space, while the resulting bundle has no dependency on the original files. Packaging refuses to overwrite an existing output.

```sh
swift build -c release --package-path cadenza
/path/to/mlx-environment/bin/python -m unittest discover -s cadenza/Tests -v
/path/to/mlx-environment/bin/python cadenza/package.py
open dist/Cadenza.app
```

For a truly bare model call, provide one or more mono 16 kHz WAV phrases under 29 seconds. Multiple inputs share one loaded model and do not import the LiveTR3 framework:

```sh
/path/to/mlx-environment/bin/python cadenza/engine/raw_model.py /private/phrase.wav
```

The private continuous replay harness runs direct-model → paced pipeline → direct-model after a real-audio warmup. Keep its audio, reference, and outputs outside tracked files:

```sh
/path/to/mlx-environment/bin/python cadenza/validate.py \
  --audio /private/recording.wav --reference /private/reference.txt \
  --output dist/logs/cadenza/replay
```

The native diagnostic launch uses the same child, pipe, segmenter, queue, and view as microphone capture, substituting a paced mono 16 kHz file:

```sh
open -n dist/Cadenza.app --args --replay /private/recording.wav
```

Quit a diagnostic launch and reopen normally before microphone use. `Logs & audio` opens `~/Library/Application Support/Cadenza/`: `events.jsonl` contains private model text and timings, `engine-stderr.log` contains runtime diagnostics, and `Sessions/` retains the received capture and individual phrase WAVs. Native microphone recovery files are CAF files in the same root. Recordings remain until you remove them; disk-write errors stop capture visibly. Failed phrases can be retried after the queue drains while their engine remains alive; after a child crash, retained files are the recovery source. No private fixtures or generated replay outputs belong in the PR.

## Icon

`Resources/AppIcon.png` is the original image produced with the built-in image generation tool; `AppIcon.icns` contains its macOS sizes. The prompt requested “a single sculptural ribbon forms two interlocking flowing speech waves, one warm ivory and one soft turquoise, on a deep midnight teal rounded-square tile,” with a clean small-size silhouette and no text or microphone pictogram.
