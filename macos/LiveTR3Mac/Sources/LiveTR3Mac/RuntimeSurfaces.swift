import SwiftUI

struct RuntimeOverlay: View {
    let state: LiveTR3Runtime.State
    let message: String

    var body: some View {
        VStack(spacing: 14) {
            ZStack {
                if state == .starting {
                    ProgressView()
                        .controlSize(.large)
                } else {
                    Image(systemName: state.symbolName)
                        .font(.system(size: 40, weight: .semibold))
                        .foregroundStyle(state.tint)
                        .symbolRenderingMode(.hierarchical)
                }
            }
            .frame(height: 48)

            Text(state.label)
                .font(.title2.weight(.semibold))

            Text(message)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 420)
        }
        .padding(.horizontal, 36)
        .padding(.vertical, 30)
        .liveGlassSurface(cornerRadius: 28)
    }
}
