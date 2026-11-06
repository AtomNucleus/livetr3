import XCTest
@testable import LiveTR3Mac

final class CaptureActivityTests: XCTestCase {
    func testHoldsOneActivityUntilEnded() {
        let activity = CaptureActivity()
        XCTAssertFalse(activity.isActive)

        activity.begin()
        activity.begin()
        XCTAssertTrue(activity.isActive)

        activity.end()
        XCTAssertFalse(activity.isActive)
        activity.end()
        XCTAssertFalse(activity.isActive)
    }
}

final class AudioLevelMeterTests: XCTestCase {
    @MainActor
    func testMeterPublishesTheLoudestLevelAtMostTwelveTimesASecond() {
        let meter = AudioLevelMeter()
        var publishes = 0
        let token = meter.objectWillChange.sink { publishes += 1 }
        defer { token.cancel() }
        // One second of 50 Hz engine levels.
        for frame in 0..<50 {
            meter.record(frame == 7 ? 0.9 : 0.1, at: Double(frame) * 0.02)
        }
        XCTAssertLessThanOrEqual(publishes, 13)
        XCTAssertGreaterThanOrEqual(publishes, 10)
        XCTAssertTrue(meter.levels.contains(0.9), "A brief peak between publishes still shows")
        XCTAssertEqual(meter.levels.count, AudioLevelMeter.barCount)
    }
}
