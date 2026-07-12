import SwiftUI

/// A catalog of every operator interface variation, used by the gallery window
/// (launched with `LIVETR3_GALLERY=1`) so all ten can be browsed and opened.
enum VariationCatalog {
    struct Item: Identifiable, Hashable {
        let id: String
        let title: String
        let subtitle: String
        let symbol: String
    }

    static let all: [Item] = [
        Item(id: "aurora", title: "Aurora", subtitle: "Dual pane + floating glass dock", symbol: "sparkles"),
        Item(id: "studio", title: "Studio", subtitle: "Split view, settings in sidebar", symbol: "sidebar.left"),
        Item(id: "broadcast", title: "Broadcast", subtitle: "Toolbar + settings inspector", symbol: "dot.radiowaves.left.and.right"),
        Item(id: "stack", title: "Stack", subtitle: "Single column, segmented focus", symbol: "square.stack"),
        Item(id: "dashboard", title: "Dashboard", subtitle: "Status tiles + transcript cards", symbol: "rectangle.3.group"),
        Item(id: "focus", title: "Focus", subtitle: "One language + floating mic pill", symbol: "scope"),
        Item(id: "cockpit", title: "Cockpit", subtitle: "Persistent tabbed control panel", symbol: "gauge.with.dots.needle.67percent"),
        Item(id: "ribbon", title: "Ribbon", subtitle: "Command ribbon + status ribbon", symbol: "menubar.rectangle"),
        Item(id: "carddeck", title: "Card Deck", subtitle: "Liquid Glass card deck", symbol: "rectangle.on.rectangle"),
        Item(id: "teleprompter", title: "Teleprompter", subtitle: "Full-bleed reading + auto HUD", symbol: "text.alignleft"),
        Item(id: "tp-session-sheet", title: "Teleprompter Session Sheet", subtitle: "Auto HUD + dashboard settings sheet", symbol: "doc.text"),
        Item(id: "tp-overhead-rail", title: "Teleprompter Overhead Rail", subtitle: "Top rail controls + teleprompter scroll", symbol: "rectangle.topthird.inset.filled"),
        Item(id: "tp-corner-command", title: "Teleprompter Corner Command", subtitle: "Corner command stack + settings sheet", symbol: "arrow.down.right.circle"),
        Item(id: "tp-center-stage", title: "Teleprompter Center Stage", subtitle: "Centered cues + bottom dock", symbol: "text.aligncenter"),
        Item(id: "tp-split-reference", title: "Teleprompter Split Reference", subtitle: "Source strip + translation scroll", symbol: "rectangle.split.2x1"),
        Item(id: "tp-presenter-hud", title: "Teleprompter Presenter HUD", subtitle: "Dual HUD bands + session sheet", symbol: "person.crop.rectangle.stack"),
        Item(id: "tp-compact-capsule", title: "Teleprompter Compact Capsule", subtitle: "Fixed small floating pill", symbol: "capsule"),
        Item(id: "tp-wide-dock", title: "Teleprompter Wide Dock", subtitle: "Full-width floating dock bar", symbol: "rectangle.bottomhalf.inset.filled"),
        Item(id: "tp-fluid-pill", title: "Teleprompter Fluid Pill", subtitle: "Pill width scales with window", symbol: "arrow.left.and.right"),
        Item(id: "tp-breakpoint-bar", title: "Teleprompter Breakpoint Bar", subtitle: "Capsule or dock by window width", symbol: "rectangle.compress.vertical"),
        Item(id: "tp-minimal-icon-pill", title: "Teleprompter Minimal Icon Pill", subtitle: "Tiny pill expands on hover", symbol: "circle.circle"),
        Item(id: "tp-slim-ribbon", title: "Teleprompter Slim Ribbon", subtitle: "Low-height full-width ribbon", symbol: "minus.rectangle"),
        Item(id: "tp-centered-island", title: "Teleprompter Centered Island", subtitle: "Centered pill tracks window size", symbol: "circle.dashed"),
        Item(id: "tp-stacked-dock", title: "Teleprompter Stacked Dock", subtitle: "Two-tier dock grows with width", symbol: "square.stack.3d.down.right")
    ]

    static func item(for id: String?) -> Item? {
        all.first { $0.id == id }
    }

    @ViewBuilder
    static func view(for id: String?) -> some View {
        switch id {
        case "aurora": AuroraConsoleView()
        case "studio": StudioConsoleView()
        case "broadcast": BroadcastConsoleView()
        case "stack": StackConsoleView()
        case "dashboard": DashboardConsoleView()
        case "focus": FocusConsoleView()
        case "cockpit": CockpitConsoleView()
        case "ribbon": RibbonConsoleView()
        case "carddeck": CardDeckConsoleView()
        case "teleprompter": TeleprompterConsoleView()
        case "tp-session-sheet": TeleprompterSessionSheetView()
        case "tp-overhead-rail": TeleprompterOverheadRailView()
        case "tp-corner-command": TeleprompterCornerCommandView()
        case "tp-center-stage": TeleprompterCenterStageView()
        case "tp-split-reference": TeleprompterSplitReferenceView()
        case "tp-presenter-hud": TeleprompterPresenterHUDView()
        case "tp-compact-capsule": TeleprompterCompactCapsuleView()
        case "tp-wide-dock": TeleprompterWideDockView()
        case "tp-fluid-pill": TeleprompterFluidPillView()
        case "tp-breakpoint-bar": TeleprompterBreakpointBarView()
        case "tp-minimal-icon-pill": TeleprompterMinimalIconPillView()
        case "tp-slim-ribbon": TeleprompterSlimRibbonView()
        case "tp-centered-island": TeleprompterCenteredIslandView()
        case "tp-stacked-dock": TeleprompterStackedDockView()
        default:
            ContentUnavailableViewCompat(
                title: "Choose a variation",
                message: "Select an interface from the sidebar to preview it.",
                symbol: "square.grid.2x2"
            )
        }
    }
}

/// Browsable gallery of all interface variations.
struct VariationGalleryView: View {
    @Environment(\.openWindow) private var openWindow
    @State private var selection: String? = VariationCatalog.all.first?.id
    @State private var didOpenAll = false

    private var opensAllOnLaunch: Bool {
        ProcessInfo.processInfo.environment["LIVETR3_OPEN_ALL"] != "0"
    }

    private var requestedLaunchIDs: [String]? {
        guard let requestedIDs = ProcessInfo.processInfo.environment["LIVETR3_OPEN_VARIATIONS"] else {
            return nil
        }
        return requestedIDs
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
    }

    private var variationsToOpenOnLaunch: [VariationCatalog.Item] {
        if let ids = requestedLaunchIDs {
            return VariationCatalog.all.filter { ids.contains($0.id) }
        }

        return opensAllOnLaunch ? VariationCatalog.all : []
    }

    var body: some View {
        NavigationSplitView {
            List(VariationCatalog.all, selection: $selection) { item in
                Label {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(item.title)
                        Text(item.subtitle)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                } icon: {
                    Image(systemName: item.symbol)
                }
                .tag(item.id)
            }
            .navigationTitle("Variations")
            .navigationSplitViewColumnWidth(min: 240, ideal: 280, max: 320)
            .toolbar {
                ToolbarItem {
                    Button {
                        for item in VariationCatalog.all {
                            openWindow(id: LiveTR3WindowID.variation, value: item.id)
                        }
                    } label: {
                        Label("Open All in Windows", systemImage: "macwindow.on.rectangle")
                    }
                }
            }
        } detail: {
            VariationCatalog.view(for: selection)
                .navigationTitle(VariationCatalog.item(for: selection)?.title ?? "Variation")
                .toolbar {
                    if let selection {
                        ToolbarItem {
                            Button {
                                openWindow(id: LiveTR3WindowID.variation, value: selection)
                            } label: {
                                Label("Open in Window", systemImage: "macwindow")
                            }
                        }
                    }
                }
        }
        .onAppear {
            guard !didOpenAll else { return }
            let items = variationsToOpenOnLaunch
            guard !items.isEmpty else { return }
            didOpenAll = true
            Task {
                for item in items {
                    openWindow(id: LiveTR3WindowID.variation, value: item.id)
                    try? await Task.sleep(nanoseconds: 150_000_000)
                }
            }
        }
    }
}

/// Standalone window chrome for a single variation opened from the gallery.
struct VariationWindowRoot: View {
    let id: String

    var body: some View {
        VariationCatalog.view(for: id)
            .frame(minWidth: 900, minHeight: 640)
    }
}

/// Minimal fallback so the gallery builds on macOS 14 without `ContentUnavailableView` edge cases.
private struct ContentUnavailableViewCompat: View {
    let title: String
    let message: String
    let symbol: String

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: symbol)
                .font(.system(size: 40, weight: .semibold))
                .foregroundStyle(.secondary)
            Text(title).font(.title2.weight(.semibold))
            Text(message)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

#if canImport(PreviewsMacros)
#Preview("Gallery") {
    VariationGalleryView()
        .frame(width: 1240, height: 820)
}
#endif
