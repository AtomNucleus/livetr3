import AVFoundation
import Foundation

/// The tap records a recovery file before handing converted audio to the bounded pipe.
final class AudioCapture {
    private let engine = AVAudioEngine()
    private var replayTask: Task<Void, Never>?
    private var tapped = false
    private let target = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16_000,
                                       channels: 1, interleaved: false)!

    func start(folder: URL, send: @escaping (Data) -> Bool,
               failed: @escaping (String) -> Void) throws {
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0,
              let converter = AVAudioConverter(from: format, to: target) else {
            throw NSError(domain: "Cadenza", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "No usable microphone input"])
        }
        let recording = try AVAudioFile(forWriting: folder.appendingPathComponent("microphone-\(UUID().uuidString).caf"),
                                        settings: format.settings)
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { [target] buffer, _ in
            do {
                try recording.write(from: buffer)
                let capacity = AVAudioFrameCount(ceil(Double(buffer.frameLength) * 16_000 / format.sampleRate) + 64)
                let output = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: capacity)!
                var provided = false
                var error: NSError?
                converter.convert(to: output, error: &error) { _, status in
                    if provided { status.pointee = .noDataNow; return nil }
                    provided = true
                    status.pointee = .haveData
                    return buffer
                }
                if let error { throw error }
                if let samples = output.floatChannelData?[0], output.frameLength > 0 {
                    let bytes = Data(bytes: samples, count: Int(output.frameLength) * 4)
                    if !send(bytes) {
                        failed("Audio transport filled. Capture stopped; microphone audio is retained in Logs.")
                    }
                }
            } catch { failed("Audio capture failed: \(error.localizedDescription)") }
        }
        tapped = true
        do { try engine.start() } catch { stop(); throw error }
    }

    /// Diagnostic file replay uses the same pipe and phrase collector as microphone capture.
    func replay(url: URL, send: @escaping (Data) -> Bool, finished: @escaping () -> Void,
                failed: @escaping (String) -> Void) throws {
        let file = try AVAudioFile(forReading: url)
        guard file.processingFormat.sampleRate == 16_000, file.processingFormat.channelCount == 1 else {
            throw NSError(domain: "Cadenza", code: 2,
                          userInfo: [NSLocalizedDescriptionKey: "Replay expects mono 16 kHz audio"])
        }
        replayTask = Task.detached {
            do {
                let clock = ContinuousClock()
                let started = clock.now
                while file.framePosition < file.length && !Task.isCancelled {
                    let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: 320)!
                    try file.read(into: buffer, frameCount: 320)
                    if let samples = buffer.floatChannelData?[0] {
                        if !send(Data(bytes: samples, count: Int(buffer.frameLength) * 4)) {
                            failed("Replay transport filled; source file is retained.")
                            return
                        }
                    }
                    let deadline = started + .seconds(Double(file.framePosition) / 16_000)
                    try await clock.sleep(until: deadline)
                }
                if !Task.isCancelled { finished() }
            } catch {
                if !Task.isCancelled { failed(error.localizedDescription) }
            }
        }
    }

    func stop() {
        replayTask?.cancel()
        replayTask = nil
        engine.stop()
        if tapped { engine.inputNode.removeTap(onBus: 0); tapped = false }
    }
    deinit { stop() }
}
