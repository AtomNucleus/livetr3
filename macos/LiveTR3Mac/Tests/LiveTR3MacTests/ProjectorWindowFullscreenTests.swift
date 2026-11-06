import AppKit
import XCTest
@testable import LiveTR3Mac

@MainActor
final class ProjectorWindowFullscreenTests: XCTestCase {
    func testGreenButtonCanEnterFullscreenWithoutChangingOtherWindowBehavior() {
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 720),
                              styleMask: [.titled, .closable, .miniaturizable],
                              backing: .buffered, defer: true)
        window.collectionBehavior = [.fullScreenNone, .managed]
        ProjectorWindowFullscreen.configure(window)
        XCTAssertTrue(window.styleMask.contains(.resizable))
        XCTAssertTrue(window.collectionBehavior.contains(.fullScreenPrimary))
        XCTAssertTrue(window.collectionBehavior.contains(.managed))
        XCTAssertFalse(window.collectionBehavior.contains(.fullScreenNone))
        XCTAssertFalse(window.collectionBehavior.contains(.fullScreenAuxiliary))
        ProjectorWindowFullscreen.configure(window)
        XCTAssertTrue(window.collectionBehavior.contains(.fullScreenPrimary))
    }

    func testFullscreenSurvivesSwiftUIResettingTheReusedWindow() {
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 720),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable],
                              backing: .buffered, defer: true)
        window.isReleasedWhenClosed = false
        window.contentView?.addSubview(ProjectorWindowFullscreen.WindowView())
        XCTAssertTrue(window.collectionBehavior.contains(.fullScreenPrimary))

        // What SwiftUI's Window scene writes when the projector closes; reopening reuses the window.
        window.collectionBehavior = [.fullScreenAuxiliary, .fullScreenAllowsTiling]
        XCTAssertTrue(window.collectionBehavior.contains(.fullScreenPrimary))
        XCTAssertFalse(window.collectionBehavior.contains(.fullScreenAuxiliary))
        XCTAssertTrue(window.collectionBehavior.contains(.fullScreenAllowsTiling))

        window.collectionBehavior.insert(.fullScreenNone)
        XCTAssertFalse(window.collectionBehavior.contains(.fullScreenNone))
        XCTAssertTrue(window.collectionBehavior.contains(.fullScreenPrimary))
    }
}
