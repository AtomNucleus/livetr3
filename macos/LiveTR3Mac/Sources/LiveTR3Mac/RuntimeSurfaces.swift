import SwiftUI

struct RuntimeOverlay: View {
    let state: LiveTR3Runtime.State
    let message: String

    var body: some View {
        VStack(spacing: 14) {
            ProgressView()
                .controlSize(.large)
                .opacity(state == .failed ? 0 : 1)
            Image(systemName: state.symbolName)
                .font(.system(size: 34, weight: .semibold))
                .foregroundStyle(state.tint)
            Text(state.label)
                .font(.title2.weight(.semibold))
            Text(message)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 480)
        }
        .padding(30)
        .liveGlassSurface(cornerRadius: 26)
    }
}
