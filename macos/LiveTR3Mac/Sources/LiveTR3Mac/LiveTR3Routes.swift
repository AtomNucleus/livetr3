import Foundation

enum LiveTR3Routes {
    private static let nativeSessionID = "native"

    static let operatorURL = URL(string: "http://127.0.0.1:5173/?session=\(nativeSessionID)")!
    static let projectorURL = URL(string: "http://127.0.0.1:5173/projector?session=\(nativeSessionID)")!
}
