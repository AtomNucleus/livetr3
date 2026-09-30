import AppKit
import SwiftUI
import XCTest
@testable import LiveTR3Mac

final class ProjectorLiveCaptionTests: XCTestCase {
    private func entry(_ id: Int, state: UtteranceState = .final) -> TranscriptUtterance {
        TranscriptUtterance(id: id, original: "We have ninety liters, not nineteen.",
            translation: "Tenemos noventa litros, no diecinueve.", state: state,
            stableOriginalLength: 0, stableTranslationLength: 0,
            startedAt: Date(), endedAt: state == .partial ? nil : Date())
    }

    func testLateFinalKeepsLiveUtteranceLastAndPreservesHistory() {
        let input = [entry(3, state: .partial), entry(1), entry(2)]
        let ordered = ProjectorLiveCaptionStage.orderedEntries(input)
        XCTAssertEqual(ordered.map(\.id), [1, 2, 3])
        XCTAssertEqual(ordered.last?.state, .partial)
        XCTAssertEqual(Set(ordered.map(\.translation)), Set(input.map(\.translation)))
    }

    @MainActor
    func testRenderLiveProjectorAndOperatorAt720pAnd1080p() async throws {
        var repo = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 { repo.deleteLastPathComponent() }
        let output = repo.appending(path: "dist/logs/native-latency-2026-09-30/renders")
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        for size in [CGSize(width: 1280, height: 720), CGSize(width: 1920, height: 1080)] {
            for style in ProjectorPresentationStyle.allCases {
                let view = ProjectorLiveCaptionStage(entries: [entry(1), entry(2, state: .partial)],
                    layout: ProjectorCaptionLayout(size: size, requestedFontSize: 72, style: style),
                    sourceLanguage: "English", targetLanguage: "Spanish")
                try await render(view, size: size, url: output.appending(path: "projector-\(style.rawValue)-\(Int(size.height)).png"))
            }
            let defaults = UserDefaults.standard
            let oldSession = defaults.object(forKey: "LiveTR3.sessionID")
            let testID = UUID().uuidString
            let manager = SessionManager(sessionID: testID)
            defer {
                if let oldSession { defaults.set(oldSession, forKey: "LiveTR3.sessionID") }
                else { defaults.removeObject(forKey: "LiveTR3.sessionID") }
                defaults.removeObject(forKey: SessionManager.fontStorageKey(testID))
            }
            let runtime = LiveTR3Runtime()
            let session = SessionController(sessionManager: manager, runtime: runtime)
            for id in 1...4 {
                session.transcript.handle(.caption(type: .final, utteranceID: id,
                    original: "We have ninety liters, not nineteen.", translation: "Tenemos noventa litros, no diecinueve."))
            }
            let operatorView = TeleprompterSessionSheetOperatorView(session: session, sessionManager: manager, onOpenProjector: {})
            try await render(operatorView, size: size, url: output.appending(path: "operator-\(Int(size.height)).png"))
        }
    }

    @MainActor
    private func render<V: View>(_ view: V, size: CGSize, url: URL) async throws {
        let host = NSHostingView(rootView: view)
        host.frame = CGRect(origin: .zero, size: size)
        let window = NSWindow(contentRect: host.frame, styleMask: .borderless, backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = host
        defer { window.close() }
        for _ in 0..<10 {
            host.layoutSubtreeIfNeeded()
            try await Task.sleep(nanoseconds: 20_000_000)
        }
        let bitmap = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        host.cacheDisplay(in: host.bounds, to: bitmap)
        try XCTUnwrap(bitmap.representation(using: .png, properties: [:])).write(to: url)
    }
}
