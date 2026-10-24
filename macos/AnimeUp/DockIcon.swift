import AppKit

/// Follows the system appearance with the Dock icon while AnimeUp runs.
///
/// A classic `.icns` holds a single image, so Finder and Launchpad always show
/// the bundle icon (the light variant). While the app is running, though, the
/// Dock icon can be replaced: this swaps in `AnimeUp-Dark.icns` when macOS is
/// in dark mode, and puts the bundle icon back in light mode, live.
final class DockIcon {
    private var observation: NSKeyValueObservation?
    private lazy var darkIcon: NSImage? = Bundle.main
        .url(forResource: "AnimeUp-Dark", withExtension: "icns")
        .flatMap { NSImage(contentsOf: $0) }

    func start() {
        update()
        observation = NSApp.observe(\.effectiveAppearance, options: [.new]) { [weak self] _, _ in
            DispatchQueue.main.async { self?.update() }
        }
    }

    private func update() {
        let dark = NSApp.effectiveAppearance
            .bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
        // nil restores the bundle icon (light).
        NSApp.applicationIconImage = dark ? darkIcon : nil
    }
}
