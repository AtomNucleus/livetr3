# Instruction-prefix KV cache (3c) — 2026-10-28

Every AST prompt starts with the same instruction tokens before the audio
(boa) token. With `LIVETR3_PREFIX_CACHE=1` the worker prefills those once and
gives each decode a private copy of their KV cache. Prefill then runs only on
the audio and the answer header. **It is on by default**; set
`LIVETR3_PREFIX_CACHE=0` to turn it off. The ABBA improves the median in both
pairs and the live-weighted p95 on the mean (below).

Outputs are in `dist/logs/prefix-cache-2026-10-28/`. Only one model worker ran
at a time, and no other LiveTR3 worker was loaded.

## How it works

`prefix_cache.PrefixKVCache` (built in the worker child only when the flag is
on):
- Prepares inputs once per decode with mlx-vlm's `_prepare_generation_inputs`.
- The prefix is every token before `boa_token_id`, keyed on the exact token ids.
  Custom vocab, code-switching, a language change or prior context therefore
  rebuild it. Each worker child builds its own, so a model reload rebuilds it
  too.
- Each decode gets a fresh cache whose arrays are copies of the template
  (`mx.array(x)`). KVCache writes into its buffers in place, so sharing one
  would corrupt the next decode.
- The full prompt is embedded as usual. Token embeddings are cut to the suffix,
  and Gemma 4's per-layer inputs stay full length, because the model slices
  them by cache offset. The worker hands that embedding output to
  `generate_step`'s single `get_input_embeddings` call, then removes the
  override.
- `stream_generate` gets the suffix ids and the copied cache. Chunked prefill
  for cancellable jobs (#26) chunks only the suffix, and the cancel hook still
  fires between chunks.
- MTP needs no change. Its drafter reads the hidden state and shared KV of
  prefill's last step, which attends over the whole cache.
- `ast_decode` traces gain `prefix_tokens`. `prompt_tokens` there now counts
  the suffix only.
- A fault in the cache path must not cost a caption or MTP. Any exception
  other than a cancel, in `prepare()` or in the cached generation, does three
  things: it traces `prefix_cache_failed`, turns the cache off for that worker,
  and reruns the decode uncached with MTP kept. A cancel still propagates as
  before.

mlx-vlm 0.7.10 doesn't help: like 0.7.4, both of its reuse paths
(`PromptCacheState` and APC) still require a text-only suffix
(`prefix_leaves_text_only_suffix`). This is built on the pinned 0.7.4.

## Offline identity check

`prefix_identity.py` loads the production worker (target and MTP drafter). It
decodes each window greedily through `MLXWorker.ast`, uncached and then
cached, and compares the full outputs.

| Windows | Identical | MTP acceptance, uncached / cached | Tokens per round | MTP lost |
| --- | ---: | --- | --- | ---: |
| 30 spike windows, full prefill | 28/30 | 0.696 / 0.704 | 2.39 / 2.41 | 0 |
| same, chunk 32 | 28/30 | 0.705 / 0.699 | 2.41 / 2.40 | 0 |
| 10 windows, prompts alternating vocab / code-switching (rebuild every call) | 9/10 | 0.701 / 0.710 | 2.40 / 2.42 | 0 |
| every FLEURS-8 final of pass 3e-chunk32-b2 | 82/93 | 0.691 / 0.689 | 2.38 / 2.38 | 0 |
| every sermon-v2 final of the same pass | 138/149 | 0.639 / 0.638 | 2.28 / 2.28 | 0 |
| **total** | **285/312** | | | |

The final windows were cut from the clip using each final's last audio frame
and its `segment_commit` sample count.

The 27 differing pairs are numeric drift, not a cache fault. Running the same
prefill in different shapes is not bit-identical in MLX (the spike measured
logits up to 1.1 apart with the same argmax). Chunking alone, with no cache,
changes 1 of the 30 spike windows (full vs chunk 32). The cache changes 2.

The differences go both ways. Every pair, uncached → cached:
- spike / chunk 32 / prompts, sermon-v2 04@5: a final "." added on both lines (3 pairs)
- sermon-v2 04@15: "mantenerte" → "te mantenga"
- sermon-v2 06@55, full and chunk 32: "arrepíntense" → "arrepentirse"
- FLEURS 02#3008: "having to go" → "have to go"
- FLEURS 03#4003: punctuation and quotes dropped; "involucrado directamente" → "directamente involucrado"
- FLEURS 03#4005: "cancelled" → "canceled"
- FLEURS 04#5008: "queues feature" → "que uses feature" (worse)
- FLEURS 05#6002: "panfletos" → "folletos"
- FLEURS 05#6012: "el 35 milímetro" → "35 milímetros" (better)
- FLEURS 05#6018: "thing" added at the cut start
- FLEURS 06#7008: "No sabemos… puede haber tenido" → "No lo sabemos… puede que tuviera"
- FLEURS 06#7011: "Si cruzas" → "Si cruzar" (worse)
- FLEURS 07#8001: "material" → "materials"
- FLEURS 08#9011: "done lat" → "dun lat"
- sermon-v2 01#2013: "So" → "so"
- sermon-v2 02#3014: commas and the final period dropped
- sermon-v2 03#4002: "ruidoso" → "retumbante"
- sermon-v2 03#4019: "deshechas" → "derogadas"
- sermon-v2 03#4025: periods dropped; "como un niño"
- sermon-v2 04#5024: periods → commas; one extra word "a" at the cut; translation shortened
- sermon-v2 05#6010: "y así" → "y así que"
- sermon-v2 05#6015: "dysfunctionality" → "disfunctionality"
- sermon-v2 06#7008: "esas gran" → "esa gran" (better)
- sermon-v2 06#7016: "He is" → "He's"
- sermon-v2 06#7028: "nace" → "nazca"

None of them touches a number or a negation.

## Replay: screen and ABBA

The setup is the same as Phase 3: `script/scoreboard.py`, real Gemma 4 E4B
8-bit with MTP, cap 6 s, silence 600 ms. FLEURS-8, sermon-v1 and sermon-v2 are
pooled, with chunk-32 interruptible prefill on. The ABBA ran in the order A1,
B1, B2, A2 (A = cache off, B = on). Latencies are in seconds.

| Pass | Cache | Live-weighted median | Live-weighted p95 | Pooled median / p95 | First target | Gap p95 | WER | chrF++ | Numbers / negation | Dropped |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- | ---: |
| 3c-screen | on | 1.51 | 2.53 | 1.67 / 2.61 | 2.47 | 1.83 | 4.75% | 55.4 | 2/51, 1/55 | 0 |
| A1 | off | 1.59 | 2.43 | 1.74 / 2.61 | 2.65 | 1.92 | 4.78% | 55.5 | 2/51, 1/55 | 0 |
| B1 | on | 1.55 | 2.49 | 1.71 / 2.59 | 2.47 | 1.87 | 4.84% | 55.5 | 2/51, 1/55 | 0 |
| B2 | on | 1.49 | 2.46 | 1.65 / 2.62 | 2.56 | 1.81 | 4.84% | 55.3 | 2/51, 1/55 | 0 |
| A2 | off | 1.62 | 2.59 | 1.79 / 2.69 | 2.69 | 1.97 | 4.99% | 55.4 | 2/51, 1/55 | 0 |

The earlier chunk-32 passes on #26 gave 1.59 / 2.47 and 1.54 / 2.42.

Pair by pair (on − off):

| | A1 → B1 | B2 → A2 | Mean of B − mean of A |
| --- | ---: | ---: | ---: |
| Live-weighted median | −0.04 | −0.13 | −0.09 |
| Live-weighted p95 | **+0.06** | −0.13 | −0.04 |
| First target | −0.18 | −0.13 | −0.16 |
| Gap p95 | −0.05 | −0.16 | −0.11 |
| WER | +0.06 pt | −0.15 pt | −0.05 pt |
| chrF++ | 0.0 | −0.1 | −0.1 |

Against the gate:
- WER (at most +0.3 pt) and chrF++ (at most −0.5): pass.
- Dropped finals, numbers and negation: pass (0 dropped; unchanged).
- First target and gap p95, no worse: pass in both pairs.
- Live-weighted median, must improve: pass in both pairs.
- Live-weighted p95, must improve: **mixed.** It improves on the ABBA means
  and in pair 2. In pair 1 it is 0.06 s worse, inside the ±0.08 s
  pass-to-pass noise.

### Per-decode prefill (`ast_decode`, time to first response)

| Pass | Previews median / p95 | Finals median / p95 | MTP acceptance / tokens per round | Previews run |
| --- | --- | --- | --- | ---: |
| A1, off | 0.443 / 0.621 | 0.498 / 0.642 | 0.67 / 2.33 | 1,076 |
| B1, on | 0.280 / 0.496 | 0.379 / 0.617 | 0.67 / 2.33 | 1,245 |
| B2, on | 0.273 / 0.506 | 0.367 / 0.600 | 0.67 / 2.33 | 1,284 |
| A2, off | 0.453 / 0.641 | 0.485 / 0.702 | 0.67 / 2.34 | 1,054 |

The prefill drop is **about 0.17 s per preview and 0.12 s per final**
(medians). The 77 cached tokens are a larger share of a preview's shorter
prompt, which drops from a median of 138 tokens to 59, about five chunks of 32
down to two. Finals go from 185 tokens to 108 in one full-speed prefill. MTP is
unchanged in every pass, with no fallbacks.

Why p95 moves less than the median: faster previews mean the session
schedules about 17% more of them. Finals then queue behind those a little
more often. Final queue p95 was 0.121 and 0.097 s on vs 0.094 and 0.124 s off.
That trims part of the tail gain.

## Decision

**Adopted, on by default.** The coordinator reviewed the passes and confirmed
the numbers. Silence-ended finals, 89% of live, improved at the median by
0.09 s and 0.13 s in the two pairs, which matches the 0.12 s drop in final
prefill. The pair-1 p95 regression is inside the A1-to-A2 spread of 0.16 s,
so no third pair was run.

## Tests

`tests/test_prefix_cache.py` (Apple Silicon only, like the other MLX tests)
checks:
- one build per distinct prefix, and a rebuild when it changes
- private per-decode copies
- no prefix without the audio token
- the embedding override is served once and always removed
- the flag defaults on
- a failure in `prepare()` or in cached generation still returns the caption,
  keeps MTP, and leaves later decodes uncached
- a cancel in the cached path still propagates

Results: 182 backend tests pass with the shared env.
