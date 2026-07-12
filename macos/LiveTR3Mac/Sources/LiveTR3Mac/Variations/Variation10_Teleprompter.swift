import SwiftUI

/// Variation 10 — "Teleprompter"
///
/// A presenter-facing reading surface: the translation fills the window at the
/// operator-set projector font size, with the source shown small above for
/// reference. A single Liquid Glass HUD holds all controls and auto-hides while
/// reading, reappearing on hover or when idle — keeping the reading area clean
/// without removing any capability.
struct TeleprompterConsoleView: View {
    @StateObject private var model: ConsoleModel
    @State private var hudVisible = true
    @State private var settingsOpen = false

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        ZStack(alignment: .bottom) {
            reader
            hud
                .padding(.bottom, 22)
                .opacity(hudVisible || settingsOpen ? 1 : 0)
                .animation(.easeInOut(duration: 0.2), value: hudVisible)
        }
        .background(Color.black.opacity(0.92))
        .onHover { hovering in
            hudVisible = hovering
        }
    }

    private var reader: some View {
        VStack(spacing: 0) {
            if let banner = model.banner {
                ConsoleBannerView(banner: banner)
            }
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        ForEach(model.entries) { entry in
                            VStack(alignment: .leading, spacing: 6) {
                                if !entry.original.isEmpty {
                                    Text(entry.original)
                                        .font(.title3)
                                        .foregroundStyle(.white.opacity(0.5))
                                }
                                Text(entry.translation)
                                    .font(.system(size: model.projectorFontSize, weight: .semibold))
                                    .foregroundStyle(entry.state == .partial ? .white.opacity(0.7) : .white)
                            }
                            .id(entry.id)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    .padding(.horizontal, 40)
                    .padding(.vertical, 40)
                }
                .onChange(of: model.entries.count) { _, _ in
                    if let last = model.entries.last {
                        withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo(last.id, anchor: .bottom) }
                    }
                }
            }
        }
    }

    private var hud: some View {
        HStack(spacing: 16) {
            ConsoleStatusBadge(model: model)
            ConsoleWaveform(model: model)
            ConsolePartialsIndicator(active: model.partialActive)
            Divider().frame(height: 22)
            HStack(spacing: 8) {
                Text("Aa").font(.caption).foregroundStyle(.secondary)
                Slider(value: $model.projectorFontSize, in: 36...144, step: 2)
                    .frame(width: 140)
            }
            Divider().frame(height: 22)
            ConsoleTransportControls(model: model)
            Button {
                settingsOpen.toggle()
            } label: {
                Image(systemName: "slider.horizontal.3")
            }
            .buttonStyle(.bordered)
            .popover(isPresented: $settingsOpen, arrowEdge: .bottom) {
                ScrollView { ConsoleSettingsPanel(model: model) }
                    .frame(width: 560, height: 620)
            }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 12)
        .liveGlassSurface(cornerRadius: 24, interactive: true)
        .liveGlassGroup()
        .shadow(color: .black.opacity(0.35), radius: 18, y: 8)
    }
}

#if canImport(PreviewsMacros)
#Preview("Teleprompter") {
    TeleprompterConsoleView()
        .frame(width: 1000, height: 700)
}
#endif
