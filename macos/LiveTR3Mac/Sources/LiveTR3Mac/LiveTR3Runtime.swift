import Foundation

@MainActor
final class LiveTR3Runtime: ObservableObject {
    enum State: Equatable {
        case idle
        case starting
        case ready
        case failed
    }

    @Published private(set) var state: State = .idle
    @Published private(set) var statusMessage = "Local runtime is not running."
    @Published private(set) var webReloadToken = 0

    let operatorURL = LiveTR3Routes.operatorURL

    private let repoRoot: URL
    private let logDirectory: URL
    private var backendProcess: Process?
    private var webProcess: Process?

    init() {
        self.repoRoot = Self.findRepoRoot()
        self.logDirectory = Self.findRepoRoot().appending(path: "dist/logs")
    }

    func start() async {
        guard state != .starting && state != .ready else { return }

        state = .starting
        statusMessage = "Starting backend and operator UI..."

        do {
            try launchBackend()
            try launchWebServer()
            try await waitForReady()
            state = .ready
            statusMessage = "Backend and operator UI are running locally."
            webReloadToken += 1
        } catch {
            state = .failed
            statusMessage = error.localizedDescription
            stop()
        }
    }

    func restart() async {
        stop()
        await start()
    }

    func stop() {
        backendProcess?.terminate()
        webProcess?.terminate()
        backendProcess = nil
        webProcess = nil
        if state != .failed {
            state = .idle
            statusMessage = "Local runtime is stopped."
        }
    }

    private func launchBackend() throws {
        let backend = repoRoot.appending(path: "app/backend")
        backendProcess = try launch(
            executable: "/bin/zsh",
            arguments: [
                "-lc",
                "PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin uv run python -m uvicorn server:app --host 127.0.0.1 --port 8765"
            ],
            workingDirectory: backend
        )
    }

    private func launchWebServer() throws {
        let dist = repoRoot.appending(path: "app/frontend/dist")
        let server = repoRoot.appending(path: "macos/LiveTR3Mac/support/static_server.py")
        webProcess = try launch(
            executable: "/usr/bin/python3",
            arguments: [server.path, "--directory", dist.path, "--host", "127.0.0.1", "--port", "5173"],
            workingDirectory: dist
        )
    }

    private func launch(executable: String, arguments: [String], workingDirectory: URL) throws -> Process {
        try FileManager.default.createDirectory(at: logDirectory, withIntermediateDirectories: true)
        let logURL = logDirectory.appending(path: "\(workingDirectory.lastPathComponent)-runtime.log")
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        let logHandle = try FileHandle(forWritingTo: logURL)

        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.currentDirectoryURL = workingDirectory
        process.standardOutput = logHandle
        process.standardError = logHandle
        try process.run()
        return process
    }

    private func waitForReady() async throws {
        let backendHealth = URL(string: "http://127.0.0.1:8765/health")!
        let frontend = operatorURL

        try await waitUntil("Backend did not become healthy on 127.0.0.1:8765.") {
            await Self.httpOK(backendHealth)
        }
        try await waitUntil("Operator UI did not become available on 127.0.0.1:5173.") {
            await Self.httpOK(frontend)
        }
        try await waitUntil("Operator UI assets did not become available on 127.0.0.1:5173.") {
            await Self.pageContains(frontend, text: "/assets/")
        }
        try await waitUntil("Operator JavaScript bundle did not become available on 127.0.0.1:5173.") {
            await Self.httpOK(await Self.assetURL(from: frontend, matching: ".js"))
        }
        try await waitUntil("Operator stylesheet did not become available on 127.0.0.1:5173.") {
            await Self.httpOK(await Self.assetURL(from: frontend, matching: ".css"))
        }
        try await waitUntil("Audio worklet did not become available on 127.0.0.1:5173.") {
            await Self.httpOK(URL(string: "http://127.0.0.1:5173/audio-worklet.js")!)
        }
    }

    private func waitUntil(_ timeoutMessage: String, check: @escaping () async -> Bool) async throws {
        for _ in 0..<80 {
            if await check() { return }
            try await Task.sleep(nanoseconds: 250_000_000)
        }
        throw RuntimeError(message: timeoutMessage)
    }

    private static func httpOK(_ url: URL) async -> Bool {
        do {
            let (_, response) = try await URLSession.shared.data(from: url)
            guard let http = response as? HTTPURLResponse else { return false }
            return (200..<400).contains(http.statusCode)
        } catch {
            return false
        }
    }

    private static func pageContains(_ url: URL, text: String) async -> Bool {
        do {
            let (data, response) = try await URLSession.shared.data(from: url)
            guard let http = response as? HTTPURLResponse, (200..<400).contains(http.statusCode) else {
                return false
            }
            return String(data: data, encoding: .utf8)?.contains(text) ?? false
        } catch {
            return false
        }
    }

    private static func assetURL(from page: URL, matching suffix: String) async -> URL {
        do {
            let (data, _) = try await URLSession.shared.data(from: page)
            guard let html = String(data: data, encoding: .utf8) else { return page }
            let pattern = #"\/assets\/[^"']+\#(suffix)"#
            guard let regex = try? NSRegularExpression(pattern: pattern),
                  let match = regex.firstMatch(in: html, range: NSRange(html.startIndex..., in: html)),
                  let range = Range(match.range, in: html) else {
                return page
            }
            return URL(string: "http://127.0.0.1:5173\(html[range])") ?? page
        } catch {
            return page
        }
    }

    private static func findRepoRoot() -> URL {
        let bundleParent = Bundle.main.bundleURL.deletingLastPathComponent()
        if bundleParent.lastPathComponent == "dist" {
            return bundleParent.deletingLastPathComponent()
        }

        var sourceURL = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 {
            sourceURL.deleteLastPathComponent()
        }
        return sourceURL
    }

    private struct RuntimeError: LocalizedError {
        let message: String
        var errorDescription: String? { message }
    }
}
