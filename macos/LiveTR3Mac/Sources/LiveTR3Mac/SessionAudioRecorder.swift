import Foundation

/// Saves the 16 kHz audio sent to the engine as a 16-bit WAV, so a session's captions
/// can be checked against what was said (`script/compare_session.py`).
///
/// All file work runs on the recorder's own queue; `append` only hands the frame over.
/// Gaps longer than `gapSeconds` (pause, device switch, slow start) are written as
/// silence, so the file's timeline follows the wall clock and lines up with the
/// engine's session archive. A JSON sidecar records the start time for that match.
final class SessionAudioRecorder: @unchecked Sendable {
    static let enabledKey = "LiveTR3.recordSessionAudio"
    static let sampleRate = 16_000
    static let gapSeconds = 0.25

    /// Next to the engine's `sessions` folder.
    static var directory: URL {
        LiveTR3Runtime.archiveRoot.deletingLastPathComponent().appending(path: "recordings")
    }

    static var isEnabled: Bool { UserDefaults.standard.bool(forKey: enabledKey) }

    let url: URL
    private let sidecarURL: URL
    private let startedAt: Date
    private let startedUptime: TimeInterval
    private let clock: @Sendable () -> TimeInterval
    private let queue = DispatchQueue(label: "com.livetr3.session-recorder", qos: .utility)
    private let handle: FileHandle
    private var samplesWritten: Int64 = 0
    private var samplesAtHeaderUpdate: Int64 = 0
    private var closed = false

    init(directory: URL, startedAt: Date = Date(),
         clock: @escaping @Sendable () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) throws {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd'T'HH-mm-ssZ"
        let slug = formatter.string(from: startedAt)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        url = directory.appending(path: "\(slug).wav")
        sidecarURL = directory.appending(path: "\(slug).json")
        self.startedAt = startedAt
        self.clock = clock
        startedUptime = clock()
        FileManager.default.createFile(atPath: url.path, contents: Self.header(dataBytes: 0))
        handle = try FileHandle(forWritingTo: url)
        try handle.seekToEnd()
        writeSidecar(durationSeconds: nil)
    }

    /// `frame` is little-endian Float32 mono at 16 kHz, as sent to the engine.
    func append(_ frame: Data) {
        let arrivedAt = clock()
        queue.async { [self] in
            guard !closed else { return }
            let incoming = Int64(frame.count / MemoryLayout<Float>.size)
            let expected = Int64((arrivedAt - startedUptime) * Double(Self.sampleRate))
            let gap = expected - incoming - samplesWritten
            if gap > Int64(Self.gapSeconds * Double(Self.sampleRate)) {
                write(Data(count: Int(gap) * 2), samples: gap)
            }
            write(Self.int16PCM(frame), samples: incoming)
        }
    }

    func finish() {
        queue.async { [self] in
            guard !closed else { return }
            closed = true
            updateHeader()
            try? handle.close()
            writeSidecar(durationSeconds: Double(samplesWritten) / Double(Self.sampleRate))
        }
    }

    /// Waits for queued writes; for tests.
    func waitForWrites() { queue.sync {} }

    private func write(_ data: Data, samples: Int64) {
        do {
            try handle.write(contentsOf: data)
        } catch {
            closed = true
            try? handle.close()
            return
        }
        samplesWritten += samples
        // Keep the header current so quitting mid-session or a crash still leaves
        // a playable file missing at most the last second.
        if samplesWritten - samplesAtHeaderUpdate >= Int64(Self.sampleRate) {
            updateHeader()
        }
    }

    private func updateHeader() {
        samplesAtHeaderUpdate = samplesWritten
        let dataBytes = UInt32(clamping: samplesWritten * 2)
        do {
            try handle.seek(toOffset: 4)
            try handle.write(contentsOf: Self.le32(36 + dataBytes))
            try handle.seek(toOffset: 40)
            try handle.write(contentsOf: Self.le32(dataBytes))
            try handle.seekToEnd()
        } catch {}
    }

    private func writeSidecar(durationSeconds: Double?) {
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        var meta: [String: Any] = [
            "audio": url.lastPathComponent,
            "started_at": iso.string(from: startedAt),
            "sample_rate": Self.sampleRate,
            "archive_root": LiveTR3Runtime.archiveRoot.path,
        ]
        if let durationSeconds { meta["duration_seconds"] = durationSeconds }
        if let data = try? JSONSerialization.data(withJSONObject: meta, options: [.prettyPrinted, .sortedKeys]) {
            try? data.write(to: sidecarURL, options: .atomic)
        }
    }

    static func int16PCM(_ frame: Data) -> Data {
        frame.withUnsafeBytes { raw in
            let floats = raw.bindMemory(to: Float.self)
            var out = Data(count: floats.count * 2)
            out.withUnsafeMutableBytes { dst in
                let ints = dst.bindMemory(to: Int16.self)
                for (index, sample) in floats.enumerated() {
                    ints[index] = Int16(max(-1, min(1, sample)) * 32_767).littleEndian
                }
            }
            return out
        }
    }

    static func header(dataBytes: UInt32) -> Data {
        var data = Data("RIFF".utf8)
        data += le32(36 + dataBytes)
        data += Data("WAVEfmt ".utf8)
        data += le32(16)
        data += le16(1)                         // PCM
        data += le16(1)                         // mono
        data += le32(UInt32(sampleRate))
        data += le32(UInt32(sampleRate * 2))    // byte rate
        data += le16(2)                         // block align
        data += le16(16)                        // bits per sample
        data += Data("data".utf8)
        data += le32(dataBytes)
        return data
    }

    private static func le32(_ value: UInt32) -> Data { withUnsafeBytes(of: value.littleEndian) { Data($0) } }
    private static func le16(_ value: UInt16) -> Data { withUnsafeBytes(of: value.littleEndian) { Data($0) } }
}
