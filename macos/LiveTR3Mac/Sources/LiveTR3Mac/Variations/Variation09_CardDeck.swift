import SwiftUI

/// Variation 9 — "Card Deck"
///
/// Leans fully into Liquid Glass: a control card and two transcript cards float
/// as a grouped deck inside a `GlassEffectContainer` so their materials blend
/// and morph together (HIG: wrap related glass elements in a container). The
/// deck sits over a soft background wash. Settings expand from the control card.
struct CardDeckConsoleView: View {
    @StateObject private var model: ConsoleModel
    @State private var settingsOpen = false

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color.accentColor.opacity(0.18), Color.purple.opacity(0.12)],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            .ignoresSafeArea()

            VStack(spacing: 14) {
                controlCard
                if let banner = model.banner {
                    ConsoleBannerView(banner: banner)
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                }
                HStack(spacing: 14) {
                    transcriptCard(title: model.config.source_lang, language: model.config.source_lang, field: .original)
                    transcriptCard(title: model.config.target_lang, language: model.config.target_lang, field: .translation)
                }
            }
            .padding(18)
            .liveGlassGroup()
        }
    }

    private var controlCard: some View {
        HStack(spacing: 16) {
            ConsoleStatusBadge(model: model)
            Spacer(minLength: 12)
            ConsoleWaveform(model: model)
            ConsolePartialsIndicator(active: model.partialActive)
            Spacer(minLength: 12)
            ConsoleTransportControls(model: model)
            Button {
                settingsOpen.toggle()
            } label: {
                Label("Controls", systemImage: "slider.horizontal.3")
            }
            .buttonStyle(.bordered)
            .popover(isPresented: $settingsOpen, arrowEdge: .bottom) {
                ScrollView { ConsoleSettingsPanel(model: model) }
                    .frame(width: 560, height: 620)
            }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 14)
        .liveGlassSurface(cornerRadius: 22, interactive: true)
    }

    private func transcriptCard(title: String, language: String, field: TranscriptLineView.TranscriptField) -> some View {
        VStack(spacing: 0) {
            HStack {
                Text(title).font(.headline)
                Spacer()
            }
            .padding(.horizontal, 18)
            .padding(.vertical, 12)

            ConsoleTranscriptPane(title: title, language: language, entries: model.entries, field: field, showHeader: false)
        }
        .liveGlassSurface(cornerRadius: 22)
    }
}

#if canImport(PreviewsMacros)
#Preview("Card Deck") {
    CardDeckConsoleView()
        .frame(width: 1180, height: 740)
}
#endif
