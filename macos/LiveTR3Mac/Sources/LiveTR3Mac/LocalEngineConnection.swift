import Foundation
import Network

@MainActor
final class LocalEngineConnection: CaptionEngine {
    var onMessage: ((LiveTR3ServerMessage) -> Void)?
    var onDisconnect: (() -> Void)?

    private var traceRole = "unknown"
    private let socketPath: String
    private var connection: NWConnection?
    private let audioTransport = NativeAudioTransport()
    private var receiveTask: Task<Void, Never>?

    init(socketPath: String = LiveTR3Runtime.engineSocketPath.path) {
        self.socketPath = socketPath
    }

    func connect(sessionID: String, mode: CaptionEngineConnectionMode) async throws {
        disconnect()
        traceRole = mode == .viewer ? "projector" : "operator"

        let connection = NWConnection(to: .unix(path: socketPath), using: .tcp)
        self.connection = connection

        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            let gate = ConnectionContinuationGate(continuation)
            connection.stateUpdateHandler = { state in
                switch state {
                case .ready:
                    gate.resume()
                case .failed(let error), .waiting(let error):
                    gate.resume(throwing: error)
                case .cancelled:
                    gate.resume(throwing: CancellationError())
                default:
                    break
                }
            }
            connection.start(queue: .global(qos: .userInitiated))
        }

        try Task.checkCancellation()
        guard self.connection === connection else { throw CancellationError() }
        startReceiveLoop()
        sendJSON(["type": "hello", "session": sessionID])

        switch mode {
        case .viewer:
            sendJSON(["type": "join_viewer"])
        case .resume:
            sendJSON(["type": "resume"])
        case .start:
            break
        }
        // Publish only after hello/resume are queued; capture can run during reconnect.
        audioTransport.setConnection(connection)
    }

    func sendJSON(_ payload: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: payload) else {
            return
        }
        sendFrame(type: .text, payload: data)
    }

    func sendConfig(_ config: ClientConfig) {
        guard let data = try? JSONEncoder().encode(config),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return
        }
        var payload = object
        payload["type"] = "config"
        sendJSON(payload)
    }

    func sendBinary(_ data: Data) {
        sendFrame(type: .binary, payload: data)
    }

    func audioSender() -> ((Data) -> Void)? {
        let transport = audioTransport
        return { data in transport.send(data) }
    }

    func disconnect() {
        receiveTask?.cancel()
        receiveTask = nil
        audioTransport.setConnection(nil)
        connection?.cancel()
        connection = nil
    }

    private func sendFrame(type: LocalEngineFrameType, payload: Data) {
        guard let connection else { return }
        Self.sendFrame(connection: connection, type: type, payload: payload)
    }

    nonisolated fileprivate static func sendFrame(connection: NWConnection, type: LocalEngineFrameType, payload: Data) {
        var framed = Data()
        framed.append(type.rawValue)
        framed.append(UInt8((payload.count >> 24) & 0xff))
        framed.append(UInt8((payload.count >> 16) & 0xff))
        framed.append(UInt8((payload.count >> 8) & 0xff))
        framed.append(UInt8(payload.count & 0xff))
        framed.append(payload)
        connection.send(content: framed, completion: .contentProcessed { _ in })
    }

    private func startReceiveLoop() {
        receiveTask?.cancel()
        receiveTask = Task { [weak self] in
            guard let self else { return }
            while !Task.isCancelled {
                do {
                    let header = try await self.receiveExact(length: 5)
                    let frameType = LocalEngineFrameType(rawValue: header[header.startIndex])
                    let length = Int(header[header.startIndex + 1]) << 24
                        | Int(header[header.startIndex + 2]) << 16
                        | Int(header[header.startIndex + 3]) << 8
                        | Int(header[header.startIndex + 4])
                    let payload = try await self.receiveExact(length: length)
                    if frameType == .text,
                       let parsed = LiveTR3ServerMessage.parse(payload) {
                        LatencyTrace.shared.record("socket_caption", Self.traceFields(parsed).merging(["surface": self.traceRole]) { _, next in next })
                        self.onMessage?(parsed)
                    }
                } catch {
                    if !Task.isCancelled {
                        self.onDisconnect?()
                    }
                    return
                }
            }
        }
    }

    nonisolated static func traceFields(_ message: LiveTR3ServerMessage) -> [String: Any] {
        if case .caption(let type, let id, let original, let translation) = message {
            return ["utterance": id, "type": String(describing: type), "source_chars": original.count, "translation_chars": translation.count, "source_signature": original.hashValue, "translation_signature": translation.hashValue]
        }
        return ["type": "other"]
    }

    private func receiveExact(length: Int) async throws -> Data {
        guard length > 0 else { return Data() }
        guard let connection else {
            throw LiveTR3SessionError(message: "Local engine connection is closed.")
        }

        var result = Data()
        while result.count < length {
            let remaining = length - result.count
            let chunk = try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Data, Error>) in
                connection.receive(minimumIncompleteLength: 1, maximumLength: remaining) { data, _, isComplete, error in
                    if let error {
                        continuation.resume(throwing: error)
                    } else if let data, !data.isEmpty {
                        continuation.resume(returning: data)
                    } else if isComplete {
                        continuation.resume(throwing: LiveTR3SessionError(message: "Local engine connection closed."))
                    } else {
                        continuation.resume(returning: Data())
                    }
                }
            }
            if chunk.isEmpty {
                throw LiveTR3SessionError(message: "Local engine connection closed.")
            }
            result.append(chunk)
        }
        return result
    }
}

fileprivate enum LocalEngineFrameType: UInt8 {
    case text = 0x01
    case binary = 0x02
}

private final class ConnectionContinuationGate: @unchecked Sendable {
    private let lock = NSLock()
    private var didResume = false
    private let continuation: CheckedContinuation<Void, Error>

    init(_ continuation: CheckedContinuation<Void, Error>) {
        self.continuation = continuation
    }

    func resume() {
        guard markResumed() else { return }
        continuation.resume()
    }

    func resume(throwing error: Error) {
        guard markResumed() else { return }
        continuation.resume(throwing: error)
    }

    private func markResumed() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        if didResume {
            return false
        }
        didResume = true
        return true
    }
}

/// Connection ownership changes on MainActor; audio submissions stay on the capture queue.
/// The lock also ensures reconnecting updates an already captured sender closure.
final class NativeAudioTransport: @unchecked Sendable {
    private let lock = NSLock()
    private var connection: NWConnection?
    func setConnection(_ next: NWConnection?) {
        lock.lock()
        defer { lock.unlock() }
        connection = next
    }
    func send(_ data: Data) {
        lock.lock()
        defer { lock.unlock() }
        guard let connection else { return }
        LatencyTrace.shared.record("audio_send", ["bytes": data.count])
        LocalEngineConnection.sendFrame(connection: connection, type: .binary, payload: data)
    }
}
