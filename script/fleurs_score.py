#!/usr/bin/env python3
"""Score fleurs_replay.py outputs against the FLEURS English and Spanish references.

Needs sacrebleu and whisper-normalizer (not part of the backend environment):
  python -I script/fleurs_score.py --eval-dir dist/eval/fleurs-v1 dist/logs/fleurs/ab/*

English: WER after Whisper's English normalizer (numbers, contractions,
spelling), plus errors on reference number and negation words and on words
within two of a final boundary. Spanish: corpus chrF++ and BLEU with one
segment per clip, so caption boundaries need not match sentence boundaries.
"""
import argparse
import json
from pathlib import Path
import re
import statistics

import numpy as np
import sacrebleu
from whisper_normalizer.english import EnglishTextNormalizer

normalize = EnglishTextNormalizer()
NEGATION = {"not", "no", "never", "nor", "none", "nothing", "without", "cannot"}
RUN = re.compile(r"^(\d+)-(?:(\d+)s-)?(\d+)ms-(clip-\d+)-summary\.json$")


def tokens(text):
    # FLORES marks editorial insertions like "[w]hile"; the normalizer would
    # drop the bracketed letters, so keep them as plain text.
    return normalize(text.replace("[", "").replace("]", "")).split()


def align(ref, hyp):
    """Edit alignment; returns (errors, per-reference-word error flags, deletions, insertions)."""
    costs = np.zeros((len(ref) + 1, len(hyp) + 1), dtype=np.int32)
    costs[:, 0] = np.arange(len(ref) + 1)
    costs[0, :] = np.arange(len(hyp) + 1)
    for i, a in enumerate(ref, 1):
        for j, b in enumerate(hyp, 1):
            costs[i, j] = min(costs[i - 1, j - 1] + (a != b), costs[i - 1, j] + 1, costs[i, j - 1] + 1)
    i, j = len(ref), len(hyp)
    wrong, near_hyp, deletions, insertions = [False] * len(ref), [], 0, 0
    while i or j:
        if i and j and costs[i, j] == costs[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]):
            if ref[i - 1] != hyp[j - 1]:
                wrong[i - 1] = True
                near_hyp.append(j - 1)
            i, j = i - 1, j - 1
        elif i and costs[i, j] == costs[i - 1, j] + 1:
            wrong[i - 1] = True
            near_hyp.append(j)
            deletions += 1
            i -= 1
        else:
            near_hyp.append(j - 1)
            insertions += 1
            j -= 1
    return int(costs[-1, -1]), wrong, near_hyp, deletions, insertions


def score_clip(summary, english, spanish):
    finals = [row for row in summary["finals"] if row.get("original")]
    ref = tokens(english)
    hyp, boundaries = [], []
    for row in finals:
        hyp += tokens(row["original"])
        boundaries.append(len(hyp))
    errors, wrong, near_hyp, deletions, insertions = align(ref, hyp)
    boundaries = boundaries[:-1]
    near_boundary = sum(any(abs(j - b) <= 2 for b in boundaries) for j in near_hyp)
    numeric = [k for k, word in enumerate(ref) if re.search(r"\d", word)]
    negation = [k for k, word in enumerate(ref) if word in NEGATION]
    latency = summary.get("final_latency_seconds", [])
    return dict(
        ref_words=len(ref), errors=errors, deletions=deletions, insertions=insertions,
        near_boundary_errors=near_boundary,
        numeric_words=len(numeric), numeric_errors=sum(wrong[k] for k in numeric),
        negation_words=len(negation), negation_errors=sum(wrong[k] for k in negation),
        spanish_hypothesis=" ".join(row["translation"] for row in finals), spanish_reference=spanish,
        dropped_finals=sum("incomplete" in row.get("message", "") for row in summary["errors"]),
        other_errors=sum("incomplete" not in row.get("message", "") for row in summary["errors"]),
        finals=len(finals), forced=summary["forced_finals"], reused=summary["reused_boundaries"],
        final_latency=latency, last_final_after_clip=summary["last_final_after_clip_seconds"],
        first_target=summary["final_retained_word_growth"]["first_translation_seconds"],
        gap_p95=summary["final_retained_word_growth"]["p95_seconds"],
        gaps_over_two=summary["final_retained_word_growth"]["over_two_seconds"])


def final_inference_seconds(run_dir):
    trace = run_dir / "backend.jsonl"
    if not trace.exists():
        return []
    rows = [json.loads(line) for line in trace.read_text().splitlines() if line.strip()]
    return [row["inference_seconds"] for row in rows
            if row.get("stage") == "worker_complete" and row.get("priority") == "final"
            and isinstance(row.get("utterance"), int) and row["utterance"] >= 2000]


def aggregate(clips, inference):
    total = lambda key: sum(c[key] for c in clips)
    latency = [x for c in clips for x in c["final_latency"]]
    hyps = [c["spanish_hypothesis"] for c in clips]
    refs = [[c["spanish_reference"] for c in clips]]
    return dict(
        clips=len(clips), ref_words=total("ref_words"),
        wer=total("errors") / total("ref_words"),
        deletions=total("deletions"), insertions=total("insertions"),
        near_boundary_errors=total("near_boundary_errors"),
        numeric=f'{total("numeric_errors")}/{total("numeric_words")}',
        negation=f'{total("negation_errors")}/{total("negation_words")}',
        chrf_pp=sacrebleu.corpus_chrf(hyps, refs, word_order=2).score,
        bleu=sacrebleu.corpus_bleu(hyps, refs).score,
        dropped_finals=total("dropped_finals"), other_errors=total("other_errors"),
        finals=total("finals"), forced=total("forced"), reused=total("reused"),
        final_latency_median=statistics.median(latency) if latency else None,
        final_latency_p95=float(np.percentile(latency, 95)) if latency else None,
        last_final_after_clip_mean=statistics.mean(c["last_final_after_clip"] for c in clips),
        first_target_mean=statistics.mean(c["first_target"] for c in clips if c["first_target"] is not None),
        gap_p95_mean=statistics.mean(c["gap_p95"] for c in clips if c["gap_p95"] is not None),
        gaps_over_two=total("gaps_over_two"),
        final_inference_median=statistics.median(inference) if inference else None)


def main(args):
    results = {}
    for run_dir in args.runs:
        meta = json.loads((run_dir / "metadata.json").read_text())
        by_condition = {}
        for path in sorted(run_dir.glob("*-summary.json")):
            match = RUN.match(path.name)
            if not match:
                continue
            clip = match.group(4)
            summary = json.loads(path.read_text())
            by_condition.setdefault(f"{match.group(2) or 6}s {match.group(3)}ms", []).append(score_clip(
                summary, (args.eval_dir / f"{clip}.en.txt").read_text(),
                (args.eval_dir / f"{clip}.es.txt").read_text()))
        inference = final_inference_seconds(run_dir)
        for condition, clips in by_condition.items():
            name = f"{run_dir.name} {meta['mode']} {condition}"
            results[name] = aggregate(clips, inference if len(by_condition) == 1 else [])
    columns = [("WER", "wer", "{:.2%}"), ("del", "deletions", "{}"), ("ins", "insertions", "{}"),
               ("near cut", "near_boundary_errors", "{}"), ("numbers", "numeric", "{}"),
               ("negation", "negation", "{}"), ("chrF++", "chrf_pp", "{:.1f}"), ("BLEU", "bleu", "{:.1f}"),
               ("dropped", "dropped_finals", "{}"), ("final lat med", "final_latency_median", "{:.2f}"),
               ("p95", "final_latency_p95", "{:.2f}"), ("last after clip", "last_final_after_clip_mean", "{:.2f}"),
               ("first target", "first_target_mean", "{:.2f}"), ("gap p95", "gap_p95_mean", "{:.2f}"),
               (">2 s", "gaps_over_two", "{}"), ("infer med", "final_inference_median", "{:.2f}")]
    print("| run | " + " | ".join(c[0] for c in columns) + " |")
    print("|---|" + "---:|" * len(columns))
    for name, row in results.items():
        cells = [fmt.format(row[key]) if row[key] is not None else "—" for _, key, fmt in columns]
        print(f"| {name} | " + " | ".join(cells) + " |")
    if args.json:
        args.json.write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-dir", type=Path, required=True)
    parser.add_argument("--json", type=Path)
    parser.add_argument("runs", type=Path, nargs="+")
    main(parser.parse_args())
