import { useCallback, useMemo, useState } from "react";
import type { ServerMessage, TranscriptUtterance } from "../lib/protocol";
import { longestCommonPrefixLength } from "../lib/protocol";

export function useTranscriptStore() {
  const [entries, setEntries] = useState<TranscriptUtterance[]>([]);
  const [lastError, setLastError] = useState<string | null>(null);
  const [partialTickAt, setPartialTickAt] = useState(0);
  const [workerStatus, setWorkerStatus] = useState<{
    state: "starting" | "ready" | "recovering" | "failed";
    message: string;
  } | null>(null);

  const handleServerMessage = useCallback((message: ServerMessage) => {
    if (message.type === "error") {
      setLastError(message.message);
      return;
    }

    if (message.type === "status") {
      setWorkerStatus(message);
      if (message.state === "ready") {
        setLastError(null);
      }
      return;
    }

    if (message.type === "speech_start") {
      setEntries((current) => {
        if (current.some((entry) => entry.id === message.utterance_id)) return current;
        return [
          ...current,
          {
            id: message.utterance_id,
            original: "",
            translation: "",
            state: "partial",
            stableOriginalLength: 0,
            stableTranslationLength: 0,
            startedAt: Date.now(),
          },
        ];
      });
      return;
    }

    if (message.type === "level") return;
    if (message.type === "partial") {
      setPartialTickAt(Date.now());
    }

    setEntries((current) => {
      const existing = current.find((entry) => entry.id === message.utterance_id);
      const previousOriginal = existing?.original ?? "";
      const previousTranslation = existing?.translation ?? "";
      const updated: TranscriptUtterance = {
        id: message.utterance_id,
        original: message.original,
        translation: message.translation,
        state: message.type,
        stableOriginalLength:
          message.type === "partial"
            ? longestCommonPrefixLength(previousOriginal, message.original)
            : message.original.length,
        stableTranslationLength:
          message.type === "partial"
            ? longestCommonPrefixLength(previousTranslation, message.translation)
            : message.translation.length,
        startedAt: existing?.startedAt ?? Date.now(),
        endedAt: message.type === "partial" ? existing?.endedAt : Date.now(),
      };
      if (!existing) return [...current, updated];
      return current.map((entry) => (entry.id === message.utterance_id ? updated : entry));
    });
  }, []);

  const clear = useCallback(() => {
    setEntries([]);
    setLastError(null);
    setWorkerStatus(null);
  }, []);

  return useMemo(
    () => ({
      entries,
      lastError,
      partialTickAt,
      workerStatus,
      handleServerMessage,
      clear,
    }),
    [entries, lastError, partialTickAt, workerStatus, handleServerMessage, clear],
  );
}
