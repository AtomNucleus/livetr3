import { useEffect, useRef, useState } from "react";
import type { TranscriptUtterance } from "../lib/protocol";
import { isRtlLanguage } from "../lib/protocol";
import { TranscriptLine } from "./TranscriptLine";

interface Props {
  entries: TranscriptUtterance[];
  sourceLanguage: string;
  targetLanguage: string;
}

function usePinnedScroll<T extends HTMLElement>(deps: unknown[]) {
  const ref = useRef<T | null>(null);
  const [pinned, setPinned] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node || pinned) return;
    node.scrollTop = node.scrollHeight;
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps

  const onScroll = () => {
    const node = ref.current;
    if (!node) return;
    const distanceFromBottom = node.scrollHeight - node.scrollTop - node.clientHeight;
    setPinned(distanceFromBottom > 48);
  };

  return { ref, onScroll, pinned };
}

export function DualPane({ entries, sourceLanguage, targetLanguage }: Props) {
  const originalPane = usePinnedScroll<HTMLDivElement>([entries]);
  const translationPane = usePinnedScroll<HTMLDivElement>([entries]);
  const originalDir = isRtlLanguage(sourceLanguage) ? "rtl" : "ltr";
  const translationDir = isRtlLanguage(targetLanguage) ? "rtl" : "ltr";

  return (
    <main data-testid="dual-pane" className="grid min-h-0 flex-1 grid-rows-2">
      <section
        data-testid="source-pane"
        className="min-h-0 border-b border-line bg-ink"
        aria-label={`${sourceLanguage} transcript`}
      >
        <div className="flex h-full flex-col">
          <div className="flex items-center justify-between border-b border-line px-5 py-3">
            <h2 data-testid="source-language-label" className="text-sm font-semibold text-mint">
              {sourceLanguage}
            </h2>
            {originalPane.pinned ? (
              <span data-testid="source-scroll-pinned" className="text-xs text-amber">
                Scroll pinned
              </span>
            ) : null}
          </div>
          <div
            data-testid="source-scroll"
            ref={originalPane.ref}
            onScroll={originalPane.onScroll}
            className="min-h-0 flex-1 overflow-y-auto px-5 py-4"
          >
            {entries.map((entry) => (
              <TranscriptLine key={entry.id} entry={entry} field="original" dir={originalDir} />
            ))}
          </div>
        </div>
      </section>

      <section
        data-testid="target-pane"
        className="min-h-0 bg-panel"
        aria-label={`${targetLanguage} translation`}
      >
        <div className="flex h-full flex-col">
          <div className="flex items-center justify-between border-b border-line px-5 py-3">
            <h2 data-testid="target-language-label" className="text-sm font-semibold text-mint">
              {targetLanguage}
            </h2>
            {translationPane.pinned ? (
              <span data-testid="target-scroll-pinned" className="text-xs text-amber">
                Scroll pinned
              </span>
            ) : null}
          </div>
          <div
            data-testid="target-scroll"
            ref={translationPane.ref}
            onScroll={translationPane.onScroll}
            className="min-h-0 flex-1 overflow-y-auto px-5 py-4"
          >
            {entries.map((entry) => (
              <TranscriptLine
                key={entry.id}
                entry={entry}
                field="translation"
                dir={translationDir}
              />
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}

