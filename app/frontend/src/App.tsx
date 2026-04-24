import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";
import { DualPane } from "./components/DualPane";
import { Header } from "./components/Header";
import { useAudioCapture } from "./hooks/useAudioCapture";
import { useTranscriptStore } from "./hooks/useTranscriptStore";
import { exportSrt, exportTxt, exportVtt } from "./lib/exports";
import {
  getOrCreateSessionId,
  openProjectorWindow,
  readProjectorFontSize,
  writeProjectorFontSize,
} from "./lib/projector";
import type { ClientConfig } from "./lib/protocol";

const CUSTOM_VOCAB_STORAGE_KEY = "livetr3.custom-vocab";

declare global {
  interface Window {
    webkitAudioContext?: typeof AudioContext;
    __livetr3LastOperatorFinalRender?: {
      id: number;
      text: string;
      at: number;
    };
  }
}

export default function App() {
  const [sessionId] = useState(() => getOrCreateSessionId());
  const [config, setConfigState] = useState<ClientConfig>(() => {
    const storedVocab = window.localStorage.getItem(CUSTOM_VOCAB_STORAGE_KEY);
    const customVocab = storedVocab
      ? storedVocab
          .split("\n")
          .map((item) => item.trim())
          .filter(Boolean)
      : ["Surreal", "Amy", "Morgan"];
    return {
      version: 2,
      source_lang: "English",
      target_lang: "Spanish",
      custom_vocab: customVocab,
      segmenter: "silero",
      polish_enabled: true,
      code_switching_enabled: false,
      partial_interval_seconds: 2,
      max_utterance_seconds: 25,
      silero_threshold: 0.5,
      speech_pad_ms: 300,
      min_silence_ms: 400,
    };
  });
  const [selectedDeviceId, setSelectedDeviceId] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(true);
  const [levels, setLevels] = useState<number[]>(Array(10).fill(0));
  const [projectorFontSize, setProjectorFontSize] = useState(() => readProjectorFontSize(sessionId));
  const { entries, lastError, workerStatus, handleServerMessage, clear } = useTranscriptStore();

  const onWaveform = useCallback((rms: number) => {
    setLevels((current) => [...current.slice(-9), rms]);
  }, []);

  const audio = useAudioCapture({ onServerMessage: handleServerMessage, onWaveform });
  const rms = levels.at(-1) ?? 0;
  const selectedDevice = audio.devices.find((device) => device.deviceId === selectedDeviceId);

  const makeLiveConfig = useCallback(
    (
      next: ClientConfig,
      applyTarget: "immediate" | "next_utterance" = "immediate",
    ): ClientConfig => ({
      ...next,
      version: 2,
      apply_target: applyTarget,
      input_device_id: selectedDeviceId || null,
      input_device_label: selectedDevice?.label || null,
    }),
    [selectedDevice?.label, selectedDeviceId],
  );

  const setConfig = useCallback(
    (
      next: ClientConfig,
      applyTarget: "immediate" | "next_utterance" = "immediate",
    ) => {
      const normalized = { ...next, version: 2, apply_target: "immediate" as const };
      setConfigState(normalized);
      if (audio.status === "running") {
        audio.sendConfig(makeLiveConfig(normalized, applyTarget));
      }
    },
    [audio, makeLiveConfig],
  );

  const startStop = useCallback(() => {
    if (audio.status === "running" || audio.status === "connecting") {
      audio.stop();
    } else {
      void audio.start(makeLiveConfig(config), selectedDeviceId, sessionId);
    }
  }, [audio, config, makeLiveConfig, selectedDeviceId, sessionId]);

  const pauseResume = useCallback(() => {
    if (audio.paused) {
      audio.resume();
    } else {
      audio.pause();
    }
  }, [audio]);

  const commitNow = useCallback(() => {
    audio.commitNow();
  }, [audio]);

  const swapDirection = useCallback(() => {
    setConfig(
      {
        ...config,
        source_lang: config.target_lang,
        target_lang: config.source_lang,
      },
      "next_utterance",
    );
  }, [config, setConfig]);

  const skipNextPolish = useCallback(() => {
    audio.skipNextPolish();
  }, [audio]);

  const handleSelectedDeviceId = useCallback(
    (deviceId: string) => {
      setSelectedDeviceId(deviceId);
      if (audio.status === "running") {
        void audio.switchDevice(deviceId || undefined);
      }
    },
    [audio],
  );

  const handleProjectorFontSize = useCallback(
    (size: number) => {
      setProjectorFontSize(writeProjectorFontSize(sessionId, size));
    },
    [sessionId],
  );

  const openProjector = useCallback(() => {
    void openProjectorWindow(sessionId);
  }, [sessionId]);

  const doExportTxt = useCallback(() => {
    exportTxt(entries, config.source_lang, config.target_lang);
  }, [entries, config.source_lang, config.target_lang]);

  const doExportSrt = useCallback(() => {
    exportSrt(entries, config.source_lang, config.target_lang);
  }, [entries, config.source_lang, config.target_lang]);

  const doExportVtt = useCallback(() => {
    exportVtt(entries, config.source_lang, config.target_lang);
  }, [entries, config.source_lang, config.target_lang]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const isTyping =
        target?.tagName === "INPUT" || target?.tagName === "TEXTAREA" || target?.tagName === "SELECT";
      if (event.code === "Space" && !isTyping) {
        event.preventDefault();
        startStop();
      }
      if (event.metaKey && event.key.toLowerCase() === "e") {
        event.preventDefault();
        doExportTxt();
      }
      if (event.metaKey && event.key === ",") {
        event.preventDefault();
        setSettingsOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [doExportTxt, startStop]);

  useEffect(() => {
    window.localStorage.setItem(CUSTOM_VOCAB_STORAGE_KEY, config.custom_vocab.join("\n"));
  }, [config.custom_vocab]);

  useLayoutEffect(() => {
    const finalEntry = [...entries].reverse().find((entry) => entry.state === "final");
    if (!finalEntry) return;
    window.__livetr3LastOperatorFinalRender = {
      id: finalEntry.id,
      text: finalEntry.translation,
      at: Date.now(),
    };
  }, [entries]);

  const error = useMemo(() => lastError ?? audio.error, [lastError, audio.error]);

  return (
    <div
      data-testid="app-shell"
      data-session-id={sessionId}
      className="flex h-screen flex-col overflow-hidden bg-ink text-zinc-50"
    >
      <Header
        config={config}
        setConfig={setConfig}
        devices={audio.devices}
        selectedDeviceId={selectedDeviceId}
        setSelectedDeviceId={handleSelectedDeviceId}
        status={audio.status}
        paused={audio.paused}
        onStartStop={startStop}
        onPauseResume={pauseResume}
        onCommitNow={commitNow}
        onSwapDirection={swapDirection}
        onSkipNextPolish={skipNextPolish}
        onExportTxt={doExportTxt}
        onExportSrt={doExportSrt}
        onExportVtt={doExportVtt}
        onOpenProjector={openProjector}
        onClear={clear}
        levels={levels}
        rms={rms}
        projectorFontSize={projectorFontSize}
        setProjectorFontSize={handleProjectorFontSize}
        settingsOpen={settingsOpen}
        setSettingsOpen={setSettingsOpen}
      />
      {workerStatus && workerStatus.state !== "ready" ? (
        <div
          data-testid="worker-status-banner"
          className="border-b border-amber-900 bg-amber-950 px-5 py-2 text-sm text-amber-100"
        >
          {workerStatus.message}
        </div>
      ) : null}
      {error ? (
        <div data-testid="error-banner" className="border-b border-red-900 bg-red-950 px-5 py-2 text-sm text-red-100">
          {error}
        </div>
      ) : null}
      <DualPane
        entries={entries}
        sourceLanguage={config.source_lang}
        targetLanguage={config.target_lang}
      />
    </div>
  );
}
