import Foundation

/// Opt-in diagnostics. Wall-clock anchors correlate processes; intervals use uptime.
/// Never records audio or caption text. View callbacks are layout proxies, not photons.
final class LatencyTrace: @unchecked Sendable {
    static let shared = LatencyTrace()
    private let lock = NSLock()
    private let handle: FileHandle?
    private let uptimeAnchor = ProcessInfo.processInfo.systemUptime
    private let unixAnchor = Date().timeIntervalSince1970
    private init() {
        if let path = ProcessInfo.processInfo.environment["LIVETR3_NATIVE_TRACE"] {
            FileManager.default.createFile(atPath: path, contents: nil)
            handle = try? FileHandle(forWritingTo: URL(fileURLWithPath: path))
        } else { handle = nil }
    }
    var isEnabled: Bool { handle != nil }
    func record(_ stage: String, _ fields: [String: Any] = [:]) {
        guard let handle else { return }
        let now = ProcessInfo.processInfo.systemUptime
        var event = fields
        event["stage"] = stage
        event["uptime"] = now
        event["unix"] = unixAnchor + now - uptimeAnchor
        event["pid"] = ProcessInfo.processInfo.processIdentifier
        guard var data = try? JSONSerialization.data(withJSONObject: event, options: [.sortedKeys]) else { return }
        data.append(10)
        lock.lock()
        defer { lock.unlock() }
        try? handle.write(contentsOf: data)
    }
}
