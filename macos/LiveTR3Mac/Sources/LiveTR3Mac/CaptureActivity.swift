import Foundation

/// Holds a user-initiated, latency-critical activity while capture runs, so
/// App Nap and timer coalescing cannot delay audio frames or captions when the
/// operator window is hidden behind the projector.
final class CaptureActivity {
    private var token: NSObjectProtocol?

    var isActive: Bool { token != nil }

    func begin() {
        guard token == nil else { return }
        token = ProcessInfo.processInfo.beginActivity(
            options: [.userInitiated, .latencyCritical],
            reason: "Live caption capture"
        )
    }

    func end() {
        guard let token else { return }
        ProcessInfo.processInfo.endActivity(token)
        self.token = nil
    }

    deinit {
        end()
    }
}
