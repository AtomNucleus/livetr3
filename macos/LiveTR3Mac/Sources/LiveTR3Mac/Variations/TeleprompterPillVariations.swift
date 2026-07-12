import SwiftUI

// MARK: - Teleprompter Session Sheet pill / floating-bar variations
//
// All variants keep Teleprompter Session Sheet behavior: full-bleed reading,
// dashboard settings sheet, auto-hiding controls on idle — but explore different
// pill and bar sizes, including layouts that adapt to window width.

// MARK: Shared shell + sizing

private struct TeleprompterPillMetrics {
    let containerWidth: CGFloat
    let containerHeight: CGFloat

    var isCompact: Bool { containerWidth < 760 }
    var isNarrow: Bool { containerWidth < 560 }

    /// Fluid pill: grows with the window but stays within readable bounds.
    var fluidPillWidth: CGFloat {
        min(max(containerWidth * 0.62, 380), 920)
    }

    /// Island pill: centered capsule that scales between 42% and 68% of width.
    var islandPillWidth: CGFloat {
        let ratio = containerWidth < 700 ? 0.78 : (containerWidth < 1100 ? 0.58 : 0.48)
        return min(max(containerWidth * ratio, 340), 880)
    }

    /// Corner radius that softens as the pill grows.
    func cornerRadius(for width: CGFloat, style: PillCornerStyle) -> CGFloat {
        switch style {
        case .capsule: width / 2
        case .rounded: min(max(width * 0.08, 14), 28)
        case .dock: 18
        }
    }

    var horizontalPadding: CGFloat {
        isNarrow ? 12 : (isCompact ? 14 : 18)
    }

    var verticalPadding: CGFloat {
        isNarrow ? 8 : (isCompact ? 10 : 12)
    }

    var bottomInset: CGFloat {
        isCompact ? 16 : 22
    }

    enum PillCornerStyle {
        case capsule
        case rounded
        case dock
    }
}

private struct TeleprompterSessionSheetShell<Pill: View>: View {
    @ObservedObject var model: ConsoleModel
    @Binding var settingsPresented: Bool
    @ViewBuilder var pill: (TeleprompterPillMetrics) -> Pill

    @State private var hudVisible = true

    var body: some View {
        GeometryReader { geometry in
            let metrics = TeleprompterPillMetrics(
                containerWidth: geometry.size.width,
                containerHeight: geometry.size.height
            )

            ZStack(alignment: .bottom) {
                TeleprompterCueReader(model: model)
                pill(metrics)
                    .padding(.bottom, metrics.bottomInset)
                    .opacity(hudVisible || settingsPresented ? 1 : 0)
                    .animation(.easeInOut(duration: 0.2), value: hudVisible)
            }
            .frame(width: geometry.size.width, height: geometry.size.height)
        }
        .background(Color.black.opacity(0.92))
        .onHover { hudVisible = $0 }
        .sheet(isPresented: $settingsPresented) {
            DashboardSessionControlsSheet(model: model, isPresented: $settingsPresented)
        }
    }
}

private struct TeleprompterPillChrome<Content: View>: View {
    let width: CGFloat?
    let cornerRadius: CGFloat
    let horizontalPadding: CGFloat
    let verticalPadding: CGFloat
    var fillsWidth = false
    @ViewBuilder var content: () -> Content

    var body: some View {
        Group {
            if let width {
                paddedContent.frame(width: width)
            } else if fillsWidth {
                paddedContent.frame(maxWidth: .infinity)
            } else {
                paddedContent
            }
        }
        .liveGlassSurface(cornerRadius: cornerRadius, interactive: true)
        .liveGlassGroup()
        .shadow(color: .black.opacity(0.35), radius: 18, y: 8)
    }

    private var paddedContent: some View {
        content()
            .padding(.horizontal, horizontalPadding)
            .padding(.vertical, verticalPadding)
    }
}

private struct TeleprompterPillControls: View {
    @ObservedObject var model: ConsoleModel
    @Binding var settingsPresented: Bool
    var metrics: TeleprompterPillMetrics
    var density: PillControlDensity

    enum PillControlDensity {
        case full
        case compact
        case minimal
    }

    var body: some View {
        switch density {
        case .full:
            fullControls
        case .compact:
            compactControls
        case .minimal:
            minimalControls
        }
    }

    private var fullControls: some View {
        HStack(spacing: metrics.isCompact ? 10 : 16) {
            TeleprompterTransportCluster(model: model, includeFontSlider: !metrics.isNarrow)
            controlsButton(label: "Controls")
        }
    }

    private var compactControls: some View {
        HStack(spacing: 10) {
            ConsoleStatusBadge(model: model, compact: true)
            if !metrics.isNarrow {
                ConsoleWaveform(model: model)
            }
            ConsolePartialsIndicator(active: model.partialActive)
            ConsoleTransportControls(model: model, showPause: !metrics.isNarrow)
            controlsButton(label: metrics.isNarrow ? nil : "Controls")
        }
    }

    private var minimalControls: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(model.statusColor)
                .frame(width: 9, height: 9)
            Button(action: model.startStop) {
                Image(systemName: model.status == .running ? "stop.fill" : "play.fill")
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.small)
            controlsButton(label: nil)
        }
    }

    @ViewBuilder
    private func controlsButton(label: String?) -> some View {
        Button {
            settingsPresented = true
        } label: {
            if let label {
                Label(label, systemImage: "slider.horizontal.3")
            } else {
                Image(systemName: "slider.horizontal.3")
            }
        }
        .buttonStyle(.bordered)
    }
}

// MARK: 1 — Compact Capsule (fixed small pill)

struct TeleprompterCompactCapsuleView: View {
    @StateObject private var model: ConsoleModel
    @State private var settingsPresented = false

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        TeleprompterSessionSheetShell(model: model, settingsPresented: $settingsPresented) { metrics in
            TeleprompterPillChrome(
                width: min(460, metrics.containerWidth - 48),
                cornerRadius: 28,
                horizontalPadding: 14,
                verticalPadding: 10
            ) {
                TeleprompterPillControls(
                    model: model,
                    settingsPresented: $settingsPresented,
                    metrics: metrics,
                    density: .compact
                )
            }
        }
    }
}

#if canImport(PreviewsMacros)
#Preview("Teleprompter Compact Capsule") {
    TeleprompterCompactCapsuleView()
        .frame(width: 1000, height: 700)
}
#endif

// MARK: 2 — Wide Dock (full-width floating bar)

struct TeleprompterWideDockView: View {
    @StateObject private var model: ConsoleModel
    @State private var settingsPresented = false

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        TeleprompterSessionSheetShell(model: model, settingsPresented: $settingsPresented) { metrics in
            TeleprompterPillChrome(
                width: nil,
                cornerRadius: metrics.cornerRadius(for: metrics.containerWidth, style: .dock),
                horizontalPadding: metrics.horizontalPadding + 4,
                verticalPadding: metrics.verticalPadding,
                fillsWidth: true
            ) {
                TeleprompterPillControls(
                    model: model,
                    settingsPresented: $settingsPresented,
                    metrics: metrics,
                    density: .full
                )
            }
            .padding(.horizontal, 20)
        }
    }
}

#if canImport(PreviewsMacros)
#Preview("Teleprompter Wide Dock") {
    TeleprompterWideDockView()
        .frame(width: 1100, height: 720)
}
#endif

// MARK: 3 — Fluid Pill (width scales with window)

struct TeleprompterFluidPillView: View {
    @StateObject private var model: ConsoleModel
    @State private var settingsPresented = false

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        TeleprompterSessionSheetShell(model: model, settingsPresented: $settingsPresented) { metrics in
            let width = metrics.fluidPillWidth
            TeleprompterPillChrome(
                width: width,
                cornerRadius: metrics.cornerRadius(for: width, style: .rounded),
                horizontalPadding: metrics.horizontalPadding,
                verticalPadding: metrics.verticalPadding
            ) {
                TeleprompterPillControls(
                    model: model,
                    settingsPresented: $settingsPresented,
                    metrics: metrics,
                    density: metrics.isCompact ? .compact : .full
                )
            }
        }
    }
}

#if canImport(PreviewsMacros)
#Preview("Teleprompter Fluid Pill") {
    TeleprompterFluidPillView()
        .frame(width: 1000, height: 700)
}
#endif

#if canImport(PreviewsMacros)
#Preview("Teleprompter Fluid Pill — Narrow") {
    TeleprompterFluidPillView()
        .frame(width: 520, height: 640)
}
#endif

// MARK: 4 — Breakpoint Bar (pill vs dock by window width)

struct TeleprompterBreakpointBarView: View {
    @StateObject private var model: ConsoleModel
    @State private var settingsPresented = false

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        TeleprompterSessionSheetShell(model: model, settingsPresented: $settingsPresented) { metrics in
            Group {
                if metrics.isCompact {
                    TeleprompterPillChrome(
                        width: min(520, metrics.containerWidth * 0.88),
                        cornerRadius: 30,
                        horizontalPadding: 14,
                        verticalPadding: 10
                    ) {
                        TeleprompterPillControls(
                            model: model,
                            settingsPresented: $settingsPresented,
                            metrics: metrics,
                            density: .compact
                        )
                    }
                } else {
                    TeleprompterPillChrome(
                        width: nil,
                        cornerRadius: 20,
                        horizontalPadding: 20,
                        verticalPadding: 12,
                        fillsWidth: true
                    ) {
                        TeleprompterPillControls(
                            model: model,
                            settingsPresented: $settingsPresented,
                            metrics: metrics,
                            density: .full
                        )
                    }
                    .padding(.horizontal, 24)
                }
            }
            .animation(.easeInOut(duration: 0.22), value: metrics.isCompact)
        }
    }
}

#if canImport(PreviewsMacros)
#Preview("Teleprompter Breakpoint Bar") {
    TeleprompterBreakpointBarView()
        .frame(width: 1040, height: 700)
}
#endif

#if canImport(PreviewsMacros)
#Preview("Teleprompter Breakpoint Bar — Compact") {
    TeleprompterBreakpointBarView()
        .frame(width: 640, height: 680)
}
#endif

// MARK: 5 — Minimal Icon Pill (tiny capsule, expands on hover)

struct TeleprompterMinimalIconPillView: View {
    @StateObject private var model: ConsoleModel
    @State private var settingsPresented = false
    @State private var expanded = false

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        TeleprompterSessionSheetShell(model: model, settingsPresented: $settingsPresented) { metrics in
            TeleprompterPillChrome(
                width: expanded ? min(420, metrics.containerWidth - 40) : 148,
                cornerRadius: expanded ? 26 : 74,
                horizontalPadding: expanded ? 14 : 10,
                verticalPadding: expanded ? 10 : 8
            ) {
                Group {
                    if expanded {
                        TeleprompterPillControls(
                            model: model,
                            settingsPresented: $settingsPresented,
                            metrics: metrics,
                            density: .compact
                        )
                    } else {
                        TeleprompterPillControls(
                            model: model,
                            settingsPresented: $settingsPresented,
                            metrics: metrics,
                            density: .minimal
                        )
                    }
                }
            }
            .onHover { expanded = $0 }
            .animation(.spring(response: 0.28, dampingFraction: 0.86), value: expanded)
        }
    }
}

#if canImport(PreviewsMacros)
#Preview("Teleprompter Minimal Icon Pill") {
    TeleprompterMinimalIconPillView()
        .frame(width: 960, height: 680)
}
#endif

// MARK: 6 — Slim Ribbon (low-height full-width bar)

struct TeleprompterSlimRibbonView: View {
    @StateObject private var model: ConsoleModel
    @State private var settingsPresented = false

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        TeleprompterSessionSheetShell(model: model, settingsPresented: $settingsPresented) { metrics in
            TeleprompterPillChrome(
                width: nil,
                cornerRadius: 12,
                horizontalPadding: 16,
                verticalPadding: 6,
                fillsWidth: true
            ) {
                HStack(spacing: 12) {
                    ConsoleStatusBadge(model: model, compact: true)
                    ConsoleWaveform(model: model)
                    Spacer(minLength: 8)
                    ConsolePartialsIndicator(active: model.partialActive)
                    ConsoleTransportControls(model: model, showPause: false)
                    Button {
                        settingsPresented = true
                    } label: {
                        Image(systemName: "slider.horizontal.3")
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                }
            }
            .padding(.horizontal, 16)
        }
    }
}

#if canImport(PreviewsMacros)
#Preview("Teleprompter Slim Ribbon") {
    TeleprompterSlimRibbonView()
        .frame(width: 1080, height: 700)
}
#endif

// MARK: 7 — Centered Island (pill width tracks window, always centered)

struct TeleprompterCenteredIslandView: View {
    @StateObject private var model: ConsoleModel
    @State private var settingsPresented = false

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        TeleprompterSessionSheetShell(model: model, settingsPresented: $settingsPresented) { metrics in
            let width = metrics.islandPillWidth
            HStack {
                Spacer(minLength: 0)
                TeleprompterPillChrome(
                    width: width,
                    cornerRadius: metrics.cornerRadius(for: width, style: .capsule),
                    horizontalPadding: metrics.horizontalPadding,
                    verticalPadding: metrics.verticalPadding
                ) {
                    TeleprompterPillControls(
                        model: model,
                        settingsPresented: $settingsPresented,
                        metrics: metrics,
                        density: metrics.isNarrow ? .compact : .full
                    )
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, max(12, metrics.containerWidth * 0.04))
        }
    }
}

#if canImport(PreviewsMacros)
#Preview("Teleprompter Centered Island") {
    TeleprompterCenteredIslandView()
        .frame(width: 1200, height: 720)
}
#endif

#if canImport(PreviewsMacros)
#Preview("Teleprompter Centered Island — Narrow") {
    TeleprompterCenteredIslandView()
        .frame(width: 560, height: 640)
}
#endif

// MARK: 8 — Stacked Dock (two-tier bar that grows with width)

struct TeleprompterStackedDockView: View {
    @StateObject private var model: ConsoleModel
    @State private var settingsPresented = false

    init(model: ConsoleModel = ConsoleModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        TeleprompterSessionSheetShell(model: model, settingsPresented: $settingsPresented) { metrics in
            let barWidth = min(max(metrics.containerWidth * 0.84, 400), 1040)
            TeleprompterPillChrome(
                width: barWidth,
                cornerRadius: 22,
                horizontalPadding: metrics.horizontalPadding,
                verticalPadding: metrics.verticalPadding
            ) {
                if metrics.isCompact {
                    VStack(spacing: 10) {
                        HStack {
                            ConsoleStatusBadge(model: model)
                            Spacer()
                            ConsolePartialsIndicator(active: model.partialActive)
                        }
                        HStack {
                            ConsoleWaveform(model: model)
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
                } else {
                    HStack(spacing: 16) {
                        ConsoleStatusBadge(model: model)
                        ConsoleWaveform(model: model)
                        ConsolePartialsIndicator(active: model.partialActive)
                        if metrics.containerWidth > 900 {
                            HStack(spacing: 8) {
                                Text("Aa").font(.caption).foregroundStyle(.secondary)
                                Slider(value: $model.projectorFontSize, in: 36...144, step: 2)
                                    .frame(width: min(180, metrics.containerWidth * 0.14))
                            }
                        }
                        Spacer(minLength: 8)
                        ConsoleTransportControls(model: model)
                        Button {
                            settingsPresented = true
                        } label: {
                            Label("Controls", systemImage: "slider.horizontal.3")
                        }
                        .buttonStyle(.bordered)
                    }
                }
            }
        }
    }
}

#if canImport(PreviewsMacros)
#Preview("Teleprompter Stacked Dock") {
    TeleprompterStackedDockView()
        .frame(width: 1100, height: 720)
}
#endif

#if canImport(PreviewsMacros)
#Preview("Teleprompter Stacked Dock — Compact") {
    TeleprompterStackedDockView()
        .frame(width: 620, height: 680)
}
#endif
