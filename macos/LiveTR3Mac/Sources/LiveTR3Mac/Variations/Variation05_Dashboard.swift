import SwiftUI

/// Variation 5 — "Dashboard"
///
/// A monitoring layout: a row of status metric tiles on Liquid Glass sits above
/// two transcript cards. It emphasizes at-a-glance session health for a lead
/// operator. Settings open in a sheet so the dashboard stays glanceable.
struct DashboardConsoleView: View {
    @StateObject private var model: ConsoleModel
    @State private var settingsPresented = false

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        VStack(spacing: 16) {
            metrics
            if let banner = model.banner {
                ConsoleBannerView(banner: banner)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
            }
            transcriptCards
        }
        .padding(16)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(.background)
        .sheet(isPresented: $settingsPresented) {
            VStack(spacing: 0) {
                HStack {
                    Text("Session controls").font(.headline)
                    Spacer()
                    Button("Done") { settingsPresented = false }
                        .keyboardShortcut(.defaultAction)
                }
                .padding()
                Divider()
                ScrollView { ConsoleSettingsPanel(model: model) }
            }
            .frame(width: 620, height: 660)
        }
    }

    private var metrics: some View {
        HStack(spacing: 12) {
            metricTile(title: "Status", value: model.statusLabel, detail: model.directionText, symbol: model.statusSymbol, tint: model.statusColor)
            metricTile(title: "Input", value: model.selectedDeviceName, detail: "Silero VAD", symbol: "mic", tint: .secondary)
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text("Signal").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    ConsolePartialsIndicator(active: model.partialActive)
                }
                HStack {
                    ConsoleWaveform(model: model)
                    Spacer()
                    ConsoleTransportControls(model: model)
                }
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .liveGlassSurface(cornerRadius: 18)

            Button {
                settingsPresented = true
            } label: {
                Label("Controls", systemImage: "slider.horizontal.3")
                    .frame(maxWidth: .infinity, minHeight: 64)
            }
            .buttonStyle(.bordered)
            .frame(width: 140)
        }
        .liveGlassGroup()
    }

    private func metricTile(title: String, value: String, detail: String, symbol: String, tint: Color) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: symbol)
                .font(.title3)
                .foregroundStyle(tint)
                .frame(width: 26)
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.caption).foregroundStyle(.secondary)
                Text(value).font(.title3.weight(.semibold)).lineLimit(1).minimumScaleFactor(0.7)
                Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .liveGlassSurface(cornerRadius: 18)
    }

    private var transcriptCards: some View {
        HStack(spacing: 12) {
            card(title: model.config.source_lang, field: .original, language: model.config.source_lang)
            card(title: model.config.target_lang, field: .translation, language: model.config.target_lang)
        }
    }

    private func card(title: String, field: TranscriptLineView.TranscriptField, language: String) -> some View {
        ConsoleTranscriptPane(title: title, language: language, entries: model.entries, field: field)
            .background(.quaternary)
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .strokeBorder(.separator)
            }
    }
}

#if canImport(PreviewsMacros)
#Preview("Dashboard") {
    DashboardConsoleView()
        .frame(width: 1200, height: 760)
}
#endif
