// AppDelegate.swift - launch sequence, menus, quitting.

import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuItemValidation {
    private var paths: AppPaths?
    /// The folders chosen in the interface when the server was started:
    /// when one changes, the server restarts on the new folders.
    private var folderChoices: [String?] = []
    /// The quit was already confirmed (or doesn't need asking: an update).
    private var quitConfirmed = false
    /// The theme last applied to the windows (see `applyTheme`).
    private var appliedTheme: String?
    private var dataWatch: Timer?
    private var updating = false
    private var server: ServerProcess?
    /// PID of a server we found already running at launch (left over from a
    /// crash) and reused instead of starting a new one.
    private var adoptedPID: pid_t?

    private var preparing: PreparingWindow?
    private var mainWindow: MainWindowController?

    private var pollTimer: Timer?
    private var pollInFlight = false
    private var startedAt = Date()
    private var ready = false
    private var quitting = false

    /// The first launch downloads uv, Python and the dependencies: several
    /// minutes on a slow connection. Give up only after this long.
    private let startupTimeout: TimeInterval = 12 * 60

    // MARK: Launch

    func applicationDidFinishLaunching(_ notification: Notification) {
        do {
            let p = try AppPaths.resolve()
            paths = p
            detectLanguage(state: p.state, data: p.data)
            applyTheme()
            // Requests left by a previous session (written while the app
            // wasn't watching) must not quit or update this one.
            for stale in ["quit-request", "update-request"] {
                try? FileManager.default.removeItem(at: p.state.appendingPathComponent(stale))
            }
        } catch {
            buildMenus()
            NSApp.activate(ignoringOtherApps: true)
            let alert = NSAlert()
            alert.alertStyle = .critical
            alert.messageText = tr("AnimeUp could not start", "AnimeUp non è riuscito ad avviarsi")
            alert.informativeText = describe(error)
            alert.addButton(withTitle: tr("Quit", "Esci"))
            alert.runModal()
            NSApp.terminate(nil)
            return
        }
        buildMenus()
        NSApp.activate(ignoringOtherApps: true)

        // A server already answering on our port is one of ours, left over
        // from a crash of the app: reuse it rather than fail on a busy port.
        checkHealth { [weak self] ok in
            guard let self else { return }
            if ok {
                self.adoptedPID = listenerPID()
                self.becameReady()
            } else {
                self.startServer()
            }
        }
    }

    private func describe(_ error: Error) -> String {
        switch error {
        case AppPaths.Failure.missingProgram(let path):
            return tr("The program files are missing from the app bundle:\n\(path)\n\nDownload AnimeUp again.",
                      "Mancano i file del programma dentro l'app:\n\(path)\n\nScarica di nuovo AnimeUp.")
        case AppPaths.Failure.cannotCreate(let path, let underlying):
            return tr("Can't create the folder\n\(path)\n\n\(underlying.localizedDescription)",
                      "Impossibile creare la cartella\n\(path)\n\n\(underlying.localizedDescription)")
        default:
            return error.localizedDescription
        }
    }

    /// Starts `animeup ui` and waits for it, showing the preparing window.
    private func startServer() {
        guard let paths else { return }
        ready = false

        let window = preparing ?? PreparingWindow()
        preparing = window
        window.show(line: tr("Starting…", "Avvio…"))
        // After a restart this sits on top of the (stale) main window.
        window.makeKeyAndOrderFront(nil)

        let proc = ServerProcess(paths: paths)
        proc.onLine = { [weak self] line in self?.preparing?.show(line: line) }
        proc.onExit = { [weak self, weak proc] how in
            guard let self, let proc, proc === self.server else { return }
            self.serverExited(how)
        }
        server = proc
        do {
            try proc.start()
        } catch {
            proc.writeLog("[app] could not start the launcher: \(error.localizedDescription)\n")
            startupFailed(title: tr("AnimeUp could not start", "AnimeUp non è riuscito ad avviarsi"),
                          lines: [error.localizedDescription])
            return
        }

        startedAt = Date()
        pollTimer?.invalidate()
        pollTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            self?.poll()
        }
    }

    private func poll() {
        guard !ready, !quitting else { return }
        if Date().timeIntervalSince(startedAt) > startupTimeout {
            pollTimer?.invalidate()
            server?.writeLog("[app] server not ready after \(Int(startupTimeout / 60)) minutes: giving up\n")
            let lines = server?.recentLines() ?? []
            let old = server
            server = nil            // its exit is expected now: no second alert
            old?.terminate()
            startupFailed(title: tr("AnimeUp is taking too long to start",
                                    "AnimeUp ci mette troppo ad avviarsi"),
                          lines: lines)
            return
        }
        guard !pollInFlight else { return }
        pollInFlight = true
        checkHealth { [weak self] ok in
            guard let self else { return }
            self.pollInFlight = false
            if ok && !self.ready && self.server?.hasExited == false {
                self.becameReady()
            }
        }
    }

    private func becameReady() {
        ready = true
        pollTimer?.invalidate()
        pollTimer = nil
        server?.writeLog("[app] server ready on \(serverURL.absoluteString)\n")

        // Main window first, then close the preparing one: closing the only
        // window would quit the app.
        if let mainWindow {
            mainWindow.reloadPage(nil)
            mainWindow.showWindow(nil)
        } else {
            let controller = MainWindowController()
            mainWindow = controller
            controller.showWindow(nil)
            controller.load()
        }
        mainWindow?.window?.makeKeyAndOrderFront(nil)
        preparing?.close()
        preparing = nil
        watchDataFolder()
    }

    // MARK: Folders and requests from the interface

    /// The interface writes a newly chosen folder to `<state>/input-folder`
    /// or `<state>/output-folder`; the server reads its folders only when it
    /// starts, so the app restarts it on the new ones. The interface also
    /// leaves requests here (install an update, quit). A look every 2 s is
    /// plenty for things done through a folder picker or a button.
    private func watchDataFolder() {
        guard let paths else { return }
        folderChoices = AppPaths.choices(state: paths.state)
        dataWatch?.invalidate()
        dataWatch = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
            guard let self, let paths = self.paths, self.ready, !self.quitting else { return }
            if AppPaths.choices(state: paths.state) != self.folderChoices {
                self.switchDataFolder(); return
            }
            // A drive that wasn't connected at launch is back: move to the
            // chosen folder, but never under a running job's feet.
            if AppPaths.cameBack(paths.unavailableInput) || AppPaths.cameBack(paths.unavailableOutput),
               RunningJobs.pids(output: paths.output).isEmpty {
                self.switchDataFolder(); return
            }
            self.checkUpdateRequest()
            self.checkQuitRequest()
            self.applyTheme()
            self.followLanguage()
        }
    }

    /// Menus and About were in the language found at launch: switching the
    /// interface to English left them in Italian until the next launch.
    private func followLanguage() {
        guard let paths else { return }
        let before = italian
        detectLanguage(state: paths.state, data: paths.data)
        if italian != before { buildMenus() }
    }

    /// Dark, Light or System, as chosen in the interface's Preferences.
    private func applyTheme() {
        guard let paths else { return }
        let theme = savedTheme(state: paths.state)
        guard theme != appliedTheme else { return }
        appliedTheme = theme
        switch theme {
        case "dark": NSApp.appearance = NSAppearance(named: .darkAqua)
        case "light": NSApp.appearance = NSAppearance(named: .aqua)
        default: NSApp.appearance = nil
        }
    }

    /// The sidebar's "Quit AnimeUp" button: the same as ⌘Q, confirmation
    /// included.
    private func checkQuitRequest() {
        guard let paths else { return }
        let request = paths.state.appendingPathComponent("quit-request")
        guard FileManager.default.fileExists(atPath: request.path) else { return }
        try? FileManager.default.removeItem(at: request)
        NSApp.terminate(nil)
    }

    // MARK: Updates

    /// The interface's "Install update" button leaves a request file; the
    /// app takes it from there (see Updater.swift for why it's done here).
    private func checkUpdateRequest() {
        guard let paths, ready, !updating else { return }
        let request = Updater.requestFile(state: paths.state)
        guard FileManager.default.fileExists(atPath: request.path) else { return }
        try? FileManager.default.removeItem(at: request)
        updating = true
        Task { @MainActor in
            await self.runUpdate()
            self.updating = false
        }
    }

    /// AnimeUp → Check for Updates…: the same flow as the interface's
    /// Install update, and an answer even when there's nothing new.
    @objc func checkForUpdates(_ sender: Any?) {
        guard !updating else { return }
        updating = true
        Task { @MainActor in
            await self.runUpdate(manual: true)
            self.updating = false
        }
    }

    @MainActor private func runUpdate(manual: Bool = false) async {
        if case .failure(let e) = Updater.replaceableLocation() { updateFailed(e); return }
        let release: Release
        do {
            release = try await Updater.latestRelease()
        } catch {
            updateFailed(error); return
        }
        guard Updater.isNewer(release.version, than: appVersion) else {
            if manual {
                NSApp.activate(ignoringOtherApps: true)
                let alert = NSAlert()
                alert.messageText = tr("AnimeUp is up to date", "AnimeUp è aggiornato")
                alert.informativeText = tr("You have the latest version (\(appVersion)).",
                                           "Hai l'ultima versione (\(appVersion)).")
                alert.addButton(withTitle: "OK")
                alert.runModal()
            } else {
                updateFailed(UpdateError.notNewer(release.version))
            }
            return
        }

        NSApp.activate(ignoringOtherApps: true)
        let ask = NSAlert()
        ask.messageText = tr("Install AnimeUp \(release.version)?", "Installare AnimeUp \(release.version)?")
        let mb = max(1, release.size / 1_000_000)
        // A job, a comparison or a calibration left running across the swap
        // would go on with the old version's code while its files are being
        // replaced: they are stopped first, and the dialog says so.
        let busy = paths.map { RunningJobs.pids(output: $0.output) + RunningJobs.background(state: $0.state) } ?? []
        var text = tr(
            "AnimeUp downloads the new version from GitHub (about \(mb) MB), checks it against the checksum published with the release, replaces itself and restarts. Your files, settings and calibration stay as they are.",
            "AnimeUp scarica la nuova versione da GitHub (circa \(mb) MB), la verifica con il checksum pubblicato nella release, si sostituisce e si riavvia. File, impostazioni e taratura restano come sono.")
        if !busy.isEmpty {
            text += "\n\n" + tr(
                "Something is running (a job, a comparison or a calibration): AnimeUp stops it before updating. A job resumes later from its last saved chunk; a calibration has to start again.",
                "C'è qualcosa in corso (una lavorazione, un confronto o una taratura): AnimeUp lo ferma prima di aggiornarsi. Una lavorazione si riprende poi dall'ultimo blocco salvato; una taratura va rifatta.")
        }
        ask.informativeText = text
        ask.addButton(withTitle: busy.isEmpty ? tr("Install and Restart", "Installa e riavvia")
                                              : tr("Stop and Install", "Ferma e installa"))
        ask.addButton(withTitle: tr("Cancel", "Annulla"))
        guard ask.runModal() == .alertFirstButtonReturn else { return }

        let window = PreparingWindow()
        window.title = "AnimeUp"
        window.show(line: tr("Downloading AnimeUp \(release.version)…", "Scarico AnimeUp \(release.version)…"))
        window.makeKeyAndOrderFront(nil)
        do {
            let work = FileManager.default.temporaryDirectory
                .appendingPathComponent("AnimeUp-update-\(UUID().uuidString)", isDirectory: true)
            try FileManager.default.createDirectory(at: work, withIntermediateDirectories: true)
            let newApp = try await Updater.download(release, into: work)
            window.show(line: tr("Installing and restarting…", "Installo e riavvio…"))
            let current = try Updater.replaceableLocation().get()
            let stillBusy = paths.map { RunningJobs.pids(output: $0.output) + RunningJobs.background(state: $0.state) } ?? []
            if !stillBusy.isEmpty {
                RunningJobs.stop(stillBusy)
                let deadline = Date().addingTimeInterval(15)
                while stillBusy.contains(where: { kill($0, 0) == 0 }) && Date() < deadline {
                    try? await Task.sleep(nanoseconds: 200_000_000)
                }
            }
            let old = try Updater.swap(current: current, with: newApp)
            server?.writeLog("[app] updated to \(release.version): restarting\n")
            Updater.relaunch(newApp: current, oldCopy: old)
            quitConfirmed = true          // anything running was stopped above
            NSApp.terminate(nil)
        } catch {
            window.orderOut(nil)
            updateFailed(error)
        }
    }

    @MainActor private func updateFailed(_ error: Error) {
        NSApp.activate(ignoringOtherApps: true)
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = tr("AnimeUp couldn't update itself", "AnimeUp non è riuscito ad aggiornarsi")
        alert.informativeText = error.localizedDescription
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: tr("Open Release Page", "Apri la pagina della release"))
        if alert.runModal() == .alertSecondButtonReturn {
            NSWorkspace.shared.open(releasesPage)
        }
    }

    private func switchDataFolder() {
        dataWatch?.invalidate()
        let old = server
        server = nil                      // its exit is expected: no alert
        old?.writeLog("[app] folders changed: restarting the server\n")
        old?.terminate()
        if let pid = adoptedPID {
            kill(pid, SIGTERM)
            adoptedPID = nil
        }
        do {
            let p = try AppPaths.resolve()
            paths = p
            detectLanguage(state: p.state, data: p.data)
        } catch {
            startupFailed(title: tr("AnimeUp could not start", "AnimeUp non è riuscito ad avviarsi"),
                          lines: [describe(error)])
            return
        }
        startServer()
    }

    // MARK: Failures

    private func serverExited(_ how: String) {
        guard !quitting else { return }
        pollTimer?.invalidate()
        let lines = server?.recentLines() ?? []
        server = nil
        if ready {
            serverStopped(lines: lines, how: how)
        } else {
            startupFailed(title: tr("AnimeUp could not start", "AnimeUp non è riuscito ad avviarsi"),
                          lines: lines)
        }
    }

    /// The launcher gave up before the server was ready.
    private func startupFailed(title: String, lines: [String]) {
        // orderOut, not close: closing the last window would quit the app.
        preparing?.orderOut(nil)
        let alert = NSAlert()
        alert.alertStyle = .critical
        alert.messageText = title
        alert.informativeText = summary(lines)
        alert.addButton(withTitle: tr("Quit", "Esci"))
        alert.addButton(withTitle: tr("Open Log", "Apri registro"))
        alert.addButton(withTitle: tr("Try Again", "Riprova"))
        while true {
            switch alert.runModal() {
            case .alertSecondButtonReturn:
                openLog(nil)                      // and keep the alert up
            case .alertThirdButtonReturn:
                startServer()
                return
            default:
                NSApp.terminate(nil)
                return
            }
        }
    }

    /// The server died while the interface was open.
    private func serverStopped(lines: [String], how: String) {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = tr("The AnimeUp server stopped (\(how))",
                               "Il server di AnimeUp si è fermato (\(how))")
        alert.informativeText = summary(lines) + "\n\n" + tr(
            "Running upscaling jobs are not affected.",
            "Le lavorazioni in corso non ne risentono.")
        alert.addButton(withTitle: tr("Restart", "Riavvia"))
        alert.addButton(withTitle: tr("Open Log", "Apri registro"))
        alert.addButton(withTitle: tr("Quit", "Esci"))
        while true {
            switch alert.runModal() {
            case .alertFirstButtonReturn:
                startServer()
                return
            case .alertSecondButtonReturn:
                openLog(nil)
            default:
                NSApp.terminate(nil)
                return
            }
        }
    }

    private func summary(_ lines: [String]) -> String {
        let tail = lines.suffix(12)
        return tail.isEmpty
            ? tr("The launcher printed nothing. Details are in the log.",
                 "Il lanciatore non ha scritto nulla. I dettagli sono nel registro.")
            : tail.joined(separator: "\n")
    }

    // MARK: Quitting

    /// Closing the window doesn't quit: AnimeUp keeps working in the
    /// background, like HandBrake, and the Dock icon brings the window back.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag {
            if let mainWindow, ready {
                mainWindow.showWindow(nil)
                mainWindow.window?.makeKeyAndOrderFront(nil)
            } else {
                preparing?.makeKeyAndOrderFront(nil)
            }
        }
        return true
    }

    /// Quitting stops the jobs too, so with one running it asks first.
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard !quitConfirmed, let paths else { return .terminateNow }
        let running = RunningJobs.pids(output: paths.output)
        let background = RunningJobs.background(state: paths.state)
        guard !running.isEmpty || !background.isEmpty else { return .terminateNow }
        NSApp.activate(ignoringOtherApps: true)
        let alert = NSAlert()
        alert.alertStyle = .warning
        if running.isEmpty {
            alert.messageText = tr("Quit AnimeUp and stop what's running?", "Uscire da AnimeUp e fermare quello che è in corso?")
            alert.informativeText = tr(
                "A calibration or a model comparison is running. Quitting stops it: a calibration saves nothing until it finishes, a comparison keeps the clips already made.\n\nTo let it finish, close the window instead.",
                "È in corso una taratura o un confronto dei modelli. Uscendo si ferma: la taratura non salva niente finché non finisce, il confronto tiene le clip già fatte.\n\nPer lasciarlo finire chiudi invece la finestra.")
            alert.addButton(withTitle: tr("Stop and Quit", "Ferma e esci"))
            alert.addButton(withTitle: tr("Cancel", "Annulla"))
            guard alert.runModal() == .alertFirstButtonReturn else { return .terminateCancel }
            RunningJobs.stop(background)
            quitConfirmed = true
            return .terminateNow
        }
        alert.messageText = tr("Quit AnimeUp and stop the job?", "Uscire da AnimeUp e fermare la lavorazione?")
        alert.informativeText = tr(
            "A job is running. Quitting stops it and the rest of the queue. The work done is saved one chunk at a time, so you can resume later and lose at most the chunk in progress.\n\nTo keep it working, close the window instead: AnimeUp carries on in the background and the Dock icon brings it back.",
            "C'è una lavorazione in corso. Uscendo si fermano lei e il resto della coda. Il lavoro fatto è salvato un blocco alla volta: potrai riprenderla perdendo al massimo il blocco in corso.\n\nPer lasciarla lavorare chiudi invece la finestra: AnimeUp continua in background e l'icona nel Dock la riapre.")
        alert.addButton(withTitle: tr("Stop Job and Quit", "Ferma e esci"))
        alert.addButton(withTitle: tr("Cancel", "Annulla"))
        guard alert.runModal() == .alertFirstButtonReturn else { return .terminateCancel }
        server?.writeLog("[app] quit with a job running: stopping it\n")
        RunningJobs.stop(running + background)
        quitConfirmed = true
        return .terminateNow
    }

    func applicationWillTerminate(_ notification: Notification) {
        quitting = true
        pollTimer?.invalidate()
        dataWatch?.invalidate()
        // Only the server here: jobs run in their own sessions, and the ones
        // to stop were stopped when the quit was confirmed.
        server?.terminate()
        if let pid = adoptedPID {
            kill(pid, SIGTERM)
            let deadline = Date().addingTimeInterval(4)
            while kill(pid, 0) == 0 && Date() < deadline {
                usleep(100_000)
            }
        }
    }

    // MARK: Menu actions

    @objc func showAbout(_ sender: Any?) {
        let credits = NSMutableAttributedString(
            string: tr("Local, offline anime upscaler for Apple Silicon.",
                       "Upscaler di anime locale e offline per Apple Silicon.") + "\n",
            attributes: [.font: NSFont.systemFont(ofSize: 11),
                         .foregroundColor: NSColor.secondaryLabelColor])
        let repo = "github.com/Interstellar0verdrive/AnimeUp"
        credits.append(NSAttributedString(string: repo, attributes: [
            .font: NSFont.systemFont(ofSize: 11),
            .link: URL(string: "https://" + repo)!]))
        let centred = NSMutableParagraphStyle()
        centred.alignment = .center
        credits.addAttribute(.paragraphStyle, value: centred,
                             range: NSRange(location: 0, length: credits.length))
        NSApp.orderFrontStandardAboutPanel(options: [
            .applicationName: "AnimeUp",
            .applicationVersion: appVersion,
            .version: "",
            .credits: credits,
        ])
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc func openInputFolder(_ sender: Any?) {
        if let folder = paths?.input { NSWorkspace.shared.open(folder) }
    }

    @objc func openOutputFolder(_ sender: Any?) {
        if let folder = paths?.output { NSWorkspace.shared.open(folder) }
    }

    @objc func openInBrowser(_ sender: Any?) {
        NSWorkspace.shared.open(serverURL)
    }

    @objc func openLog(_ sender: Any?) {
        if let log = paths?.logFile { NSWorkspace.shared.open(log) }
    }

    @objc func reloadPage(_ sender: Any?) { mainWindow?.reloadPage(sender) }
    @objc func actualSize(_ sender: Any?) { mainWindow?.actualSize(sender) }
    @objc func zoomIn(_ sender: Any?) { mainWindow?.zoomIn(sender) }
    @objc func zoomOut(_ sender: Any?) { mainWindow?.zoomOut(sender) }

    func validateMenuItem(_ item: NSMenuItem) -> Bool {
        switch item.action {
        case #selector(reloadPage(_:)), #selector(actualSize(_:)),
             #selector(zoomIn(_:)), #selector(zoomOut(_:)), #selector(openInBrowser(_:)):
            return ready && mainWindow != nil
        case #selector(openInputFolder(_:)), #selector(openOutputFolder(_:)), #selector(openLog(_:)):
            return paths != nil
        default:
            return true
        }
    }

    // MARK: Menus

    private func buildMenus() {
        let bar = NSMenu()

        // App menu (its title is replaced by the app name).
        let appMenu = submenu(in: bar, "AnimeUp")
        add(appMenu, tr("About AnimeUp", "Informazioni su AnimeUp"), #selector(showAbout(_:)), target: self)
        add(appMenu, tr("Check for Updates…", "Controlla aggiornamenti…"),
            #selector(checkForUpdates(_:)), target: self)
        appMenu.addItem(.separator())
        let services = add(appMenu, tr("Services", "Servizi"), nil)
        services.submenu = NSMenu()
        NSApp.servicesMenu = services.submenu
        appMenu.addItem(.separator())
        add(appMenu, tr("Hide AnimeUp", "Nascondi AnimeUp"), #selector(NSApplication.hide(_:)), "h")
        add(appMenu, tr("Hide Others", "Nascondi altre"),
            #selector(NSApplication.hideOtherApplications(_:)), "h", [.command, .option])
        add(appMenu, tr("Show All", "Mostra tutte"), #selector(NSApplication.unhideAllApplications(_:)))
        appMenu.addItem(.separator())
        add(appMenu, tr("Quit AnimeUp", "Esci da AnimeUp"), #selector(NSApplication.terminate(_:)), "q")

        // File
        let file = submenu(in: bar, tr("File", "Archivio"))
        add(file, tr("Open Videos to Process Folder", "Apri la cartella dei video da elaborare"),
            #selector(openInputFolder(_:)), "o", [.command, .shift], target: self)
        add(file, tr("Open Finished Videos Folder", "Apri la cartella dei video finiti"),
            #selector(openOutputFolder(_:)), "f", [.command, .shift], target: self)
        add(file, tr("Open in Browser", "Apri nel browser"), #selector(openInBrowser(_:)), "b",
            [.command, .shift], target: self)
        add(file, tr("Show Log", "Mostra registro"), #selector(openLog(_:)), target: self)
        file.addItem(.separator())
        add(file, tr("Close Window", "Chiudi finestra"), #selector(NSWindow.performClose(_:)), "w")

        // Edit: without these, copy/paste don't work in a WKWebView.
        let edit = submenu(in: bar, tr("Edit", "Composizione"))
        add(edit, tr("Undo", "Annulla"), Selector(("undo:")), "z")
        add(edit, tr("Redo", "Ripeti"), Selector(("redo:")), "z", [.command, .shift])
        edit.addItem(.separator())
        add(edit, tr("Cut", "Taglia"), #selector(NSText.cut(_:)), "x")
        add(edit, tr("Copy", "Copia"), #selector(NSText.copy(_:)), "c")
        add(edit, tr("Paste", "Incolla"), #selector(NSText.paste(_:)), "v")
        add(edit, tr("Select All", "Seleziona tutto"), #selector(NSText.selectAll(_:)), "a")

        // View
        let view = submenu(in: bar, tr("View", "Vista"))
        add(view, tr("Reload", "Ricarica"), #selector(reloadPage(_:)), "r", target: self)
        view.addItem(.separator())
        add(view, tr("Actual Size", "Dimensioni reali"), #selector(actualSize(_:)), "0", target: self)
        add(view, tr("Zoom In", "Ingrandisci"), #selector(zoomIn(_:)), "+", target: self)
        // ⌘= as well, since "+" needs Shift on many layouts.
        let zoomInAlt = add(view, tr("Zoom In", "Ingrandisci"), #selector(zoomIn(_:)), "=", target: self)
        zoomInAlt.isHidden = true
        zoomInAlt.allowsKeyEquivalentWhenHidden = true
        add(view, tr("Zoom Out", "Riduci"), #selector(zoomOut(_:)), "-", target: self)
        view.addItem(.separator())
        add(view, tr("Enter Full Screen", "Entra in modalità a tutto schermo"),
            #selector(NSWindow.toggleFullScreen(_:)), "f", [.command, .control])

        // Window
        let window = submenu(in: bar, tr("Window", "Finestra"))
        add(window, tr("Minimize", "Contrai"), #selector(NSWindow.performMiniaturize(_:)), "m")
        add(window, tr("Zoom", "Zoom"), #selector(NSWindow.performZoom(_:)))
        window.addItem(.separator())
        add(window, tr("Bring All to Front", "Porta tutto in primo piano"),
            #selector(NSApplication.arrangeInFront(_:)))
        NSApp.windowsMenu = window

        NSApp.mainMenu = bar
    }

    private func submenu(in bar: NSMenu, _ title: String) -> NSMenu {
        let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        let menu = NSMenu(title: title)
        item.submenu = menu
        bar.addItem(item)
        return menu
    }

    @discardableResult
    private func add(_ menu: NSMenu, _ title: String, _ action: Selector?, _ key: String = "",
                     _ modifiers: NSEvent.ModifierFlags = .command, target: AnyObject? = nil) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.keyEquivalentModifierMask = modifiers
        item.target = target   // nil = first responder (the web view, the window)
        menu.addItem(item)
        return item
    }
}
