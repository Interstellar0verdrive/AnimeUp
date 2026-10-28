import SwiftUI

/// Native alerts of boards O2/O6.
@MainActor
enum AlertBuilder {
    static func build(_ alert: AppAlert, model: AppModel) -> Alert {
        switch alert.kind {
        case .noVideos(let folder, let subfolders, let paths):
            let name = (folder as NSString).lastPathComponent
            var text = model.t("nat.alert.novideos_text")
            if !subfolders { text += "\n" + model.t("nat.alert.novideos_sub") }
            if subfolders {
                return Alert(title: Text(model.t("nat.alert.novideos_title", ["folder": name])),
                             message: Text(text), dismissButton: .default(Text(model.t("nat.btn.ok"))))
            }
            return Alert(title: Text(model.t("nat.alert.novideos_title", ["folder": name])),
                         message: Text(text),
                         primaryButton: .default(Text(model.t("nat.alert.look_sub"))) {
                             model.add(paths.map { URL(fileURLWithPath: $0) }, subfolders: true)
                         },
                         secondaryButton: .cancel(Text(model.t("nat.btn.ok"))))
        case .workNotWritable(let folder):
            return Alert(title: Text(model.t("nat.alert.notwritable_title", ["folder": folder])),
                         message: Text(model.t("nat.alert.notwritable_text")),
                         primaryButton: .default(Text(model.t("nat.alert.choose_another"))) {
                             DispatchQueue.main.async { model.chooseWorkFolder() }
                         },
                         secondaryButton: .cancel(Text(model.t("nat.btn.cancel"))))
        case .workInsideFinished(let folder):
            return Alert(title: Text(model.t("nat.alert.inside_title")),
                         message: Text(model.t("nat.alert.inside_text", ["folder": folder])),
                         primaryButton: .default(Text(model.t("nat.alert.choose_another"))) {
                             DispatchQueue.main.async { model.chooseWorkFolder() }
                         },
                         secondaryButton: .cancel(Text(model.t("nat.btn.cancel"))))
        case .changeAfterQueue:
            return Alert(title: Text(model.t("nat.alert.after_title")),
                         message: Text(model.t("nat.alert.after_text")),
                         dismissButton: .default(Text(model.t("nat.btn.ok"))))
        case .info(let title, let text):
            return Alert(title: Text(title), message: Text(text), dismissButton: .default(Text(model.t("nat.btn.ok"))))
        }
    }
}
