import Combine
import XCTest
@testable import LiveTR3Mac

@MainActor
final class ProjectorConnectionTests: XCTestCase {
    func testTranscriptChangesInvalidateProjectorConnection() {
        let connection = ProjectorConnection(sessionID: "projector-publisher-test")
        var didPublish = false
        let observation = connection.objectWillChange.sink { _ in
            didPublish = true
        }

        connection.transcript.handle(
            .caption(type: .partial, utteranceID: 1, original: "Hello", translation: "Hola")
        )

        XCTAssertTrue(didPublish)
        withExtendedLifetime(observation) {}
    }
}

@MainActor
private final class ProjectorTestEngine: CaptionEngine {
    var onMessage: ((LiveTR3ServerMessage) -> Void)?
    var onDisconnect: (() -> Void)?
    var calls: [(String, CaptionEngineConnectionMode)] = []
    var disconnectCount = 0
    var fails = false
    var suspends = false
    private var pending: CheckedContinuation<Void, Error>?

    func connect(sessionID: String, mode: CaptionEngineConnectionMode) async throws {
        calls.append((sessionID, mode))
        if fails { throw LiveTR3SessionError(message: "Simulated offline engine") }
        if suspends {
            try await withCheckedThrowingContinuation { pending = $0 }
        }
    }
    func disconnect() {
        disconnectCount += 1
        pending?.resume(throwing: CancellationError())
        pending = nil
    }
    func sendJSON(_ payload: [String: Any]) { XCTFail("Viewer must not send producer controls") }
    func sendConfig(_ config: ClientConfig) { XCTFail("Viewer must not configure the engine") }
    func sendBinary(_ data: Data) { XCTFail("Viewer must not send audio") }
}

@MainActor
private final class ProjectorRetryClock {
    var delays: [TimeInterval] = []
    private var pending: CheckedContinuation<Void, Error>?
    func wait(_ delay: TimeInterval) async throws {
        delays.append(delay)
        try await withCheckedThrowingContinuation { pending = $0 }
    }
    func advance() {
        let continuation = pending
        pending = nil
        continuation?.resume()
    }
}

extension ProjectorConnectionTests {
    private func eventually(_ predicate: () -> Bool, file: StaticString = #filePath, line: UInt = #line) async {
        for _ in 0..<1_000 {
            if predicate() { return }
            try? await Task.sleep(for: .milliseconds(1))
        }
        XCTFail("Condition did not become true", file: file, line: line)
    }

    func testFailedAttemptsBackOffWithCapAndRecoveryClearsErrors() async {
        let clock = ProjectorRetryClock()
        var engines: [ProjectorTestEngine] = []
        let connection = ProjectorConnection(sessionID: "same-session", makeEngine: {
            let engine = ProjectorTestEngine()
            engine.fails = engines.count < 6
            engines.append(engine)
            return engine
        }, waitForRetry: clock.wait)
        connection.transcript.handle(.error(message: "Stale error"))
        connection.connect()
        for count in 1...6 {
            await eventually { clock.delays.count == count }
            XCTAssertNotNil(connection.connectionError)
            // Repeated appearance/connect calls must not bypass the scheduled retry.
            connection.connect()
            XCTAssertEqual(engines.count, count)
            clock.advance()
        }
        await eventually { engines.count == 7 && connection.connectionError == nil }
        XCTAssertEqual(clock.delays, [0.5, 1, 2, 4, 8, 8])
        XCTAssertNil(connection.transcript.lastError)
        for engine in engines {
            XCTAssertEqual(engine.calls.count, 1)
            XCTAssertEqual(engine.calls.first?.0, "same-session")
            if case .viewer = engine.calls.first?.1 {} else { XCTFail("Must rejoin as viewer") }
        }
        engines.last?.onMessage?(.status(state: .ready, message: "Ready"))
        engines.last?.onDisconnect?()
        await eventually { clock.delays.count == 7 }
        XCTAssertEqual(clock.delays.last, 0.5, "Healthy traffic resets the backoff")
        connection.disconnect()
        clock.advance()
    }

    func testUnexpectedDisconnectRetainsHistoryAndDoesNotReplayDuplicateSnapshot() async {
        let clock = ProjectorRetryClock()
        var engines: [ProjectorTestEngine] = []
        let connection = ProjectorConnection(sessionID: "audience", makeEngine: {
            let engine = ProjectorTestEngine()
            engines.append(engine)
            return engine
        }, waitForRetry: clock.wait)
        connection.connect()
        await eventually { engines.first?.calls.count == 1 }
        let first = engines[0]
        let layout = ProjectorCaptionLayout(size: CGSize(width: 1280, height: 720), requestedFontSize: 72, style: .split)
        var presentation = ProjectorCaptionPresentation()
        first.onMessage?(.caption(type: .final, utteranceID: 9, original: "Welcome.", translation: "Bienvenidos."))
        presentation.receive(connection.transcript.entries, at: 0)
        presentation.tick(at: 0, layout: layout)
        first.onMessage?(.caption(type: .final, utteranceID: 10, original: "Thank you.", translation: "Gracias."))
        presentation.receive(connection.transcript.entries, at: 1)
        presentation.tick(at: 4, layout: layout)
        let deadline = presentation.holdUntil
        let staleMessage = first.onMessage
        let staleDisconnect = first.onDisconnect
        first.onDisconnect?()
        await eventually { clock.delays.count == 1 }
        XCTAssertEqual(connection.transcript.entries.count, 2)
        clock.advance()
        await eventually { engines.count == 2 && connection.connectionError == nil }
        let recovered = engines[1]
        staleDisconnect?()
        staleMessage?(.error(message: "Old connection error"))
        XCTAssertNil(connection.connectionError)
        XCTAssertNil(connection.transcript.lastError)
        recovered.onMessage?(.caption(type: .final, utteranceID: 1, original: "Old history", translation: "Historia antigua"))
        recovered.onMessage?(.caption(type: .final, utteranceID: 10, original: "Thank you.", translation: "Gracias."))
        recovered.onMessage?(.caption(type: .partial, utteranceID: 10, original: "Late", translation: "Tarde"))
        presentation.receive(connection.transcript.entries, at: 5)
        presentation.tick(at: 500, layout: layout)
        XCTAssertEqual(connection.transcript.entries.map(\.id), [9, 10])
        XCTAssertEqual(presentation.previous?.utteranceID, 9)
        XCTAssertEqual(presentation.current?.translation, "Gracias.")
        XCTAssertEqual(presentation.holdUntil, deadline, "Replay must not restart reading time")
        recovered.onMessage?(.caption(type: .partial, utteranceID: 11, original: "Please sit.", translation: ""))
        presentation.receive(connection.transcript.entries, at: 501)
        presentation.tick(at: 502, layout: layout)
        XCTAssertTrue(presentation.isTranslationPending)
        XCTAssertEqual(presentation.current?.utteranceID, 10)
        recovered.onMessage?(.caption(type: .final, utteranceID: 11, original: "Please sit.", translation: "Siéntense."))
        presentation.receive(connection.transcript.entries, at: 503)
        presentation.tick(at: 503, layout: layout)
        XCTAssertFalse(presentation.isTranslationPending)
        XCTAssertEqual(presentation.previous?.utteranceID, 10)
        XCTAssertEqual(presentation.current?.translation, "Siéntense.")
        connection.disconnect()
    }

    func testIntentionalCloseCancelsRetryAndLateCallbacks() async {
        let clock = ProjectorRetryClock()
        let engine = ProjectorTestEngine()
        var attempts = 0
        let connection = ProjectorConnection(sessionID: "close", makeEngine: {
            attempts += 1
            return engine
        }, waitForRetry: clock.wait)
        connection.connect()
        await eventually { engine.calls.count == 1 }
        let lateDisconnect = engine.onDisconnect
        engine.onDisconnect?()
        await eventually { clock.delays.count == 1 }
        connection.disconnect()
        clock.advance()
        lateDisconnect?()
        for _ in 0..<10 { await Task.yield() }
        XCTAssertEqual(attempts, 1)
        XCTAssertNil(connection.connectionError)
    }

    func testClosingDuringConnectDoesNotOverlapOrReconnectAndCanReopen() async {
        let clock = ProjectorRetryClock()
        var engines: [ProjectorTestEngine] = []
        let connection = ProjectorConnection(sessionID: "close-startup", makeEngine: {
            let engine = ProjectorTestEngine()
            engine.suspends = engines.isEmpty
            engines.append(engine)
            return engine
        }, waitForRetry: clock.wait)
        connection.connect()
        connection.connect()
        await eventually { engines.first?.calls.count == 1 }
        XCTAssertEqual(engines.count, 1)
        connection.disconnect()
        XCTAssertEqual(engines[0].disconnectCount, 1)
        connection.connect()
        await eventually { engines.count == 2 && engines[1].calls.count == 1 }
        for _ in 0..<10 { await Task.yield() }
        XCTAssertTrue(clock.delays.isEmpty)
        XCTAssertNil(connection.connectionError)
        connection.disconnect()
        for _ in 0..<10 { await Task.yield() }
        XCTAssertTrue(clock.delays.isEmpty, "Intentional disconnect of a connected viewer must not retry")
    }

    func testImmediateClosePreventsScheduledConnectFromOpeningTransport() async {
        let engine = ProjectorTestEngine()
        let connection = ProjectorConnection(sessionID: "immediate-close", makeEngine: { engine })
        connection.connect()
        connection.disconnect()
        for _ in 0..<10 { await Task.yield() }
        XCTAssertTrue(engine.calls.isEmpty)
        XCTAssertNil(connection.connectionError)
    }

    func testMissingLocalSocketFailsInsteadOfHanging() async {
        let connection = LocalEngineConnection(socketPath: "/tmp/livetr3-missing-\(UUID().uuidString).sock")
        let finished = expectation(description: "Missing socket fails")
        let task = Task {
            defer { finished.fulfill() }
            do {
                try await connection.connect(sessionID: "isolated-test", mode: .viewer)
                XCTFail("A missing socket must not connect")
            } catch {}
        }
        await fulfillment(of: [finished], timeout: 3)
        connection.disconnect()
        task.cancel()
    }
}
