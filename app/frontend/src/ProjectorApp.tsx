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
      next > 36 &&
      (node.scrollHeight > node.clientHeight || node.scrollWidth > node.clientWidth)
    ) {
      next -= 2;
      node.style.setProperty("--projector-font-size", `${next}px`);
    }
    setFontSize(next);
  }, [contentKey, containerVersion, maxFontSize]);

  return { ref, fontSize };
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

  useEffect(() => {
    if (!sessionId) {
      setConnectionError("Missing projector session token");
      return;
    }

    const wsUrl = new URL("ws://127.0.0.1:8765/");
    wsUrl.searchParams.set("session", sessionId);
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      setConnectionError(null);
      ws.send(JSON.stringify({ type: "join_viewer" }));
    };
    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      handleServerMessage(message);
    };
    ws.onerror = () => setConnectionError("Projector connection failed");
    ws.onclose = () =>
      setConnectionError((current) => current ?? "Projector connection closed");

    return () => ws.close();
  }, [handleServerMessage, sessionId]);

  const statusText =
    connectionError ??
    lastError ??
    (workerStatus && workerStatus.state !== "ready" ? workerStatus.message : null);

  return (
    <main className="flex h-screen flex-col overflow-hidden bg-black text-white">
      {statusText ? (
        <div className="px-8 pt-6 text-sm uppercase tracking-[0.2em] text-amber-300">
          {statusText}
        </div>
      ) : null}
      <div className="min-h-0 flex-1 px-10 pb-10 pt-6">
        <div
          ref={ref}
          className="flex h-full flex-col justify-end gap-6 overflow-hidden rounded-[32px] border border-white/10 bg-white/[0.03] px-10 py-10"
          style={
            {
              ["--projector-font-size" as string]: `${fontSize}px`,
            } as CSSProperties
          }
        >
          {targetEntries.length ? (
            targetEntries.map((entry) => (
              <p
                key={entry.id}
                className={[
                  "whitespace-pre-wrap break-words font-semibold leading-[1.08] text-white",
                  entry.state === "partial" ? "opacity-70 italic" : "opacity-100",
                ].join(" ")}
                style={{ fontSize: "var(--projector-font-size)" }}
              >
                {entry.translation}
              </p>
            ))
          ) : (
            <p
              className="text-center font-semibold uppercase tracking-[0.24em] text-white/35"
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
