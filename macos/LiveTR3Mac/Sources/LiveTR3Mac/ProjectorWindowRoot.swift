import SwiftUI

struct ProjectorWindowRoot: View {
    @EnvironmentObject private var sessionManager: SessionManager

    var body: some View {
        ProjectorContainer(sessionID: sessionManager.sessionID)
            .background(ProjectorWindowFullscreen())
            .environmentObject(sessionManager)
    }
}

private struct ProjectorContainer: View {
    @StateObject private var connection: ProjectorConnection
    @EnvironmentObject private var sessionManager: SessionManager

    init(sessionID: String) {
        _connection = StateObject(wrappedValue: ProjectorConnection(sessionID: sessionID))
    }

    var body: some View {
        ProjectorView(connection: connection, sessionManager: sessionManager)
            .frame(minWidth: 1_280, minHeight: 720)
    }
}
