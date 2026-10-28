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
        if ProcessInfo.processInfo.environment["ANIMEUP_SNAPSHOT_TOOLS"] == "1" {
            Task { @MainActor in
                var n = 0
                for _ in 0..<240 {
                    try? await Task.sleep(for: .seconds(3))
                    if model.showsToolsWindow {
                        n += 1
                        render(ToolsSetupView().environment(model), width: 600, "\(base)-tools-live-\(n).png")
                        log.info("tools window: \(String(describing: model.tools2.rows))")
                    } else if n > 0 {
                        renderComposite(model, "\(base)-after-tools.png")
                        break
                    }
                }
            }
        }
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
            let env = ProcessInfo.processInfo.environment
            if env["ANIMEUP_SNAPSHOT_SETTINGS"] == "1" {
                for tab in SettingsTab.allCases {
                    render(SettingsPage(tab: tab).environment(model), width: 640, "\(base)-settings-\(tab.rawValue).png")
                }
                model.jobRunning = true
                render(SettingsPage(tab: .output).environment(model), width: 640, "\(base)-settings-output-locked.png")
                model.jobRunning = false
                var fake = model.tools2
                model.tools2.rows = [.init(key: "ffmpeg", state: .done, bytes: 38_000_000, total: 38_000_000),
                                     .init(key: "realesrgan", state: .running, bytes: 30_000_000, total: 46_000_000),
                                     .init(key: "realcugan"), .init(key: "python", state: .done)]
                model.tools2.phase = .installing
                render(ToolsSetupView().environment(model), width: 600, "\(base)-tools-downloading.png")
                model.tools2.rows[1].state = .failed
                model.tools2.phase = .failed(key: "realesrgan", error: "URLError: connection lost")
                render(ToolsSetupView().environment(model), width: 600, "\(base)-tools-failed.png")
                fake.phase = .notNeeded
                model.tools2 = fake
            }
            if let videos = env["ANIMEUP_SNAPSHOT_ADD"] {
                model.add([URL(fileURLWithPath: videos)], subfolders: true)
                try? await Task.sleep(for: .seconds(4))
                model.tab = .queue
                if let first = model.files.first(where: { $0.state == .analysing }) ?? model.files.first {
                    model.expanded = first.id
                }
                try? await Task.sleep(for: .seconds(1))
                renderQueue(model, "\(base)-queue-analysing.png")
                renderComposite(model, "\(base)-start-files.png")
                for _ in 0..<120 where model.activity.running || model.files.contains(where: { $0.state != .ready }) {
                    try? await Task.sleep(for: .seconds(1))
                    await model.refreshFiles()
                }
                model.expanded = model.files.first(where: { !$0.warnings.isEmpty })?.id ?? model.files.first?.id
                model.selection = []
                try? await Task.sleep(for: .seconds(1))
                renderQueue(model, "\(base)-queue-ready.png")
                model.expanded = model.files.first(where: { $0.name.contains("720p") })?.id ?? model.expanded
                model.panelTab = .processing
                try? await Task.sleep(for: .seconds(1))
                renderQueue(model, "\(base)-queue-plan.png")
                model.panelTab = .analysis
                renderComposite(model, "\(base)-start-files-done.png")
                model.localizer.setLanguage("it")
                renderQueue(model, "\(base)-queue-ready-it.png")
                model.localizer.setLanguage(model.settings?.language ?? "en")
            }
            if let name = env["ANIMEUP_SNAPSHOT_RUN"], let f = model.files.first(where: { $0.name.contains(name) }) {
                await runScenario(model, f.id, base)
            }
            if env["ANIMEUP_SNAPSHOT_CAL"] == "1" {
                model.showCalibration = true
                render(CalibrationSheet().environment(model), width: 520, "\(base)-cal-intro.png")
                model.startCalibration()
                for _ in 0..<40 {
                    try? await Task.sleep(for: .seconds(1))
                    if let r = model.calRun, r.running, (r.index ?? 0) >= 1 { break }
                }
                render(CalibrationSheet().environment(model), width: 520, "\(base)-cal-running.png")
                renderQueue(model, "\(base)-cal-sidebar.png")
                log.info("calibration run: \(String(describing: model.calRun))")
                model.stopCalibration()
                try? await Task.sleep(for: .seconds(3))
                log.info("calibration after stop: \(String(describing: model.calRun))")
                render(CalibrationSheet().environment(model), width: 520, "\(base)-cal-stopped.png")
                model.showCalibration = false
            }
            if env["ANIMEUP_SNAPSHOT_TABS"] == "1" {
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

    /// Start → pause → resume → stop → resume → done, with renders.
    static func runScenario(_ model: AppModel, _ id: String, _ base: String) async {
        func wait(_ what: String, _ limit: Int, _ cond: () -> Bool) async {
            for _ in 0..<limit where !cond() { try? await Task.sleep(for: .seconds(1)) }
            log.info("scenario \(what): \(String(describing: model.job(id)))")
        }
        model.tab = .queue
        model.expanded = id
        model.panelTab = .processing
        try? await model.engine.queueStart([id])
        await wait("running", 120) { model.job(id)?.stage == "upscale" && (model.job(id)?.framesDone ?? 0) > 20 && model.job(id)?.state == .running }
        renderQueue(model, "\(base)-run-running.png")
        model.command("queue.pause")
        await wait("paused", 20) { model.job(id)?.state == .paused }
        renderQueue(model, "\(base)-run-paused.png")
        model.command("queue.resume")
        await wait("resumed", 60) { model.job(id)?.state == .running && model.job(id)?.stage == "upscale" }
        model.command("queue.stop", id: id)
        await wait("stopped", 60) { model.job(id)?.state == .interrupted && !model.progress.queue.running }
        renderQueue(model, "\(base)-run-interrupted.png")
        model.showFinished = false
        model.command("job.resume", id: id)
        await wait("resumed job", 30) { model.job(id)?.state == .running }
        await wait("done", 900) { model.job(id)?.state == .done }
        try? await Task.sleep(for: .seconds(3))
        renderQueue(model, "\(base)-run-done.png")
        render(FinishedSheet().environment(model), width: 480, "\(base)-run-finished.png")
        log.info("scenario finished sheet: \(String(describing: model.finished))")
    }

    static func render<V: View>(_ view: V, width: CGFloat, _ path: String) {
        let renderer = ImageRenderer(content: view.frame(width: width).environment(\.colorScheme, .dark))
        renderer.scale = 2
        if let image = renderer.nsImage, let tiff = image.tiffRepresentation,
           let rep = NSBitmapImageRep(data: tiff), let png = rep.representation(using: .png, properties: [:]) {
            try? png.write(to: URL(fileURLWithPath: path))
        }
    }

    static func renderQueue(_ model: AppModel, _ path: String) {
        let view = HStack(spacing: 0) {
            SidebarView()
                .padding(.top, 44)
                .frame(width: 236)
                .frame(maxHeight: .infinity)
                .background(RoundedRectangle(cornerRadius: 16).fill(AU.side)
                    .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(AU.glassLine)))
                .padding([.leading, .vertical], 8)
            VStack(spacing: 0) {
                QueueContent().padding(.top, 28).padding(.horizontal, 28).padding(.bottom, 16)
                Spacer(minLength: 0)
                QueueActionBar().padding(.horizontal, 28).padding(.bottom, 24)
            }
        }
        .frame(width: 1360, alignment: .top)
        .frame(minHeight: 840, alignment: .top)
        .background(AU.bg)
        .environment(model)
        .environment(\.colorScheme, .dark)
        render(view, width: 1360, path)
    }

    static func capture(_ path: String) {
        guard let window = NSApp.windows.first(where: { $0.isVisible && $0.title == "AnimeUp" }) ?? NSApp.windows.first,
              let view = window.contentView?.superview ?? window.contentView,
              let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return }
        view.cacheDisplay(in: view.bounds, to: rep)
        if let png = rep.representation(using: .png, properties: [:]) {
            try? png.write(to: URL(fileURLWithPath: path))
            log.info("snapshot \(path)")
        }
    }
}
#endif
