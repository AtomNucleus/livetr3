# Quiet-boundary inference handoff — 2026-09-30

A complete Gemma preview can now close its exact decoded audio prefix without
re-decoding that prefix as a final. The prefix must cover at least half the
configured chunk cap and end with 160 ms of audio below the existing frame RMS
speech threshold. Preview selection searches only the most recent second for
such a pause. Every newer frame remains buffered in the next utterance, with
only the already-configured overlap repeated. Silero state and pending samples
survive the split.

Reuse requires complete, nontruncated source and target text, matching decoded
input, exact raw-prefix equality, a current utterance/configuration, and no
pending configuration change. Eligibility is checked under the finalization
lock. Failures retain the ordinary final decode and its bounded retry. No other
model, target fabrication, correction learning, or incomplete-final promotion
is introduced. Final timestamps identify the snapshot's last spoken frame.

## Deterministic and native validation

- Backend: 140 tests passed, including frame conservation, Silero continuity,
  stale/invalid-result rejection, snapshot selection, and timestamp coverage.
- Native: release build passed; 50 tests executed, one optional audience-render
  test skipped, no failures. The enabled operator/projector render test passed.
- Import checks, Python compilation and diff whitespace checks passed.
- The existing app bundle was not changed or launched. A separate local test
  bundle and isolated-socket launcher are under `dist/`.

## Recorded-audio replay

The retained private 51-second recording plus two seconds of silence was paced
through the real segmenter/session/Gemma worker. Configuration: six-second cap,
250 ms preview interval, 400 ms silence threshold and 300 ms overlap. Runs used
one worker sequentially, isolated temporary audio resources, and no concurrently
running LiveTR3 inference. The baseline is main at e8b2c48.

| Metric | Forward baseline | Forward change | Reverse baseline | Reverse change |
| --- | ---: | ---: | ---: | ---: |
| Largest target-growth gap, seconds | 2.751 | 2.594 | 3.149 | 2.489 |
| Gaps over two seconds | 4 | 3 | 4 | 4 |
| 95th-percentile target-growth gap, seconds | 1.562 | 1.588 | 1.547 | 1.582 |
| Source word errors / reference words | 6 / 133 | 5 / 133 | 6 / 133 | 5 / 133 |
| Complete finals / unique final IDs | 13 / 13 | 13 / 13 | 13 / 13 | 13 / 13 |
| Reused complete prefixes | 0 | 1 | 0 | 1 |
| Errors / empty finals | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |

The reverse pair ran the changed implementation first. Source scoring joins all
finals in order, normalizes case/punctuation, and does not remove overlap words.
Target-growth events are nonempty translations that exceed the longest prior
translation for that utterance. Measurements include the backend, not native
capture, Unix-socket delivery or displayed-caption cadence. Local raw events,
reference scoring and replay scripts are retained at
`dist/logs/boundary-handoff-2026-09-30/` and its `reverse/` directory; private audio
and transcripts are not added to Git.

This removed one redundant boundary decode on this clip and reduced the worst
gap in both run orders. It did not improve overall p95 cadence or establish
continuous translation. Finals differ at the reused boundary because speech is
split at a different point. No human Spanish reference was available, so no
target accuracy score is claimed. A short RMS pause can still occur within a
semantic phrase, and quiet/whispered speech needs further acoustic validation.
Gemma still generates the source before the target and runs finals/previews on
one serialized worker; remaining model decoding delays persist.

An unrestricted prefix handoff was rejected after it increased source errors
from 6 to 10 by splitting words. A model-punctuation-only restriction preserved
the baseline text but produced no handoffs or measurable benefit. Those checks
motivated the acoustic pause and exact-coverage guards in the final change.
