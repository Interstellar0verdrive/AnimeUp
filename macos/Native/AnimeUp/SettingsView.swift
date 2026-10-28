import DesignSystem
import Models
import SwiftUI

/// Placeholder for the Settings window (boards ST1–ST5 come later). For now
/// it carries the live language switch.
struct SettingsView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Form {
            Picker(model.t("nat.settings.language"), selection: Binding(
                get: { model.localizer.language },
                set: { model.setLanguage($0) })) {
                ForEach(Localizer.languages, id: \.code) { Text($0.name).tag($0.code) }
            }
            .pickerStyle(.menu)
            Text(model.t("nat.settings.later")).auSmall()
        }
        .formStyle(.grouped)
        .frame(width: 460)
        .fixedSize()
        .navigationTitle(model.t("nat.settings.title"))
    }
}
