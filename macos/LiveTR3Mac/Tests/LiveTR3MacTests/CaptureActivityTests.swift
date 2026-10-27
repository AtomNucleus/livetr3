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
