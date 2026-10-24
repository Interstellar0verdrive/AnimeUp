// AppDelegate.swift - launch sequence, menus, quitting.

import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuItemValidation {
    private var paths: AppPaths?
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
            detectLanguage(data: p.data)
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

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        quitting = true
        pollTimer?.invalidate()
        // Only the server: upscaling jobs run in their own sessions and are
        // left alone.
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
        let credits = NSAttributedString(
            string: tr("Local, offline anime upscaler for Apple Silicon.",
                       "Upscaler di anime locale e offline per Apple Silicon."),
            attributes: [.font: NSFont.systemFont(ofSize: 11),
                         .foregroundColor: NSColor.secondaryLabelColor])
        NSApp.orderFrontStandardAboutPanel(options: [
            .applicationName: "AnimeUp",
            .applicationVersion: appVersion,
            .version: "",
            .credits: credits,
        ])
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc func openDataFolder(_ sender: Any?) {
        if let data = paths?.data { NSWorkspace.shared.open(data) }
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
        case #selector(openDataFolder(_:)), #selector(openLog(_:)):
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
        add(file, tr("Open Data Folder", "Apri cartella dati"), #selector(openDataFolder(_:)), "o",
            [.command, .shift], target: self)
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
