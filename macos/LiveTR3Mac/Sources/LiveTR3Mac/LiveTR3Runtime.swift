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

    private let repoRoot: URL
    private let logDirectory: URL
    private var backendProcess: Process?

    init() {
        self.repoRoot = Self.findRepoRoot()
        self.logDirectory = Self.findRepoRoot().appending(path: "dist/logs")
    }

    func start() async {
        guard state != .starting && state != .ready else { return }

        state = .starting
        statusMessage = "Starting backend..."

        do {
            try launchBackend()
            try await waitForReady()
            state = .ready
            statusMessage = "Backend is running locally."
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
        backendProcess = nil
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
        try await waitUntil("Backend did not become healthy on 127.0.0.1:8765.") {
            await Self.httpOK(LiveTR3Routes.backendHealth)
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
