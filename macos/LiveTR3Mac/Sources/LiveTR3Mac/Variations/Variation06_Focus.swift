import SwiftUI

/// Variation 6 — "Focus"
///
/// A distraction-free reading mode that shows one language at a time at large
/// type, with a glass language toggle to flip between source and translation.
/// A floating glass mic pill carries transport; a gear opens the full controls
/// in a popover. All capability is retained, just progressively revealed.
struct FocusConsoleView: View {
    @StateObject private var model: ConsoleModel
    @State private var showingTranslation = true
    @State private var settingsOpen = false

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    private var activeLanguage: String {
        showingTranslation ? model.config.target_lang : model.config.source_lang
    }

    private var activeField: TranscriptLineView.TranscriptField {
        showingTranslation ? .translation : .original
    }

    var body: some View {
        ZStack(alignment: .bottom) {
            VStack(spacing: 0) {
                if let banner = model.banner {
                    ConsoleBannerView(banner: banner)
                }
                ConsoleTranscriptPane(
                    title: activeLanguage,
                    language: activeLanguage,
                    entries: model.entries,
                    field: activeField,
                    showHeader: false
                )
            }
            .background(.background)

            micPill
                .padding(.bottom, 24)
        }
        .overlay(alignment: .top) { languageToggle.padding(.top, 16) }
    }

    private var languageToggle: some View {
        Picker("Language", selection: $showingTranslation) {
            Text(model.config.source_lang).tag(false)
            Text(model.config.target_lang).tag(true)
        }
        .pickerStyle(.segmented)
        .labelsHidden()
        .frame(maxWidth: 280)
        .padding(6)
        .liveGlassSurface(cornerRadius: 14)
    }

    private var micPill: some View {
        HStack(spacing: 14) {
            ConsoleStatusBadge(model: model, compact: true)
            ConsoleWaveform(model: model)
            ConsolePartialsIndicator(active: model.partialActive)
            Divider().frame(height: 22)
            ConsoleTransportControls(model: model)
            Button {
                settingsOpen.toggle()
            } label: {
                Image(systemName: "slider.horizontal.3")
            }
            .buttonStyle(.bordered)
            .buttonBorderShape(.circle)
            .popover(isPresented: $settingsOpen, arrowEdge: .bottom) {
                ScrollView { ConsoleSettingsPanel(model: model) }
                    .frame(width: 560, height: 620)
            }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 12)
        .liveGlassSurface(cornerRadius: 26, interactive: true)
        .liveGlassGroup()
        .shadow(color: .black.opacity(0.2), radius: 16, y: 6)
    }
}

#if canImport(PreviewsMacros)
#Preview("Focus") {
    FocusConsoleView()
        .frame(width: 900, height: 640)
}
#endif
