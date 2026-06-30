import SwiftUI

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
            return Color(red: 0.45, green: 0.95, blue: 0.78)
        }
        return Color.white.opacity(0.18 + Double(min(level, 1)) * 0.35)
    }
}
