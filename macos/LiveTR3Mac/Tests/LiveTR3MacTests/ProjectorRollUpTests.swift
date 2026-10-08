import AppKit
import SwiftUI
import XCTest
@testable import LiveTR3Mac

final class ProjectorRollUpTests: XCTestCase {
    private let start = Date(timeIntervalSinceReferenceDate: 0)

    private func entry(_ id: Int, _ translation: String, state: UtteranceState = .final,
                       startedAt: TimeInterval = 0, endedAt: TimeInterval? = 1) -> TranscriptUtterance {
        TranscriptUtterance(id: id, original: "", translation: translation, state: state,
            stableOriginalLength: 0, stableTranslationLength: 0,
            startedAt: start.addingTimeInterval(startedAt),
            endedAt: state == .partial ? nil : endedAt.map { start.addingTimeInterval($0) })
    }

    /// Tick like the projector clock, every 0.1 s.
    private func run(_ feed: inout ProjectorRollUpFeed, from: Double, to: Double) {
        var now = from
        while now < to - 1e-9 {
            now += 0.1
            feed.tick(at: now)
        }
    }

    private func text(_ feed: ProjectorRollUpFeed) -> String {
        feed.words.map(\.text).joined(separator: " ")
    }

    func testFinishedCaptionIsRevealedAtReadingPaceNotAllAtOnce() {
        var feed = ProjectorRollUpFeed()
        feed.receive([entry(1, "uno dos tres cuatro cinco seis")])
        feed.tick(at: 10)
        XCTAssertEqual(feed.words.count, 1, "The first word after silence appears at once")
        run(&feed, from: 10, to: 10.5)
        XCTAssertLessThan(feed.words.count, 6)
        run(&feed, from: 10.5, to: 12.5)
        XCTAssertEqual(text(feed), "uno dos tres cuatro cinco seis")
    }

    func testLongBacklogSpeedsUpButStillFlows() {
        var feed = ProjectorRollUpFeed()
        let long = (1...24).map { "w\($0)" }.joined(separator: " ")
        feed.receive([entry(1, long)])
        feed.tick(at: 0)
        run(&feed, from: 0, to: 0.5)
        XCTAssertLessThan(feed.words.count, 12)
        run(&feed, from: 0.5, to: 2)
        XCTAssertGreaterThanOrEqual(feed.words.count, 15)
        run(&feed, from: 2, to: 4)
        XCTAssertEqual(feed.words.count, 24)
    }

    func testDraftWithholdsGrowingLastWordAndTurnsFinalInPlace() {
        var feed = ProjectorRollUpFeed()
        feed.receive([entry(1, "la esperanza no aver", state: .partial)])
        feed.tick(at: 0)
        run(&feed, from: 0, to: 5)
        XCTAssertEqual(text(feed), "la esperanza no")
        XCTAssertTrue(feed.words.allSatisfy(\.isDraft))
        let ids = feed.words.map(\.id)

        feed.receive([entry(1, "la esperanza no avergüenza.")])
        run(&feed, from: 5, to: 5.5)
        XCTAssertEqual(text(feed), "la esperanza no avergüenza.")
        XCTAssertEqual(Array(feed.words.prefix(3)).map(\.id), ids)
        XCTAssertFalse(feed.words.contains(where: \.isDraft))
    }

    func testRewrittenDraftSwapsWordsInPlaceWithoutMovingLaterCaptions() {
        var feed = ProjectorRollUpFeed()
        feed.receive([entry(1, "uno dos tres"), entry(2, "cuatro cinco seis ", state: .partial)])
        feed.tick(at: 0)
        run(&feed, from: 0, to: 5)
        feed.receive([entry(1, "uno dos tres"), entry(2, "cuatro", state: .partial)])
        feed.tick(at: 5.1)
        XCTAssertEqual(text(feed), "uno dos tres", "A shrinking draft hides only its own words")
        feed.receive([entry(1, "uno dos tres"), entry(2, "siete ocho")])
        run(&feed, from: 5.1, to: 6)
        XCTAssertEqual(text(feed), "uno dos tres siete ocho")
    }

    func testLongPauseStartsANewParagraph() {
        var feed = ProjectorRollUpFeed()
        feed.receive([entry(1, "uno dos", startedAt: 0, endedAt: 2),
                      entry(2, "tres", startedAt: 2.5, endedAt: 3),
                      entry(3, "cuatro", startedAt: 6, endedAt: 7)])
        feed.tick(at: 0)
        run(&feed, from: 0, to: 5)
        XCTAssertEqual(feed.words.map(\.startsParagraph), [false, false, false, true])
    }

    func testKeepsOnlyTheNewestWords() {
        var feed = ProjectorRollUpFeed()
        let entries = (1...30).map { entry($0, "a b c d e f") }
        feed.receive(entries)
        feed.tick(at: 0)
        run(&feed, from: 0, to: 30)
        XCTAssertEqual(feed.words.count, ProjectorRollUpFeed.maxWords)
        XCTAssertEqual(feed.words.last?.id, "30-5")
        XCTAssertFalse(feed.words[0].startsParagraph)
    }

    func testClearingTheTranscriptClearsTheProjector() {
        var feed = ProjectorRollUpFeed()
        feed.receive([entry(1, "uno dos")])
        feed.tick(at: 0)
        feed.receive([])
        feed.tick(at: 1)
        XCTAssertTrue(feed.words.isEmpty)
    }

    @MainActor
    func testSavedFocusLookAndFreshInstallsUseRollUp() {
        let defaults = UserDefaults.standard
        let key = SessionManager.styleStorageKey
        let old = defaults.object(forKey: key)
        defer { if let old { defaults.set(old, forKey: key) } else { defaults.removeObject(forKey: key) } }
        let id = UUID().uuidString
        defaults.set("focus", forKey: key)
        XCTAssertEqual(SessionManager(sessionID: id).projectorStyle, .rollUp)
        defaults.removeObject(forKey: key)
        XCTAssertEqual(SessionManager(sessionID: id).projectorStyle, .rollUp)
        defaults.set("split", forKey: key)
        XCTAssertEqual(SessionManager(sessionID: id).projectorStyle, .split)
    }

    @MainActor
    func testRenderRollUpAt720pAnd1080p() async throws {
        var repo = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 { repo.deleteLastPathComponent() }
        let output = repo.appending(path: "dist/logs/native-latency-2026-09-30/renders")
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        let entries = [
            entry(1, "Hermanos, hoy quiero hablarles de la esperanza.", startedAt: 0, endedAt: 4),
            entry(2, "Cuando Pablo escribió a los romanos, estaba encadenado, lejos de su casa y sin saber si volvería a ver a sus amigos.", startedAt: 4.2, endedAt: 12),
            entry(3, "Y aun así escribió que la esperanza no avergüenza, porque sabía en", state: .partial, startedAt: 12.3),
        ]
        var feed = ProjectorRollUpFeed()
        feed.receive(entries)
        feed.tick(at: 0)
        run(&feed, from: 0, to: 30)
        for size in [CGSize(width: 1280, height: 720), CGSize(width: 1920, height: 1080)] {
            let view = ProjectorRollUpStage(entries: entries,
                layout: ProjectorCaptionLayout(size: size, requestedFontSize: 72, style: .rollUp),
                targetLanguage: "Spanish", feed: feed)
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
            try XCTUnwrap(bitmap.representation(using: .png, properties: [:]))
                .write(to: output.appending(path: "projector-rollup-stage-\(Int(size.height)).png"))
        }
    }
}
