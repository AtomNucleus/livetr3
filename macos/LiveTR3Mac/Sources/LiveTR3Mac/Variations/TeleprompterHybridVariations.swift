import SwiftUI

// MARK: - Shared teleprompter + dashboard settings sheet building blocks
//
// These hybrids keep the Teleprompter reading surface (large translation type,
// optional source reference, minimal chrome) and use the Dashboard-style session
// controls sheet (header + Done + scrollable grouped settings panel).

/// Dashboard-style settings presentation: a titled sheet with a Done dismiss action.
struct DashboardSessionControlsSheet: View {
    @ObservedObject var model: ConsoleModel
    @Binding var isPresented: Bool

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Session controls")
                    .font(.headline)
                Spacer()
                Button("Done") { isPresented = false }
                    .keyboardShortcut(.defaultAction)
            }
            .padding()
            Divider()
            ScrollView {
                ConsoleSettingsPanel(model: model)
            }
        }
        .frame(width: 620, height: 660)
    }
}

/// Shared teleprompter cue reader with configurable layout.
struct TeleprompterCueReader: View {
    @ObservedObject var model: ConsoleModel
    var alignment: HorizontalAlignment = .leading
    var textAlignment: TextAlignment = .leading
    var showSource = true
    var cueSpacing: CGFloat = 18
    var horizontalPadding: CGFloat = 40
    var verticalPadding: CGFloat = 40

    var body: some View {
        VStack(spacing: 0) {
            if let banner = model.banner {
                ConsoleBannerView(banner: banner)
            }
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: alignment, spacing: cueSpacing) {
                        ForEach(model.entries) { entry in
                            cueBlock(for: entry)
                                .id(entry.id)
                        }
                    }
                    .padding(.horizontal, horizontalPadding)
                    .padding(.vertical, verticalPadding)
                }
                .onChange(of: model.entries.count) { _, _ in
                    scrollToLatest(using: proxy)
                }
                .onChange(of: model.entries.last?.translation) { _, _ in
                    scrollToLatest(using: proxy)
                }
            }
        }
    }

    @ViewBuilder
    private func cueBlock(for entry: TranscriptUtterance) -> some View {
        VStack(alignment: alignment, spacing: 6) {
            if showSource, !entry.original.isEmpty {
                Text(entry.original)
                    .font(.title3)
                    .foregroundStyle(.white.opacity(0.5))
                    .multilineTextAlignment(textAlignment)
            }
            Text(entry.translation)
                .font(.system(size: model.projectorFontSize, weight: .semibold))
                .foregroundStyle(entry.state == .partial ? .white.opacity(0.7) : .white)
                .multilineTextAlignment(textAlignment)
        }
        .frame(maxWidth: .infinity, alignment: frameAlignment)
    }

    private var frameAlignment: Alignment {
        switch alignment {
        case .center: .center
        case .trailing: .trailing
        default: .leading
        }
    }

    private func scrollToLatest(using proxy: ScrollViewProxy) {
        guard let last = model.entries.last else { return }
        withAnimation(.easeOut(duration: 0.2)) {
            proxy.scrollTo(last.id, anchor: .bottom)
        }
    }
}

/// Compact transport + font slider cluster reused across teleprompter HUDs.
struct TeleprompterTransportCluster: View {
    @ObservedObject var model: ConsoleModel
    var includeFontSlider = true

    var body: some View {
        HStack(spacing: 12) {
            ConsoleStatusBadge(model: model, compact: true)
            ConsoleWaveform(model: model)
            ConsolePartialsIndicator(active: model.partialActive)
            if includeFontSlider {
                Divider().frame(height: 22)
                HStack(spacing: 8) {
                    Text("Aa")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Slider(value: $model.projectorFontSize, in: 36...144, step: 2)
                        .frame(width: 120)
                }
            }
            Divider().frame(height: 22)
            ConsoleTransportControls(model: model)
        }
    }
}

// MARK: - Hybrid 1: Teleprompter Session Sheet
//
// The direct merge: auto-hiding bottom glass HUD from Teleprompter, with
// Dashboard's session controls sheet instead of a popover.

struct TeleprompterSessionSheetView: View {
    @StateObject private var model: ConsoleModel
    @State private var hudVisible = true
    @State private var settingsPresented = false

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        ZStack(alignment: .bottom) {
            TeleprompterCueReader(model: model)
            bottomHUD
                .padding(.bottom, 22)
                .opacity(hudVisible || settingsPresented ? 1 : 0)
                .animation(.easeInOut(duration: 0.2), value: hudVisible)
        }
        .background(Color.black.opacity(0.92))
        .onHover { hudVisible = $0 }
        .sheet(isPresented: $settingsPresented) {
            DashboardSessionControlsSheet(model: model, isPresented: $settingsPresented)
        }
    }

    private var bottomHUD: some View {
        HStack(spacing: 16) {
            TeleprompterTransportCluster(model: model)
            Button {
                settingsPresented = true
            } label: {
                Label("Controls", systemImage: "slider.horizontal.3")
            }
            .buttonStyle(.bordered)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 12)
        .liveGlassSurface(cornerRadius: 24, interactive: true)
        .liveGlassGroup()
        .shadow(color: .black.opacity(0.35), radius: 18, y: 8)
    }
}

#if canImport(PreviewsMacros)
#Preview("Teleprompter Session Sheet") {
    TeleprompterSessionSheetView()
        .frame(width: 1000, height: 700)
}
#endif

// MARK: - Hybrid 2: Teleprompter Overhead Rail
//
// Status and transport live in a persistent top glass rail; the reading surface
// stays full-bleed below. Settings open in the Dashboard sheet from the rail.

struct TeleprompterOverheadRailView: View {
    @StateObject private var model: ConsoleModel
    @State private var settingsPresented = false

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        VStack(spacing: 0) {
            topRail
            TeleprompterCueReader(model: model)
        }
        .background(Color.black.opacity(0.92))
        .sheet(isPresented: $settingsPresented) {
            DashboardSessionControlsSheet(model: model, isPresented: $settingsPresented)
        }
    }

    private var topRail: some View {
        HStack(spacing: 16) {
            TeleprompterTransportCluster(model: model)
            Spacer(minLength: 12)
            Button {
                settingsPresented = true
            } label: {
                Label("Session controls", systemImage: "slider.horizontal.3")
            }
            .buttonStyle(.borderedProminent)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
        .background(.bar.opacity(0.35))
        .overlay(alignment: .bottom) { Divider().opacity(0.35) }
    }
}

#if canImport(PreviewsMacros)
#Preview("Teleprompter Overhead Rail") {
    TeleprompterOverheadRailView()
        .frame(width: 1000, height: 700)
}
#endif

// MARK: - Hybrid 3: Teleprompter Corner Command
//
// A compact glass command stack in the bottom-trailing corner keeps the reading
// area almost entirely clear. Full controls live in the Dashboard sheet.

struct TeleprompterCornerCommandView: View {
    @StateObject private var model: ConsoleModel
    @State private var commandVisible = true
    @State private var settingsPresented = false

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            TeleprompterCueReader(model: model, horizontalPadding: 56, verticalPadding: 48)
            cornerStack
                .padding(24)
                .opacity(commandVisible || settingsPresented ? 1 : 0.35)
                .animation(.easeInOut(duration: 0.2), value: commandVisible)
        }
        .background(Color.black.opacity(0.94))
        .onHover { commandVisible = $0 }
        .sheet(isPresented: $settingsPresented) {
            DashboardSessionControlsSheet(model: model, isPresented: $settingsPresented)
        }
    }

    private var cornerStack: some View {
        VStack(alignment: .trailing, spacing: 10) {
            HStack(spacing: 8) {
                ConsolePartialsIndicator(active: model.partialActive)
                ConsoleWaveform(model: model)
            }
            ConsoleTransportControls(model: model, showPause: false)
            Button {
                settingsPresented = true
            } label: {
                Label("Controls", systemImage: "slider.horizontal.3")
                    .frame(minWidth: 120)
            }
            .buttonStyle(.borderedProminent)
        }
        .padding(14)
        .liveGlassSurface(cornerRadius: 20, interactive: true)
        .liveGlassGroup()
        .shadow(color: .black.opacity(0.4), radius: 16, y: 6)
    }
}

#if canImport(PreviewsMacros)
#Preview("Teleprompter Corner Command") {
    TeleprompterCornerCommandView()
        .frame(width: 960, height: 680)
}
#endif

// MARK: - Hybrid 4: Teleprompter Center Stage
//
// Cues are centered for presenter-style reading. A slim bottom dock carries
// transport; session setup opens in the Dashboard sheet.

struct TeleprompterCenterStageView: View {
    @StateObject private var model: ConsoleModel
    @State private var settingsPresented = false

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        VStack(spacing: 0) {
            TeleprompterCueReader(
                model: model,
                alignment: .center,
                textAlignment: .center,
                showSource: false,
                cueSpacing: 28,
                horizontalPadding: 80,
                verticalPadding: 60
            )
            bottomDock
        }
        .background(
            RadialGradient(
                colors: [Color.white.opacity(0.06), Color.black.opacity(0.96)],
                center: .center,
                startRadius: 40,
                endRadius: 520
            )
        )
        .sheet(isPresented: $settingsPresented) {
            DashboardSessionControlsSheet(model: model, isPresented: $settingsPresented)
        }
    }

    private var bottomDock: some View {
        HStack(spacing: 14) {
            ConsoleStatusBadge(model: model)
            Spacer()
            ConsolePartialsIndicator(active: model.partialActive)
            ConsoleTransportControls(model: model)
            Button {
                settingsPresented = true
            } label: {
                Label("Controls", systemImage: "slider.horizontal.3")
            }
            .buttonStyle(.bordered)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 12)
        .background(.bar.opacity(0.25))
        .overlay(alignment: .top) { Divider().opacity(0.25) }
    }
}

#if canImport(PreviewsMacros)
#Preview("Teleprompter Center Stage") {
    TeleprompterCenterStageView()
        .frame(width: 1000, height: 720)
}
#endif

// MARK: - Hybrid 5: Teleprompter Split Reference
//
// A fixed source reference strip sits above the main translation scroll so the
// operator can glance at the original without leaving teleprompter mode.
// Settings use the Dashboard sheet from the top control strip.

struct TeleprompterSplitReferenceView: View {
    @StateObject private var model: ConsoleModel
    @State private var settingsPresented = false

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        VStack(spacing: 0) {
            controlStrip
            referenceStrip
            Divider().opacity(0.25)
            TeleprompterCueReader(model: model, showSource: false, verticalPadding: 28)
        }
        .background(Color.black.opacity(0.92))
        .sheet(isPresented: $settingsPresented) {
            DashboardSessionControlsSheet(model: model, isPresented: $settingsPresented)
        }
    }

    private var controlStrip: some View {
        HStack(spacing: 12) {
            ConsoleStatusBadge(model: model)
            ConsoleWaveform(model: model)
            ConsolePartialsIndicator(active: model.partialActive)
            Spacer()
            ConsoleTransportControls(model: model)
            Button {
                settingsPresented = true
            } label: {
                Label("Controls", systemImage: "slider.horizontal.3")
            }
            .buttonStyle(.bordered)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 10)
        .background(.bar.opacity(0.3))
    }

    private var referenceStrip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 16) {
                ForEach(model.entries.filter { !$0.original.isEmpty }) { entry in
                    Text(entry.original)
                        .font(.callout)
                        .foregroundStyle(.white.opacity(0.55))
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .background(.white.opacity(0.08), in: Capsule())
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 10)
        }
        .frame(maxHeight: 56)
    }
}

#if canImport(PreviewsMacros)
#Preview("Teleprompter Split Reference") {
    TeleprompterSplitReferenceView()
        .frame(width: 1040, height: 720)
}
#endif

// MARK: - Hybrid 6: Teleprompter Presenter HUD
//
// Large translation with inline source above each cue, plus a presenter HUD that
// fades on idle and exposes font size + transport. Session controls open in the
// Dashboard sheet — the pattern the user preferred from Dashboard.

struct TeleprompterPresenterHUDView: View {
    @StateObject private var model: ConsoleModel
    @State private var hudVisible = true
    @State private var settingsPresented = false

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        ZStack {
            TeleprompterCueReader(
                model: model,
                cueSpacing: 22,
                horizontalPadding: 48,
                verticalPadding: 48
            )

            VStack {
                presenterHeader
                    .opacity(hudVisible || settingsPresented ? 1 : 0)
                    .animation(.easeInOut(duration: 0.2), value: hudVisible)
                Spacer()
                presenterFooter
                    .opacity(hudVisible || settingsPresented ? 1 : 0)
                    .animation(.easeInOut(duration: 0.2), value: hudVisible)
            }
        }
        .background(Color.black.opacity(0.93))
        .onHover { hudVisible = $0 }
        .sheet(isPresented: $settingsPresented) {
            DashboardSessionControlsSheet(model: model, isPresented: $settingsPresented)
        }
    }

    private var presenterHeader: some View {
        HStack {
            Label(model.directionText, systemImage: "character.book.closed")
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Spacer()
            ConsolePartialsIndicator(active: model.partialActive)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 10)
        .background(.black.opacity(0.45))
    }

    private var presenterFooter: some View {
        HStack(spacing: 14) {
            TeleprompterTransportCluster(model: model)
            Button {
                settingsPresented = true
            } label: {
                Label("Session controls", systemImage: "slider.horizontal.3")
            }
            .buttonStyle(.borderedProminent)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 12)
        .liveGlassSurface(cornerRadius: 22, interactive: true)
        .liveGlassGroup()
        .padding(.horizontal, 20)
        .padding(.bottom, 20)
        .shadow(color: .black.opacity(0.35), radius: 16, y: 8)
    }
}

#if canImport(PreviewsMacros)
#Preview("Teleprompter Presenter HUD") {
    TeleprompterPresenterHUDView()
        .frame(width: 1000, height: 700)
}
#endif
