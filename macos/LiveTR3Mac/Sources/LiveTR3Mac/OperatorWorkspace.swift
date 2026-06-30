import SwiftUI

struct OperatorWorkspace: View {
    @EnvironmentObject private var runtime: LiveTR3Runtime
    @EnvironmentObject private var session: SessionController
    @EnvironmentObject private var sessionManager: SessionManager
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        VStack(spacing: 0) {
            OperatorStatusBar()
                .environmentObject(runtime)

            Divider()

            Group {
                if runtime.state == .ready {
                    NativeOperatorView(
                        session: session,
                        sessionManager: sessionManager,
                        onOpenProjector: openProjector
                    )
                } else {
                    RuntimeOverlay(state: runtime.state, message: runtime.statusMessage)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .background(.background)
    }

    private func openProjector() {
        openWindow(id: LiveTR3WindowID.projector)
    }
}

private struct OperatorStatusBar: View {
    @EnvironmentObject private var runtime: LiveTR3Runtime

    var body: some View {
        HStack(spacing: 12) {
            Label(runtime.state.label, systemImage: runtime.state.symbolName)
                .font(.callout.weight(.semibold))
                .foregroundStyle(runtime.state.tint)

            Text(runtime.statusMessage)
                .font(.callout)
                .foregroundStyle(.secondary)
                .lineLimit(1)

            Spacer(minLength: 16)

            Text("ws://127.0.0.1:8765")
                .font(.caption)
                .foregroundStyle(.secondary)

            Button {
                Task { await runtime.restart() }
            } label: {
                Label("Restart", systemImage: "arrow.clockwise")
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .disabled(runtime.state == .starting)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(.bar)
    }
}
