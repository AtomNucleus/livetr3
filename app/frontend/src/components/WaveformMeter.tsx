interface Props {
  levels: number[];
  rms: number;
}

export function WaveformMeter({ levels, rms }: Props) {
  const bars = levels.slice(-10);
  return (
    <div data-testid="waveform-meter" className="flex items-center gap-3">
      <div
        data-testid="mic-level-indicator"
        className="h-3 w-3 rounded-full"
        style={{
          backgroundColor: rms > 0.01 ? "#6ee7b7" : "#52525b",
          boxShadow: rms > 0.01 ? "0 0 16px rgba(110, 231, 183, 0.5)" : "none",
        }}
      />
      <div data-testid="waveform-bars" className="flex h-10 w-48 items-end gap-1">
        {bars.map((level, index) => (
          <span
            data-testid={`waveform-bar-${index}`}
            key={`${index}-${level}`}
            className="block w-full rounded-sm bg-mint"
            style={{ height: `${Math.max(8, Math.min(40, level * 520))}px`, opacity: 0.35 + level * 8 }}
          />
        ))}
      </div>
      <span data-testid="rms-readout" className="w-20 text-right text-xs tabular-nums text-zinc-400">
        {rms.toFixed(3)}
      </span>
    </div>
  );
}

