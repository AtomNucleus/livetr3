import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { CSSProperties } from "react";
import { useTranscriptStore } from "./hooks/useTranscriptStore";
import { projectorFontStorageKey, readProjectorFontSize } from "./lib/projector";

declare global {
  interface Window {
    __livetr3LastProjectorFinalRender?: {
      id: number;
      text: string;
      at: number;
    };
  }
}

const PROJECTOR_RECONNECT_DELAYS_MS = [250, 500, 1000, 2000, 5000];

function useProjectorFontSize(sessionId: string) {
  const [fontSize, setFontSize] = useState(() => readProjectorFontSize(sessionId));

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== projectorFontStorageKey(sessionId)) return;
      setFontSize(readProjectorFontSize(sessionId));
    };

    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [sessionId]);

  return fontSize;
}

function useAutoFitFont(maxFontSize: number, contentKey: string) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [fontSize, setFontSize] = useState(maxFontSize);
  const [containerVersion, setContainerVersion] = useState(0);

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof ResizeObserver === "undefined") return;

    const observer = new ResizeObserver(() => {
      setContainerVersion((current) => current + 1);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;

    let next = maxFontSize;
    node.style.setProperty("--projector-font-size", `${next}px`);
    while (
      next > 24 &&
      (node.scrollHeight > node.clientHeight || node.scrollWidth > node.clientWidth)
    ) {
      next -= 2;
      node.style.setProperty("--projector-font-size", `${next}px`);
    }
    setFontSize(next);
  }, [contentKey, containerVersion, maxFontSize]);

  return { ref, fontSize };
}

function ProjectorCaption({
  id,
  text,
  stableLength,
  isPartial,
  isCurrent,
}: {
  id: number;
  text: string;
  stableLength: number;
  isPartial: boolean;
  isCurrent: boolean;
}) {
  const stable = isPartial ? text.slice(0, stableLength) : text;
  const unstable = isPartial ? text.slice(stableLength) : "";
  const opacity = isPartial ? 0.92 : isCurrent ? 1 : 0.72;
  const scale = isCurrent ? 1 : 0.82;

  return (
    <p
      data-testid={`projector-caption-${id}`}
      className="max-w-[min(18ch,100%)] self-center whitespace-pre-wrap break-words text-center font-bold leading-[1.14] text-white transition-opacity duration-[90ms]"
      style={{
        fontSize: `calc(var(--projector-font-size) * ${scale})`,
        opacity,
        textShadow: "0 2px 0 rgb(0 0 0 / 0.88), 0 0 28px rgb(0 0 0 / 0.92)",
      }}
    >
      <span style={{ opacity: 1 }}>{stable}</span>
      {unstable ? <span style={{ opacity: 0.82 }}>{unstable}</span> : null}
    </p>
  );
}

export default function ProjectorApp() {
  const sessionId = useMemo(
    () => new URLSearchParams(window.location.search).get("session") ?? "",
    [],
  );
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const { entries, lastError, workerStatus, handleServerMessage } = useTranscriptStore();
  const projectorFontSize = useProjectorFontSize(sessionId);
  const targetEntries = useMemo(
    () => entries.filter((entry) => entry.translation.trim()).slice(-2),
    [entries],
  );
  const contentKey = targetEntries
    .map((entry) => `${entry.id}:${entry.translation}:${entry.state}`)
    .join("|");
  const { ref, fontSize } = useAutoFitFont(projectorFontSize, contentKey);

  useLayoutEffect(() => {
    const finalEntry = [...entries].reverse().find((entry) => entry.state === "final");
    if (!finalEntry) return;
    window.__livetr3LastProjectorFinalRender = {
      id: finalEntry.id,
      text: finalEntry.translation,
      at: Date.now(),
    };
  }, [entries]);

  useEffect(() => {
    if (!sessionId) {
      setConnectionError("Missing projector session token");
      return;
    }

    let closedByEffect = false;
    let reconnectAttempt = 0;
    let reconnectTimer: number | undefined;
    let ws: WebSocket | undefined;

    const connect = () => {
      const wsUrl = new URL("ws://127.0.0.1:8765/");
      wsUrl.searchParams.set("session", sessionId);
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        reconnectAttempt = 0;
        setConnectionError(null);
        ws?.send(JSON.stringify({ type: "join_viewer" }));
      };
      ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        handleServerMessage(message);
      };
      ws.onerror = () => {
        setConnectionError("Projector connection failed");
      };
      ws.onclose = () => {
        if (closedByEffect) return;
        const delay =
          PROJECTOR_RECONNECT_DELAYS_MS[
            Math.min(reconnectAttempt, PROJECTOR_RECONNECT_DELAYS_MS.length - 1)
          ];
        reconnectAttempt += 1;
        setConnectionError(`Projector reconnecting in ${Math.round(delay / 1000)}s`);
        reconnectTimer = window.setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      closedByEffect = true;
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [handleServerMessage, sessionId]);

  const statusText =
    connectionError ??
    lastError ??
    (workerStatus && workerStatus.state !== "ready" ? workerStatus.message : null);

  return (
    <main
      data-testid="projector-shell"
      data-session-id={sessionId}
      className="flex h-screen flex-col overflow-hidden bg-black text-white"
    >
      {statusText ? (
        <div className="px-8 pt-6 text-sm uppercase tracking-[0.2em] text-amber-300">
          {statusText}
        </div>
      ) : null}
      <div className="min-h-0 flex-1 bg-[radial-gradient(circle_at_center,rgba(39,39,42,0.44),rgba(0,0,0,1)_70%)] px-[clamp(28px,5vw,96px)] py-[clamp(26px,5vh,72px)]">
        <div
          ref={ref}
          className="flex h-full flex-col justify-end gap-[clamp(18px,3vh,42px)] overflow-hidden"
          style={
            {
              ["--projector-font-size" as string]: `${fontSize}px`,
            } as CSSProperties
          }
        >
          {targetEntries.length ? (
            targetEntries.map((entry, index) => (
              <ProjectorCaption
                key={entry.id}
                id={entry.id}
                text={entry.translation}
                stableLength={entry.stableTranslationLength}
                isPartial={entry.state === "partial"}
                isCurrent={index === targetEntries.length - 1}
              />
            ))
          ) : (
            <p
              className="text-center font-semibold uppercase tracking-[0.24em] text-white/40"
              style={{ fontSize: "calc(var(--projector-font-size) * 0.5)" }}
            >
              Waiting for live captions
            </p>
          )}
        </div>
      </div>
    </main>
  );
}
