import SwiftUI

/// Audio levels arrive for every capture buffer and engine frame, 50+ times a
/// second. Publishing each one from the session controller re-rendered every view
/// that observes the session, the operator window and projector included, and
/// kept the main thread busy enough to stall caption delivery. Only the meter
/// observes this, and it publishes the loudest recent level about 12 times a second.
@MainActor
final class AudioLevelMeter: ObservableObject {
    static let barCount = 10
    static let publishInterval: TimeInterval = 0.08

    @Published private(set) var levels: [Float] = Array(repeating: 0, count: barCount)
    private var pending: Float?
    private var lastPublish: TimeInterval = -.infinity

    func record(_ rms: Float, at now: TimeInterval = ProcessInfo.processInfo.systemUptime) {
        pending = max(pending ?? 0, rms)
        guard now - lastPublish >= Self.publishInterval, let value = pending else { return }
        lastPublish = now
        pending = nil
        var next = levels
        if next.count >= Self.barCount { next.removeFirst() }
        next.append(value)
        levels = next
    }
}

struct LiveWaveformMeter: View {
    @ObservedObject var meter: AudioLevelMeter

    var body: some View {
        WaveformMeterView(levels: meter.levels, rms: meter.levels.last ?? 0)
    }
}

struct WaveformMeterView: View {
    let levels: [Float]
    let rms: Float

    var body: some View {
        HStack(spacing: 3) {
            ForEach(Array(levels.enumerated()), id: \.offset) { index, level in
                RoundedRectangle(cornerRadius: 2)
                    .fill(barColor(for: index, level: level))
                    .frame(width: 4, height: barHeight(for: level))
            }
        }
        .frame(height: 28, alignment: .bottom)
        .accessibilityLabel("Audio level \(Int(rms * 100)) percent")
    }

    private func barHeight(for level: Float) -> CGFloat {
        let normalized = min(max(CGFloat(level) * 120, 4), 28)
        return normalized
    }

    private func barColor(for index: Int, level: Float) -> Color {
        if index == levels.count - 1 {
            return .accentColor
        }
        return Color.secondary.opacity(0.4 + Double(min(level, 1)) * 0.4)
    }
}
