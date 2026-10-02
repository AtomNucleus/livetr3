// swift-tools-version: 5.10
import PackageDescription
let package = Package(name: "Cadenza", platforms: [.macOS(.v14)],
                      products: [.executable(name: "Cadenza", targets: ["Cadenza"])],
                      targets: [.executableTarget(name: "Cadenza")])
