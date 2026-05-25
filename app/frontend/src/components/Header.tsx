import { useEffect, useState } from "react";
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
  partialTickAt: number;
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
  partialTickAt,
  settingsOpen,
  setSettingsOpen,
}: Props) {
  const [partialPulseActive, setPartialPulseActive] = useState(false);

  useEffect(() => {
    if (!partialTickAt) return;
    setPartialPulseActive(true);
    const timeout = window.setTimeout(() => setPartialPulseActive(false), 150);
    return () => window.clearTimeout(timeout);
  }, [partialTickAt]);

  const update = <K extends keyof ClientConfig>(key: K, value: ClientConfig[K]) =>
    setConfig({ ...config, [key]: value });

  const controlClass =
    "h-9 rounded-md border border-line bg-ink px-2.5 text-sm text-zinc-100 outline-none focus:border-mint";
  const secondaryButtonClass =
    "min-h-9 rounded-md border border-line bg-panel px-3 py-1.5 text-sm font-medium text-zinc-100 disabled:opacity-45";
  const headerButtonClass =
    "min-h-10 rounded-md border border-line bg-panel px-3 py-2 text-sm font-semibold text-zinc-100 disabled:opacity-45";
  const settingsSectionClass = "grid gap-3 border-b border-line pb-4 last:border-b-0 last:pb-0";
  const sectionHeadingClass = "text-xs font-semibold uppercase text-zinc-500";

  return (
    <header data-testid="header-bar" className="relative z-20 border-b border-line bg-shell">
      <div className="grid min-h-[76px] grid-cols-[minmax(220px,0.9fr)_minmax(300px,1fr)_auto] items-center gap-4 px-5 py-3 max-lg:grid-cols-1">
        <div className="min-w-0">
          <div className="text-xs font-semibold uppercase text-zinc-500">Operator</div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-zinc-300">
            <span className="inline-flex items-center gap-2 font-semibold text-zinc-100">
              <span
                className={[
                  "h-2.5 w-2.5 rounded-full",
                  status === "running" ? "bg-mint" : status === "connecting" ? "bg-amber-300" : "bg-zinc-500",
                ].join(" ")}
              />
              {status === "running" ? "Live" : status === "connecting" ? "Connecting" : "Ready"}
            </span>
            <span className="text-zinc-600">/</span>
            <span className="truncate">
              {config.source_lang} to {config.target_lang}
            </span>
          </div>
        </div>

        <div className="flex min-w-0 items-center justify-center gap-4 max-lg:justify-start">
          <WaveformMeter levels={levels} rms={rms} />
          <div className="flex items-center gap-2 whitespace-nowrap text-xs font-semibold uppercase text-zinc-400">
            <span
              data-testid="partial-tick-indicator"
              aria-label="Partial activity"
              className={[
                "h-2.5 w-2.5 rounded-full bg-mint transition-opacity duration-150",
                partialPulseActive ? "opacity-100" : "opacity-20",
              ].join(" ")}
            />
            Partials
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 max-lg:justify-start">
          <button
            data-testid="start-stop-button"
            className="min-h-10 rounded-md bg-mint px-5 py-2 text-sm font-semibold text-black disabled:opacity-45"
            type="button"
            onClick={onStartStop}
            disabled={status === "connecting"}
          >
            {status === "running" ? "End" : status === "connecting" ? "Connecting" : "Start"}
          </button>
          <button
            data-testid="pause-resume-button"
            className={headerButtonClass}
            type="button"
            onClick={onPauseResume}
            disabled={status !== "running"}
          >
            {paused ? "Resume" : "Pause"}
          </button>
          <button
            data-testid="settings-toggle"
            aria-expanded={settingsOpen}
            className={headerButtonClass}
            type="button"
            onClick={() => setSettingsOpen(!settingsOpen)}
          >
            Settings
          </button>
        </div>
      </div>

      {settingsOpen ? (
        <div data-testid="settings-panel" className="absolute right-5 top-[calc(100%+8px)] grid max-h-[calc(100vh-110px)] w-[min(920px,calc(100vw-40px))] gap-4 overflow-auto rounded-lg border border-line bg-shell p-4 shadow-2xl">
          <section aria-labelledby="language-settings-heading" className={settingsSectionClass}>
            <h2 id="language-settings-heading" className={sectionHeadingClass}>
              Caption setup
            </h2>
            <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]">
              <label data-testid="source-language-control" className="grid gap-2 text-sm text-zinc-300">
                Source language
                <select
                  data-testid="source-language-input"
                  className={controlClass}
                  value={config.source_lang}
                  onChange={(event) => update("source_lang", event.target.value)}
                >
                  {languages.map((language) => (
                    <option key={language} value={language}>
                      {language}
                    </option>
                  ))}
                </select>
              </label>
              <button
                data-testid="swap-direction-button"
                type="button"
                className={`${secondaryButtonClass} self-end`}
                disabled={status !== "running"}
                onClick={onSwapDirection}
              >
                Swap next
              </button>
              <label data-testid="target-language-control" className="grid gap-2 text-sm text-zinc-300">
                Target language
                <select
                  data-testid="target-language-input"
                  className={controlClass}
                  value={config.target_lang}
                  onChange={(event) => update("target_lang", event.target.value)}
                >
                  {languages.map((language) => (
                    <option key={language} value={language}>
                      {language}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </section>

          <section aria-labelledby="audio-settings-heading" className={settingsSectionClass}>
            <h2 id="audio-settings-heading" className={sectionHeadingClass}>
              Input
            </h2>
            <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto_auto]">
              <label data-testid="mic-selector-label" className="grid gap-2 text-sm text-zinc-300">
                Mic
                <select
                  data-testid="mic-selector"
                  className={controlClass}
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

              <div data-testid="segmenter-status" className="self-end pb-2 text-sm text-zinc-300">
                VAD: Silero
              </div>
              <label data-testid="polish-toggle-control" className="flex items-end gap-2 pb-2 text-sm text-zinc-300">
                <input
                  data-testid="polish-toggle"
                  type="checkbox"
                  checked={config.polish_enabled}
                  onChange={(event) => update("polish_enabled", event.target.checked)}
                />
                Polish finals
              </label>
              <label data-testid="asr-correction-toggle-control" className="flex items-end gap-2 pb-2 text-sm text-zinc-300">
                <input
                  data-testid="asr-correction-toggle"
                  type="checkbox"
                  checked={config.asr_correction_enabled ?? true}
                  onChange={(event) => update("asr_correction_enabled", event.target.checked)}
                />
                Correct finalized ASR
              </label>
              <label data-testid="bilingual-context-toggle-control" className="flex items-end gap-2 pb-2 text-sm text-zinc-300">
                <input
                  data-testid="bilingual-context-toggle"
                  type="checkbox"
                  checked={Boolean(config.bilingual_context_enabled)}
                  onChange={(event) => update("bilingual_context_enabled", event.target.checked)}
                />
                Learn bilingual context
              </label>
              <label data-testid="transcript-learning-toggle-control" className="flex items-end gap-2 pb-2 text-sm text-zinc-300">
                <input
                  data-testid="transcript-learning-toggle"
                  type="checkbox"
                  checked={config.transcript_learning_enabled ?? true}
                  onChange={(event) => update("transcript_learning_enabled", event.target.checked)}
                />
                Learn from transcript
              </label>
            </div>
          </section>

          <section aria-labelledby="display-settings-heading" className={settingsSectionClass}>
            <h2 id="display-settings-heading" className={sectionHeadingClass}>
              Output
            </h2>
            <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
              <label data-testid="projector-font-control" className="grid gap-2 text-sm text-zinc-300">
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

              <button
                data-testid="open-projector-button"
                className="self-end rounded-lg border border-mint px-4 py-2 text-sm font-semibold text-mint"
                type="button"
                onClick={onOpenProjector}
              >
                Open Projector
              </button>
            </div>
          </section>

          <section aria-labelledby="session-actions-heading" className={settingsSectionClass}>
            <h2 id="session-actions-heading" className={sectionHeadingClass}>
              Live session actions
            </h2>
            <div className="flex flex-wrap gap-2">
              <button
                data-testid="commit-now-button"
                type="button"
                className={secondaryButtonClass}
                disabled={status !== "running"}
                onClick={onCommitNow}
              >
                Commit Now
              </button>
              <button
                data-testid="skip-polish-button"
                type="button"
                className={secondaryButtonClass}
                disabled={status !== "running" || !config.polish_enabled}
                onClick={onSkipNextPolish}
              >
                Skip Next Polish
              </button>
              <button
                data-testid="clear-button"
                className={secondaryButtonClass}
                type="button"
                onClick={onClear}
              >
                Clear Transcript
              </button>
            </div>
          </section>

          <section aria-labelledby="export-actions-heading" className={settingsSectionClass}>
            <h2 id="export-actions-heading" className={sectionHeadingClass}>
              Export
            </h2>
            <div className="flex flex-wrap gap-2">
              <button
                data-testid="export-txt-button"
                className={secondaryButtonClass}
                type="button"
                onClick={onExportTxt}
              >
                TXT
              </button>
              <button
                data-testid="export-srt-button"
                className={secondaryButtonClass}
                type="button"
                onClick={onExportSrt}
              >
                SRT
              </button>
              <button
                data-testid="export-vtt-button"
                className={secondaryButtonClass}
                type="button"
                onClick={onExportVtt}
              >
                VTT
              </button>
            </div>
          </section>

          <details data-testid="custom-vocab-disclosure" className={settingsSectionClass}>
            <summary className={`${sectionHeadingClass} cursor-pointer`}>
              Custom vocabulary
            </summary>
            <label data-testid="custom-vocab-control" className="mt-3 grid gap-2 text-sm text-zinc-300">
              Vocabulary hints
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
          </details>

          <details data-testid="advanced-timing-disclosure" className={settingsSectionClass}>
            <summary className={`${sectionHeadingClass} cursor-pointer`}>
              Advanced timing
            </summary>
            <div className="mt-3 grid gap-3 md:grid-cols-3">
              <label className="flex items-center gap-2 text-sm text-zinc-300 md:col-span-3">
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
                  min="0.3"
                  max="3"
                  step="0.05"
                  className={controlClass}
                  value={config.partial_interval_seconds ?? 0.75}
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
                  className={controlClass}
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
                  className={controlClass}
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
                  className={controlClass}
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
                  className={controlClass}
                  value={config.min_silence_ms ?? 400}
                  onChange={(event) => update("min_silence_ms", Number(event.target.value))}
                />
              </label>
            </div>
          </details>

        </div>
      ) : null}
    </header>
  );
}
