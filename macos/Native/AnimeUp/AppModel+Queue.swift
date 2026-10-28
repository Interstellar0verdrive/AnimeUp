import AppKit
import Engine
import Models

enum PanelTab: String { case analysis, processing }

/// Native alerts the app shows (boards O2, O6).
struct AppAlert: Identifiable, CustomStringConvertible {
    var description: String { "\(kind)" }
    enum Kind {
        case noVideos(folder: String, subfoldersIncluded: Bool, paths: [String])
        case workNotWritable(folder: String)
        case workInsideFinished(folder: String)
        case changeAfterQueue
        case info(title: String, text: String)
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
        if let e = expanded, !ids.contains(e) { expanded = nil }
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

    /// Ticked files' estimate, in seconds.
    var selectionEstimate: Double {
        files.filter { isTicked($0) }.compactMap { plans[$0.id]?.estimate }.reduce(0, +)
    }

    /// Short model name: catalog label without "Real-ESRGAN " / "Real-".
    func shortModel(_ key: String) -> String {
        let k = "mot.modello.\(key).label"
        let label = localizer.has(k) ? t(k) : key
        return label.hasPrefix("Real-ESRGAN ") ? String(label.dropFirst(12))
            : label.hasPrefix("Real-") ? String(label.dropFirst(5)) : label
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
                    lastReceived = result.added.count
                    tab = .queue
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
        add(back.map(\.url), subfolders: false)
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

    func isTicked(_ f: QueueFile) -> Bool { f.state == .ready && !unticked.contains(f.id) }

    var analysingCount: Int { files.filter { $0.state == .analysing || $0.state == .queued }.count }
    var warningCount: Int { files.filter { !$0.warnings.isEmpty }.count }

    /// "5 files · 1 analysing" for the sidebar.
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
        setWorkFolder(url)
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
