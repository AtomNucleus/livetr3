import { useCallback, useEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";
import type { ClientConfig, ServerMessage } from "../lib/protocol";

interface AudioCaptureOptions {
  onServerMessage: (message: ServerMessage) => void;
  onWaveform: (rms: number) => void;
}

export function useAudioCapture({ onServerMessage, onWaveform }: AudioCaptureOptions) {
  const [status, setStatus] = useState<"idle" | "connecting" | "running">("idle");
  const [error, setError] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const nodeRef = useRef<AudioWorkletNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const pausedRef = useRef(false);
  const manualStopRef = useRef(false);
  const reconnectTimerRef = useRef<number | null>(null);
  const reconnectAttemptRef = useRef(0);
  const configRef = useRef<ClientConfig | null>(null);
  const sessionIdRef = useRef<string | undefined>(undefined);
  const testAudioAbortRef = useRef<AbortController | null>(null);

  const refreshDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    const all = await navigator.mediaDevices.enumerateDevices();
    setDevices(all.filter((device) => device.kind === "audioinput"));
  }, []);

  const sendJson = useCallback((payload: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload));
    }
  }, []);

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const connectSocket = useCallback(
    async (mode: "start" | "resume") => {
      const config = configRef.current;
      if (!config) {
        throw new Error("Missing audio session configuration");
      }

      const wsUrl = new URL("ws://127.0.0.1:8765/");
      if (sessionIdRef.current) {
        wsUrl.searchParams.set("session", sessionIdRef.current);
      }

      const ws = new WebSocket(wsUrl);
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      await new Promise<void>((resolve, reject) => {
        ws.onopen = () => resolve();
        ws.onerror = () => reject(new Error("Could not connect to backend WebSocket"));
      });

      ws.onmessage = (event) => {
        const message = JSON.parse(event.data) as ServerMessage;
        if (message.type === "level") onWaveform(message.rms);
        onServerMessage(message);
      };
      ws.onclose = () => {
        wsRef.current = null;
        if (manualStopRef.current) {
          setStatus("idle");
          return;
        }
        setStatus("connecting");
        setError("Backend connection lost. Reconnecting...");
        const scheduleReconnect = () => {
          const delay = Math.min(1000 * 2 ** reconnectAttemptRef.current, 8000);
          reconnectTimerRef.current = window.setTimeout(() => {
            reconnectTimerRef.current = null;
            reconnectAttemptRef.current += 1;
            void connectSocket("resume").catch((exc) => {
              setError(exc instanceof Error ? exc.message : String(exc));
              wsRef.current = null;
              if (!manualStopRef.current) {
                setStatus("connecting");
                scheduleReconnect();
              }
            });
          }, delay);
        };
        scheduleReconnect();
      };

      if (mode === "resume") {
        ws.send(JSON.stringify({ type: "resume" }));
        ws.send(JSON.stringify({ type: "config", ...config }));
      } else {
        ws.send(JSON.stringify({ type: "config", ...config }));
        ws.send(JSON.stringify({ type: "start" }));
      }

      reconnectAttemptRef.current = 0;
      setStatus("running");
      setError(null);
    },
    [onServerMessage, onWaveform],
  );

  const replaceStream = useCallback(
    async (deviceId?: string, isFallback = false) => {
      if (!contextRef.current || !nodeRef.current) return;

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          deviceId: deviceId ? { exact: deviceId } : undefined,
          channelCount: 1,
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        },
      });

      const source = contextRef.current.createMediaStreamSource(stream);
      source.connect(nodeRef.current);

      sourceRef.current?.disconnect();
      streamRef.current?.getTracks().forEach((track) => track.stop());

      streamRef.current = stream;
      sourceRef.current = source;
      await refreshDevices();

      for (const track of stream.getAudioTracks()) {
        track.onended = () => {
          setError("Microphone disconnected. Switching to the default input.");
          void replaceStream(undefined, true).catch((exc) => {
            setError(
              exc instanceof Error
                ? exc.message
                : "Microphone disconnected and fallback input could not be opened.",
            );
          });
        };
      }

      if (!isFallback) {
        setError(null);
      }
    },
    [refreshDevices],
  );

  const stop = useCallback(() => {
    manualStopRef.current = true;
    clearReconnectTimer();
    sendJson({ type: "stop" });
    wsRef.current?.close();
    wsRef.current = null;
    sourceRef.current?.disconnect();
    sourceRef.current = null;
    nodeRef.current?.disconnect();
    nodeRef.current = null;
    testAudioAbortRef.current?.abort();
    testAudioAbortRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    void contextRef.current?.close();
    contextRef.current = null;
    pausedRef.current = false;
    setPaused(false);
    setStatus("idle");
  }, [clearReconnectTimer, sendJson]);

  const start = useCallback(
    async (config: ClientConfig, deviceId?: string, sessionId?: string) => {
      if (status !== "idle") return;
      setError(null);
      setStatus("connecting");
      manualStopRef.current = false;
      configRef.current = config;
      sessionIdRef.current = sessionId;

      try {
        await refreshDevices();

        const testAudioUrl = new URLSearchParams(window.location.search).get("test_audio_url");
        if (testAudioUrl) {
          await connectSocket("start");
          const abort = new AbortController();
          testAudioAbortRef.current = abort;
          void streamTestAudio(testAudioUrl, abort.signal, wsRef, pausedRef).catch((exc) => {
            if (!abort.signal.aborted) {
              setError(exc instanceof Error ? exc.message : String(exc));
            }
          });
          return;
        }

        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        const context = new AudioContextClass();
        contextRef.current = context;
        await context.audioWorklet.addModule("/audio-worklet.js");
        const node = new AudioWorkletNode(context, "livetr3-audio-worklet");
        const silent = context.createGain();
        silent.gain.value = 0;

        node.port.onmessage = (event: MessageEvent) => {
          const { type, buffer, rms } = event.data as {
            type: string;
            buffer?: ArrayBuffer;
            rms?: number;
          };
          if (
            type === "pcm" &&
            buffer &&
            wsRef.current?.readyState === WebSocket.OPEN &&
            !pausedRef.current
          ) {
            wsRef.current.send(buffer);
          }
          if (type === "level" && typeof rms === "number") {
            onWaveform(rms);
          }
        };

        node.connect(silent);
        silent.connect(context.destination);
        nodeRef.current = node;
        await replaceStream(deviceId);
        await connectSocket("start");
      } catch (exc) {
        stop();
        setError(formatAudioStartError(exc));
      }
    },
    [connectSocket, refreshDevices, replaceStream, status, stop],
  );

  const pause = useCallback(() => {
    pausedRef.current = true;
    setPaused(true);
  }, []);

  const resume = useCallback(() => {
    pausedRef.current = false;
    setPaused(false);
  }, []);

  const switchDevice = useCallback(
    async (deviceId?: string) => {
      await replaceStream(deviceId);
    },
    [replaceStream],
  );

  const sendConfig = useCallback(
    (config: ClientConfig) => {
      configRef.current = config;
      sendJson({ type: "config", ...config });
    },
    [sendJson],
  );

  const commitNow = useCallback(() => {
    sendJson({ type: "commit_now" });
  }, [sendJson]);

  const skipNextPolish = useCallback(() => {
    sendJson({ type: "skip_polish" });
  }, [sendJson]);

  useEffect(() => {
    void refreshDevices();
    return stop;
  }, [refreshDevices, stop]);

  return {
    status,
    error,
    paused,
    devices,
    refreshDevices,
    start,
    stop,
    pause,
    resume,
    switchDevice,
    sendConfig,
    commitNow,
    skipNextPolish,
  };
}

function formatAudioStartError(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError") {
      return "Microphone access was blocked. Allow mic access for this page and try again.";
    }
    if (error.name === "NotFoundError") {
      return "No microphone input is available.";
    }
    if (error.name === "NotReadableError") {
      return "The microphone is busy or unavailable to the browser right now.";
    }
  }
  return error instanceof Error ? error.message : String(error);
}

async function streamTestAudio(
  url: string,
  signal: AbortSignal,
  wsRef: MutableRefObject<WebSocket | null>,
  pausedRef: MutableRefObject<boolean>,
) {
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`Could not load test audio: ${response.status}`);
  }
  const arrayBuffer = await response.arrayBuffer();
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  const context = new AudioContextClass();
  try {
    const decoded = await context.decodeAudioData(arrayBuffer.slice(0));
    const mono = mixToMono(decoded);
    const audio = resampleLinear(mono, decoded.sampleRate, 16_000);
    const padded = padToFrame(audio, 320);
    const silence = new Float32Array(6_400);
    while (!signal.aborted) {
      await sendFrames(padded, signal, wsRef, pausedRef);
      await sendFrames(silence, signal, wsRef, pausedRef);
    }
  } finally {
    void context.close();
  }
}

function mixToMono(buffer: AudioBuffer): Float32Array {
  const output = new Float32Array(buffer.length);
  for (let channel = 0; channel < buffer.numberOfChannels; channel += 1) {
    const data = buffer.getChannelData(channel);
    for (let index = 0; index < data.length; index += 1) {
      output[index] += data[index] / buffer.numberOfChannels;
    }
  }
  return output;
}

function resampleLinear(input: Float32Array, fromRate: number, toRate: number): Float32Array {
  if (fromRate === toRate) return input;
  const outputLength = Math.floor((input.length * toRate) / fromRate);
  const output = new Float32Array(outputLength);
  const ratio = fromRate / toRate;
  for (let index = 0; index < output.length; index += 1) {
    const source = index * ratio;
    const lower = Math.floor(source);
    const upper = Math.min(lower + 1, input.length - 1);
    const fraction = source - lower;
    output[index] = input[lower] + (input[upper] - input[lower]) * fraction;
  }
  return output;
}

function padToFrame(input: Float32Array, frameSize: number): Float32Array {
  const pad = (frameSize - (input.length % frameSize)) % frameSize;
  if (!pad) return input;
  const output = new Float32Array(input.length + pad);
  output.set(input);
  return output;
}

async function sendFrames(
  audio: Float32Array,
  signal: AbortSignal,
  wsRef: MutableRefObject<WebSocket | null>,
  pausedRef: MutableRefObject<boolean>,
) {
  for (let offset = 0; offset < audio.length && !signal.aborted; offset += 320) {
    if (!pausedRef.current && wsRef.current?.readyState === WebSocket.OPEN) {
      const frame = audio.slice(offset, offset + 320);
      wsRef.current.send(frame.buffer);
    }
    await sleep(20, signal);
  }
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timeout = window.setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        window.clearTimeout(timeout);
        resolve();
      },
      { once: true },
    );
  });
}
