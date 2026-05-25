import SwiftUI

@main
struct LiveTR3App: App {
    @StateObject private var runtime = LiveTR3Runtime()
    @AppStorage("LiveTR3.startsRuntimeAutomatically") private var startsRuntimeAutomatically = true
    @Environment(\.openWindow) private var openWindow

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(runtime)
                .frame(minWidth: 1120, minHeight: 760)
                .task {
                    guard startsRuntimeAutomatically else { return }
                    await runtime.start()
                }
        }
        .windowStyle(.titleBar)

        Window("Projector", id: "projector") {
            ProjectorWindow()
                .environmentObject(runtime)
                .frame(minWidth: 960, minHeight: 540)
        }
        .windowStyle(.titleBar)
        .commands {
            CommandGroup(after: .appInfo) {
                Button("Restart Local Runtime") {
                    Task { await runtime.restart() }
                }
                .keyboardShortcut("r", modifiers: [.command, .shift])

                Button("Open Projector") {
                    openWindow(id: "projector")
                }
                .keyboardShortcut("p", modifiers: [.command, .shift])
            }
        }

        Settings {
            SettingsView()
        }
    }
}
