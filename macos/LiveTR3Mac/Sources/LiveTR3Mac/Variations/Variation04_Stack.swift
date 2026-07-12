import SwiftUI

/// Variation 4 — "Stack"
///
/// A single-column, top-to-bottom reading layout for narrow windows. A
/// segmented "focus" control chooses whether to show both languages, only the
/// source, or only the translation, so an operator can trade detail for larger
/// type without losing any capability. Settings open in a sheet.
struct StackConsoleView: View {
    enum Focus: String, CaseIterable, Identifiable {
        case both = "Both"
        case source = "Source"
        case target = "Target"
        var id: String { rawValue }
    }

    @StateObject private var model: ConsoleModel
    @State private var focus: Focus = .both
    @State private var settingsPresented = false

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            if let banner = model.banner {
                ConsoleBannerView(banner: banner)
            }
            panes
        }
        .background(.background)
        .sheet(isPresented: $settingsPresented) {
            settingsSheet
        }
    }

    private var header: some View {
        VStack(spacing: 12) {
            HStack(spacing: 14) {
                ConsoleStatusBadge(model: model)
                Spacer()
                ConsoleWaveform(model: model)
                ConsolePartialsIndicator(active: model.partialActive)
            }
            HStack(spacing: 10) {
                Picker("Focus", selection: $focus) {
                    ForEach(Focus.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(maxWidth: 320)

                Spacer()
                ConsoleTransportControls(model: model)
                Button {
                    settingsPresented = true
                } label: {
                    Label("Controls", systemImage: "slider.horizontal.3")
                }
                .buttonStyle(.bordered)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
        .background(.bar)
        .overlay(alignment: .bottom) { Divider() }
    }

    @ViewBuilder
    private var panes: some View {
        VStack(spacing: 0) {
            if focus != .target {
                ConsoleTranscriptPane(
                    title: model.config.source_lang,
                    language: model.config.source_lang,
                    entries: model.entries,
                    field: .original
                )
            }
            if focus == .both {
                Divider()
            }
            if focus != .source {
                ConsoleTranscriptPane(
                    title: model.config.target_lang,
                    language: model.config.target_lang,
                    entries: model.entries,
                    field: .translation
                )
            }
        }
    }

    private var settingsSheet: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Controls").font(.headline)
                Spacer()
                Button("Done") { settingsPresented = false }
                    .keyboardShortcut(.defaultAction)
            }
            .padding()
            Divider()
            ScrollView { ConsoleSettingsPanel(model: model) }
        }
        .frame(width: 600, height: 640)
    }
}

#if canImport(PreviewsMacros)
#Preview("Stack") {
    StackConsoleView()
        .frame(width: 720, height: 760)
}
#endif
