// Windows.swift - the "Preparing AnimeUp..." window and the main web window.

import AppKit
import WebKit

/// AnimeUp's page background (#101113 dark, #F6F7F9 light): used behind the
/// web view so there's no flash of the wrong colour while the page loads. It
/// follows the window's appearance, which follows the theme chosen in the
/// interface (System, Dark, Light).
let pageBackground = NSColor(name: "AnimeUpPage") { appearance in
    appearance.bestMatch(from: [.darkAqua, .aqua]) == .aqua
        ? NSColor(srgbRed: 0xF6 / 255.0, green: 0xF7 / 255.0, blue: 0xF9 / 255.0, alpha: 1)
        : NSColor(srgbRed: 0x10 / 255.0, green: 0x11 / 255.0, blue: 0x13 / 255.0, alpha: 1)
}

// MARK: - Preparing window

/// Small window shown while the launcher sets things up and the server starts.
final class PreparingWindow: NSWindow {
    private let detail = NSTextField(labelWithString: "")
    private let spinner = NSProgressIndicator()

    init() {
        super.init(contentRect: NSRect(x: 0, y: 0, width: 460, height: 150),
                   styleMask: [.titled, .closable], backing: .buffered, defer: false)
        title = "AnimeUp"
        isReleasedWhenClosed = false
        appearance = NSAppearance(named: .darkAqua)

        let heading = NSTextField(labelWithString: tr("Preparing AnimeUp…", "Preparo AnimeUp…"))
        heading.font = .systemFont(ofSize: 15, weight: .semibold)

        spinner.style = .bar
        spinner.isIndeterminate = true
        spinner.controlSize = .regular
        spinner.startAnimation(nil)

        detail.stringValue = tr("Starting…", "Avvio…")
        detail.font = .systemFont(ofSize: 12)
        detail.textColor = .secondaryLabelColor
        detail.lineBreakMode = .byTruncatingTail
        detail.maximumNumberOfLines = 1
        detail.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)

        let hint = NSTextField(labelWithString: tr(
            "The first launch downloads what AnimeUp needs and can take a few minutes.",
            "Il primo avvio scarica ciò che serve ad AnimeUp e può richiedere qualche minuto."))
        hint.font = .systemFont(ofSize: 11)
        hint.textColor = .tertiaryLabelColor
        hint.lineBreakMode = .byWordWrapping
        hint.maximumNumberOfLines = 2
        hint.preferredMaxLayoutWidth = 412

        let stack = NSStackView(views: [heading, spinner, detail, hint])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 10
        stack.edgeInsets = NSEdgeInsets(top: 20, left: 24, bottom: 20, right: 24)
        stack.translatesAutoresizingMaskIntoConstraints = false

        let content = NSView()
        content.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            stack.topAnchor.constraint(equalTo: content.topAnchor),
            stack.bottomAnchor.constraint(equalTo: content.bottomAnchor),
            spinner.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -48),
            detail.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -48),
            hint.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -48),
        ])
        contentView = content
        setContentSize(content.fittingSize)
        center()
    }

    /// Shows the latest launcher message ("Downloading uv…").
    func show(line: String) {
        detail.stringValue = line
        detail.toolTip = line
    }
}

// MARK: - Main window

/// The main window: a WKWebView on the local server.
/// The page's way to ask the app for native things (`window.webkit.
/// messageHandlers.animeup`). A separate object holding the controller
/// weakly: WebKit retains its handlers.
private final class PageBridge: NSObject, WKScriptMessageHandler {
    weak var owner: MainWindowController?
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        owner?.pageAsked(message.body)
    }
}

final class MainWindowController: NSWindowController, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    let webView: WKWebView
    private static let zoomKey = "pageZoom"
    /// Where the chosen folder is handed to the server (`folder-choice.json`).
    private let stateDir: URL?
    private let bridge = PageBridge()

    init(stateDir: URL?) {
        self.stateDir = stateDir
        let config = WKWebViewConfiguration()
        config.userContentController.add(bridge, name: "animeup")
        config.preferences.isElementFullscreenEnabled = true
        config.websiteDataStore = .default()   // Streamlit keeps a little state in localStorage
        webView = WKWebView(frame: .zero, configuration: config)
        webView.allowsBackForwardNavigationGestures = false
        webView.allowsMagnification = true
        webView.underPageBackgroundColor = pageBackground
        let saved = UserDefaults.standard.double(forKey: Self.zoomKey)
        webView.pageZoom = saved > 0 ? saved : 1.0

        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1440, height: 900),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable],
                              backing: .buffered, defer: false)
        window.title = "AnimeUp"
        window.minSize = NSSize(width: 1000, height: 700)
        window.backgroundColor = pageBackground
        // No fixed appearance here: the window follows the app's, which
        // `applyTheme` sets from the interface's choice. Forced to dark, the
        // page always saw a dark system and "System" never followed macOS
        // (reported by the user).
        window.tabbingMode = .disallowed
        window.isReleasedWhenClosed = false
        window.contentView = webView

        // Default size on first launch, clamped to the screen; afterwards
        // the frame the user left it with.
        if let visible = NSScreen.main?.visibleFrame {
            let size = NSSize(width: min(1440, visible.width), height: min(900, visible.height))
            window.setContentSize(size)
        }
        window.center()
        window.setFrameAutosaveName("AnimeUpMainWindow")

        super.init(window: window)
        bridge.owner = self
        webView.navigationDelegate = self
        webView.uiDelegate = self
    }

    /// "Change…" next to a folder: the native panel, as a sheet of this
    /// window. The script-run picker the server used belonged to a background
    /// process: it floated above every app and AnimeUp stayed active, so
    /// Finder shortcuts like ⌘↑ didn't work.
    func pageAsked(_ body: Any) {
        guard let request = body as? [String: Any],
              let which = request["pick"] as? String, ["input", "output"].contains(which),
              let window, let stateDir else { return }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        panel.message = request["prompt"] as? String ?? ""
        panel.prompt = tr("Choose", "Scegli")
        if let start = request["start"] as? String, !start.isEmpty {
            panel.directoryURL = URL(fileURLWithPath: start, isDirectory: true)
        }
        panel.beginSheetModal(for: window) { [weak self] response in
            guard response == .OK, let url = panel.url, let self else { return }
            let choice = ["which": which, "path": url.path]
            guard let data = try? JSONSerialization.data(withJSONObject: choice) else { return }
            try? data.write(to: stateDir.appendingPathComponent("folder-choice.json"), options: .atomic)
            self.webView.evaluateJavaScript("window.auCartellaScelta && window.auCartellaScelta()")
        }
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    func load() {
        webView.load(URLRequest(url: serverURL))
    }

    // MARK: Zoom (View menu)

    func setZoom(_ z: CGFloat) {
        let clamped = min(max(z, 0.5), 3.0)
        webView.pageZoom = clamped
        UserDefaults.standard.set(Double(clamped), forKey: Self.zoomKey)
    }

    @objc func actualSize(_ sender: Any?) { setZoom(1.0) }
    @objc func zoomIn(_ sender: Any?) { setZoom(webView.pageZoom * 1.1) }
    @objc func zoomOut(_ sender: Any?) { setZoom(webView.pageZoom / 1.1) }
    @objc func reloadPage(_ sender: Any?) {
        if webView.url == nil { load() } else { webView.reload() }
    }

    // MARK: Links: ours stay here, everything else opens in the browser

    static func isLocal(_ url: URL) -> Bool {
        guard let scheme = url.scheme?.lowercased() else { return true }
        switch scheme {
        case "http", "https", "ws", "wss":
            return localHosts.contains(url.host?.lowercased() ?? "")
        case "about", "data", "blob", "javascript":
            return true
        default:
            return false   // mailto:, file:, custom schemes: let macOS handle them
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { return decisionHandler(.allow) }
        if !Self.isLocal(url) {
            // Only user-initiated or top-level navigations go to the browser;
            // a third-party iframe trying to load something is just blocked.
            if action.targetFrame?.isMainFrame != false {
                NSWorkspace.shared.open(url)
            }
            return decisionHandler(.cancel)
        }
        if action.shouldPerformDownload {
            return decisionHandler(.download)
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        // Anything the web view can't display (a file served for download)
        // is saved instead of failing silently.
        decisionHandler(response.canShowMIMEType ? .allow : .download)
    }

    /// `target=_blank` and `window.open`: external URLs go to the browser,
    /// local ones load in this same window (there are no app tabs).
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url {
            if Self.isLocal(url) {
                webView.load(action.request)
            } else {
                NSWorkspace.shared.open(url)
            }
        }
        return nil
    }

    /// The web content process died (memory pressure, crash): reload.
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        load()
    }

    /// Page failed to load at all (server momentarily away): retry shortly.
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
                 withError error: Error) {
        let code = (error as NSError).code
        if code == NSURLErrorCancelled { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in self?.load() }
    }

    // MARK: JavaScript panels

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "OK")
        present(alert) { _ in completionHandler() }
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: tr("Cancel", "Annulla"))
        present(alert) { completionHandler($0 == .alertFirstButtonReturn) }
    }

    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String,
                 defaultText: String?, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping (String?) -> Void) {
        let alert = NSAlert()
        alert.messageText = prompt
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 300, height: 24))
        field.stringValue = defaultText ?? ""
        alert.accessoryView = field
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: tr("Cancel", "Annulla"))
        present(alert) { completionHandler($0 == .alertFirstButtonReturn ? field.stringValue : nil) }
    }

    /// `<input type=file>` (st.file_uploader).
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.canChooseFiles = true
        if let window {
            panel.beginSheetModal(for: window) { completionHandler($0 == .OK ? panel.urls : nil) }
        } else {
            completionHandler(panel.runModal() == .OK ? panel.urls : nil)
        }
    }

    private func present(_ alert: NSAlert, then: @escaping (NSApplication.ModalResponse) -> Void) {
        if let window {
            alert.beginSheetModal(for: window, completionHandler: then)
        } else {
            then(alert.runModal())
        }
    }

    // MARK: Downloads -> ~/Downloads

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        download.delegate = self
    }

    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        download.delegate = self
    }

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse,
                  suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let fm = FileManager.default
        let folder = fm.urls(for: .downloadsDirectory, in: .userDomainMask).first
            ?? fm.homeDirectoryForCurrentUser
        let name = (suggestedFilename as NSString).lastPathComponent
        let base = (name as NSString).deletingPathExtension
        let ext = (name as NSString).pathExtension
        var target = folder.appendingPathComponent(name)
        var n = 2
        while fm.fileExists(atPath: target.path) {
            target = folder.appendingPathComponent(ext.isEmpty ? "\(base) \(n)" : "\(base) \(n).\(ext)")
            n += 1
        }
        completionHandler(target)
    }

    func downloadDidFinish(_ download: WKDownload) {}
}
