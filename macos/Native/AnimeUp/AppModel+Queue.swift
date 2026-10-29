import AppKit
import Engine
import Models

enum PanelTab: String { case analysis, processing }

/// Alerts the app shows (boards O1–O3).
struct AppAlert: Identifiable, CustomStringConvertible {
    var description: String { "\(kind)" }
    enum Kind {
        case noVideos(folder: String, subfoldersIncluded: Bool, paths: [String])
        case workNotWritable(folder: String)
        case workInsideFinished(folder: String)
        case changeAfterQueue
        case info(title: String, text: String)
        case error(title: String, text: String)
        /// O3: the main window closed while something runs.
        case closeNotice
        /// O1: the disk holding the work folder went away.
        case diskMissing(volume: String)
        /// O2: a new work folder while interrupted files keep their work in the old one.
        case moveWithInterrupted(url: URL, count: Int)
    }
    let id = UUID()
    var kind: Kind
}

extension AppModel {
    // MARK: files

    func refreshFiles() async {
        guard let list = try? await engine.filesList() else { return }
        let ids = Set(list.files.map(\.id))
        files = list.files
        activity = list.activity
        unticked = unticked.intersection(ids)
        selection = selection.intersection(ids)
        openRows = openRows.intersection(ids)
        await refreshPlans()
    }

    func refreshPlans() async {
        guard files.contains(where: { $0.state == .ready }),
              let reply = try? await engine.plans() else {
            if files.isEmpty { plans = [:] }
            return
        }
        plans = reply.plans
        calibratedWhen = reply.calibratedWhen
    }

    func plan(_ id: String) -> FilePlan? { plans[id].flatMap { $0.ready ? $0 : nil } }

    func chooseModel(_ key: String, for ids: [String]) {
        Task {
            try? await engine.setFiles(ids, model: key)
            await refreshPlans()
        }
    }

    /// "Same for all": the model for every analysed file it can process.
    func sameForAll(_ key: String) {
        let ids = files.filter { f in
            f.state == .ready && plans[f.id]?.option(key)?.unreachable == nil
        }.map(\.id)
        chooseModel(key, for: ids)
    }

    func chooseHeight(_ height: Int?, for id: String) {
        Task {
            try? await engine.setFiles([id], height: height.map { $0 as any Sendable } ?? NSNull())
            await refreshPlans()
        }
    }

    /// What "Same for all" would cost with `key`: every file it applies to, in seconds.
    func sameForAllEstimate(_ key: String) -> Double? {
        let times = files.filter { $0.state == .ready }
            .compactMap { plans[$0.id]?.option(key) }
            .filter { $0.unreachable == nil }
            .compactMap(\.estimate)
        return times.isEmpty ? nil : times.reduce(0, +)
    }

    /// Ticked files' estimate, in seconds.
    var selectionEstimate: Double {
        files.filter { isTicked($0) }.compactMap { plans[$0.id]?.estimate }.reduce(0, +)
    }

    /// Short model name: catalog label without "Real-ESRGAN " / "Real-".
    /// "animevideov3", "CUGAN no-denoise"; `compact` drops the family too
    /// ("no-denoise"), for tight columns such as "Model now → after".
    func shortModel(_ key: String, compact: Bool = false) -> String {
        let k = "mot.modello.\(key).label"
        let label = localizer.has(k) ? t(k) : key
        let short = label.hasPrefix("Real-ESRGAN ") ? String(label.dropFirst(12))
            : label.hasPrefix("Real-") ? String(label.dropFirst(5)) : label
        return compact && short.hasPrefix("CUGAN ") ? String(short.dropFirst(6)) : short
    }

    func scheduleFilesRefresh() {
        guard !refreshPending else { return }
        refreshPending = true
        Task {
            try? await Task.sleep(for: .milliseconds(150))
            refreshPending = false
            await refreshFiles()
        }
    }

    func add(_ urls: [URL], subfolders: Bool? = nil) {
        guard !urls.isEmpty else { return }
        let include = subfolders ?? includeSubfolders
        Task {
            do {
                let result = try await engine.addFiles(urls.map(\.path), subfolders: include)
                await refreshFiles()
                if result.added.isEmpty, result.already == 0, let empty = result.emptyFolders.first {
                    alert = AppAlert(kind: .noVideos(folder: empty, subfoldersIncluded: include,
                                                     paths: urls.map(\.path)))
                } else if !result.added.isEmpty {
                    // The page stays: Start shows "Your videos", Compare its analysis note,
                    // the Queue its new rows. The Queue is one click away.
                    lastReceived = result.added.count
                } else if result.already > 0 {
                    // Nothing new: say so instead of doing nothing (S4).
                    alert = AppAlert(kind: .info(title: localizer.tn("nat.add.already_title", result.already),
                                                 text: t("nat.add.already_text")))
                }
            } catch {
                log.error("files.add failed: \(String(describing: error))")
            }
        }
    }

    func remove(_ ids: Set<String>) {
        let gone = files.filter { ids.contains($0.id) }
        guard !gone.isEmpty else { return }
        undoRemoved = gone
        files.removeAll { ids.contains($0.id) }
        Task {
            try? await engine.removeFiles(Array(ids))
            await refreshFiles()
        }
    }

    func undoRemove() {
        let back = undoRemoved
        undoRemoved = []
        guard !back.isEmpty else { return }
        Task {
            _ = try? await engine.addFiles(back.map(\.url.path), subfolders: false, restore: true)
            await refreshFiles()
            await refreshPlans()
        }
    }

    func reanalyse(_ ids: [String]?) {
        Task {
            try? await engine.reanalyse(ids)
            await refreshFiles()
        }
    }

    func deepAnalysis(_ id: String) {
        Task {
            try? await engine.deepAnalysis([id])
            await refreshFiles()
        }
    }

    func showInFinder(_ ids: Set<String>) {
        let urls = files.filter { ids.contains($0.id) }.map(\.url)
        NSWorkspace.shared.activateFileViewerSelecting(urls)
    }

    func file(_ id: String) -> QueueFile? { files.first { $0.id == id } }

    /// Done files are skipped unless redone, and interrupted ones have their own
    /// Resume (F6): neither is ticked. A redo that would overwrite waits for an answer (F6e).
    func isTicked(_ f: QueueFile) -> Bool {
        f.state == .ready && !unticked.contains(f.id) && !jobBlocksTick(f.id)
    }
    func jobBlocksTick(_ id: String) -> Bool {
        guard let s = job(id)?.state else { return false }
        if s == .done { return !isRedo(id) || redoNeedsAnswer(id) }
        return s == .interrupted
    }

    // MARK: Redo (F6d, F6e)

    /// A finished file put back in the Queue.
    func isRedo(_ id: String) -> Bool { redo.contains(id) && job(id)?.state == .done }

    /// The plan's video is the one already made: same folder, same name.
    func redoOverwrites(_ id: String) -> Bool {
        guard let made = job(id)?.output, let p = plan(id), let name = p.outputName else { return false }
        let folder = p.outputNextToSource == false ? p.outputFolder : file(id).map { ($0.path as NSString).deletingLastPathComponent }
        guard let folder else { return false }
        return URL(fileURLWithPath: folder).appendingPathComponent(name).standardizedFileURL.path
            == URL(fileURLWithPath: made).standardizedFileURL.path
    }

    func redoNeedsAnswer(_ id: String) -> Bool { isRedo(id) && redoOverwrites(id) && !redoConfirmed.contains(id) }

    func startRedo(_ id: String) {
        redo.insert(id); redoConfirmed.remove(id); unticked.remove(id)
        panelTabs[id] = .processing
    }

    func cancelRedo(_ id: String) { redo.remove(id); redoConfirmed.remove(id) }

    func confirmOverwrite(_ id: String) { redoConfirmed.insert(id); unticked.remove(id) }

    var analysingCount: Int { files.filter { $0.state == .analysing || $0.state == .queued }.count }
    var warningCount: Int { files.filter { !$0.warnings.isEmpty }.count }

    /// "5 files · 1 analysing" for the sidebar.
    /// The Compare tab's second line follows the test (boards C1–C4): its step, or its progress.
    var compareSubtitle: String {
        if let st = cmp.status, st.running == true {
            return t("nat.tab.compare_testing", ["pct": Int(((st.quota ?? 0) * 100).rounded())])
        }
        if compareFiles.isEmpty { return t("nat.tab.compare_sub") }
        switch cmp.step {
        case .clips: return t("nat.tab.compare_step1")
        case .models: return t("nat.tab.compare_step2")
        case .results: return t("nat.tab.compare_results")
        }
    }

    /// A test has finished and its results are on the page (Compare, step 3).
    var compareHasResults: Bool {
        !compareFiles.isEmpty && cmp.step == .results && cmp.status?.running != true
    }

    /// Start is done once this Mac is calibrated and videos are in (the tick on boards C1–F7).
    var startDone: Bool { (calibration?.isCalibrated ?? false) && !files.isEmpty }

    var queueSubtitle: String {
        if files.isEmpty { return t("nat.tab.queue_sub") }
        if progress.queue.running {
            let live = progress.files.values.first { $0.state == .running || $0.state == .paused }
            return t("nat.run.tab_sub", ["i": progress.queue.position ?? 1, "n": progress.queue.total ?? 1,
                                         "pct": Int(((live?.fraction ?? 0) * 100).rounded())])
        }
        var parts = [localizer.tn("nat.queue.files", files.count)]
        if analysingCount > 0 {
            parts.append(t("nat.queue.analysing_n", ["n": analysingCount]))
        } else if warningCount > 0 {
            parts.append(localizer.tn("nat.queue.warnings", warningCount))
        }
        return parts.joined(separator: " · ")
    }

    // MARK: open panel

    func openVideosPanel() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = true
        panel.canChooseFiles = true
        panel.allowedContentTypes = [.movie, .video, .mpeg4Movie, .quickTimeMovie, .folder]
        panel.prompt = t("nat.open.prompt")
        let box = SubfoldersAccessory(title: t("nat.open.subfolders"), note: t("nat.open.subfolders_note"),
                                      on: includeSubfolders)
        panel.accessoryView = box.view
        panel.isAccessoryViewDisclosed = true
        if panel.runModal() == .OK {
            includeSubfolders = box.isOn
            add(panel.urls, subfolders: box.isOn)
        }
    }

    // MARK: work folder

    func validateAndSetWorkFolder(_ url: URL) {
        if jobRunning {
            alert = AppAlert(kind: .changeAfterQueue)
            return
        }
        if !FileManager.default.isWritableFile(atPath: url.path) {
            alert = AppAlert(kind: .workNotWritable(folder: url.lastPathComponent))
            return
        }
        // Inside a folder of finished videos: any file's folder (finished
        // videos go next to the originals by default).
        let path = url.standardizedFileURL.path + "/"
        if files.contains(where: { path.hasPrefix($0.url.deletingLastPathComponent().standardizedFileURL.path + "/") }) {
            alert = AppAlert(kind: .workInsideFinished(folder: url.lastPathComponent))
            return
        }
        // O2: interrupted files can only be resumed from the folder that holds their work.
        let interrupted = progress.files.values.filter { $0.state == .interrupted }.count
        if interrupted > 0, url.standardizedFileURL.path != folders.map({ URL(fileURLWithPath: $0.workFolder).standardizedFileURL.path }) {
            alert = AppAlert(kind: .moveWithInterrupted(url: url, count: interrupted))
            return
        }
        setWorkFolder(url)
    }

    /// O3: closing the window while a job or a test runs says it keeps going,
    /// until "Don't Show Again". Shown right away: the window's views are gone.
    func windowClosed() {
        guard jobRunning || cmp.status?.running == true,
              !UserDefaults.standard.bool(forKey: Self.closeNoticeOffKey) else { return }
        DispatchQueue.main.async { AlertBuilder.present(AppAlert(kind: .closeNotice), model: self) }
    }
    static let closeNoticeOffKey = "closeNoticeOff"

    /// O1: the work disk went missing, or is missing at launch while work waits on it.
    func checkWorkDisk(was old: FoldersState?) {
        guard let f = folders, !f.reachable else { return }
        let lost = old?.reachable == true
        let waiting = progress.queue.running || progress.files.values.contains { $0.state == .interrupted }
        if lost || (old == nil && waiting) { alert = AppAlert(kind: .diskMissing(volume: f.volume)) }
    }
}

/// The "Include subfolders" accessory of the Open panel (board S7).
final class SubfoldersAccessory {
    let view: NSView
    private let check: NSButton

    init(title: String, note: String, on: Bool) {
        check = NSButton(checkboxWithTitle: title, target: nil, action: nil)
        check.state = on ? .on : .off
        let label = NSTextField(wrappingLabelWithString: note)
        label.font = .systemFont(ofSize: 11)
        label.textColor = .secondaryLabelColor
        let stack = NSStackView(views: [check, label])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 4
        stack.edgeInsets = NSEdgeInsets(top: 10, left: 16, bottom: 10, right: 16)
        stack.translatesAutoresizingMaskIntoConstraints = false
        let container = NSView(frame: NSRect(x: 0, y: 0, width: 480, height: 56))
        container.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            stack.topAnchor.constraint(equalTo: container.topAnchor),
            stack.bottomAnchor.constraint(equalTo: container.bottomAnchor),
        ])
        view = container
    }

    var isOn: Bool { check.state == .on }
}
