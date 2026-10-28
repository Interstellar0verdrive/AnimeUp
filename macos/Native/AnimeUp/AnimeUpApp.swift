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
            CommandGroup(replacing: .newItem) {
                Button(model.t("nat.add.open")) { model.openVideos() }
                    .keyboardShortcut("o", modifiers: .command)
            }
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

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { MainActor.assumeIsolated { model?.reopenMainWindow?() } }
        return true
    }

    func applicationWillTerminate(_ notification: Notification) {
        MainActor.assumeIsolated { model?.terminateEngineNow() }
    }
}
