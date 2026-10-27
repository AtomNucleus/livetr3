#!/usr/bin/env python3
"""Build sermon-v2: licensed English preaching and scripture-reading clips.

Seven clips of 1.5 to 2 minutes (12 minutes in all). Scripture: World English
Bible readings (public domain, from eBible.org and LibriVox), referenced to the
2005 WEB text they were read from (Project Gutenberg #8294), with the
public-domain Santa Biblia libre Latinoamericano as the Spanish reference.
Preaching: two Two Journeys Ministry sermons and one Desiring God episode,
used under their non-commercial permissions, and a public-domain White House
recording of a eulogy preached to a congregation; these have English
references only. Transcripts are the publishers' own human transcripts.

Each clip is cut inside a pause (times chosen once from Parakeet word timings
and the audio level), leveled like build_fleurs_eval.py, and written with its
references and a manifest (URL, license, sha256) into the ignored output.
Two Journeys and Desiring God block scripted page requests, so their
transcripts come from fixed Wayback Machine snapshots. Downloads are cached
in --sources and checked against the hashes below; nothing is committed.

Needs ffmpeg and the backend venv (numpy, soundfile):
  app/backend/.venv/bin/python -I script/build_sermon_eval.py --output dist/eval/sermon-v2
"""
import argparse
import hashlib
import html
import json
import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_fleurs_eval import NOISE_RMS, RATE, SPEECH_P95_RMS, frame_rms, level  # noqa: E402

PUBLIC = "public domain"
TWO_JOURNEYS = ("© Two Journeys Ministry; non-commercial use without fee or changes, with credit "
                "(https://twojourneys.org/copyright-policy/)")
DESIRING_GOD = ("By John Piper. © Desiring God Foundation. Source: desiringGod.org; personal or "
                "noncommercial use, audio not redistributed (https://www.desiringgod.org/permissions)")
AUDIO = {
    "ebible-mat18": dict(
        url="https://ebible.org/webaudio/Mat18.mp3",
        sha256="65f41d3ace8cf6bbaa175f8c6620dc694f31eeb392befad54aa92414a489dc47",
        license=PUBLIC, credit="World English Bible, read by Michael Paul Johnson (eBible.org)"),
    "librivox-psalms-81-90": dict(
        url="https://archive.org/download/bible_web_old_testament_0901_librivox2/oldtestament_070_worldenglishbible_64kb.mp3",
        sha256="77121c1e647e63c542e1c16e2d0ed041533b66b4eb4a40a2df5776a019eaff19",
        license=PUBLIC, credit="World English Bible, read by Sibella Denton (LibriVox)"),
    "librivox-1corinthians-12-16": dict(
        url="https://archive.org/download/web_new_testament_0811_librivox1/worldenglishbible2_33_1corinthians_64kb.mp3",
        sha256="c426b409bb5b73bf405d784ab7ef5d24e4d8d34c4ffd98fe17803c8bc831572a",
        license=PUBLIC, credit="World English Bible, read by William Healey (LibriVox)"),
    "twojourneys-2004-03-21": dict(
        url="https://twojourneys.org/wp-content/uploads/ekklesia360/0e7061250_1519935511_20040321a-the-secret-of-christian-contentment-part-1-andrew-m-davis-42414120553802.mp3",
        sha256="adb937c828f30d2579b59229cb690ca8e8830507947e8322e803c90a32542032",
        license=TWO_JOURNEYS, credit="Andy Davis, The Secret of Christian Contentment, Part 1 (2004)"),
    "twojourneys-2021-02-14": dict(
        url="https://twojourneys.org/wp-content/uploads/ekklesia360/0e11536234_1613336671_2-14-21-sermon-audio.mp3",
        sha256="2b3b4a414dc751a3d48de04d3b12014ca0913ef2103c6a598bbc8c098a71da6b",
        license=TWO_JOURNEYS, credit="Andy Davis, Healthy Churches Are Full of Love (2021)"),
    "desiringgod-apj-2294": dict(
        url="https://audio.desiringgod.org/resources/17849/media/86f2d0a8-21b4-4de0-a398-90fef54f0f99/20261001-en-the-gospel-before-jesus-died.mp3",
        sha256="20765e001ff6d8adf7a8590984a5c44cac7d5d359e202b79db30bb2a8decae0b",
        license=DESIRING_GOD, credit="John Piper, Ask Pastor John 2294: The Gospel Before Jesus Died (2026)"),
    "whitehouse-2015-06-26": dict(
        url="https://obamawhitehouse.archives.gov/videos/2015/June/062615_CharlestonSC.mp3",
        sha256="832ecf17cc8c53916dd180b4d271ef976a03112aba600f86b9518998835768e1",
        license=PUBLIC + " (U.S. government work)",
        credit="President Obama, eulogy for the Reverend Clementa Pinckney (2015)"),
}
# The readings follow the 2005 WEB wording ("reconcile accounts", "number our
# days"), not today's eBible text, so English verses come from that edition.
BIBLES = {
    "web2005": dict(url="https://www.gutenberg.org/cache/epub/8294/pg8294.txt",
                    license=PUBLIC, credit="World English Bible, 2005 text (Project Gutenberg #8294)"),
    "bll": dict(url="https://eBible.org/Scriptures/spabll_vpl.zip", member="spabll_vpl.txt",
                license=PUBLIC, credit="Santa Biblia libre Latinoamericano (eBible.org)"),
}
# Each transcript: page URL, and the raw-HTML markers that bound its text.
PAGES = {
    "twojourneys-2004-03-21": dict(
        url="https://web.archive.org/web/20241207175437id_/https://twojourneys.org/sermons/series/philippians/the-secret-of-christian-contentment-part-1-philippians-sermon-21-of-24/",
        within=('id="transcript" role="tabpanel"', 'id="notes" role="tabpanel"')),
    "twojourneys-2021-02-14": dict(
        url="https://web.archive.org/web/20250126121120id_/https://twojourneys.org/sermons/series/1-corinthians/healthy-churches-are-full-of-love-1-corinthians-sermon-69/",
        within=('id="transcript" role="tabpanel"', 'id="notes" role="tabpanel"')),
    "desiringgod-apj-2294": dict(
        url="https://web.archive.org/web/20261002015744id_/https://www.desiringgod.org/interviews/the-gospel-before-jesus-died",
        within=("Audio Transcript", None)),
    "whitehouse-2015-06-26": dict(
        url="https://obamawhitehouse.archives.gov/the-press-office/2015/06/26/remarks-president-eulogy-honorable-reverend-clementa-pinckney",
        within=(None, None)),
}
# Cut times are seconds into the ffmpeg decode of the source. Scripture
# references are verse ranges (plus the reader's announcement where the cut
# includes it); transcript references run from the first to the last phrase.
CLIPS = [
    dict(name="clip-01", kind="scripture", audio="ebible-mat18", start=166.80, end=266.57,
         english=("web2005", "Matthew 18:21-35"), spanish=("bll", "MAT 18:21-35")),
    dict(name="clip-02", kind="scripture", audio="librivox-psalms-81-90", start=910.75, end=1009.45,
         english=("web2005", "Psalms 90:1-17", "Psalm 90."), spanish=("bll", "PSA 90:1-17", "Salmo 90.")),
    dict(name="clip-03", kind="scripture", audio="librivox-1corinthians-12-16", start=271.80, end=392.30,
         english=("web2005", "1 Corinthians 13:1-13"), spanish=("bll", "1CO 13:1-13")),
    dict(name="clip-04", kind="preached", audio="twojourneys-2004-03-21", start=27.60, end=134.55,
         english=("twojourneys-2004-03-21", "We were looking, this morning", "rainy, icy. Discontent.")),
    dict(name="clip-05", kind="preached", audio="twojourneys-2021-02-14", start=460.02, end=551.85,
         english=("twojourneys-2021-02-14", "Now, this is the end of a long journey",
                  "final statements here under love.")),
    dict(name="clip-06", kind="preached", audio="desiringgod-apj-2294", start=327.40, end=437.65,
         english=("desiringgod-apj-2294", "Now, why is that good news?", "who is Christ the Lord”")),
    dict(name="clip-07", kind="preached", audio="whitehouse-2015-06-26", start=1160.50, end=1268.60,
         english=("whitehouse-2015-06-26", "According to the Christian tradition", "worthy of this gift.")),
]
# Page and Bible downloads are recorded but not pinned, since a snapshot can be
# re-served with new markup; the extracted references are, so changed wording
# fails the build.
REFERENCE_SHA256 = {
    "clip-01.en": "e0220239d1708ec3257e97006610d6f28ffe837a391cbe71cd3714e75e1b9bd5",
    "clip-01.es": "8bc327735cc9403d1ae0a869e29beb12e89e5aae12a0fcfe8ace39894d02cb67",
    "clip-02.en": "67c7f1560e5cdeac334acc96b3a8261cbb6e5d4a75cd9cd3f548f2e1e0256117",
    "clip-02.es": "fd5a213eb11816dc8026d85369cb6b261d5876bbe1128a05848a2c2624573c15",
    "clip-03.en": "edf7016bc5f679eae3d5ae5363e91ed59821e14b596f8d415266702259daa15c",
    "clip-03.es": "f60b2eb3567d419d445c3f02e9b25854c3e1295790c123930a5a0225833e2175",
    "clip-04.en": "459823b70acc8b3d6ab700f1b3bd90f0984cca5a7b6add3c6847aeb19d9fbc9b",
    "clip-05.en": "5cd0f395a70b3108f1dc74453d2069de0b4806bdc1170577ceb71a5c3cbb99b5",
    "clip-06.en": "5a7b706fa4f5e2953ba9354f07a094b735ff251fefe9fb781c66a04ffc1046a5",
    "clip-07.en": "522b45be22aacbfef34be4b7f6a24b2d5a614853b0e69846d07af21ab0ec114f",
}


def fetch(url, path, sha256=None):
    if not path.exists():
        request = urllib.request.Request(url, headers={"User-Agent": "LiveTR3 eval builder (non-commercial)"})
        with urllib.request.urlopen(request, timeout=300) as response:
            data = response.read()
        path.write_bytes(data)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if sha256 and digest != sha256:
        raise ValueError(f"{path.name} changed upstream: sha256 {digest}, expected {sha256}")
    return digest


def decode(path):
    # ffmpeg, not libsndfile: libsndfile's MP3 reads disagree on these files.
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(RATE),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def verses(text, selector):
    book, chapter, first, last = re.fullmatch(r"(.+) (\d+):(\d+)-(\d+)", selector).groups()
    wanted = range(int(first), int(last) + 1)
    if text.lstrip("\ufeff").startswith("The Project Gutenberg"):
        # "Book 46 1 Corinthians", then "013:001 If I speak ..." with wrapped
        # lines and {footnotes}; Psalm titles are marked <<...>>.
        body = re.split(rf"^Book \d\d {re.escape(book)}\s*$", text, flags=re.M)[1]
        body = re.split(r"^Book \d\d ", body, flags=re.M)[0]
        found = {int(m[2]): m[3] for m in re.finditer(r"^(\d{3}):(\d{3}) (.*?)(?=^\d{3}:\d{3} |\Z)", body, re.M | re.S)
                 if int(m[1]) == int(chapter) and int(m[2]) in wanted}
        found = {k: re.sub(r"\{[^}]*\}|<<|>>", "", v) for k, v in found.items()}
    else:
        found = {}
        for line in text.splitlines():
            match = re.match(r"(\S+) (\d+):(\d+) (.*)", line)
            if match and match[1] == book and match[2] == chapter and int(match[3]) in wanted:
                found[int(match[3])] = match[4]
    if sorted(found) != list(wanted):
        raise ValueError(f"Missing verses in {selector}")
    return re.sub(r"\s+", " ", " ".join(found[k] for k in wanted)).strip()


def transcript(raw, within, first, last):
    begin = raw.index(within[0]) if within[0] else 0
    raw = raw[begin: raw.index(within[1], begin) if within[1] else None]
    paragraphs = [html.unescape(re.sub(r"<[^>]+>", "", p)) for p in re.findall(r"<p[^>]*>(.*?)</p>", raw, re.S)]
    text = re.sub(r"\s+", " ", " ".join(paragraphs))
    begin = text.index(first)
    text = text[begin: text.index(last, begin) + len(last)]
    # Drop stage directions and editors' citations such as "(Applause.)" and
    # "(Mark 1:15)"; keep bracketed words, which the speakers said.
    text = re.sub(r"\([^)]*\)", " ", text).replace("[", "").replace("]", "")
    return re.sub(r"\s+", " ", text).strip()


def reference(spec, bibles, pages):
    if spec[0] in BIBLES:
        return " ".join([*spec[2:], verses(bibles[spec[0]], spec[1])])
    return transcript(pages[spec[0]], PAGES[spec[0]]["within"], *spec[1:])


def main(args):
    args.output.mkdir(parents=True, exist_ok=True)
    sources = args.sources or args.output.with_name(args.output.name + "-sources")
    sources.mkdir(parents=True, exist_ok=True)
    manifest = dict(name="sermon-v2", builder="script/build_sermon_eval.py",
                    level=dict(speech_p95_rms=SPEECH_P95_RMS, noise_rms=NOISE_RMS), sources={}, clips=[])
    for key, spec in AUDIO.items():
        manifest["sources"][key] = dict(spec, sha256=fetch(spec["url"], sources / f"{key}.mp3", spec["sha256"]))
    bibles, pages = {}, {}
    for key, spec in BIBLES.items():
        path = sources / (key + Path(spec["url"]).suffix)
        digest = fetch(spec["url"], path)
        if "member" in spec:
            with zipfile.ZipFile(path) as archive:
                bibles[key] = archive.read(spec["member"]).decode("utf-8")
        else:
            bibles[key] = path.read_text(encoding="utf-8")
        manifest["sources"][key] = dict(spec, sha256=digest)
    for key, spec in PAGES.items():
        digest = fetch(spec["url"], sources / f"{key}.html")
        pages[key] = (sources / f"{key}.html").read_text(encoding="utf-8", errors="replace")
        manifest["sources"][key + "-transcript"] = dict(url=spec["url"], license=AUDIO[key]["license"], sha256=digest)
    decoded = {}
    for index, clip in enumerate(CLIPS):
        if clip["audio"] not in decoded:
            decoded[clip["audio"]] = decode(sources / f"{clip['audio']}.mp3")
        audio = level(decoded[clip["audio"]][round(clip["start"] * RATE): round(clip["end"] * RATE)])
        # Raise the recording's own floor to the live room floor, as FLEURS does.
        floor = float(np.percentile(frame_rms(audio), 5))
        noise = float(np.sqrt(max(0.0, NOISE_RMS ** 2 - floor ** 2)))
        audio = audio + np.random.default_rng(index).normal(0, noise, audio.size).astype(np.float32)
        name = clip["name"]
        sf.write(args.output / f"{name}.wav", audio, RATE, subtype="PCM_16")
        entry = dict(name=name, kind=clip["kind"], credit=AUDIO[clip["audio"]]["credit"],
                     license=AUDIO[clip["audio"]]["license"], audio_source=clip["audio"],
                     start_seconds=clip["start"], end_seconds=clip["end"], seconds=round(audio.size / RATE, 3),
                     floor_rms=round(floor, 6), added_noise_rms=round(noise, 6),
                     sha256=hashlib.sha256((args.output / f"{name}.wav").read_bytes()).hexdigest())
        for lang, suffix in (("english", "en"), ("spanish", "es")):
            if lang not in clip:
                continue
            text = reference(clip[lang], bibles, pages)
            key = f"{name}.{suffix}"
            digest = hashlib.sha256(text.encode()).hexdigest()
            if REFERENCE_SHA256 and REFERENCE_SHA256.get(key) != digest:
                raise ValueError(f"{key} reference changed upstream: sha256 {digest}")
            (args.output / f"{key}.txt").write_text(text + "\n")
            entry[lang] = dict(source=clip[lang][0], selector=" … ".join(clip[lang][1:]),
                               words=len(text.split()), sha256=digest)
        manifest["clips"].append(entry)
        print(f"{name}: {entry['seconds']:.1f} s, {clip['kind']}, {entry['english']['words']} words, "
              f"floor {floor:.5f}, {entry['credit']}")
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"{sum(c['seconds'] for c in manifest['clips']) / 60:.1f} min in {len(CLIPS)} clips")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sources", type=Path, help="Download cache; default: <output>-sources")
    main(parser.parse_args())
