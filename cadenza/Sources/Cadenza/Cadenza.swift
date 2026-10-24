import SwiftUI
import AVFoundation

struct Phrase: Identifiable {
    let id: String
    var source = ""
    var spanish = ""
    var state = "Queued"
    var error: String?
    var delay: Double?
    var retryable = false
}

@MainActor @Observable final class Session {
    var phrases: [Phrase] = []
    var status = "Ready to load Gemma"
    var ready = false
    var loading = false
    var capturing = false
    var pending = 0
    var draining = false
    var recovery: String?
    var message: String?
    var quitting = false
    private var pipe: EnginePipe?
    private let capture = AudioCapture()
    private var startWhenReady = false
    let logs = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Cadenza")
    private var replay: URL? {
        let args = CommandLine.arguments
        guard let index = args.firstIndex(of: "--replay"), args.count > index + 1 else { return nil }
        return URL(fileURLWithPath: args[index + 1])
    }

    init() {
        try? FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true,
                                                 attributes: [.posixPermissions: 0o700])
    }

    func start() {
        guard !capturing, pending == 0, !loading, !draining else { return }
        message = nil
        if !ready {
            loading = true
            startWhenReady = true
            status = "Loading Gemma…"
            let child = EnginePipe()
            child.event = { [weak self] event in Task { @MainActor in self?.receive(event) } }
            child.exited = { [weak self] in
                Task { @MainActor in
                    guard let self else { return }
                    self.capture.stop(); self.capturing = false
                    self.ready = false; self.loading = false; self.pipe = nil
                    self.pending = 0; self.draining = false
                    for index in self.phrases.indices where self.phrases[index].state != "Complete" {
                        self.phrases[index].state = "Failed"
                        self.phrases[index].retryable = false
                        self.phrases[index].error = "Engine exited. Audio remains in Logs; restart and replay the retained file."
                    }
                    if self.quitting { NSApp.reply(toApplicationShouldTerminate: true) }
                    else { self.status = "Engine stopped" }
                }
            }
            pipe = child
            do { try child.launch(logs: logs) }
            catch { pipe = nil; loading = false; message = error.localizedDescription; status = "Couldn’t start engine" }
            return
        }
        Task {
            let permitted: Bool
            if replay != nil { permitted = true }
            else { permitted = await AVCaptureDevice.requestAccess(for: .audio) }
            guard permitted else { message = "Allow microphone access in System Settings → Privacy & Security → Microphone."; return }
            beginCapture()
        }
    }

    private func beginCapture() {
        guard let pipe, ready, !quitting, !capturing else { return }
        guard pipe.send(["type": "start"]) else { message = "Engine unavailable"; return }
        capturing = true
        let failed: (String) -> Void = { [weak self] text in
            Task { @MainActor in
                guard let self, self.capturing else { return }
                self.message = text; self.stop()
            }
        }
        do {
            if let replay {
                status = "Replaying recording"
                try capture.replay(url: replay, send: pipe.audio, finished: { [weak self] in
                    Task { @MainActor in self?.stop() }
                }, failed: failed)
            } else {
                status = "Listening"
                try capture.start(folder: logs, send: pipe.audio, failed: failed)
            }
        } catch { message = error.localizedDescription; stop() }
    }

    func stop() {
        guard capturing else { return }
        capture.stop()
        capturing = false
        draining = true
        pipe?.send(["type": "stop"])
        status = "Finishing captured phrases…"
    }

    func retry(_ id: String) {
        guard ready, !capturing, pending == 0, !draining else { return }
        if let i = phrases.firstIndex(where: { $0.id == id }) {
            phrases[i].error = nil; phrases[i].state = "Queued"
        }
        pending = 1
        pipe?.send(["type": "retry", "id": id])
    }

    func quit() -> NSApplication.TerminateReply {
        guard pipe != nil else { return .terminateNow }
        quitting = true
        stop()
        pipe?.send(["type": "quit"])
        status = "Finishing before quitting…"
        return .terminateLater
    }

    private func receive(_ event: [String: Any]) {
        let type = event["type"] as? String ?? ""
        switch type {
        case "loading": status = "Loading Gemma…"
        case "ready":
            ready = true; loading = false; status = "Ready"
            if startWhenReady { startWhenReady = false; start() }
        case "capturing": recovery = event["recovery"] as? String
        case "queued":
            if let id = event["id"] as? String { phrases.append(Phrase(id: id)) }
        case "backlog": pending = event["pending"] as? Int ?? 0
        case "working", "partial", "final", "failed":
            guard let id = event["id"] as? String,
                  let index = phrases.firstIndex(where: { $0.id == id }),
                  phrases[index].state != "Complete" else { return }
            if let source = event["source"] as? String { phrases[index].source = source }
            if let spanish = event["spanish"] as? String { phrases[index].spanish = spanish }
            if type == "working" || type == "partial" { phrases[index].state = "Receiving…" }
            if type == "final" { phrases[index].state = "Complete"; phrases[index].delay = event["end_to_final"] as? Double }
            if type == "failed" { phrases[index].retryable = true; phrases[index].state = "Failed"; phrases[index].error = event["message"] as? String }
        case "overload", "error", "fatal":
            message = event["message"] as? String; stop()
            if type == "fatal" { ready = false; loading = false; status = "Couldn’t load Gemma" }
        case "drained": draining = false; status = "Finished — ready for another session"
        case "stopped": recovery = event["recovery"] as? String
        default: break
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    static var session: Session?
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        MainActor.assumeIsolated { Self.session?.quit() ?? .terminateNow }
    }
}

@main struct CadenzaApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @State private var session = Session()
    @AppStorage("captionSize") private var captionSize = 24.0
    var body: some Scene {
        WindowGroup("Cadenza") {
            VStack(alignment: .leading, spacing: 18) {
                HStack(alignment: .center) {
                    Image(nsImage: NSImage(named: NSImage.applicationIconName)!).resizable().frame(width: 48, height: 48)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Cadenza").font(.title.bold())
                        Text("English → Español · on this Mac").foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button(session.capturing ? "Stop" : "Start") {
                        if session.capturing { session.stop() } else { session.start() }
                    }
                    .buttonStyle(.borderedProminent).controlSize(.large)
                    .disabled(!session.capturing && (session.loading || session.pending > 0 || session.draining || session.quitting))
                    .keyboardShortcut(.space, modifiers: [])
                }
                HStack {
                    Circle().fill(session.capturing ? Color.teal : Color.secondary).frame(width: 8, height: 8)
                    Text(session.status)
                    Spacer()
                    if session.pending > 0 { Text("\(session.pending) phrase\(session.pending == 1 ? "" : "s") pending").monospacedDigit() }
                }.font(.callout).foregroundStyle(.secondary)
                if let message = session.message {
                    Text(message).foregroundStyle(.orange).textSelection(.enabled)
                }
                Divider()
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 20) {
                            if session.phrases.isEmpty {
                                VStack(alignment: .leading, spacing: 12) {
                                    Text("Speak a short phrase.").font(.title2)
                                    Text("Cadenza waits for a pause, then transcribes and translates it in one Gemma call. You can keep speaking while the answer arrives.")
                                        .foregroundStyle(.secondary)
                                }.padding(.top, 36).frame(maxWidth: .infinity, alignment: .leading)
                            }
                            ForEach(session.phrases) { phrase in
                                VStack(alignment: .leading, spacing: 8) {
                                    HStack {
                                        Text(phrase.state).font(.caption).foregroundStyle(.secondary)
                                        if let delay = phrase.delay { Text(String(format: "%.1f s after commit", delay)).font(.caption).foregroundStyle(.secondary) }
                                        Spacer()
                                        if phrase.retryable {
                                            Button("Retry") { session.retry(phrase.id) }
                                                .disabled(!session.ready || session.capturing || session.pending > 0 || session.draining)
                                        }
                                    }
                                    if !phrase.source.isEmpty { Text(phrase.source).font(.system(size: captionSize - 2)).textSelection(.enabled) }
                                    if !phrase.spanish.isEmpty { Text(phrase.spanish).font(.system(size: captionSize)).foregroundStyle(.teal).textSelection(.enabled) }
                                    if let error = phrase.error { Text(error).font(.callout).foregroundStyle(.orange) }
                                }.padding(18).frame(maxWidth: .infinity, alignment: .leading)
                                    .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 14)).id(phrase.id)
                            }
                            Color.clear.frame(height: 1).id("bottom")
                        }
                    }
                    .defaultScrollAnchor(session.phrases.isEmpty ? .top : .bottom)
                    .onChange(of: session.phrases.count) { _, _ in proxy.scrollTo("bottom", anchor: .bottom) }
                }
                HStack {
                    Text("Completed phrases stay as returned.").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button("Logs & audio") { NSWorkspace.shared.open(session.logs) }
                    Button("Clear") { session.phrases.removeAll() }
                        .disabled(session.capturing || session.pending > 0 || session.draining || session.loading)
                }
            }
            .padding(24).frame(minWidth: 640, idealWidth: 800, minHeight: 480, idealHeight: 720)
            .onAppear {
                AppDelegate.session = session
                if CommandLine.arguments.contains("--replay") { session.start() }
            }
        }
        Settings {
            Form {
                Slider(value: $captionSize, in: 18...36, step: 1) { Text("Caption size") }
                Text("Audio and model output remain on this Mac. Logs & audio opens the retained session recordings, including failed phrases.").foregroundStyle(.secondary)
            }.padding(24).frame(width: 400)
        }
    }
}
