// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "memoryagent-calendar",
    platforms: [
        .macOS(.v13),
    ],
    targets: [
        .executableTarget(
            name: "memoryagent-calendar",
            path: "Sources",
            exclude: [
                "memoryagent-calendar/Resources/Info.plist",
            ],
            linkerSettings: [
                // Embed usage strings so TCC can show prompts and list this binary under Privacy → Calendars.
                .unsafeFlags([
                    "-Xlinker", "-sectcreate",
                    "-Xlinker", "__TEXT",
                    "-Xlinker", "__info_plist",
                    "-Xlinker", "Sources/memoryagent-calendar/Resources/Info.plist",
                ]),
            ]
        ),
    ]
)
