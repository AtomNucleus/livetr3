import SwiftUI

struct RuntimeWorkspace: View {
    @EnvironmentObject private var runtime: LiveTR3Runtime
    @AppStorage("LiveTR3.showsAdvancedRuntimeDetails") private var showsAdvancedRuntimeDetails = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                SectionHero(
                    title: "Runtime",
                    subtitle: runtime.statusMessage,
                    symbolName: runtime.state.symbolName
                )

                HStack(spacing: 12) {
                    RuntimeMetric(title: "Backend", value: "8765", detail: runtime.state == .ready ? "Healthy" : runtime.state.label)
                    RuntimeMetric(title: "Operator UI", value: "5173", detail: runtime.state == .ready ? "Serving" : "Waiting")
                    RuntimeMetric(title: "Engine", value: "Parakeet", detail: "Local speech")
                }

                if showsAdvancedRuntimeDetails {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Local Endpoints")
                            .font(.headline)
                        Text("Backend: http://127.0.0.1:8765")
                            .textSelection(.enabled)
                        Text("Operator: http://127.0.0.1:5173")
                            .textSelection(.enabled)
                    }
                    .font(.callout.monospaced())
                    .foregroundStyle(.secondary)
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .liveGlassSurface(cornerRadius: 16)
                }

                Button {
                    Task { await runtime.restart() }
                } label: {
                    Label("Restart local runtime", systemImage: "arrow.clockwise")
                }
                .buttonStyle(.borderedProminent)
                .disabled(runtime.state == .starting)
            }
            .padding(32)
        }
    }
}
