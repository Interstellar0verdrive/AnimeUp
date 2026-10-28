// swift-tools-version: 6.2
// AnimeUpKit: the pieces of the native app that don't need the app target.
//   Models        Codable mirrors of the engine's replies, the localiser
//   Engine        EngineClient: spawns `animeup serve` and speaks JSON lines
//   DesignSystem  colour tokens, type styles, buttons and AnimeUp's own views
import PackageDescription

let package = Package(
    name: "AnimeUpKit",
    platforms: [.macOS(.v26)],
    products: [
        .library(name: "Models", targets: ["Models"]),
        .library(name: "Engine", targets: ["Engine"]),
        .library(name: "DesignSystem", targets: ["DesignSystem"]),
    ],
    targets: [
        .target(name: "Models"),
        .target(name: "Engine", dependencies: ["Models"]),
        .target(name: "DesignSystem"),
        .testTarget(name: "ModelsTests", dependencies: ["Models"]),
        .testTarget(name: "EngineTests", dependencies: ["Engine", "Models"]),
    ],
    swiftLanguageModes: [.v5]
)
