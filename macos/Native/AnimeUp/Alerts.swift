import AppKit
import DesignSystem

/// The folder, information and error alerts (boards O1–O3), drawn as AUAlert.
@MainActor
enum AlertBuilder {
    static func present(_ alert: AppAlert, model: AppModel) {
        switch alert.kind {
        case .noVideos(let folder, let subfolders, let paths):
            var text = model.t("nat.alert.novideos_text")
            if !subfolders { text += "\n" + model.t("nat.alert.novideos_sub") }
            let a = AUAlert(icon: .folderEmpty, tone: .yellow,
                            title: model.t("nat.alert.novideos_title", ["folder": (folder as NSString).lastPathComponent]), text: text)
            if subfolders {
                a.button(model.t("nat.btn.ok"), role: .primary)
                a.runModal()
            } else {
                a.button(model.t("nat.alert.look_sub"), role: .primary)
                a.button(model.t("nat.btn.ok"))
                if a.runModal() == 0 {
                    model.add(paths.map { URL(fileURLWithPath: $0) }, subfolders: true)
                }
            }
        case .workNotWritable(let folder):
            let a = AUAlert(icon: .folderReadonly, tone: .red,
                            title: model.t("nat.alert.notwritable_title", ["folder": folder]), text: model.t("nat.alert.notwritable_text"))
            a.button(model.t("nat.alert.choose_another"), role: .primary)
            a.button(model.t("nat.btn.cancel"))
            if a.runModal() == 0 { model.chooseWorkFolder() }
        case .workInsideFinished(let folder):
            let a = AUAlert(icon: .folderInside, tone: .yellow,
                            title: model.t("nat.alert.inside_title"), text: model.t("nat.alert.inside_text", ["folder": folder]))
            a.button(model.t("nat.alert.choose_another"), role: .primary)
            a.button(model.t("nat.btn.cancel"))
            if a.runModal() == 0 { model.chooseWorkFolder() }
        case .changeAfterQueue:
            let a = AUAlert(icon: .folderBusy, tone: .yellow,
                            title: model.t("nat.alert.after_title"), text: model.t("nat.alert.after_text"))
            a.button(model.t("nat.btn.ok"), role: .primary)
            a.runModal()
        case .closeNotice:
            let a = AUAlert(icon: .windowClose, tone: .accent, title: model.t("nat.alert.close_title"), text: model.t("nat.alert.close_text"))
            a.button(model.t("nat.btn.ok"), role: .primary)
            a.checkbox = model.t("nat.btn.dont_show")
            a.runModal()
            if a.checked { UserDefaults.standard.set(true, forKey: AppModel.closeNoticeOffKey) }
        case .diskMissing(let volume):
            let a = AUAlert(icon: .diskMissing, tone: .red,
                            title: model.t("nat.alert.disk_title"), text: model.t("nat.alert.disk_text", ["volume": volume]))
            // Esc tries again (harmless); choosing a folder is a deliberate click.
            a.button(model.t("nat.btn.retry"), role: .primary, cancel: true)
            a.button(model.t("nat.alert.choose_another"))
            if a.runModal() == 0 { model.refreshFolders() } else { model.chooseWorkFolder() }
        case .moveWithInterrupted(let url, let count):
            let a = AUAlert(icon: .folderMove, tone: .yellow,
                            title: model.t("nat.alert.move_title"), text: model.localizer.tn("nat.alert.move_text", count))
            a.button(model.t("nat.alert.use_new"), role: .primary)
            a.button(model.t("nat.btn.cancel"))
            if a.runModal() == 0 { model.setWorkFolder(url) }
        case .info(let title, let text):
            let a = AUAlert(icon: .info, tone: .accent, title: title, text: text)
            a.button(model.t("nat.btn.ok"), role: .primary)
            a.runModal()
        case .error(let title, let text):
            let a = AUAlert(icon: .error, tone: .red, title: title, text: text)
            a.button(model.t("nat.btn.ok"), role: .primary)
            a.runModal()
        }
    }
}
