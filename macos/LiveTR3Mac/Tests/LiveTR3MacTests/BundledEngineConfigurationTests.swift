import Foundation
import XCTest
@testable import LiveTR3Mac

final class BundledEngineConfigurationTests: XCTestCase {
    func testRelocatedBundleUsesItsOwnModelsAndPython() {
        let configuration = BundledEngineConfiguration(
            resources: URL(fileURLWithPath: "/Volumes/Friend Disk/LiveTR3.app/Contents/Resources"),
            applicationSupport: URL(fileURLWithPath: "/Users/friend/Library/Application Support")
        )
        let environment = configuration.environment(inheriting: [
            "MODEL_PATH": "/Users/ed/old-model", "PYTHONHOME": "/opt/homebrew/python",
            "HF_HUB_OFFLINE": "0", "LIVETR3_GEMMA_MTP": "0"
        ])
        XCTAssertEqual(environment["MODEL_PATH"], configuration.resources.appending(path: "Engine/models/gemma-target").path)
        XCTAssertEqual(environment["LIVETR3_MTP_MODEL"], configuration.resources.appending(path: "Engine/models/gemma-mtp").path)
        XCTAssertEqual(environment["PYTHONHOME"], configuration.resources.appending(path: "Engine/python").path)
        XCTAssertEqual(environment["LIVETR3_GEMMA_MTP"], "1")
        XCTAssertEqual(environment["HF_HUB_OFFLINE"], "1")
        XCTAssertEqual(environment["PYTHONDONTWRITEBYTECODE"], "1")
        XCTAssertTrue(configuration.socket.path.hasPrefix("/Users/friend/Library/Application Support/"))
        XCTAssertTrue(configuration.logs.path.hasPrefix("/Users/friend/Library/Application Support/"))
        XCTAssertFalse(environment.values.contains { $0.contains("/Users/ed/") || $0.contains("/opt/homebrew/") })
    }

    func testReplayArchiveOverrideIsPreserved() {
        let configuration = BundledEngineConfiguration(resources: URL(fileURLWithPath: "/Applications/LiveTR3.app/Contents/Resources"), applicationSupport: URL(fileURLWithPath: "/tmp/support"))
        XCTAssertEqual(configuration.environment(inheriting: ["LIVETR3_ARCHIVE_ROOT": "/tmp/replay"])["LIVETR3_ARCHIVE_ROOT"], "/tmp/replay")
    }
}
