import DesignSystem
import SwiftUI

/// "Finished videos" on Start and in Settings › Folders: next to the originals,
/// or a folder of the person's choice (the folder itself is listed once chosen).
struct FinishedFolderMenu: View {
    @Environment(AppModel.self) private var model
    var width: CGFloat = 280
    var height: CGFloat = 28
    var size: CGFloat = 13

    var body: some View {
        let chosen = model.folders?.finishedFolder
        PopupMenu({
            var items: [AUMenuItem] = [.item(model.t("nat.where.next_to"), checked: chosen == nil) { model.setFinishedFolder(nil) }]
            if let chosen { items.append(.item(URL(fileURLWithPath: chosen).lastPathComponent, checked: true) {}) }
            return items + [.separator, .item(model.t("nat.where.choose")) { model.chooseFinishedFolder() }]
        }) {
            PopupLabel(chosen.map { URL(fileURLWithPath: $0).lastPathComponent } ?? model.t("nat.where.next_to"),
                       width: width, height: height, size: size)
        }
        // Its width at most; narrower when the column is (Start in one column, at 720 pt).
        .fixedSize(horizontal: false, vertical: true)
        .frame(maxWidth: width, alignment: .leading)
        .help(chosen ?? "")
    }
}
