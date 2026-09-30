import Foundation
import Network
import XCTest
@testable import LiveTR3Mac

final class NativeAudioTransportTests: XCTestCase {
    @MainActor
    func testAudioStillSendsWhileMainActorIsBlocked() async throws {
        let path = "/tmp/livetr3-audio-test-\(UUID().uuidString).sock"
        let parameters = NWParameters.tcp
        parameters.requiredLocalEndpoint = .unix(path: path)
        let listener = try NWListener(using: parameters)
        let listening = expectation(description: "listener ready")
        let received = expectation(description: "binary frame received")
        let payload = Data(repeating: 42, count: 1280)
        listener.stateUpdateHandler = { state in if case .ready = state { listening.fulfill() } }
        listener.newConnectionHandler = { connection in
            connection.start(queue: .global())
            connection.receive(minimumIncompleteLength: 1285, maximumLength: 1285) { data, _, _, error in
                XCTAssertNil(error)
                XCTAssertEqual(data?.first, 2)
                XCTAssertEqual(data?.suffix(1280), payload)
                received.fulfill()
                connection.cancel()
            }
        }
        listener.start(queue: .global())
        defer { listener.cancel(); try? FileManager.default.removeItem(atPath: path) }
        await fulfillment(of: [listening], timeout: 3)
        let client = NWConnection(to: .unix(path: path), using: .tcp)
        let ready = expectation(description: "client ready")
        client.stateUpdateHandler = { state in if case .ready = state { ready.fulfill() } }
        client.start(queue: .global())
        defer { client.cancel() }
        await fulfillment(of: [ready], timeout: 3)
        let transport = NativeAudioTransport()
        transport.setConnection(client)
        let sent = DispatchSemaphore(value: 0)
        DispatchQueue.global().async {
            transport.send(payload)
            sent.signal()
        }
        // This synchronous wait occupies MainActor. An actor-hop sender cannot satisfy it.
        XCTAssertEqual(sent.wait(timeout: .now() + 1), .success)
        await fulfillment(of: [received], timeout: 3)
        transport.setConnection(nil)
        transport.send(payload) // Retiring a connection must be safe for an existing callback.
    }
}
