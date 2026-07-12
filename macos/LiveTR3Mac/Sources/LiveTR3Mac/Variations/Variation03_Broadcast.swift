import SwiftUI

/// Variation 3 — "Broadcast"
///
/// A toolbar-first layout for a live control room. Primary transport and status
/// sit in the window toolbar; the full grouped settings live in a trailing
/// `.inspector` (HIG: progressive disclosure of secondary controls) that can be
/// shown or hidden without leaving the transcript.
struct BroadcastConsoleView: View {
    @StateObject private var model: ConsoleModel
    @State private var inspectorPresented = true

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if let banner = model.banner {
                    ConsoleBannerView(banner: banner)
                }
                HStack(spacing: 0) {
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
            .navigationTitle("On Air")
            .toolbar {
                ToolbarItemGroup(placement: .principal) {
                    ConsoleStatusBadge(model: model)
                    ConsoleWaveform(model: model)
                    ConsolePartialsIndicator(active: model.partialActive)
                }
                ToolbarItemGroup(placement: .primaryAction) {
                    ConsoleTransportControls(model: model)
                    Button {
                        inspectorPresented.toggle()
                    } label: {
                        Label("Controls", systemImage: "sidebar.trailing")
                    }
                }
            }
            .inspector(isPresented: $inspectorPresented) {
                ConsoleSettingsForm(model: model)
                    .inspectorColumnWidth(min: 320, ideal: 360, max: 440)
            }
        }
    }
}

#if canImport(PreviewsMacros)
#Preview("Broadcast") {
    BroadcastConsoleView()
        .frame(width: 1200, height: 720)
}
#endif
