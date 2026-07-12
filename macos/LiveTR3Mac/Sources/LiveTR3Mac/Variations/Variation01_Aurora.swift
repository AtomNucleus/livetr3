import SwiftUI

/// Variation 1 — "Aurora"
///
/// Keeps the familiar dual-pane transcript edge-to-edge and floats a single
/// Liquid Glass control dock over the content. The dock is the one interactive
/// glass surface (HIG: reserve interactive glass for control-bearing surfaces),
/// and settings open from it as a popover so the reading area stays uncluttered.
struct AuroraConsoleView: View {
    @StateObject private var model: ConsoleModel
    @State private var settingsOpen = false

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        ZStack(alignment: .bottom) {
            VStack(spacing: 0) {
                if let banner = model.banner {
                    ConsoleBannerView(banner: banner)
                }
                VStack(spacing: 0) {
                    ConsoleTranscriptPane(
                        title: model.config.source_lang,
                        language: model.config.source_lang,
                        entries: model.entries,
                        field: .original
                    )
                    Divider()
                    ConsoleTranscriptPane(
                        title: model.config.target_lang,
                        language: model.config.target_lang,
                        entries: model.entries,
                        field: .translation
                    )
                }
            }
            .background(.background)

            controlDock
                .padding(.bottom, 20)
        }
    }

    private var controlDock: some View {
        HStack(spacing: 16) {
            ConsoleStatusBadge(model: model)
            Divider().frame(height: 24)
            ConsoleWaveform(model: model)
            ConsolePartialsIndicator(active: model.partialActive)
            Divider().frame(height: 24)
            ConsoleTransportControls(model: model)

            Button {
                settingsOpen.toggle()
            } label: {
                Label("Controls", systemImage: "slider.horizontal.3")
            }
            .buttonStyle(.bordered)
            .popover(isPresented: $settingsOpen, arrowEdge: .bottom) {
                ConsoleSettingsPanel(model: model).frame(width: 560)
            }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 12)
        .liveGlassSurface(cornerRadius: 22, interactive: true)
        .liveGlassGroup()
        .shadow(color: .black.opacity(0.18), radius: 18, y: 8)
    }
}

#if canImport(PreviewsMacros)
#Preview("Aurora") {
    AuroraConsoleView()
        .frame(width: 1040, height: 700)
}
#endif
