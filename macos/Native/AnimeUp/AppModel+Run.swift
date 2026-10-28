import AppKit
import Engine
import Models
import UserNotifications

extension AppModel {
    // MARK: progress

    func applyProgress(_ p: QueueProgress) {
        let before = lastJobStates
        progress = p
        jobRunning = p.queue.running
        var now: [String: QueueProgress.Job.State] = [:]
        for (id, job) in p.files { now[id] = job.state }
        // Notifications for files that just finished or stopped.
        for (id, state) in now where before[id] != nil && before[id] != state {
            let name = file(id)?.name ?? ""
            if state == .done {
                let w = p.files[id]?.warnings?.count ?? 0
                notify(t("nat.note.file_done_title"), w == 0 ? t("nat.note.file_done", ["name": name])
                       : localizer.tn("nat.note.file_done_warn", w, ["name": name]))
            } else if state == .interrupted, before[id] == .running {
                notify(t("nat.note.file_stopped_title"), t("nat.note.file_stopped", ["name": name]))
            }
        }
        lastJobStates = now
        DockProgress.update(self)
    }

    func job(_ id: String) -> QueueProgress.Job? { progress.files[id] }

    /// The first queued file of the run (it starts after the rest between files).
    var nextQueuedId: String? { (progress.queue.ids ?? []).first { job($0)?.state == .queued } }

    var queueTicked: [String] { files.filter { isTicked($0) && job($0.id)?.state != .done }.map(\.id) }

    // MARK: commands

    func startQueue() {
        let ids = queueTicked
        guard !ids.isEmpty else { return }
        Task {
            do { try await engine.queueStart(ids) } catch { show(error) }
            if let p = try? await engine.queueStatus() { applyProgress(p) }
        }
    }

    func command(_ method: String, id: String? = nil) {
        Task {
            do { try await engine.queueCommand(method, id: id) } catch { show(error) }
            if let p = try? await engine.queueStatus() { applyProgress(p) }
        }
    }

    private func show(_ error: Error) {
        log.error("command failed: \(error)")
        var text = String(describing: error)
        if case EngineError.remote(let code, let message) = error {
            text = code == "busy" ? t(message == "calibrating" ? "nat.run.busy_calibrating" : "nat.run.busy") : message
        }
        alert = AppAlert(kind: .info(title: t("nat.run.error_title"), text: text))
    }

    /// Stop on a row: "Stop this file?" (O1), with Stop All when others follow.
    func confirmStop(_ id: String) {
        let others = (progress.queue.ids ?? []).filter { $0 != id && job($0)?.state == .queued }
        let a = NSAlert()
        a.alertStyle = .warning
        a.messageText = t("nat.run.stop_title")
        a.informativeText = t("nat.run.stop_text")
        let stop = a.addButton(withTitle: t("nat.run.stop"))
        stop.hasDestructiveAction = true
        if !others.isEmpty { a.addButton(withTitle: t("nat.run.stop_all")) }
        a.addButton(withTitle: t("nat.btn.cancel"))
        switch a.runModal() {
        case .alertFirstButtonReturn: command("queue.stop", id: id)
        case .alertSecondButtonReturn where !others.isEmpty: command("queue.stopAll")
        default: break
        }
    }

    func confirmStopAll() {
        let a = NSAlert()
        a.alertStyle = .warning
        a.messageText = t("nat.run.stopall_title")
        a.informativeText = t("nat.run.stopall_text")
        a.addButton(withTitle: t("nat.run.stop_all")).hasDestructiveAction = true
        a.addButton(withTitle: t("nat.btn.cancel"))
        if a.runModal() == .alertFirstButtonReturn { command("queue.stopAll") }
    }

    func confirmDiscard(_ id: String) {
        let a = NSAlert()
        a.alertStyle = .warning
        a.messageText = t("nat.run.discard_title", ["name": file(id)?.name ?? ""])
        a.informativeText = t("nat.run.discard_text")
        a.addButton(withTitle: t("nat.run.discard")).hasDestructiveAction = true
        a.addButton(withTitle: t("nat.btn.cancel"))
        if a.runModal() == .alertFirstButtonReturn { command("job.discard", id: id) }
    }

    /// ⌘Q while a job runs (O1): it stops now and can be resumed.
    func confirmQuitWhileRunning() -> Bool {
        log.info("quit requested while the queue runs")
        let a = NSAlert()
        a.alertStyle = .warning
        a.messageText = t("nat.run.quit_title")
        a.informativeText = t("nat.run.quit_text")
        a.addButton(withTitle: t("nat.run.quit")).hasDestructiveAction = true
        a.addButton(withTitle: t("nat.btn.cancel"))
        guard a.runModal() == .alertFirstButtonReturn else { return false }
        // Synchronously enough: the engine signals the group before we go.
        let sem = DispatchSemaphore(value: 0)
        Task.detached { [engine] in
            try? await engine.queueCommand("queue.stopAll")
            sem.signal()
        }
        _ = sem.wait(timeout: .now() + 3)
        return true
    }

    func quitApp() {
        let sheetOpen = showFinished || showCalibration || cmp.showUseMany
        showFinished = false
        showCalibration = false
        cmp.showUseMany = false
        for w in NSApp.windows { if let sheet = w.attachedSheet { w.endSheet(sheet) } }
        DispatchQueue.main.asyncAfter(deadline: .now() + (sheetOpen ? 0.35 : 0)) { NSApp.terminate(nil) }
    }

    // MARK: end of queue (M6)

    func queueFinished(_ launch: [String: JSONValue]?) {
        guard let launch else { return }
        finished = launch
        showFinished = true
        tab = .queue
        let ok = launch["succeeded"]?.array.count ?? 0
        let failed = (launch["failed"]?.array.count ?? 0) + (launch["interrupted"]?.array.count ?? 0)
        notify(t("nat.note.queue_done_title"),
               failed == 0 ? localizer.tn("nat.note.queue_done", ok) : t("nat.note.queue_done_some", ["ok": ok, "failed": failed]))
        Task { await refreshFiles() }
    }

    func markFinishedSeen() {
        if let label = finished?["launch"]?.string { UserDefaults.standard.set(label, forKey: "finishedSeen") }
        showFinished = false
    }

    /// At launch: the unseen finished sheet, and the Queue tab when something is pending.
    func afterLaunch() {
        let pending = progress.queue.running || progress.files.values.contains { $0.state == .interrupted }
        if pending { tab = .queue }
        Task {
            if let r = try? await engine.lastLaunch(), let launch = r.launch,
               let label = launch["launch"]?.string,
               UserDefaults.standard.string(forKey: "finishedSeen") != label,
               !progress.queue.running,
               (launch["ended"]?.number ?? 0) > Date().timeIntervalSince1970 - 7 * 86400 {
                finished = launch
                showFinished = true
                tab = .queue
            }
        }
    }

    func openLog(_ path: String?) {
        guard let path else { return }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        p.arguments = ["-a", "Console", path]
        try? p.run()
    }

    // MARK: notifications

    func notify(_ title: String, _ body: String) {
        guard settings?.notifications ?? true else { return }
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
            guard granted else { return }
            let content = UNMutableNotificationContent()
            content.title = title
            content.body = body
            center.add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
        }
    }

    // MARK: calibration (M7)

    func calibrate() {
        if progress.queue.running {
            let a = NSAlert()
            a.messageText = t("nat.cal.after_queue_title")
            a.informativeText = t("nat.cal.after_queue_text")
            a.addButton(withTitle: t("nat.btn.ok"))
            a.runModal()
            return
        }
        showCalibration = true
    }

    func startCalibration() {
        Task {
            do {
                _ = try await engine.raw("calibration.start")
                calRun = try? await engine.calibrationRun()
            } catch { show(error) }
        }
    }

    func stopCalibration() {
        Task {
            _ = try? await engine.raw("calibration.stop")
            calRun = try? await engine.calibrationRun()
        }
    }

    func closeCalibration() {
        showCalibration = false
        if let r = calRun, !r.running, r.state == "done" || r.state == "failed" {
            Task { _ = try? await engine.raw("calibration.seen") }
        }
    }
}

/// O3: progress bar and badge on the Dock icon while the queue runs.
@MainActor
enum DockProgress {
    static func update(_ model: AppModel) {
        let tile = NSApp.dockTile
        guard model.settings?.dockProgress ?? true, model.progress.queue.running else {
            if tile.contentView != nil || tile.badgeLabel != nil {
                tile.contentView = nil
                tile.badgeLabel = nil
                tile.display()
            }
            return
        }
        let q = model.progress.queue
        let live = model.progress.files.values.first { $0.state == .running || $0.state == .paused }
        let total = Double(max(1, q.total ?? 1))
        let done = Double(max(0, (q.position ?? 1) - 1))
        let fraction = (done + (live?.fraction ?? 0)) / total
        let view = (tile.contentView as? DockView) ?? DockView(frame: NSRect(x: 0, y: 0, width: 128, height: 128))
        view.fraction = fraction
        view.paused = q.paused
        tile.contentView = view
        let left = (q.total ?? 1) - (q.position ?? 1) + 1
        tile.badgeLabel = left > 1 ? "\(left)" : nil
        tile.display()
    }
}

final class DockView: NSView {
    var fraction: Double = 0
    var paused = false

    override func draw(_ dirtyRect: NSRect) {
        NSApp.applicationIconImage.draw(in: bounds)
        let bar = NSRect(x: 14, y: 10, width: bounds.width - 28, height: 12)
        NSColor.black.withAlphaComponent(0.55).setFill()
        NSBezierPath(roundedRect: bar, xRadius: 6, yRadius: 6).fill()
        let inner = bar.insetBy(dx: 2, dy: 2)
        var fill = inner
        fill.size.width = max(inner.height, inner.width * CGFloat(min(1, max(0, fraction))))
        (paused ? NSColor(css: "#F2B84B") : NSColor(css: "#2AC9DE")).setFill()
        NSBezierPath(roundedRect: fill, xRadius: 4, yRadius: 4).fill()
    }
}
