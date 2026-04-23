import type { TranscriptUtterance } from "./protocol";

function pad(num: number, size = 2): string {
  return String(num).padStart(size, "0");
}

function formatSrtTime(seconds: number): string {
  const ms = Math.floor((seconds % 1) * 1000);
  const whole = Math.floor(seconds);
  const s = whole % 60;
  const m = Math.floor(whole / 60) % 60;
  const h = Math.floor(whole / 3600);
  return `${pad(h)}:${pad(m)}:${pad(s)},${pad(ms, 3)}`;
}

function formatVttTime(seconds: number): string {
  return formatSrtTime(seconds).replace(",", ".");
}

function download(name: string, contents: string, type: string): void {
  const blob = new Blob([contents], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  window.setTimeout(() => {
    anchor.remove();
    URL.revokeObjectURL(url);
  }, 30_000);
}

function committed(entries: TranscriptUtterance[]): TranscriptUtterance[] {
  return entries.filter((entry) => entry.state !== "partial" && entry.original.trim());
}

export function exportTxt(entries: TranscriptUtterance[], source: string, target: string): void {
  const body = committed(entries)
    .map((entry) => `${source}: ${entry.original}\n${target}: ${entry.translation}`)
    .join("\n\n");
  download("livetr3-transcript.txt", body + "\n", "text/plain;charset=utf-8");
}

export function exportSrt(entries: TranscriptUtterance[], source: string, target: string): void {
  const body = committed(entries)
    .map((entry, index) => {
      const start = Math.max(0, (entry.startedAt - entries[0].startedAt) / 1000);
      const end = Math.max(start + 1, ((entry.endedAt ?? Date.now()) - entries[0].startedAt) / 1000);
      return `${index + 1}\n${formatSrtTime(start)} --> ${formatSrtTime(end)}\n${source}: ${
        entry.original
      }\n${target}: ${entry.translation}`;
    })
    .join("\n\n");
  download("livetr3-transcript.srt", body + "\n", "application/x-subrip;charset=utf-8");
}

export function exportVtt(entries: TranscriptUtterance[], source: string, target: string): void {
  const cues = committed(entries)
    .map((entry) => {
      const start = Math.max(0, (entry.startedAt - entries[0].startedAt) / 1000);
      const end = Math.max(start + 1, ((entry.endedAt ?? Date.now()) - entries[0].startedAt) / 1000);
      return `${formatVttTime(start)} --> ${formatVttTime(end)}\n${source}: ${
        entry.original
      }\n${target}: ${entry.translation}`;
    })
    .join("\n\n");
  download("livetr3-transcript.vtt", `WEBVTT\n\n${cues}\n`, "text/vtt;charset=utf-8");
}

export function exportAll(entries: TranscriptUtterance[], source: string, target: string): void {
  exportTxt(entries, source, target);
  exportSrt(entries, source, target);
  exportVtt(entries, source, target);
}
