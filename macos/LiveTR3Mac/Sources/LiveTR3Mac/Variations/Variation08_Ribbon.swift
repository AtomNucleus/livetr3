import SwiftUI

/// Variation 8 — "Ribbon"
///
/// A command-ribbon layout. A single top ribbon groups the most frequent live
/// controls left-to-right in reading order (caption setup, then input, then
/// transport), with rarely used controls behind a "More" popover. A slim bottom
/// status ribbon reports session health.
struct RibbonConsoleView: View {
    @StateObject private var model: ConsoleModel
    @State private var moreOpen = false

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        VStack(spacing: 0) {
            commandRibbon
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
            statusRibbon
        }
        .background(.background)
    }

    private var commandRibbon: some View {
        HStack(alignment: .bottom, spacing: 18) {
            ribbonGroup("Direction") {
                HStack(spacing: 8) {
                    LanguageMenuPicker(title: "Source", selection: model.sourceBinding, maxWidth: 150)
                    Button("Swap", action: model.swapDirection).buttonStyle(.bordered)
                    LanguageMenuPicker(title: "Target", selection: model.targetBinding, maxWidth: 150)
                }
            }
            Divider().frame(height: 44)
            ribbonGroup("Input") {
                Picker("Microphone", selection: model.deviceBinding) {
                    Text("System default").tag("")
                    ForEach(model.devices) { Text($0.name).tag($0.id) }
                }
                .labelsHidden()
                .frame(maxWidth: 200)
            }
            Spacer(minLength: 12)
            ribbonGroup("Session") {
                HStack(spacing: 8) {
                    ConsoleTransportControls(model: model)
                    Button {
                        moreOpen.toggle()
                    } label: {
                        Label("More", systemImage: "ellipsis.circle")
                    }
                    .buttonStyle(.bordered)
                    .popover(isPresented: $moreOpen, arrowEdge: .bottom) {
                        ScrollView {
                            ConsoleSettingsPanel(model: model)
                        }
                        .frame(width: 560, height: 560)
                    }
                }
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
        .background(.bar)
        .overlay(alignment: .bottom) { Divider() }
    }

    private var statusRibbon: some View {
        HStack(spacing: 16) {
            ConsoleStatusBadge(model: model)
            Spacer()
            ConsoleWaveform(model: model)
            ConsolePartialsIndicator(active: model.partialActive)
            Text(model.selectedDeviceName)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 8)
        .background(.bar)
        .overlay(alignment: .top) { Divider() }
    }

    @ViewBuilder
    private func ribbonGroup<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
            content()
        }
    }
}

#if canImport(PreviewsMacros)
#Preview("Ribbon") {
    RibbonConsoleView()
        .frame(width: 1220, height: 720)
}
#endif
