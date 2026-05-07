import SwiftUI

@main
struct LiveTR3App: App {
    @StateObject private var runtime = LiveTR3Runtime()
    @AppStorage("LiveTR3.startsRuntimeAutomatically") private var startsRuntimeAutomatically = true
    @Environment(\.openURL) private var openURL

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(runtime)
                .frame(minWidth: 1120, minHeight: 760)
                .task {
                    guard startsRuntimeAutomatically else { return }
                    await runtime.start()
                }
                .onDisappear {
                    runtime.stop()
                }
        }
        .windowStyle(.titleBar)
        .commands {
            CommandGroup(after: .appInfo) {
                Button("Restart Local Runtime") {
                    Task { await runtime.restart() }
                }
                .keyboardShortcut("r", modifiers: [.command, .shift])

                Button("Open Projector") {
                    openURL(LiveTR3Routes.projectorURL)
                }
                .keyboardShortcut("p", modifiers: [.command, .shift])
                .disabled(runtime.state != .ready)
            }
        }

        Settings {
            SettingsView()
        }
    }
}
