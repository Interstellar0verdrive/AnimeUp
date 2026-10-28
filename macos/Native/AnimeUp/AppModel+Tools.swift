import AppKit
import Engine
import Models

/// The first-launch tools window (board T1).
struct ToolsSetupState: Equatable {
    enum Phase: Equatable {
        /// Not decided yet (engine starting).
        case unknown
        /// All tools verified: the main window.
        case notNeeded
        /// The window is up and downloading (or about to).
        case installing
        /// A tool failed: Try Again / Show Log / Quit.
        case failed(key: String, error: String)
    }

    struct Row: Equatable, Identifiable {
        var key: String
        var state: ToolProgress.State = .waiting
        var bytes: Int64 = 0
        var total: Int64 = 0
        var id: String { key }
    }

    var phase: Phase = .unknown
    /// The rows shown: the missing tools plus Python (which comes with the engine).
    var rows: [Row] = []
    /// Python was being set up when the window opened (very first launch).
    var pythonPending = false

    static let sizesMB: [String: Int64] = ["ffmpeg": 38, "realesrgan": 46, "realcugan": 96, "python": 42]
}

extension AppModel {
    /// Very first launch: no Python environment yet, so the tools window
    /// opens straight away with Python downloading.
    func prepareToolsWindowIfFirstLaunch() {
        let venv = configuration.stateFolder.appendingPathComponent(".venv")
        if !FileManager.default.fileExists(atPath: venv.path) {
            tools2.phase = .installing
            tools2.pythonPending = true
            tools2.rows = ["ffmpeg", "realesrgan", "realcugan"].map { ToolsSetupState.Row(key: $0) }
                + [ToolsSetupState.Row(key: "python", state: .running)]
        }
    }

    var showsToolsWindow: Bool {
        switch tools2.phase {
        case .installing, .failed: true
        default: false
        }
    }

    /// After `tools.status`: open the window for what's missing, or not.
    func decideTools(_ status: ToolsStatus) {
        let missing = status.tools.filter { !$0.verified }.map(\.key)
        var keys: [String] = []
        if missing.contains("ffmpeg") || missing.contains("ffprobe") { keys.append("ffmpeg") }
        for k in ["realesrgan", "realcugan"] where missing.contains(k) { keys.append(k) }
        if keys.isEmpty {
            if tools2.pythonPending {
                // Only Python was missing: show it done for a moment, then go.
                markPythonDone()
            }
            finishToolsWindow()
            return
        }
        var rows = keys.map { ToolsSetupState.Row(key: $0) }
        rows.append(ToolsSetupState.Row(key: "python", state: .done))
        if !tools2.pythonPending {
            // A later launch where a tool went missing: only that tool.
            rows.removeLast()
        }
        tools2.rows = rows
        tools2.phase = .installing
        log.info("tools missing: \(keys.joined(separator: ","), privacy: .public)")
        Task { try? await engine.installTools(keys) }
    }

    private func markPythonDone() {
        if let i = tools2.rows.firstIndex(where: { $0.key == "python" }) { tools2.rows[i].state = .done }
    }

    func toolProgress(_ p: ToolProgress) {
        guard let i = tools2.rows.firstIndex(where: { $0.key == p.key }) else { return }
        tools2.rows[i].state = p.state
        if let b = p.bytes { tools2.rows[i].bytes = b }
        if let t = p.total, t > 0 { tools2.rows[i].total = t }
        if p.state == .done { tools2.rows[i].bytes = max(tools2.rows[i].bytes, tools2.rows[i].total) }
        if p.state == .failed {
            tools2.phase = .failed(key: p.key, error: p.error ?? "")
        }
    }

    func toolsFinished() async {
        guard let status = try? await engine.toolsStatus() else { return }
        tools = status
        if status.tools.allSatisfy(\.verified) {
            finishToolsWindow()
        }
    }

    func retryTools() {
        let keys = tools2.rows.filter { $0.key != "python" && $0.state != .done }.map(\.key)
        tools2.phase = .installing
        for i in tools2.rows.indices where tools2.rows[i].state == .failed { tools2.rows[i].state = .waiting }
        Task { try? await engine.installTools(keys) }
    }

    private func finishToolsWindow() {
        let wasShowing = showsToolsWindow
        tools2.phase = .notNeeded
        tools2.pythonPending = false
        if wasShowing { WindowSizer.toMain() }
    }

    /// Bytes done / total across the rows (Python counts by its nominal size).
    var toolsTotals: (done: Int64, total: Int64, index: Int, count: Int) {
        var done: Int64 = 0, total: Int64 = 0
        for r in tools2.rows {
            let nominal = (ToolsSetupState.sizesMB[r.key] ?? 0) * 1_000_000
            let t = r.total > 0 ? r.total : nominal
            total += t
            done += r.state == .done ? t : min(r.bytes, t)
        }
        let index = tools2.rows.filter { $0.state == .done }.count + 1
        return (done, total, min(index, tools2.rows.count), tools2.rows.count)
    }
}

/// Resizes the main window between the tools window (T1) and the app.
@MainActor
enum WindowSizer {
    static var main: NSWindow? {
        NSApp.windows.first { $0.identifier?.rawValue.hasPrefix("main") == true } ?? NSApp.windows.first { $0.title == "AnimeUp" }
    }

    static func toTools() {
        guard let w = main else { return }
        w.minSize = NSSize(width: 600, height: 360)
        resize(w, to: NSSize(width: 600, height: 380))
    }

    static func toMain() {
        guard let w = main else { return }
        resize(w, to: NSSize(width: 1360, height: 840))
        w.minSize = NSSize(width: 1100, height: 720)
    }

    private static func resize(_ w: NSWindow, to size: NSSize) {
        var frame = w.frameRect(forContentRect: NSRect(origin: .zero, size: size))
        let screen = w.screen?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        frame.origin.x = screen.midX - frame.width / 2
        frame.origin.y = screen.midY - frame.height / 2
        w.setFrame(frame, display: true, animate: true)
    }
}
