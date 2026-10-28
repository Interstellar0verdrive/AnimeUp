import AppKit
import Engine
import Models
import Observation
import OSLog

let log = Logger(subsystem: "io.github.interstellar0verdrive.animeup", category: "app")

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
    var folders: FoldersState?
    var tab: Tab = .start
    /// A short line under the drop zone after videos arrive (M1: no Queue yet).
    var lastReceived: Int?
    /// Set by the main window, so the Dock icon can reopen it.
    @ObservationIgnored var reopenMainWindow: (() -> Void)?
    /// Kept outside the actor so the app can signal it while quitting.
    @ObservationIgnored private(set) var enginePID: Int32?
    @ObservationIgnored private var started = false

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
        log.info("code \(self.configuration.codeFolder.path, privacy: .public), state \(self.configuration.stateFolder.path, privacy: .public)")
    }

    func t(_ key: String, _ values: [String: Any] = [:]) -> String { localizer.t(key, values) }

    // MARK: engine

    func start() {
        guard !started else { return }
        started = true
        Task { await listen() }
        Task { await launch() }
    }

    private func launch() async {
        status = .starting
        do {
            try await engine.start()
            enginePID = await engine.pid
            await loadAll(firstRun: true)
        } catch {
            log.error("engine start failed: \(String(describing: error), privacy: .public)")
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
            log.info("engine \(h.version, privacy: .public) (python \(h.python, privacy: .public), pid \(h.pid))")
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
            status = .ready
        } catch EngineError.terminated {
            // A crash while loading: the restart's `engine.started` reloads.
            log.error("engine stopped while loading")
        } catch {
            log.error("engine load failed: \(String(describing: error), privacy: .public)")
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
                }
            case "engine.started":
                enginePID = await engine.pid
                if await engine.restarts > 0 {
                    log.info("engine restarted")
                    await loadAll()
                }
            case "engine.exited":
                log.info("engine exited: \(String(data: event.data, encoding: .utf8) ?? "", privacy: .public)")
            case "engine.gave_up":
                status = .gaveUp
            default:
                log.debug("event \(event.name, privacy: .public)")
            }
        }
    }

    func refreshFolders() {
        Task { folders = try? await engine.foldersState() }
    }

    // MARK: actions

    func setLanguage(_ code: String) {
        localizer.setLanguage(code)
        Task { settings = try? await engine.setSettings(["language": code]) }
    }

    func setWorkFolder(_ url: URL) {
        Task {
            settings = try? await engine.setSettings(["work_folder": url.path])
            folders = try? await engine.foldersState()
        }
    }

    func setSpace(_ gb: Int) {
        Task { settings = try? await engine.setSettings(["disk_gb": gb]) }
    }

    func calibrate() {
        // M1: the calibration sheet comes in a later milestone.
        log.info("Calibrate pressed (calibration sheet: later milestone)")
    }

    func checkForUpdates() {
        log.info("Check for updates pressed (Sparkle: later milestone)")
    }

    func receive(_ urls: [URL]) {
        guard !urls.isEmpty else { return }
        for url in urls { log.info("video received: \(url.path, privacy: .public)") }
        lastReceived = urls.count
    }

    func openVideos() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = true
        panel.canChooseFiles = true
        panel.allowedContentTypes = [.movie, .video, .mpeg4Movie, .quickTimeMovie, .folder]
        panel.prompt = t("nat.add.open").replacingOccurrences(of: "…", with: "")
        if panel.runModal() == .OK { receive(panel.urls) }
    }

    func chooseWorkFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.message = t("nat.where.pick_work")
        if let folder = folders?.workFolder {
            panel.directoryURL = URL(fileURLWithPath: folder).deletingLastPathComponent()
        }
        if panel.runModal() == .OK, let url = panel.url { setWorkFolder(url) }
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

    func relative(_ date: Date) -> String {
        let f = RelativeDateTimeFormatter()
        f.locale = Locale(identifier: localizer.language)
        f.dateTimeStyle = .named
        f.unitsStyle = .full
        return f.localizedString(for: date, relativeTo: Date())
    }
}
