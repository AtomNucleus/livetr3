# User-tested MTP distribution and native fullscreen — 2026-10-01

The user selected the MTP version after live use and requested a shareable app
for a friend with the same Apple-silicon/32 GB hardware, the standard macOS green
projector button entering fullscreen, and merging PR #11. The normal backend now
enables the bf16 MTP drafter by default; `LIVETR3_GEMMA_MTP=0` retains the ordinary
backend path. The earlier matched-replay tradeoffs are unchanged, and no new
human Spanish or numeric-quantity score is claimed.

## Projector window

The running old projector exposed an accessibility `zoom button`, and its
single SwiftUI `Window` scene did not enter native fullscreen. A small background
NSView configures that NSWindow after attachment: retain resizing and other
collection behavior, remove `fullScreenNone`/`fullScreenAuxiliary`, and set
`fullScreenPrimary`. No fullscreen control was added to the visible app UI.

In a separately built running app, the projector exposed `full screen button`.
Clicking that green control removed the normal title-bar controls and macOS's
View menu changed to `Exit Full Screen`; Escape returned it to the windowed
state and the menu changed to `Enter Full Screen`. This checks actual native
window behavior on this Mac. It is not a physical-projector readability test.
The unit test checks the window policy is idempotent and retains other behavior.

## Self-contained distribution

`script/package_share_app.py` assembles a relocatable native `.app` from:

- The release native executable and icon.
- A relocatable python-build-standalone CPython 3.13.13 arm64 runtime.
- The existing, verified backend dependency versions, including MLX 0.32.2,
  mlx-vlm 0.7.3, Torch/torchaudio 2.11.0 and packaged Silero weights.
- Target `mlx-community/gemma-4-e4b-it-8bit`, revision
  `4255b21bd9a9d3fc807ef7abd80373f5e3a52a73`.
- BF16 MTP drafter `mlx-community/gemma-4-E4B-it-assistant-bf16`, revision
  `844e008e06ef5562bdb89428d851d0634d119dcd`.
- Model notices/licenses and the retained dependency copyright/license files.

The bundle contains no virtualenv shim pointing to the developer's Python,
Homebrew interpreter, external symlink, `.env`, private recording, transcript,
session archive or historical development log. Runtime backend modules are
copied from an explicit root-module selection. APFS file clones save local
staging space but the resulting ZIP contains complete bytes, not cache links.
Native library IDs containing wheel-build/developer paths are normalized and
all actual absolute non-system native dependency loads are rejected by the
builder. Python bytecode writes are disabled so launching preserves the sealed
bundle. The copied source environment and cached weights remain untouched.

`LiveTR3BundledMTP` in the app's Info.plist selects resource-relative Python,
target and drafter paths, offline model loading, and writable logs/cache/session
paths under `~/Library/Application Support/LiveTR3 Gemma MTP`. It uses its own
bundle identifier and socket by default. Moving the bundle changes the resolved
resource paths; it does not require the development checkout or a user-level
model cache. The path/configuration tests also check a moved app with spaces.

## Validation

The finished app was moved into a folder containing spaces. With an empty HOME,
only `/usr/bin:/bin` in PATH, offline flags and bytecode writes disabled, its own
Python imported all engine dependencies and loaded Silero. Its interpreter,
standard library and dependency import paths resolved inside the moved app,
with the expected versions. There were zero external symlinks, and backend
hashes matched the packaged manifest.

The relocated standalone app then ran the private 51.467-second recording
through its own bundled backend, Python, target and drafter, with offline loading
and an isolated native file-replay socket. All 2,674 frames were received. The
corrected post-shutdown archive check found 13 nonempty unique finals, zero
errors, 56 MTP decode attempts, zero fallback, and 4/133 source errors, matching
the previous native candidate's source score. Archive final IDs matched the
native operator store's final IDs, and signing verification passed after replay.

The operator view character-growth proxy had 109 updates, first translation at
1.147 s, p95/worst gaps of 2.092/2.752 s and seven gaps over two seconds. This
single standalone integration check is not a matched cadence comparison and
establishes no displayed-cadence or accuracy improvement. There was no microphone
capture or physical projector test in this distribution validation.

Backend validation: 150 tests passed, including the user-approved default-on
policy, explicit opt-out, compatibility failure fallback, streaming,
cancellation and bounded retries. Native validation: 54 tests executed,
53 passed and one optional test skipped. Release build, Python compilation,
diff whitespace and bundle signing checks passed. Existing Swift warnings were
unchanged. The user's running app and unrelated backends were preserved.

Only an Apple Development certificate was installed; there was no Developer ID
distribution identity. This artifact is ad-hoc signed and not notarized.
A recipient must use Apple's one-time Privacy & Security > Open Anyway route
if Gatekeeper blocks the app, then grant microphone permission when starting a
session. No system-wide Gatekeeper change or developer tooling is required.
The archive includes concise installation/use instructions with
[Apple's opening instructions](https://support.apple.com/102445).

Local evidence and private replay outputs stay in `dist/logs/share-package/`.
`script/verify_share_app.py` accepts an external private audio/reference pair,
launches the bundle's own engine in an isolated native file replay, waits until
shutdown flushes the archive, compares final IDs against native store finals,
and checks the bundle signature after execution. The initial verifier read the
archive before its last two finals were flushed; the app's native trace already
contained all 13. The corrected post-shutdown check avoids falsely reporting
those captions as source deletions.
