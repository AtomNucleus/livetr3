import Foundation

/// One process and a bounded serial writer; control commands follow accepted audio.
final class EnginePipe: @unchecked Sendable {
    private let process = Process()
    private let input = Pipe()
    private let output = Pipe()
    private let writer = DispatchQueue(label: "Cadenza.pipe.writer")
    private let lock = NSLock()
    private var packets = 0
    private var failed = false
    private var logHandle: FileHandle?
    var event: (([String: Any]) -> Void)?
    var exited: (() -> Void)?

    func launch(logs: URL) throws {
        let resources = Bundle.main.resourceURL!
        process.executableURL = resources.appendingPathComponent("Python/bin/python3")
        process.arguments = ["-B", "-s", resources.appendingPathComponent("engine/engine.py").path]
        process.currentDirectoryURL = resources
        var environment = ProcessInfo.processInfo.environment
        // Isolate the bundled interpreter from launch-shell Python/MLX experiments.
        for key in ["PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "LIVETR3_GEMMA_MTP", "LIVETR3_PHRASE_BILINGUAL"] {
            environment.removeValue(forKey: key)
        }
        environment["PYTHONNOUSERSITE"] = "1"
        environment["HF_HUB_OFFLINE"] = "1"
        environment["TOKENIZERS_PARALLELISM"] = "false"
        process.environment = environment
        process.standardInput = input
        process.standardOutput = output
        let logURL = logs.appendingPathComponent("engine-stderr.log")
        if !FileManager.default.fileExists(atPath: logURL.path) { FileManager.default.createFile(atPath: logURL.path, contents: nil) }
        logHandle = try FileHandle(forWritingTo: logURL)
        try logHandle?.seekToEnd()
        process.standardError = logHandle
        process.terminationHandler = { [weak self] _ in
            guard let self else { return }
            self.lock.lock(); self.failed = true; self.lock.unlock()
            self.exited?()
        }
        try process.run()
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self else { return }
            var pending = Data()
            while true {
                let bytes = self.output.fileHandleForReading.availableData
                if bytes.isEmpty { break }
                pending.append(bytes)
                while let newline = pending.firstIndex(of: 10) {
                    let line = pending.prefix(upTo: newline)
                    pending.removeSubrange(...newline)
                    if let object = try? JSONSerialization.jsonObject(with: line) as? [String: Any] {
                        self.event?(object)
                    }
                }
                if pending.count > 1_000_000 {
                    self.event?(["type": "fatal", "message": "Engine emitted an oversized message"])
                    break
                }
            }
        }
    }

    @discardableResult func send(_ object: [String: Any], audio: Bool = false) -> Bool {
        guard let data = try? JSONSerialization.data(withJSONObject: object) else { return false }
        lock.lock()
        if failed || (audio && packets >= 64) { lock.unlock(); return false }
        if audio { packets += 1 }
        lock.unlock()
        writer.async { [weak self] in
            guard let self else { return }
            do {
                var line = data; line.append(10)
                try self.input.fileHandleForWriting.write(contentsOf: line)
            } catch {
                self.lock.lock(); self.failed = true; self.lock.unlock()
                self.event?(["type": "fatal", "message": "Engine pipe closed; captured audio is retained"])
            }
            if audio { self.lock.lock(); self.packets -= 1; self.lock.unlock() }
        }
        return true
    }

    func audio(_ bytes: Data) -> Bool {
        send(["type": "audio", "pcm": bytes.base64EncodedString()], audio: true)
    }
}
