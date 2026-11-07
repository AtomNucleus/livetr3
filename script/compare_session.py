#!/usr/bin/env python3
"""Compare a recorded session's live captions with what was said in its audio.

Turn on "Record Session Audio" in the operator settings. Each Start then saves
the audio the engine heard as recordings/<start>.wav (beside the engine's
sessions/ folder) with a .json sidecar. This script:

1. transcribes that WAV offline with Parakeet (mlx-community/parakeet-tdt-0.6b-v3,
   cached as <start>.parakeet.json), or reads --reference, a text transcript
   you trust more (a human one);
2. reads the live finals from the session archive(s) that ran during the
   recording, placed on the recording's timeline;
3. aligns the two word by word and writes <start>.compare.html: an audio
   player, the word difference rate, stretches of speech with no caption,
   final latency, and every caption beside what the audio says, with
   differences marked. Click a time to hear that line.

Parakeet is another speech recognizer, not ground truth, so some marked
differences are its mistakes. Words are compared lowercased without
punctuation; "50" and "fifty" count as different.

Run with the backend venv (parakeet_mlx, numpy, soundfile):
  app/backend/.venv/bin/python -I script/compare_session.py            # latest recording
  app/backend/.venv/bin/python -I script/compare_session.py path/to/2026-11-06T19-00-00-0500.wav
"""
import argparse
import difflib
from datetime import datetime
import html
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys

PARAKEET = "mlx-community/parakeet-tdt-0.6b-v3"
DEFAULT_RECORDINGS = Path.home() / "Library" / "Application Support" / "LiveTR3" / "recordings"
MISSED_WORDS = 4  # this many reference words in a row with no caption is a missed stretch
WORD = re.compile(r"[^\s\-–—]+")


def key(word):
    word = word.lower().replace("’", "'").replace("‘", "'")
    return re.sub(r"[^\w']+", "", word).strip("'")


def words(text):
    return [(key(w), w) for w in WORD.findall(text) if key(w)]


def unix(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def latest_recording(directory):
    wavs = sorted(directory.glob("*.wav"), key=lambda p: p.stat().st_mtime)
    if not wavs:
        sys.exit(f"No recordings in {directory}. Turn on Record Session Audio in the app first.")
    return wavs[-1]


# --- Live captions --------------------------------------------------------------------

def live_finals(sidecar, rec_start, rec_end):
    """Finals from every archive that started during the recording, on its timeline."""
    root = Path(sidecar.get("archive_root") or DEFAULT_RECORDINGS.parent / "sessions")
    archives = []
    for meta_path in root.glob("*/meta.json"):
        try:
            started = unix(json.loads(meta_path.read_text())["started_at"])
        except (OSError, ValueError, KeyError):
            continue
        if rec_start - 10 <= started <= rec_end + 5:
            archives.append((started, meta_path.parent))
    if not archives:
        sys.exit(f"No session archive in {root} started during this recording.")
    finals = []
    for started, directory in sorted(archives):
        events = json.loads((directory / "transcript.json").read_text())
        speech_start, by_id = {}, {}
        for event in events:
            payload, at = event["payload"], started + event["timestamp_seconds"] - rec_start
            if payload["type"] == "speech_start":
                speech_start.setdefault(payload["utterance_id"], at)
            elif payload["type"] == "final" and payload.get("original", "").strip():
                by_id[payload["utterance_id"]] = (at, payload)  # a polished final replaces the first
        for utterance_id, (at, payload) in by_id.items():
            last_audio = payload.get("last_audio_frame_unix_seconds")
            end = last_audio - rec_start if last_audio else at
            finals.append(dict(
                start=speech_start.get(utterance_id, end - 6), end=end, committed=at,
                latency=at - end if last_audio else None, reason=payload.get("commit_reason"),
                original=payload["original"], translation=payload.get("translation", "")))
    finals.sort(key=lambda f: f["start"])
    return finals, [d for _, d in sorted(archives)]


# --- Reference ------------------------------------------------------------------------

def parakeet_words(wav, cache, refresh):
    if cache.exists() and not refresh:
        return json.loads(cache.read_text())
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from parakeet_mlx import from_pretrained
    print(f"Transcribing {wav.name} with Parakeet (about 1 min per hour of audio)...", flush=True)
    result = from_pretrained(PARAKEET).transcribe(str(wav), chunk_duration=60, overlap_duration=10)  # longer passes drop words
    out = []
    for token in result.tokens:
        if not out or token.text.startswith(" "):
            out.append([token.text.strip(), token.start, token.end])
        else:
            out[-1][0] += token.text
            out[-1][2] = token.end
    out = [w for w in out if w[0]]
    cache.write_text(json.dumps(out))
    return out


# --- Alignment ------------------------------------------------------------------------

def edit_ops(ref, hyp):
    """Exact word alignment of a short stretch: list of (op, i, j)."""
    n, m = len(ref), len(hyp)
    cost = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        cost[i][0] = i
    for j in range(m + 1):
        cost[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost[i][j] = min(cost[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]),
                             cost[i - 1][j] + 1, cost[i][j - 1] + 1)
    ops, i, j = [], n, m
    while i or j:
        if i and j and cost[i][j] == cost[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            ops.append(("equal" if ref[i - 1] == hyp[j - 1] else "sub", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i and cost[i][j] == cost[i - 1][j] + 1:
            ops.append(("del", i - 1, None))
            i -= 1
        else:
            ops.append(("ins", None, j - 1))
            j -= 1
    return ops[::-1]


def align(ref, hyp):
    """Anchor on long matches (fast for hour-long sessions), exact alignment between them."""
    ops = []
    matcher = difflib.SequenceMatcher(None, ref, hyp, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            ops += [("equal", i1 + k, j1 + k) for k in range(i2 - i1)]
        elif (i2 - i1) * (j2 - j1) <= 250_000:
            ops += [(op, None if i is None else i + i1, None if j is None else j + j1)
                    for op, i, j in edit_ops(ref[i1:i2], hyp[j1:j2])]
        else:  # a huge mismatch; don't spend minutes on it
            ops += [("del", i, None) for i in range(i1, i2)] + [("ins", None, j) for j in range(j1, j2)]
    return ops


# --- Report ---------------------------------------------------------------------------

def build_rows(ops, ref, owner, finals):
    """One row per final, plus rows for stretches of speech no caption covered."""
    rows = [dict(final=f, ops=[], missed=False, start=f["start"]) for f in finals]
    current, pending = None, []

    def place_pending(next_owner):
        if not pending:
            return
        if len(pending) >= MISSED_WORDS or (current is None and next_owner is None):
            times = [ref[i][2] for _, i, _ in pending if ref[i][2] is not None]
            ends = [ref[i][3] for _, i, _ in pending if ref[i][3] is not None]
            fallback = finals[current]["end"] if current is not None else 0.0
            rows.append(dict(final=None, ops=list(pending), missed=True,
                             start=min(times) if times else fallback, end=max(ends) if ends else fallback))
        else:
            rows[current if current is not None else next_owner]["ops"].extend(pending)
        pending.clear()

    for op in ops:
        if op[2] is None:
            pending.append(op)
            continue
        place_pending(owner[op[2]])
        current = owner[op[2]]
        rows[current]["ops"].append(op)
    place_pending(None)
    rows.sort(key=lambda r: r["start"])
    return rows


def render_side(row, ref, hyp, side):
    out = []
    for op, i, j in row["ops"]:
        if side == "live":
            if j is None:
                continue
            word = html.escape(hyp[j][1])
            if op == "equal":
                out.append(word)
            elif op == "sub":
                out.append(f'<mark class="sub" title="audio: {html.escape(ref[i][1])}">{word}</mark>')
            else:
                out.append(f'<mark class="ins" title="not in the audio">{word}</mark>')
        else:
            if i is None:
                continue
            word = html.escape(ref[i][1])
            if op == "equal":
                out.append(word)
            elif op == "sub":
                out.append(f'<mark class="sub" title="caption: {html.escape(hyp[j][1])}">{word}</mark>')
            else:
                out.append(f'<mark class="del" title="missing from the caption">{word}</mark>')
    return " ".join(out)


def clock(seconds):
    seconds = max(0, seconds)
    return f"{int(seconds // 3600)}:{int(seconds // 60 % 60):02d}:{seconds % 60:04.1f}" if seconds >= 3600 \
        else f"{int(seconds // 60)}:{seconds % 60:04.1f}"


def percentile(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))] if values else None


def write_report(path, wav, sidecar, archives, ref_label, ref, hyp, ops, rows, finals):
    counts = {k: sum(op == k for op, _, _ in ops) for k in ("equal", "sub", "del", "ins")}
    errors = counts["sub"] + counts["del"] + counts["ins"]
    wer = errors / max(1, len(ref))
    missed = [r for r in rows if r["missed"]]
    missed_seconds = sum(r["end"] - r["start"] for r in missed)
    timed = any(word[2] is not None for word in ref)
    latencies = [f["latency"] for f in finals if f["latency"] is not None]
    stats = [
        ("Word difference", f"{wer:.1%}", f"{errors:,} of {len(ref):,} words in the audio"),
        ("Wrong words", f"{counts['sub']:,}", "caption has a different word"),
        ("Missing words", f"{counts['del']:,}", "said but not captioned"),
        ("Extra words", f"{counts['ins']:,}", "captioned but not said"),
        ("Missed stretches", f"{len(missed)}", f"{MISSED_WORDS}+ words in a row"
         + (f", {missed_seconds:.0f} s in all" if timed else "")),
    ]
    if latencies:
        stats.append(("Final latency", f"{statistics.median(latencies):.2f} s",
                      f"median; p95 {percentile(latencies, 0.95):.2f} s over {len(latencies)} finals"))
    stat_html = "".join(f'<div class="stat"><div class="label">{a}</div><div class="value">{b}</div>'
                        f'<div class="note">{c}</div></div>' for a, b, c in stats)
    body = []
    for row in rows:
        diff = any(op != "equal" for op, _, _ in row["ops"])
        start = row["start"]
        time_cell = f'<button class="t" data-t="{max(0, start - 0.3):.2f}">{clock(start)}</button>'
        if row["missed"]:
            body.append(f'<tr class="missed diff" data-s="{start:.2f}"><td>{time_cell}</td>'
                        f'<td class="none">no caption</td><td>{render_side(row, ref, hyp, "ref")}</td><td></td></tr>')
            continue
        final = row["final"]
        meta = []
        if final["latency"] is not None:
            meta.append(f'{final["latency"]:.1f} s')
        if final["reason"]:
            meta.append(final["reason"].replace("_", " "))
        body.append(
            f'<tr class="{"diff" if diff else "same"}" data-s="{start:.2f}"><td>{time_cell}'
            f'<div class="meta">{html.escape(" · ".join(meta))}</div></td>'
            f'<td>{render_side(row, ref, hyp, "live")}</td><td>{render_side(row, ref, hyp, "ref")}</td>'
            f'<td class="es">{html.escape(final["translation"])}</td></tr>')
    archive_names = ", ".join(a.name for a in archives)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Caption check {html.escape(wav.stem)}</title>
<style>
:root {{ --bg:#fbfbfa; --fg:#1d1d1f; --muted:#6e6e73; --line:#e3e3e0; --card:#fff;
  --sub:#fde7b0; --del:#f9c8c8; --ins:#cfe3fb; --now:#eef6ee; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#161617; --fg:#ececec; --muted:#9a9aa0; --line:#2c2c2e;
  --card:#1f1f21; --sub:#6b5414; --del:#6e2626; --ins:#1f4470; --now:#203321; }} }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 -apple-system, system-ui, sans-serif; }}
header {{ position:sticky; top:0; background:var(--bg); border-bottom:1px solid var(--line); padding:12px 16px; z-index:1; }}
h1 {{ font-size:17px; margin:0 0 2px; }} .sub-h {{ color:var(--muted); font-size:13px; }}
audio {{ width:100%; margin-top:8px; }}
main {{ padding:16px; max-width:1300px; margin:auto; }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(170px, 1fr)); gap:10px; margin-bottom:12px; }}
.stat {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 12px; }}
.label {{ color:var(--muted); font-size:12px; }} .value {{ font-size:22px; font-weight:600; font-variant-numeric:tabular-nums; }}
.note {{ color:var(--muted); font-size:12px; }}
.legend {{ color:var(--muted); font-size:13px; margin:8px 0 12px; }} .legend label {{ margin-left:12px; }}
table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:10px; }}
th, td {{ text-align:left; vertical-align:top; padding:8px 10px; border-bottom:1px solid var(--line); }}
th {{ font-size:12px; color:var(--muted); font-weight:600; }}
td:first-child {{ white-space:nowrap; width:90px; }} .es {{ color:var(--muted); }}
.meta {{ color:var(--muted); font-size:11px; }} .none {{ color:var(--muted); font-style:italic; }}
button.t {{ font:inherit; font-variant-numeric:tabular-nums; border:0; background:none; color:#0a66d0; cursor:pointer; padding:0; }}
mark {{ color:inherit; border-radius:3px; padding:0 2px; }} mark.sub {{ background:var(--sub); }}
mark.del {{ background:var(--del); }} mark.ins {{ background:var(--ins); }}
tr.missed td {{ background:color-mix(in srgb, var(--del) 25%, transparent); }}
tr.now td {{ background:var(--now); }} body.only-diff tr.same {{ display:none; }}
@media (max-width:700px) {{ .es, th:last-child {{ display:none; }} td:first-child {{ width:60px; }} }}
</style></head><body>
<header><h1>Caption check: {html.escape(wav.stem)}</h1>
<div class="sub-h">Live captions vs {html.escape(ref_label)} · archive {html.escape(archive_names)}</div>
<audio controls preload="metadata" src="{html.escape(wav.name)}"></audio></header>
<main><div class="stats">{stat_html}</div>
<div class="legend"><mark class="sub">different word</mark> <mark class="del">said, not captioned</mark>
<mark class="ins">captioned, not said</mark> · hover a mark to see the other side
<label><input type="checkbox" id="only"> only lines with differences</label></div>
<table><thead><tr><th>Time</th><th>Live caption</th><th>In the audio ({html.escape(ref_label)})</th><th>Spanish</th></tr></thead>
<tbody>{"".join(body)}</tbody></table></main>
<script>
const audio = document.querySelector('audio');
const rows = [...document.querySelectorAll('tbody tr')];
document.addEventListener('click', e => {{
  const b = e.target.closest('button.t'); if (!b) return;
  audio.currentTime = +b.dataset.t; audio.play();
}});
document.getElementById('only').addEventListener('change', e => document.body.classList.toggle('only-diff', e.target.checked));
let last = null;
audio.addEventListener('timeupdate', () => {{
  let now = null;
  for (const r of rows) {{ if (+r.dataset.s <= audio.currentTime + 0.3) now = r; else break; }}
  if (now !== last) {{ last?.classList.remove('now'); now?.classList.add('now'); last = now; }}
}});
</script></body></html>
"""
    path.write_text(page, encoding="utf-8")
    return wer, counts, missed, missed_seconds if timed else None, latencies


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("recording", nargs="?", type=Path, help="a recordings/*.wav (default: the latest)")
    parser.add_argument("--recordings", type=Path, default=DEFAULT_RECORDINGS)
    parser.add_argument("--reference", type=Path, help="a trusted text transcript to compare against instead of Parakeet")
    parser.add_argument("--refresh", action="store_true", help="transcribe again even if cached")
    parser.add_argument("--no-open", action="store_true", help="don't open the report")
    args = parser.parse_args()

    wav = (args.recording or latest_recording(args.recordings)).resolve()
    sidecar = json.loads(wav.with_suffix(".json").read_text())
    rec_start = unix(sidecar["started_at"])
    import soundfile as sf
    duration = sf.info(str(wav)).duration
    finals, archives = live_finals(sidecar, rec_start, rec_start + duration)

    if args.reference:
        ref_label = args.reference.name
        ref = [(k, w, None, None) for k, w in words(args.reference.read_text())]
    else:
        ref_label = "Parakeet"
        ref = []
        for text, start, end in parakeet_words(wav, wav.with_suffix(".parakeet.json"), args.refresh):
            ref += [(k, w, start, end) for k, w in words(text)]
    hyp, owner = [], []
    for index, final in enumerate(finals):
        for k, w in words(final["original"]):
            hyp.append((k, w))
            owner.append(index)

    ops = align([r[0] for r in ref], [h[0] for h in hyp])
    rows = build_rows(ops, ref, owner, finals)
    report = wav.with_suffix(".compare.html")
    wer, counts, missed, missed_seconds, latencies = write_report(
        report, wav, sidecar, archives, ref_label, ref, hyp, ops, rows, finals)

    print(f"Recording   {wav.name}  ({duration / 60:.1f} min, archive {', '.join(a.name for a in archives)})")
    print(f"Words       {len(ref):,} in audio ({ref_label}), {len(hyp):,} captioned in {len(finals)} finals")
    print(f"Difference  {wer:.1%}  ({counts['sub']} wrong, {counts['del']} missing, {counts['ins']} extra)")
    print(f"Missed      {len(missed)} stretches of {MISSED_WORDS}+ words"
          + (f", {missed_seconds:.0f} s" if missed_seconds is not None else ""))
    if latencies:
        print(f"Latency     median {statistics.median(latencies):.2f} s, p95 {percentile(latencies, 0.95):.2f} s")
    print(f"Report      {report}")
    if not args.no_open:
        subprocess.run(["open", str(report)], check=False)


if __name__ == "__main__":
    main()
