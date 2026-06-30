import Foundation

@MainActor
final class SessionManager: ObservableObject {
    let sessionID: String

    @Published var projectorFontSize: Double {
        didSet {
            let clamped = Self.clampFontSize(projectorFontSize)
            if clamped != projectorFontSize {
                projectorFontSize = clamped
                return
            }
            UserDefaults.standard.set(clamped, forKey: Self.fontStorageKey(sessionID))
        }
    }

    init(sessionID: String? = nil) {
        let resolved = sessionID ?? UserDefaults.standard.string(forKey: "LiveTR3.sessionID") ?? UUID().uuidString
        self.sessionID = resolved
        UserDefaults.standard.set(resolved, forKey: "LiveTR3.sessionID")

        let stored = UserDefaults.standard.double(forKey: Self.fontStorageKey(resolved))
        self.projectorFontSize = stored > 0 ? Self.clampFontSize(stored) : 72
    }

    static func fontStorageKey(_ sessionID: String) -> String {
        "livetr3.projector.font.\(sessionID)"
    }

    private static func clampFontSize(_ value: Double) -> Double {
        min(144, max(36, value))
    }
}
