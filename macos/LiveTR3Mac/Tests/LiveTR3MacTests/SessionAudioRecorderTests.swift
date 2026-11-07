import Foundation
import XCTest
@testable import LiveTR3Mac

final class SessionAudioRecorderTests: XCTestCase {
    private final class FakeClock: @unchecked Sendable {
        var now: TimeInterval = 100
    }

    private func frame(_ value: Float, samples: Int = 320) -> Data {
        [Float](repeating: value, count: samples).withUnsafeBufferPointer { Data(buffer: $0) }
    }

    func testWritesPlayableWavAndFillsGapsWithSilence() throws {
        let directory = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let clock = FakeClock()
        let recorder = try SessionAudioRecorder(directory: directory, clock: { clock.now })

        clock.now = 100.02
        recorder.append(frame(0.5))      // 320 samples, on time
        clock.now = 102.02
        recorder.append(frame(-0.5))     // after a 2 s pause: silence first
        recorder.finish()
        recorder.waitForWrites()

        let wav = try Data(contentsOf: recorder.url)
        let samples = (wav.count - 44) / 2
        XCTAssertEqual(String(decoding: wav[0..<4], as: UTF8.self), "RIFF")
        XCTAssertEqual(wav[40..<44].withUnsafeBytes { $0.loadUnaligned(as: UInt32.self) }, UInt32(samples * 2))
        XCTAssertEqual(Double(samples) / 16_000, 2.02, accuracy: 0.001)

        let pcm = wav[44...].withUnsafeBytes { Array($0.bindMemory(to: Int16.self)) }
        XCTAssertEqual(pcm.first, 16_383)
        XCTAssertEqual(pcm[1_000], 0)
        XCTAssertEqual(pcm.last, -16_383)

        let sidecar = recorder.url.deletingPathExtension().appendingPathExtension("json")
        let meta = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: sidecar)) as? [String: Any])
        XCTAssertEqual(meta["sample_rate"] as? Int, 16_000)
        XCTAssertEqual(try XCTUnwrap(meta["duration_seconds"] as? Double), 2.02, accuracy: 0.001)
        XCTAssertNotNil(meta["started_at"] as? String)
    }

    func testShortJitterIsNotPadded() throws {
        let directory = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let clock = FakeClock()
        let recorder = try SessionAudioRecorder(directory: directory, clock: { clock.now })
        for index in 1...50 {
            clock.now = 100 + Double(index) * 0.02 + (index.isMultiple(of: 7) ? 0.1 : 0)
            recorder.append(frame(0.1))
        }
        recorder.finish()
        recorder.waitForWrites()
        XCTAssertEqual(try Data(contentsOf: recorder.url).count, 44 + 50 * 320 * 2)
    }
}
