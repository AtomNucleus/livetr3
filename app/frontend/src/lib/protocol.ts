export const languages = [
  "English",
  "Spanish",
  "French",
  "German",
  "Italian",
  "Portuguese",
  "Japanese",
  "Korean",
  "Mandarin",
  "Arabic",
] as const;

export type SegmenterMode = "silero";

export interface ClientConfig {
  version?: number;
  source_lang: string;
  target_lang: string;
  custom_vocab: string[];
  segmenter: SegmenterMode;
  polish_enabled: boolean;
  apply_target?: "immediate" | "next_utterance";
  input_device_id?: string | null;
  input_device_label?: string | null;
  code_switching_enabled?: boolean;
  partial_interval_seconds?: number | null;
  max_utterance_seconds?: number | null;
  silero_threshold?: number | null;
  speech_pad_ms?: number | null;
  min_silence_ms?: number | null;
}

export type ServerMessage =
  | { type: "speech_start"; utterance_id: number }
  | {
      type: "partial" | "final" | "polished";
      utterance_id: number;
      original: string;
      translation: string;
    }
  | { type: "level"; rms: number }
  | { type: "status"; state: "starting" | "ready" | "recovering" | "failed"; message: string }
  | { type: "error"; message: string };

export interface TranscriptUtterance {
  id: number;
  original: string;
  translation: string;
  state: "partial" | "final" | "polished";
  stableOriginalLength: number;
  stableTranslationLength: number;
  startedAt: number;
  endedAt?: number;
}

export function isRtlLanguage(language: string): boolean {
  return /^(arabic|hebrew|urdu|persian|farsi)$/i.test(language.trim());
}

export function longestCommonPrefixLength(a: string, b: string): number {
  const max = Math.min(a.length, b.length);
  let i = 0;
  while (i < max && a[i] === b[i]) i += 1;
  return i;
}
