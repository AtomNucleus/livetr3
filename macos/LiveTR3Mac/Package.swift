// swift-tools-version: 5.10

import PackageDescription

let package = Package(
    name: "LiveTR3Mac",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "LiveTR3", targets: ["LiveTR3Mac"])
    ],
    targets: [
        .executableTarget(
            name: "LiveTR3Mac",
            linkerSettings: [
                // SwiftPM's default build system stamps the deployment target as the SDK version,
                // which keeps AppKit in its pre-Liquid Glass compatibility appearance.
                .unsafeFlags(["-Xlinker", "-platform_version", "-Xlinker", "macos", "-Xlinker", "14.0", "-Xlinker", "26.0"])
            ]
        ),
        .testTarget(
            name: "LiveTR3MacTests",
            dependencies: ["LiveTR3Mac"]
        )
    ]
)
