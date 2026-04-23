import type { ClientConfig } from "../lib/protocol";
import { languages } from "../lib/protocol";
import { WaveformMeter } from "./WaveformMeter";

interface Props {
  config: ClientConfig;
  setConfig: (
    next: ClientConfig,
    applyTarget?: "immediate" | "next_utterance",
  ) => void;
  devices: MediaDeviceInfo[];
  selectedDeviceId: string;
  setSelectedDeviceId: (id: string) => void;
  status: "idle" | "connecting" | "running";
  paused: boolean;
  onStartStop: () => void;
  onPauseResume: () => void;
  onCommitNow: () => void;
  onSwapDirection: () => void;
  onSkipNextPolish: () => void;
  onExportTxt: () => void;
  onExportSrt: () => void;
  onExportVtt: () => void;
  onOpenProjector: () => void;
  onClear: () => void;
  levels: number[];
  rms: number;
  projectorFontSize: number;
  setProjectorFontSize: (size: number) => void;
  settingsOpen: boolean;
  setSettingsOpen: (open: boolean) => void;
}

export function Header({
  config,
  setConfig,
  devices,
  selectedDeviceId,
  setSelectedDeviceId,
  status,
  paused,
  onStartStop,
  onPauseResume,
  onCommitNow,
  onSwapDirection,
  onSkipNextPolish,
  onExportTxt,
  onExportSrt,
  onExportVtt,
  onOpenProjector,
  onClear,
  levels,
  rms,
  projectorFontSize,
  setProjectorFontSize,
  settingsOpen,
  setSettingsOpen,
}: Props) {
  const update = <K extends keyof ClientConfig>(key: K, value: ClientConfig[K]) =>
    setConfig({ ...config, [key]: value });

  return (
    <header data-testid="header-bar" className="border-b border-line bg-[#0c0d0b]">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        <button
          data-testid="settings-toggle"
          className="rounded-md border border-line px-3 py-2 text-sm text-zinc-100"
          type="button"
          onClick={() => setSettingsOpen(!settingsOpen)}
        >
          Settings
        </button>

        <WaveformMeter levels={levels} rms={rms} />

        <div className="flex items-center gap-2">
          <button
            data-testid="clear-button"
            className="rounded-md border border-line px-3 py-2 text-sm text-zinc-100"
            type="button"
            onClick={onClear}
          >
            Clear
          </button>
          <button
            data-testid="open-projector-button"
            className="rounded-md border border-mint px-3 py-2 text-sm text-mint"
            type="button"
            onClick={onOpenProjector}
          >
            Open Projector Window
          </button>
          <button
            data-testid="export-txt-button"
            className="rounded-md border border-line px-3 py-2 text-sm text-zinc-100"
            type="button"
            onClick={onExportTxt}
          >
            TXT
          </button>
          <button
            data-testid="export-srt-button"
            className="rounded-md border border-line px-3 py-2 text-sm text-zinc-100"
            type="button"
            onClick={onExportSrt}
          >
            SRT
          </button>
          <button
            data-testid="export-vtt-button"
            className="rounded-md border border-line px-3 py-2 text-sm text-zinc-100"
            type="button"
            onClick={onExportVtt}
          >
            VTT
          </button>
          <button
            data-testid="start-stop-button"
            className="rounded-md bg-mint px-6 py-3 text-base font-semibold text-black disabled:opacity-60"
            type="button"
            onClick={onStartStop}
            disabled={status === "connecting"}
          >
            {status === "running" ? "Stop" : status === "connecting" ? "Connecting" : "Start"}
          </button>
          <button
            data-testid="pause-resume-button"
            className="rounded-md border border-line px-4 py-3 text-sm text-zinc-100 disabled:opacity-60"
            type="button"
            onClick={onPauseResume}
            disabled={status !== "running"}
          >
            {paused ? "Resume" : "Pause"}
          </button>
        </div>
      </div>

      {settingsOpen ? (
        <div data-testid="settings-panel" className="grid gap-4 border-t border-line px-5 py-4 md:grid-cols-3">
          <label data-testid="mic-selector-label" className="grid gap-2 text-sm text-zinc-300">
            Mic
            <select
              data-testid="mic-selector"
              className="rounded-md border border-line bg-ink px-3 py-2 text-zinc-100"
              value={selectedDeviceId}
              onChange={(event) => setSelectedDeviceId(event.target.value)}
            >
              <option value="">System default</option>
              {devices.map((device) => (
                <option key={device.deviceId} value={device.deviceId}>
                  {device.label || `Microphone ${device.deviceId.slice(0, 6)}`}
                </option>
              ))}
            </select>
          </label>

          <label data-testid="source-language-control" className="grid gap-2 text-sm text-zinc-300">
            Source language
            <input
              data-testid="source-language-input"
              list="source-languages"
              className="rounded-md border border-line bg-ink px-3 py-2 text-zinc-100"
              value={config.source_lang}
              onChange={(event) => update("source_lang", event.target.value)}
            />
            <datalist id="source-languages">
              {languages.map((language) => (
                <option key={language} value={language} />
              ))}
            </datalist>
          </label>

          <label data-testid="target-language-control" className="grid gap-2 text-sm text-zinc-300">
            Target language
            <input
              data-testid="target-language-input"
              list="target-languages"
              className="rounded-md border border-line bg-ink px-3 py-2 text-zinc-100"
              value={config.target_lang}
              onChange={(event) => update("target_lang", event.target.value)}
            />
            <datalist id="target-languages">
              {languages.map((language) => (
                <option key={language} value={language} />
              ))}
            </datalist>
          </label>

          <label data-testid="custom-vocab-control" className="grid gap-2 text-sm text-zinc-300 md:col-span-3">
            Custom vocabulary
            <textarea
              data-testid="custom-vocab-textarea"
              className="min-h-20 rounded-md border border-line bg-ink px-3 py-2 text-zinc-100"
              value={config.custom_vocab.join(", ")}
              onChange={(event) =>
                update(
                  "custom_vocab",
                  event.target.value
                    .split(",")
                    .map((item) => item.trim())
                    .filter(Boolean),
                )
              }
            />
          </label>

          <div data-testid="segmenter-status" className="text-sm text-zinc-300">
            VAD: Silero
          </div>

          <label data-testid="polish-toggle-control" className="flex items-center gap-2 text-sm text-zinc-300">
            <input
              data-testid="polish-toggle"
              type="checkbox"
              checked={config.polish_enabled}
              onChange={(event) => update("polish_enabled", event.target.checked)}
            />
            Polish final captions
          </label>

          <label className="flex items-center gap-2 text-sm text-zinc-300">
            <input
              data-testid="code-switch-toggle"
              type="checkbox"
              checked={Boolean(config.code_switching_enabled)}
              onChange={(event) => update("code_switching_enabled", event.target.checked)}
            />
            Code-switch aware prompting
          </label>

          <label className="grid gap-2 text-sm text-zinc-300">
            Partial interval (s)
            <input
              data-testid="partial-interval-input"
              type="number"
              min="0.5"
              max="10"
              step="0.5"
              className="rounded-md border border-line bg-ink px-3 py-2 text-zinc-100"
              value={config.partial_interval_seconds ?? 2}
              onChange={(event) => update("partial_interval_seconds", Number(event.target.value))}
            />
          </label>

          <label className="grid gap-2 text-sm text-zinc-300">
            Max utterance (s)
            <input
              data-testid="max-utterance-input"
              type="number"
              min="5"
              max="29"
              step="1"
              className="rounded-md border border-line bg-ink px-3 py-2 text-zinc-100"
              value={config.max_utterance_seconds ?? 25}
              onChange={(event) => update("max_utterance_seconds", Number(event.target.value))}
            />
          </label>

          <label className="grid gap-2 text-sm text-zinc-300">
            Silero threshold
            <input
              data-testid="silero-threshold-input"
              type="number"
              min="0.1"
              max="0.95"
              step="0.05"
              className="rounded-md border border-line bg-ink px-3 py-2 text-zinc-100"
              value={config.silero_threshold ?? 0.5}
              onChange={(event) => update("silero_threshold", Number(event.target.value))}
            />
          </label>

          <label className="grid gap-2 text-sm text-zinc-300">
            Speech pad (ms)
            <input
              data-testid="speech-pad-input"
              type="number"
              min="0"
              max="2000"
              step="50"
              className="rounded-md border border-line bg-ink px-3 py-2 text-zinc-100"
              value={config.speech_pad_ms ?? 300}
              onChange={(event) => update("speech_pad_ms", Number(event.target.value))}
            />
          </label>

          <label className="grid gap-2 text-sm text-zinc-300">
            Min silence (ms)
            <input
              data-testid="min-silence-input"
              type="number"
              min="100"
              max="5000"
              step="50"
              className="rounded-md border border-line bg-ink px-3 py-2 text-zinc-100"
              value={config.min_silence_ms ?? 400}
              onChange={(event) => update("min_silence_ms", Number(event.target.value))}
            />
          </label>

          <div className="flex flex-wrap gap-2 md:col-span-3">
            <button
              data-testid="commit-now-button"
              type="button"
              className="rounded-md border border-line px-3 py-2 text-sm text-zinc-100 disabled:opacity-60"
              disabled={status !== "running"}
              onClick={onCommitNow}
            >
              Commit Now
            </button>
            <button
              data-testid="swap-direction-button"
              type="button"
              className="rounded-md border border-line px-3 py-2 text-sm text-zinc-100 disabled:opacity-60"
              disabled={status !== "running"}
              onClick={onSwapDirection}
            >
              Queue EN/ES Swap
            </button>
            <button
              data-testid="skip-polish-button"
              type="button"
              className="rounded-md border border-line px-3 py-2 text-sm text-zinc-100 disabled:opacity-60"
              disabled={status !== "running" || !config.polish_enabled}
              onClick={onSkipNextPolish}
            >
              Skip Next Polish
            </button>
          </div>

          <label data-testid="projector-font-control" className="grid gap-2 text-sm text-zinc-300 md:col-span-2">
            Projector font size
            <div className="flex items-center gap-3">
              <input
                data-testid="projector-font-slider"
                type="range"
                min="36"
                max="144"
                step="2"
                value={projectorFontSize}
                onChange={(event) => setProjectorFontSize(Number(event.target.value))}
                className="w-full"
              />
              <span className="w-14 text-right text-xs text-zinc-400">{projectorFontSize}px</span>
            </div>
          </label>
        </div>
      ) : null}
    </header>
  );
}
