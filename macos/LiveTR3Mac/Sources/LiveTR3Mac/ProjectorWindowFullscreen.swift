import AppKit
import SwiftUI

/// SwiftUI's single Window scene can opt out of native fullscreen. Restore the
/// audience window's standard green-button behavior once its NSWindow exists.
struct ProjectorWindowFullscreen: NSViewRepresentable {
    func makeNSView(context: Context) -> WindowView { WindowView() }
    func updateNSView(_ view: WindowView, context: Context) { view.configureWindow() }

    final class WindowView: NSView {
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            configureWindow()
            // SwiftUI also applies scene configuration during attachment.
            DispatchQueue.main.async { [weak self] in self?.configureWindow() }
        }

        func configureWindow() {
            guard let window else { return }
            ProjectorWindowFullscreen.configure(window)
        }
    }

    static func configure(_ window: NSWindow) {
        window.styleMask.insert(.resizable)
        window.collectionBehavior.remove([.fullScreenNone, .fullScreenAuxiliary])
        window.collectionBehavior.insert(.fullScreenPrimary)
    }
}
