import Foundation

enum LiveTR3WindowID {
    static let projector = "projector"
}

enum LiveTR3Routes {
    static let backendHealth = URL(string: "http://127.0.0.1:8765/health")!
}
