import type { TranscriptUtterance } from "../lib/protocol";

interface Props {
  entry: TranscriptUtterance;
  field: "original" | "translation";
  dir: "ltr" | "rtl";
}

export function TranscriptLine({ entry, field, dir }: Props) {
  const text = entry[field];
  const stableLength =
    field === "original" ? entry.stableOriginalLength : entry.stableTranslationLength;
  const isPartial = entry.state === "partial";
  const stable = isPartial ? text.slice(0, stableLength) : text;
  const unstable = isPartial ? text.slice(stableLength) : "";

  return (
    <p
      data-testid={`caption-${field}-${entry.id}`}
      dir={dir}
      className={[
        "max-w-full whitespace-pre-wrap break-words rounded-md px-2 py-1 text-[28px] leading-[1.5] md:text-[34px]",
        isPartial ? "text-zinc-300 opacity-60 italic" : "text-zinc-50 opacity-100 not-italic",
        entry.state === "polished" ? "polished-pulse" : "",
      ].join(" ")}
    >
      <span data-testid={`caption-${field}-${entry.id}-stable`}>{stable}</span>
      {unstable ? (
        <span data-testid={`caption-${field}-${entry.id}-unstable`} className="opacity-70">
          {unstable}
        </span>
      ) : null}
    </p>
  );
}

