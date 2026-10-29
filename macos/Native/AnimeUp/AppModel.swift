import AppKit
import Engine
import Models
import Observation
import OSLog

/// The app's log: the unified log plus `<state>/records/app.log` (one line per
/// entry), so it can be read without Console.
struct AppLog: @unchecked Sendable {
    private let logger = Logger(subsystem: "io.github.interstellar0verdrive.animeup", category: "app")
    private let lock = NSLock()
    var file: URL?

    func info(_ s: String) { write("INFO", s); logger.info("\(s, privacy: .public)") }
    func error(_ s: String) { write("ERROR", s); logger.error("\(s, privacy: .public)") }
    func debug(_ s: String) { logger.debug("\(s, privacy: .public)") }

    private func write(_ level: String, _ s: String) {
        guard let file else { return }
        lock.lock(); defer { lock.unlock() }
        let line = "\(ISO8601DateFormatter().string(from: Date())) \(level) \(s)\n"
        if let h = try? FileHandle(forWritingTo: file) {
            h.seekToEndOfFile(); h.write(Data(line.utf8)); try? h.close()
        } else {
            try? FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
            try? Data(line.utf8).write(to: file)
        }
    }
}

nonisolated(unsafe) var log = AppLog()

enum Tab: String, CaseIterable, Identifiable {
    case start, compare, queue
    var id: String { rawValue }
}

/// Everything the windows show, fed by the engine.
@MainActor
@Observable
final class AppModel {
    enum EngineStatus: Equatable {
        case starting
        case ready
        case failed(String)
        case gaveUp
    }

    let configuration: EngineConfiguration
    let engine: EngineClient
    let localizer: Localizer

    var status: EngineStatus = .starting
    var hello: EngineHello?
    var settings: EngineSettings?
    var machine: MachineInfo?
    var calibration: CalibrationState?
    var tools: ToolsStatus?
    var folders: FoldersState? { didSet { if folders != oldValue { checkWorkDisk(was: oldValue) } } }
    var tab: Tab = .start
    /// The sidebar as the person set it from View, in a wide window; nil keeps it shown.
    var sidebarChoice: Bool?
    /// The window is narrower than `AUChrome.collapseBelow`: no sidebar, the top bar instead.
    var sidebarNarrow = false
    /// Whether the sidebar is on screen now (set by the window frame).
    var sidebarShown = true

    /// View › Show/Hide Sidebar and the top bar's button; a narrow window has no sidebar.
    func toggleSidebar() {
        guard !sidebarNarrow else { return }
        sidebarChoice = !sidebarShown
    }

    // Queue (M3)
    var files: [QueueFile] = []
    var activity = FilesActivity()
    /// Rows the user unticked (the checkbox column): every analysed file
    /// is ticked unless it's here.
    var unticked: Set<String> = []
    /// Finished files put back in the Queue with Redo (F6d), and those whose new video
    /// replaces the one made, once the user said Overwrite (F6e).
    var redo: Set<String> = []
    var redoConfirmed: Set<String> = []
    /// Selected rows (List selection: context menu, ⌫).
    var selection: Set<String> = []
    /// The Queue rows whose drawer is open: as many as you like.
    var openRows: Set<String> = []
    /// Opening a row from elsewhere (Start, Compare, the sidebar) adds it to the open
    /// ones; nil closes them all.
    var expanded: String? {
        get { openRows.first }
        set { if let id = newValue { openRows.insert(id) } else { openRows = [] } }
    }
    /// Each open drawer's tab; a row not listed opens on the first, Processing.
    var panelTabs: [String: PanelTab] = [:]
    /// Debug snapshots set it for every row at once.
    var panelTab: PanelTab {
        get { panelTabs.values.first ?? .processing }
        set { for id in files.map(\.id) { panelTabs[id] = newValue } }
    }
    func panelTab(for id: String) -> PanelTab { panelTabs[id] ?? .processing }
    var alert: AppAlert?
    var undoRemoved: [QueueFile] = []
    // Compare (M8–M9)
    var cmp = CompareState()
    // Queue run (M5–M7)
    var progress = QueueProgress()
    var calRun: CalibrationRun?
    var showCalibration = false
    /// Board K4: the calibration results sheet, and what it shows.
    var showCalibrationDetails = false
    var calDetails: CalibrationDetails?
    var finished: [String: JSONValue]?
    /// The person stopped the queue (Stop, Stop All): its end needs no summary unless something finished or failed.
    var stoppedByUser = false
    var showFinished = false
    @ObservationIgnored var lastJobStates: [String: QueueProgress.Job.State] = [:]
    // Plans (M4)
    var plans: [String: FilePlan] = [:]
    var calibratedWhen: Double?
    /// ST5: an interrupted file that started with other values.
    var pausedRecipe: QueueProgress.Recipe?
    var includeSubfolders: Bool = UserDefaults.standard.bool(forKey: "includeSubfolders") {
        didSet { UserDefaults.standard.set(includeSubfolders, forKey: "includeSubfolders") }
    }

    // Tools (M2)
    var tools2 = ToolsSetupState()
    var updates: UpdatesState?
    var defaults: EngineSettings?
    /// While a queue runs, settings are locked (M5 sets it).
    var jobRunning = false
    /// A short line under the drop zone after videos arrive (M1: no Queue yet).
    var lastReceived: Int?
    /// Set by the main window, so the Dock icon can reopen it.
    @ObservationIgnored var reopenMainWindow: (() -> Void)?
    /// Kept outside the actor so the app can signal it while quitting.
    @ObservationIgnored private(set) var enginePID: Int32?
    @ObservationIgnored private var started = false
    @ObservationIgnored var refreshPending = false

    init() {
        #if DEBUG
        let debug = true
        #else
        let debug = false
        #endif
        configuration = EngineConfiguration.standard(debug: debug)
        engine = EngineClient(configuration: configuration)
        let firstLanguage = Self.savedLanguage(in: configuration.stateFolder) ?? Localizer.systemLanguage()
        localizer = Localizer(folder: configuration.localesFolder, language: firstLanguage)
        log.file = configuration.stateFolder.appendingPathComponent("records/app.log")
        log.info("code \(self.configuration.codeFolder.path), state \(self.configuration.stateFolder.path)")
    }

    static var appVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "2.0"
    }

    func t(_ key: String, _ values: [String: Any] = [:]) -> String { localizer.t(key, values) }

    // MARK: engine

    func start() {
        guard !started else { return }
        started = true
        prepareToolsWindowIfFirstLaunch()
        Task { await listen() }
        Task { await launch() }
        // A disk coming or going changes where the work folder stands (O1).
        let center = NSWorkspace.shared.notificationCenter
        for name in [NSWorkspace.didMountNotification, NSWorkspace.didUnmountNotification] {
            center.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.refreshFolders() }
            }
        }
    }

    private func launch() async {
        status = .starting
        do {
            try await engine.start()
            enginePID = await engine.pid
            await loadAll(firstRun: true)
        } catch {
            log.error("engine start failed: \(String(describing: error))")
            status = .failed(String(describing: error))
        }
    }

    func retry() {
        Task {
            await engine.stop()
            try? await Task.sleep(for: .milliseconds(300))
            await launch()
        }
    }

    /// The first request waits for Python to be ready (on the very first
    /// launch the launcher downloads it with uv, which can take a while).
    func loadAll(firstRun: Bool = false) async {
        do {
            let h = try await engine.hello()
            hello = h
            log.info("engine \(h.version) (python \(h.python), pid \(h.pid))")
            if firstRun, Self.savedLanguage(in: configuration.stateFolder) == nil {
                // First launch: the language follows macOS (English or Italian).
                settings = try? await engine.setSettings(["language": localizer.language])
            }
            async let s = engine.settings()
            async let m = engine.machineInfo()
            async let c = engine.calibrationState()
            async let tl = engine.toolsStatus()
            async let f = engine.foldersState()
            let (settings, machine, calibration, tools, folders) = try await (s, m, c, tl, f)
            self.settings = settings
            self.machine = machine
            self.calibration = calibration
            self.tools = tools
            self.folders = folders
            localizer.setLanguage(settings.language)
            followLanguage(settings.language)
            defaults = try? await engine.defaults()
            updates = try? await engine.updatesState()
            await refreshFiles()
            if let p = try? await engine.queueStatus() { applyProgress(p) }
            calRun = try? await engine.calibrationRun()
            decideTools(tools)
            status = .ready
            if firstRun { afterLaunch() }
        } catch EngineError.terminated {
            // A crash while loading: the restart's `engine.started` reloads.
            log.error("engine stopped while loading")
        } catch {
            log.error("engine load failed: \(String(describing: error))")
            status = .failed(String(describing: error))
        }
    }

    private func listen() async {
        for await event in engine.events {
            switch event.name {
            case "settings.changed":
                if let s = try? event.decode(EngineSettings.self) {
                    settings = s
                    localizer.setLanguage(s.language)
                    followLanguage(s.language)
                }
            case "engine.started":
                enginePID = await engine.pid
                if await engine.restarts > 0 {
                    log.info("engine restarted")
                    await loadAll()
                }
            case "engine.exited":
                log.info("engine exited: \(String(data: event.data, encoding: .utf8) ?? "")")
            case "engine.gave_up":
                status = .gaveUp
            case "tools.progress":
                if let p = try? event.decode(ToolProgress.self) { toolProgress(p) }
            case "tools.done":
                await toolsFinished()
            case "queue.progress":
                if let p = try? event.decode(QueueProgress.self) { applyProgress(p) }
            case "queue.finished":
                if let r = try? event.decode(LaunchRecord.self) { queueFinished(r.launch) }
            case "compare.scan.progress":
                if let d = try? JSONSerialization.jsonObject(with: event.data) as? [String: Any] {
                    cmp.scanning = true
                    if let text = d["text"] as? String, !text.isEmpty { cmp.scanText = text }
                }
            case "compare.scan.done":
                if let c = try? event.decode(CompareClips.self), c.id == cmp.fileId {
                    cmp.scanning = false
                    cmp.scanError = nil
                    applyClips(c)
                }
            case "compare.scan.failed":
                if let d = try? JSONSerialization.jsonObject(with: event.data) as? [String: Any] {
                    cmp.scanning = false
                    cmp.scanError = d["error"] as? String
                }
            case "compare.progress":
                if let st = try? event.decode(CompareStatus.self) { applyCompareStatus(st) }
            case "calibration.progress":
                if let c = try? event.decode(CalibrationRun.self) { calRun = c }
            case "calibration.changed":
                if let c = try? event.decode(CalibrationState.self) { calibration = c; await refreshPlans() }
            case "file.added", "files.changed", "analysis.started", "analysis.done",
                 "analysis.failed", "analysis.progress":
                scheduleFilesRefresh()
            default:
                log.debug("event \(event.name)")
            }
        }
    }

    func refreshFolders() {
        Task { folders = try? await engine.foldersState() }
    }

    // MARK: actions

    func setLanguage(_ code: String) {
        localizer.setLanguage(code)
        followLanguage(code)
        Task { settings = try? await engine.setSettings(["language": code]) }
    }

    /// macOS names its own menu items (About, Services, Hide…) in the app's language
    /// from the next launch on: AnimeUp's choice, not only the system's.
    func followLanguage(_ code: String) {
        if UserDefaults.standard.stringArray(forKey: "AppleLanguages")?.first != code {
            UserDefaults.standard.set([code], forKey: "AppleLanguages")
        }
    }

    /// The standard About panel, with a link to the project under the version.
    func showAbout() {
        let link = "https://github.com/Interstellar0verdrive/AnimeUp"
        let credits = NSMutableAttributedString(string: "github.com/Interstellar0verdrive/AnimeUp", attributes: [
            .link: URL(string: link)!, .font: NSFont.systemFont(ofSize: NSFont.smallSystemFontSize),
        ])
        let centred = NSMutableParagraphStyle(); centred.alignment = .center
        credits.addAttribute(.paragraphStyle, value: centred, range: NSRange(location: 0, length: credits.length))
        NSApp.orderFrontStandardAboutPanel(options: [.credits: credits])
        NSApp.activate()
    }

    func setWorkFolder(_ url: URL) {
        Task {
            settings = try? await engine.setSettings(["work_folder": url.path])
            folders = try? await engine.foldersState()
        }
    }

    /// nil puts finished videos next to the originals again.
    func setFinishedFolder(_ url: URL?) {
        Task {
            settings = try? await engine.setSettings(["finished_folder": url?.path ?? ""])
            folders = try? await engine.foldersState()
        }
    }

    func chooseFinishedFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.message = t("nat.where.pick_finished")
        if let folder = folders?.finishedFolder { panel.directoryURL = URL(fileURLWithPath: folder) }
        if panel.runModal() == .OK, let url = panel.url { setFinishedFolder(url) }
    }

    func setSpace(_ gb: Int) {
        Task { settings = try? await engine.setSettings(["disk_gb": gb]) }
    }

    /// The sidebar footer's button is spinning while this runs.
    var checkingUpdates = false

    func receive(_ urls: [URL]) { add(urls) }

    func openVideos() { openVideosPanel() }

    func chooseWorkFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.message = t("nat.where.pick_work")
        if let folder = folders?.workFolder {
            panel.directoryURL = URL(fileURLWithPath: folder).deletingLastPathComponent()
        }
        if panel.runModal() == .OK, let url = panel.url { validateAndSetWorkFolder(url) }
    }

    func showLog() {
        NSWorkspace.shared.open(configuration.logFile)
    }

    /// Quitting: the engine goes with the app, right away.
    func terminateEngineNow() {
        if let pid = enginePID { kill(-pid, SIGTERM) }
    }

    // MARK: helpers

    static func savedLanguage(in state: URL) -> String? {
        let file = state.appendingPathComponent("records/settings.json")
        guard let data = try? Data(contentsOf: file),
              let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        return dict["language"] as? String
    }

    /// "29 Oct 2026 at 00:58", in the app's language.
    func dateTime(_ date: Date) -> String {
        date.formatted(Date.FormatStyle(date: .abbreviated, time: .shortened).locale(Locale(identifier: localizer.language)))
    }

    /// "29 Oct 2026".
    func dateOnly(_ date: Date) -> String {
        date.formatted(Date.FormatStyle(date: .abbreviated, time: .omitted).locale(Locale(identifier: localizer.language)))
    }

    func relative(_ date: Date) -> String {
        let f = RelativeDateTimeFormatter()
        f.locale = Locale(identifier: localizer.language)
        f.dateTimeStyle = .named
        f.unitsStyle = .full
        return f.localizedString(for: date, relativeTo: Date())
    }
}
