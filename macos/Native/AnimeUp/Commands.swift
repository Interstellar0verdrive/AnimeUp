import AppKit
import SwiftUI

/// Board O7: the menu bar. Every button in the window has its command here;
/// items that don't apply are dimmed, not hidden.
struct AppCommands: Commands {
    var model: AppModel
    @Environment(\.openWindow) private var openWindow

    var body: some Commands {
        // ⌘Q also when a sheet is open: close the sheets first, then quit
        // (the O2 alert still comes when a job runs).
        CommandGroup(replacing: .appTermination) {
            Button(model.t("nat.menu.quit")) { model.quitApp() }
                .keyboardShortcut("q", modifiers: .command)
        }
        // About with the project's link under the version (the standard panel's credits).
        CommandGroup(replacing: .appInfo) {
            Button { model.showAbout() } label: { Label(model.t("nat.menu.about"), systemImage: "info.circle") }
        }
        CommandGroup(after: .appInfo) {
            Button { model.checkForUpdates() } label: {
                Label(model.t("nat.menu.check_updates"), systemImage: "arrow.down.circle")
            }
            Button { model.calibrate() } label: { Label(model.t("nat.menu.calibrate"), systemImage: "gauge.medium") }
                .disabled(model.calRun?.running == true)
        }
        CommandGroup(replacing: .newItem) {
            Button(model.t("nat.add.open")) { model.openVideos() }
                .keyboardShortcut("o", modifiers: .command)
        }
        CommandGroup(after: .newItem) {
            Divider()
            Button(model.t("nat.menu.show_in_finder")) { model.showInFinder(model.selection) }
                .keyboardShortcut("r", modifiers: [.command, .shift])
                .disabled(model.selection.isEmpty)
            Button(model.t("nat.menu.reanalyse")) { model.reanalyse(Array(model.selection)) }
                .keyboardShortcut("r", modifiers: .command)
                .disabled(model.selection.isEmpty || model.progress.queue.running)
            Button(model.t("nat.menu.remove")) { model.removeWithUndo(model.selection) }
                .disabled(model.selection.isEmpty || model.progress.queue.running)
        }
        CommandGroup(before: .sidebar) {
            Button(model.t("nat.tab.start")) { model.tab = .start }.keyboardShortcut("1", modifiers: .command)
            Button(model.t("nat.tab.compare")) { model.tab = .compare }.keyboardShortcut("2", modifiers: .command)
            Button(model.t("nat.tab.queue")) { model.tab = .queue }.keyboardShortcut("3", modifiers: .command)
            Divider()
            Button(model.t(model.sidebarShown ? "nat.menu.hide_sidebar" : "nat.menu.show_sidebar")) {
                model.toggleSidebar()
            }
            .keyboardShortcut("s", modifiers: [.control, .command])
            .disabled(model.sidebarNarrow)
            Divider()
        }
        CommandMenu(model.t("nat.tab.queue")) {
            Button(model.t("nat.queue.start")) { model.startQueue() }
                .keyboardShortcut(.return, modifiers: .command)
                .disabled(model.progress.queue.running || model.queueTicked.isEmpty || model.calRun?.running == true)
            Button(model.progress.queue.paused ? model.t("nat.run.resume") : model.t("nat.run.pause")) {
                model.command(model.progress.queue.paused ? "queue.resume" : "queue.pause")
            }
            .disabled(!model.progress.queue.running || model.progress.queue.resting)
            Button(model.t("nat.run.stop_all")) { model.confirmStopAll() }
                .keyboardShortcut(".", modifiers: .command)
                .disabled(!model.progress.queue.running)
            Divider()
            Button(model.t("nat.menu.stop_test")) { model.stopTest() }
                .disabled(model.cmp.status?.running != true)
        }
        CommandGroup(after: .windowArrangement) {
            Button("AnimeUp") { openWindow(id: "main") }.keyboardShortcut("0", modifiers: .command)
        }
        CommandGroup(replacing: .help) {
            Button(model.t("nat.menu.guide")) {
                NSWorkspace.shared.open(URL(string: "https://interstellar0verdrive.github.io/AnimeUp/guide/")!)
            }
            Button(model.t("nat.cmp.model_guide")) {
                NSWorkspace.shared.open(URL(string: "https://interstellar0verdrive.github.io/AnimeUp/guide/deep-dives/models/")!)
            }
            Divider()
            Button(model.t("nat.menu.open_log")) { model.openLog(model.configuration.logFile.path) }
                .keyboardShortcut("l", modifiers: [.command, .option])
            Button(model.t("nat.menu.report")) {
                NSWorkspace.shared.open(URL(string: "https://github.com/Interstellar0verdrive/AnimeUp/issues/new")!)
            }
        }
    }
}
