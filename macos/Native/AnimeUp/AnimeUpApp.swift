import AppKit
import DesignSystem
import SwiftUI

@main
struct AnimeUpApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @State private var model = AppModel()

    var body: some Scene {
        Window("AnimeUp", id: "main") {
            MainView()
                .environment(model)
                .preferredColorScheme(.dark)
                .onAppear {
                    delegate.model = model
                    model.start()
                    #if DEBUG
                    DebugSnapshot.scheduleIfAsked(model: model)
                    #endif
                }
        }
        .defaultSize(width: 1360, height: 840)
        .windowResizability(.contentMinSize)
        .windowStyle(.hiddenTitleBar)
        .commands {
            SidebarCommands()
            AppCommands(model: model)
        }

        Settings {
            SettingsView()
                .environment(model)
                .preferredColorScheme(.dark)
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var model: AppModel?

    func applicationWillFinishLaunching(_ notification: Notification) {
        // Dark first: light screens come once the dark ones are approved.
        NSApp.appearance = NSAppearance(named: .darkAqua)
    }

    /// The red button closes the window; the app keeps running. ⌘Q quits.
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        MainActor.assumeIsolated {
            log.info("applicationShouldTerminate, jobRunning=\(model?.jobRunning ?? false)")
            guard let model, model.jobRunning else { return .terminateNow }
            return model.confirmQuitWhileRunning() ? .terminateNow : .terminateCancel
        }
    }

    /// The Dock icon menu (O7): Open Videos…, and Pause / Stop All while a queue runs.
    func applicationDockMenu(_ sender: NSApplication) -> NSMenu? {
        MainActor.assumeIsolated {
            guard let model else { return nil }
            let menu = NSMenu()
            menu.addItem(DockAction(model.t("nat.add.open")) { model.openVideos() })
            if model.progress.queue.running {
                menu.addItem(.separator())
                let paused = model.progress.queue.paused
                menu.addItem(DockAction(model.t(paused ? "nat.run.resume" : "nat.run.pause")) {
                    model.command(paused ? "queue.resume" : "queue.pause")
                })
                menu.addItem(DockAction(model.t("nat.run.stop_all")) { model.confirmStopAll() })
            }
            return menu
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { MainActor.assumeIsolated { model?.reopenMainWindow?() } }
        return true
    }

    func applicationWillTerminate(_ notification: Notification) {
        MainActor.assumeIsolated { model?.terminateEngineNow() }
    }
}


/// A menu item that runs a closure.
final class DockAction: NSMenuItem {
    private let run: @MainActor () -> Void

    init(_ title: String, _ run: @escaping @MainActor () -> Void) {
        self.run = run
        super.init(title: title, action: #selector(fire), keyEquivalent: "")
        target = self
    }

    required init(coder: NSCoder) { fatalError() }

    @objc private func fire() { MainActor.assumeIsolated { run() } }
}
