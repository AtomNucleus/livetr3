const DEFAULT_PROJECTOR_FONT_SIZE = 72;

export function getOrCreateSessionId(): string {
  const url = new URL(window.location.href);
  const existing = url.searchParams.get("session");
  if (existing) return existing;

  const next = crypto.randomUUID();
  url.searchParams.set("session", next);
  window.history.replaceState({}, "", url);
  return next;
}

export function projectorFontStorageKey(sessionId: string): string {
  return `livetr3.projector.font.${sessionId}`;
}

export function readProjectorFontSize(sessionId: string): number {
  const raw = window.localStorage.getItem(projectorFontStorageKey(sessionId));
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return DEFAULT_PROJECTOR_FONT_SIZE;
  return Math.min(144, Math.max(36, parsed));
}

export function writeProjectorFontSize(sessionId: string, fontSize: number): number {
  const clamped = Math.min(144, Math.max(36, fontSize));
  window.localStorage.setItem(projectorFontStorageKey(sessionId), String(clamped));
  return clamped;
}

export async function openProjectorWindow(sessionId: string): Promise<void> {
  const projectorUrl = new URL("/projector", window.location.origin);
  projectorUrl.searchParams.set("session", sessionId);

  let features = "popup=yes,width=1440,height=900";
  const win = window as Window & {
    getScreenDetails?: () => Promise<{
      screens: Array<{
        isPrimary?: boolean;
        availLeft?: number;
        availTop?: number;
        availWidth?: number;
        availHeight?: number;
      }>;
    }>;
  };

  if (typeof win.getScreenDetails === "function") {
    try {
      const details = await win.getScreenDetails();
      const secondary = details.screens.find((screen) => !screen.isPrimary);
      if (secondary) {
        features = [
          "popup=yes",
          `left=${secondary.availLeft ?? 0}`,
          `top=${secondary.availTop ?? 0}`,
          `width=${secondary.availWidth ?? 1440}`,
          `height=${secondary.availHeight ?? 900}`,
        ].join(",");
      }
    } catch {
      // Fall back to a normal popup when screen-placement permission is unavailable.
    }
  }

  window.open(projectorUrl.toString(), `livetr3-projector-${sessionId}`, features);
}
