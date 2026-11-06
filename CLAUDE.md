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

### Checks for UI changes

Two levels. Don't run the slow one on every edit.

**While iterating** (about 10 s warm): `./script/quick_check.sh`. It runs
`script/ui_guard.sh`, which fails if the branch touches an off-limits file above,
then `swift test`. Backend tests run only if `app/backend` changed.

**Once before a PR or merge:**

1. `./script/validate.sh` passes.
2. `./script/ui_perf_check.py` passes. It builds the branch, replays a recorded
   sermon clip through the full app path (no mic, no talking) into one shared
   engine, and runs the installed app (A, main) and the branch (B) back to back.
   It reports app CPU, final latency (median, p95), the longest gap between finals
   and model reloads for each, and fails if B is clearly worse than A. It needs
   LiveTR3 quit first and refuses to run otherwise; ask the user, never quit it.
   If it fails on CPU, `sample LiveTR3 5` while B runs and fix the hot path. If the
   result is close, rerun with `--order ABBA`.
3. If anything under `app/backend` or the tuning settings changed, also run the
   replay scoreboard in ABBA order against main (`python3 -I script/scoreboard.py`)
   and report WER and live-weighted latency next to the baseline.

Report the A/B numbers in the PR or the final message. If a check was skipped,
say so. Replay latency runs denser than live, so judge B against A, not against
the live baseline above. Live archives in
`~/Library/Application Support/LiveTR3/sessions/` stay the source for live numbers.

### When latency looks worse

Check the app's CPU and which bundle and engine are running (`ps eww` on
`uds_host`) before touching engine tuning. Most "slow model" reports so far were the
UI or a stale engine build.
