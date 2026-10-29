import AppKit
import DesignSystem
import SwiftUI

/// Gives the main window the boards' frame: no title bar of its own, the
/// content under it, and the real traffic lights moved into the
/// `TrafficLightsSlot` the page reports (the sidebar's top row, or the top
/// bar when the sidebar is folded).
struct WindowChrome: NSViewRepresentable {
    /// The slot in window coordinates, top-left origin.
    var anchor: CGRect?
    /// Called when the window closes (the red button or ⌘W): the app keeps running.
    var onClose: () -> Void = {}

    func makeNSView(context: Context) -> ChromeView { ChromeView() }

    func updateNSView(_ view: ChromeView, context: Context) {
        view.anchor = anchor
        view.onClose = onClose
        view.placeLights()
    }

    final class ChromeView: NSView {
        var anchor: CGRect?
        var onClose: () -> Void = {}
        private var observers: [NSObjectProtocol] = []

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            observers.forEach(NotificationCenter.default.removeObserver)
            observers = []
            guard let window else { return }
            window.titlebarAppearsTransparent = true
            window.titleVisibility = .hidden
            window.styleMask.insert(.fullSizeContentView)
            window.isMovableByWindowBackground = false
            window.minSize = AUChrome.minWindow
            #if DEBUG
            // ANIMEUP_WINDOW=1000x680: open at that size, to check the layout at other sizes.
            if let spec = ProcessInfo.processInfo.environment["ANIMEUP_WINDOW"],
               case let parts = spec.split(separator: "x").compactMap({ Double($0) }), parts.count == 2 {
                // After the window's saved frame has been restored.
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                    window.setContentSize(NSSize(width: parts[0], height: parts[1]))
                }
            }
            #endif
            // AppKit lays the title bar out again on these: put the buttons back each time.
            let names: [Notification.Name] = [NSWindow.didResizeNotification, NSWindow.didBecomeKeyNotification,
                                              NSWindow.didResignKeyNotification, NSWindow.didExitFullScreenNotification,
                                              NSWindow.didChangeScreenNotification]
            for name in names {
                observers.append(NotificationCenter.default.addObserver(forName: name, object: window, queue: .main) { [weak self] _ in
                    MainActor.assumeIsolated { self?.placeLights() }
                })
            }
            observers.append(NotificationCenter.default.addObserver(forName: NSWindow.willCloseNotification, object: window, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.onClose() }
            })
            placeLights()
        }

        /// Centres the three buttons in the slot, 20 pt apart (the boards' 12 pt dots, 8 pt gaps).
        func placeLights() {
            guard let window, let anchor, !window.styleMask.contains(.fullScreen) else { return }
            let kinds: [NSWindow.ButtonType] = [.closeButton, .miniaturizeButton, .zoomButton]
            let contentHeight = window.contentView?.bounds.height ?? window.frame.height
            growTitleBar(window, toCover: anchor.maxY + 6, contentHeight: contentHeight)
            for (i, kind) in kinds.enumerated() {
                guard let button = window.standardWindowButton(kind), let parent = button.superview else { continue }
                let centre = NSPoint(x: anchor.minX + 10 + CGFloat(i) * 20, y: contentHeight - anchor.midY)
                let local = parent.convert(centre, from: nil)
                button.setFrameOrigin(NSPoint(x: (local.x - button.frame.width / 2).rounded(),
                                              y: (local.y - button.frame.height / 2).rounded()))
            }
        }

        /// The buttons live in the title bar view, about 28 pt tall. Moved lower than
        /// that, half of each button fell outside it: clicks and hover only worked on
        /// its top part. The title bar (and its container) grows to reach the slot.
        private func growTitleBar(_ window: NSWindow, toCover height: CGFloat, contentHeight: CGFloat) {
            guard let titleBar = window.standardWindowButton(.closeButton)?.superview,
                  let container = titleBar.superview else { return }
            let needed = ceil(height)
            guard abs(container.frame.height - needed) > 0.5 || abs(titleBar.frame.height - needed) > 0.5 else { return }
            var frame = container.frame
            frame.origin.y = frame.maxY - needed
            frame.size.height = needed
            container.frame = frame
            titleBar.frame = container.bounds
        }

        deinit { observers.forEach(NotificationCenter.default.removeObserver) }
    }
}
