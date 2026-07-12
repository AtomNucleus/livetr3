import SwiftUI

/// Variation 7 — "Cockpit"
///
/// A dense, always-on operating station. A persistent right-hand panel keeps
/// controls one click away and uses a segmented tab to switch between task
/// groups (Setup / Session / Timing), avoiding a long scroll while audio is
/// live (HIG: split long control sets into logical groups).
struct CockpitConsoleView: View {
    enum Tab: String, CaseIterable, Identifiable {
        case setup = "Setup"
        case session = "Session"
        case timing = "Timing"
        var id: String { rawValue }
    }

    @StateObject private var model: ConsoleModel
    @State private var tab: Tab = .setup

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        HStack(spacing: 0) {
            transcriptSide
            Divider()
            controlPanel
                .frame(width: 360)
        }
        .background(.background)
    }

    private var transcriptSide: some View {
        VStack(spacing: 0) {
            HStack(spacing: 14) {
                ConsoleStatusBadge(model: model)
                Spacer()
                ConsoleWaveform(model: model)
                ConsolePartialsIndicator(active: model.partialActive)
                ConsoleTransportControls(model: model)
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 12)
            .background(.bar)
            .overlay(alignment: .bottom) { Divider() }

            if let banner = model.banner {
                ConsoleBannerView(banner: banner)
            }

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
        .frame(maxWidth: .infinity)
    }

    private var controlPanel: some View {
        VStack(spacing: 0) {
            Picker("Section", selection: $tab) {
                ForEach(Tab.allCases) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .padding(12)

            Divider()

            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    switch tab {
                    case .setup:
                        group("Caption setup") { CaptionSetupControls(model: model) }
                        group("Input") { InputControls(model: model) }
                        group("Output") { OutputControls(model: model) }
                        DisclosureGroup("Custom vocabulary") {
                            CustomVocabEditor(model: model).padding(.top, 8)
                        }
                        .font(.caption.weight(.semibold)).textCase(.uppercase).foregroundStyle(.secondary)
                    case .session:
                        group("Live session actions") { SessionActionControls(model: model) }
                        group("Export") { ExportControls(model: model) }
                    case .timing:
                        group("Advanced timing") { AdvancedTimingControls(model: model) }
                    }
                }
                .padding(16)
            }
        }
        .background(.bar)
    }

    @ViewBuilder
    private func group<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
            content()
        }
    }
}

#if canImport(PreviewsMacros)
#Preview("Cockpit") {
    CockpitConsoleView()
        .frame(width: 1200, height: 720)
}
#endif
