import SwiftUI

/// Variation 2 — "Studio"
///
/// A `NavigationSplitView` that puts all persistent setup in a grouped
/// sidebar Form (HIG: group related controls, most-important first) and keeps
/// the dual-pane transcript in the detail column. Transport lives in the
/// toolbar so Start/Stop and Pause/Resume are always reachable.
struct StudioConsoleView: View {
    @StateObject private var model: ConsoleModel
    @State private var columnVisibility: NavigationSplitViewVisibility = .all

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        NavigationSplitView(columnVisibility: $columnVisibility) {
            VStack(spacing: 0) {
                sidebarHeader
                Divider()
                ConsoleSettingsForm(model: model)
            }
            .navigationSplitViewColumnWidth(min: 320, ideal: 360, max: 420)
        } detail: {
            detail
                .navigationTitle("LiveTR3 Studio")
                .toolbar {
                    ToolbarItemGroup(placement: .primaryAction) {
                        ConsolePartialsIndicator(active: model.partialActive)
                        ConsoleTransportControls(model: model)
                    }
                }
        }
    }

    private var sidebarHeader: some View {
        HStack(spacing: 10) {
            Image(systemName: model.statusSymbol)
                .foregroundStyle(model.statusColor)
            VStack(alignment: .leading, spacing: 2) {
                Text(model.statusLabel).font(.headline)
                Text(model.directionText).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            ConsoleWaveform(model: model)
        }
        .padding(16)
    }

    private var detail: some View {
        VStack(spacing: 0) {
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
        .background(.background)
    }
}

#if canImport(PreviewsMacros)
#Preview("Studio") {
    StudioConsoleView()
        .frame(width: 1180, height: 720)
}
#endif
