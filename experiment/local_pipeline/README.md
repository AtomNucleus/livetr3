# Local English → Spanish benchmark

This isolated CLI tests Moonshine Medium Streaming recognition followed by text-only TranslateGemma 4B. It does not change LiveTR3 or Cadenza. **Real-model replay is currently unverified:** preflight refuses to load while the running Cadenza engine holds its audio model. See `EVIDENCE.md`.

## Setup on Apple silicon

Python 3.13.13 was used on a 32 GB M1 Pro. Both environments are separate from the app backend. Candidate inference uses Moonshine's native macOS/ONNX runtime and MLX; the baseline uses the existing backend code with separately installed pinned dependencies. Neither candidate path imports or runs the baseline recognizer.

```sh
uv venv --python 3.13 .venv-pipeline
uv pip install --python .venv-pipeline/bin/python -r experiment/local_pipeline/requirements.lock
uv venv --python 3.13 .venv-baseline
uv pip install --python .venv-baseline/bin/python -r experiment/local_pipeline/baseline-requirements.lock
.venv-pipeline/bin/python experiment/local_pipeline/setup.py
.venv-pipeline/bin/python -m pytest -q experiment/local_pipeline
```

Setup explicitly downloads weights into the user's model caches, outside Git. `models.json` records the exact candidate identity, conversion revision, quantization and Moonshine asset hashes. Candidate replay requires the pinned TranslateGemma snapshot already cached. Moonshine's pinned library supplies and checksum-validates the named ORT variant; a cache miss can download it, so finish setup before disconnecting the network. All speech recognition and translation execute locally. No recording or text is sent to a service.

The baseline expects the locally cached `mlx-community/gemma-4-e4b-it-8bit` model already used by LiveTR3; its current cached revision is recorded per run. Quit any app holding an inference model before replay. The harness detects known engine/server process owners and refuses them; it never terminates them. This guard is conservative and cannot discover every possible model host, so inspect other running model applications too.

## Paced comparison

From this worktree, use the private recording and its **human English reference**, without copying either into this checkout:

```sh
.venv-pipeline/bin/python experiment/local_pipeline/compare.py \
  --baseline-python "$PWD/.venv-baseline/bin/python" \
  --audio /Users/ed/Documents/GitHub/livetr3/app/backend/validation/sermon-clip.wav \
  --reference /Users/ed/Documents/GitHub/livetr3/app/backend/validation/sermon-clip.txt \
  --output dist/logs/local-pipeline/ordered
```

The order is baseline → candidate → candidate → baseline. Each process performs a full unscored paced warmup; the two candidate scored trials share one warmed model pair. Baseline models unload before the candidate loads, and the reverse baseline reloads and warms independently. This tests pipeline behavior, rather than equal-runtime isolated inference speed. To run only the candidate, invoke `replay.py` with `--audio`, `--reference`, `--output`, and optional `--runs`.

Audio is converted locally to mono 16 kHz, fed in 20 ms packets against absolute monotonic deadlines, followed by two seconds of explicit silence and a final stop. Candidate timing records pacing lag and the maximum synchronous ASR call, so slower-than-real-time feeding cannot masquerade as faster captions. Stop retains the final short packet. Cold loading is recorded separately from scored events. Memory snapshots are taken between runs with both candidate models loaded; they include VM/Metal residency, system pressure and swap, because RSS alone misses Metal allocations.

`dist/` is ignored. Event logs, scored alignments, generated transcripts, translations and diagnostic text belong there or outside the repository. Do not attach those private artifacts to a PR.

## Commit and translation policy

Moonshine supplies recognition updates every 250 ms when its runtime has enough headroom; it can adapt that interval when inference is slower. One ASR pass is processed once, even though the library emits both `Updated` and `TextChanged` callbacks.

A tentative prefix must repeat across two ASR passes and contain at least four whitespace-delimited words. The policy dispatches at most once per second per line, translating the entire stable prefix to preserve within-line context. It neither waits for punctuation nor splits out isolated changing characters. This is a stability heuristic, not recognition confidence, and it can hold or translate wrong words. The final line always supersedes it, including corrections to negation, quantities and names.

One translation runs at a time, with at most four pending lines. Pending drafts coalesce into the latest hypothesis for that line, and finals cannot be evicted by drafts. Completed text-identical snapshots can satisfy a final without another generation. New lines beyond capacity cause an explicit error and abort; accepted events remain in the local log. Failed, empty, context-overflowed or token-truncated translations cannot publish a final. Tentative output remains logged as tentative. A stalled drain fails after 90 seconds. No cross-line context, model-output learning or hidden post-editing is used.

TranslateGemma receives only the documented structured text message, with `source_lang_code="en"` and `target_lang_code="es"`, applied through its supplied tokenizer template. Greedy decoding uses a 256-token generation limit and enforces its 2K input-plus-output context limit. Long recognizer lines can hit that limit and fail explicitly; this small harness does not claim robust unlimited speech handling.

## Reading the evidence

The English score is exact case-insensitive word edit distance against the supplied human reference, using the existing benchmark normalization. Candidate summaries score both final ASR and the source spans whose translations completed; missing and duplicated translation lines and all failures are explicit.

The first Spanish character is a tentative-output timestamp. The stricter `usable_final_prefix_growth` metric counts an update only when at least three complete words match the prefix of that line's eventual Spanish final, and that retained prefix grows. It excludes a partial's unfinished last word. This is a retrospective retention proxy, **not proof of correct Spanish**. It can match a wrong final, so source-based semantic inspection is required before calling it usable. No human Spanish reference exists, so no Spanish WER or human accuracy score is claimed.

The same three-word rule is used for the baseline. Rewrites count changed previously emitted word positions, ignoring punctuation/case and excluding unfinished partial words. Report first source, first retained-prefix growth, longest growth gaps, rewrites, missing/duplicated lines, source errors, queue delay and final drain together. A lower rewrite count can simply mean later or sparser output.

Candidate events separate recognition updates, source commitment, dispatch, Spanish token growth and complete Spanish. `phrase_end_to_final` uses Moonshine's reported acoustic line endpoint, not a human word alignment. Baseline `commit_to_final` starts at backend segmentation commitment; these are different boundaries and must not be compared as equal acoustic-end latency. Backend traces expose segment commitment, inference queue wait and inference duration separately. Text-only negation/quantity/name diagnostics are saved separately after candidate replay and are not end-to-end audio measurements.

File replay does not establish live microphone, noisy-room or physical projector performance.

## Verified sources and licenses

- [Moonshine official repository](https://github.com/moonshine-ai/moonshine), [available models](https://moonshine-voice.readthedocs.io/en/latest/models/available-models/) and [Python implementation](https://github.com/moonshine-ai/moonshine/tree/main/language-bindings/python): native streaming APIs and MIT English Medium Streaming assets. The pinned installed API was also inspected locally.
- [Google announcement](https://blog.google/innovation-and-ai/technology/developers-tools/translategemma/) and [official TranslateGemma 4B card](https://huggingface.co/google/translategemma-4b-it): Gemma 3 translation family, language-code/content template, 2K context and [Gemma terms](https://ai.google.dev/gemma/terms).
- [MLX conversion card](https://huggingface.co/mlx-community/translategemma-4b-it-4bit): identifies `google/translategemma-4b-it` as its base and mlx-lm 0.29.1 as the conversion runtime. Its local config verifies affine 4-bit weights with group size 64; the tokenizer produces Google's English-to-Spanish prompt from the structured message. The benchmark runtime is pinned separately to mlx-lm 0.32.0.
