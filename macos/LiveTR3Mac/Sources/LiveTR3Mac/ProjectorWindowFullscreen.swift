import AppKit
import SwiftUI

/// SwiftUI's single Window scene opts out of native fullscreen, and re-applies that
/// whenever its scene phase changes (for example when the projector closes). Reopening
/// reuses the same NSWindow without moving this view, so watch the window's collection
/// behavior and restore the standard green-button fullscreen each time SwiftUI resets it.
struct ProjectorWindowFullscreen: NSViewRepresentable {
    func makeNSView(context: Context) -> WindowView { WindowView() }
    func updateNSView(_ view: WindowView, context: Context) { view.configureWindow() }

    final class WindowView: NSView {
        private var behaviorObservation: NSKeyValueObservation?

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            behaviorObservation = window?.observe(\.collectionBehavior) { window, _ in
                // Fires only when the behavior changes, and configure writes only when needed.
                MainActor.assumeIsolated { ProjectorWindowFullscreen.configure(window) }
            }
            configureWindow()
        }

        func configureWindow() {
            guard let window else { return }
            ProjectorWindowFullscreen.configure(window)
        }
    }

    @MainActor
    static func configure(_ window: NSWindow) {
        if !window.styleMask.contains(.resizable) {
            window.styleMask.insert(.resizable)
        }
        var behavior = window.collectionBehavior
        behavior.remove([.fullScreenNone, .fullScreenAuxiliary])
        behavior.insert(.fullScreenPrimary)
        if behavior != window.collectionBehavior {
            window.collectionBehavior = behavior
        }
    }
}
