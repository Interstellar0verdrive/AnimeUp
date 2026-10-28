#if DEBUG
import AppKit
import DesignSystem
import SwiftUI

/// Debug only: `ANIMEUP_SNAPSHOT=/path/shot` writes PNGs of the main window
/// (`shot-<n>.png`) a few seconds after launch, without needing the Screen
/// Recording permission. `ANIMEUP_SNAPSHOT_TABS=1` also captures the other tabs.
@MainActor
enum DebugSnapshot {
    static func scheduleIfAsked(model: AppModel) {
        guard let base = ProcessInfo.processInfo.environment["ANIMEUP_SNAPSHOT"], !base.isEmpty else { return }
        Task { @MainActor in
            for _ in 0..<120 where model.status != .ready { try? await Task.sleep(for: .milliseconds(500)) }
            try? await Task.sleep(for: .seconds(2))
            capture("\(base)-start.png")
            renderSidebar(model, "\(base)-sidebar.png")
            renderComposite(model, "\(base)-composite.png")
            let saved = model.localizer.language
            for lang in ["en", "it"] {
                model.localizer.setLanguage(lang)
                renderComposite(model, "\(base)-composite-\(lang).png")
            }
            model.localizer.setLanguage(saved)
            if ProcessInfo.processInfo.environment["ANIMEUP_SNAPSHOT_TABS"] == "1" {
                model.localizer.setLanguage("it")
                try? await Task.sleep(for: .seconds(1))
                capture("\(base)-start-it.png")
                model.localizer.setLanguage(model.settings?.language ?? "en")
                model.tab = .queue
                try? await Task.sleep(for: .seconds(1))
                capture("\(base)-queue.png")
                model.tab = .start
            }
        }
    }

    /// The glass sidebar doesn't survive cacheDisplay: render it on its own.
    static func renderSidebar(_ model: AppModel, _ path: String) {
        let renderer = ImageRenderer(content:
            SidebarView().environment(model)
                .frame(width: 236, height: 780)
                .padding(.top, 44)
                .background(RoundedRectangle(cornerRadius: 16).fill(AU.side))
                .background(AU.bg)
                .environment(\.colorScheme, .dark))
        renderer.scale = 2
        if let image = renderer.nsImage, let tiff = image.tiffRepresentation,
           let rep = NSBitmapImageRep(data: tiff), let png = rep.representation(using: .png, properties: [:]) {
            try? png.write(to: URL(fileURLWithPath: path))
        }
    }

    /// Sidebar and Start content side by side at the boards' window size
    /// (1360×840). AppKit-backed controls (menu, slider, link) show as
    /// placeholders in ImageRenderer.
    static func renderComposite(_ model: AppModel, _ path: String) {
        let view = HStack(spacing: 0) {
            SidebarView()
                .padding(.top, 44)
                .frame(width: 236)
                .frame(maxHeight: .infinity)
                .background(RoundedRectangle(cornerRadius: 16).fill(AU.side)
                    .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(AU.glassLine)))
                .padding([.leading, .vertical], 8)
            StartContent(minGrid: 840 - StartContent.headerHeight)
        }
        .frame(width: 1360, alignment: .top)
        .frame(minHeight: 840, alignment: .top)
        .background(AU.bg)
        .environment(model)
        .environment(\.colorScheme, .dark)
        let renderer = ImageRenderer(content: view)
        renderer.scale = 2
        if let image = renderer.nsImage, let tiff = image.tiffRepresentation,
           let rep = NSBitmapImageRep(data: tiff), let png = rep.representation(using: .png, properties: [:]) {
            try? png.write(to: URL(fileURLWithPath: path))
        }
    }

    static func capture(_ path: String) {
        guard let window = NSApp.windows.first(where: { $0.isVisible && $0.title == "AnimeUp" }) ?? NSApp.windows.first,
              let view = window.contentView?.superview ?? window.contentView,
              let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return }
        view.cacheDisplay(in: view.bounds, to: rep)
        if let png = rep.representation(using: .png, properties: [:]) {
            try? png.write(to: URL(fileURLWithPath: path))
            log.info("snapshot \(path, privacy: .public)")
        }
    }
}
#endif
