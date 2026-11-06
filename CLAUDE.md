# LiveTR3: project rules

## Caption speed and accuracy are protected

Translation accuracy and caption latency are where they should be. A UI change must
not make them worse. Treat any regression as a bug in the UI change, not a reason to
retune the engine.

Baselines to protect (main 3e4521f, 2026-11-06):

- Live final latency (from session archives): about 1.3 s median, 2.4 s p95 or better
- Replay scoreboard (`script/scoreboard.py`): pooled WER about 4.7%, chrF++ about 55.5
- App CPU while capturing: about 20-40%, never pinned at 100%

### Off limits for UI work

Unless the user asks for an engine or tuning change by name, a UI task must not edit:

- `app/backend/**`: engine, segmenter, worker, transport, prompts
- The tuning fields in `ClientConfig` and `ClientConfig.default`
  (`LiveTR3Protocol.swift`): partial interval, utterance cap, Silero threshold,
  silence and pad ms, early-commit settings
- Engine environment in `BundledEngineConfiguration.swift` (MTP, prefix cache,
  model paths)
- The socket protocol (`LiveTR3Protocol.swift` message shapes,
  `LocalEngineConnection.swift`), unless the UI feature needs a new field

If a UI feature seems to need one of these, stop and ask first.

### How the UI can slow the engine

The engine awaits `writer.drain()` on every message it sends, and the app reads the
socket on the main actor. A busy main thread therefore stalls the engine: audio stops
being read, a backlog builds, decodes time out and the model reloads. Captions then
arrive 20-30 s late. That has happened before (PR #32), so:

- Never put a high-rate value (audio level, per-buffer or per-token data) in an
  `@Published` property on `SessionController` or any object that the whole window
  observes. Use a small separate `ObservableObject`, throttled to 30 Hz or less,
  like `AudioLevelMeter` in `WaveformMeterView.swift`.
- Keep the main actor light: no file I/O, JSON encoding of whole transcripts, regex
  over the whole transcript, or sync waits in view bodies or caption handlers. Do
  heavy work off the main actor, or once per final caption, not per partial.
- Partials arrive about every 250 ms. Per-caption work, such as filters, layout and
  the projector roll-up, must run in time proportional to the new text, not to the
  whole session.
- Animations and the waveform must not redraw the caption list or the projector on
  every frame.
- Closing or hiding a window must not stop the engine or the capture
  (no `runtime.stop()` in `.onDisappear`). Pause sends `commit_now`; keep that.
- Don't add work to the audio capture queue (`AudioCaptureEngine`,
  `StreamingAudioConverter`) beyond what audio needs.

### Check before calling a UI change done

1. `./script/validate.sh` passes.
2. Run the built app, start a capture and speak (or play audio) for a minute. Check
   CPU with `ps -o %cpu= -p $(pgrep -x LiveTR3)`. It should stay in the normal range.
   If it is higher than before the change, `sample LiveTR3 5` and fix it.
3. Read the new session archive in
   `~/Library/Application Support/LiveTR3/sessions/`. Final latency is
   (meta.json `started_at` + event `timestamp_seconds`) minus
   `last_audio_frame_unix_seconds`. Compare it with the baseline. Look for gaps with
   no events followed by a burst, and for "reloading model worker" status messages.
4. If anything under `app/backend` or the tuning settings changed, also run the
   replay scoreboard in ABBA order against main (`python3 -I script/scoreboard.py`)
   and report WER and live-weighted latency next to the baseline.

Report these numbers in the PR or the final message. If a check was skipped, say so.

### When latency looks worse

Check the app's CPU and which bundle and engine are running (`ps eww` on
`uds_host`) before touching engine tuning. Most "slow model" reports so far were the
UI or a stale engine build.
