import SwiftUI

struct ProjectorWorkspace: View {
    @EnvironmentObject private var runtime: LiveTR3Runtime

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            SectionHero(
                title: "Projector",
                subtitle: runtime.state == .ready ? "Audience route is available." : runtime.statusMessage,
                symbolName: "rectangle.on.rectangle"
            )

            HStack(spacing: 12) {
                DashboardMetric(title: "Route", value: "Projector", detail: "Local audience view", symbolName: "display")
                DashboardMetric(title: "Runtime", value: runtime.state.label, detail: runtime.state == .ready ? "Serving on 5173" : "Waiting", symbolName: runtime.state.symbolName)
            }

            VStack(alignment: .leading, spacing: 12) {
                Text("Audience URL")
                    .font(.headline)
                Text(LiveTR3Routes.projectorURL.absoluteString)
                    .font(.callout.monospaced())
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)

                Link(destination: LiveTR3Routes.projectorURL) {
                    Label("Open projector", systemImage: "arrow.up.forward.app")
                }
                .buttonStyle(.borderedProminent)
                .disabled(runtime.state != .ready)
            }
            .padding(18)
            .liveGlassSurface(cornerRadius: 20)
        }
        .padding(32)
    }
}
