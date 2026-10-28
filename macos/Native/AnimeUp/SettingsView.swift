import DesignSystem
import Engine
import Models
import SwiftUI

enum SettingsTab: String, CaseIterable, Identifiable {
    case general, output, calibration, folders, updates
    var id: String { rawValue }
    var symbol: String {
        switch self {
        case .general: "gearshape"
        case .output: "slider.horizontal.3"
        case .calibration: "gauge.medium"
        case .folders: "folder"
        case .updates: "arrow.triangle.2.circlepath"
        }
    }
}

/// Boards ST1–ST5: the Settings window (⌘,), wired to settings.get/set.
struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @State var tab: SettingsTab = .general

    var body: some View {
        TabView(selection: $tab) {
            ForEach(SettingsTab.allCases) { t in
                SettingsPage(tab: t)
                    .tabItem { Label(model.t("nat.set.tab.\(t.rawValue)"), systemImage: t.symbol) }
                    .tag(t)
            }
        }
        .frame(width: 640)
        .navigationTitle(model.t("nat.set.tab.\(tab.rawValue)"))
    }
}

struct SettingsPage: View {
    @Environment(AppModel.self) private var model
    var tab: SettingsTab

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            switch tab {
            case .general: GeneralSettings()
            case .output: OutputSettings()
            case .calibration: CalibrationSettings()
            case .folders: FolderSettings()
            case .updates: UpdateSettings()
            }
        }
        .padding(20)
        .frame(width: 640, alignment: .topLeading)
        .fixedSize(horizontal: false, vertical: true)
        .background(AU.bg)
    }
}

extension AppModel {
    /// Writes one setting (English key, as on disk) and keeps the local copy in step.
    func set(_ key: String, _ value: any Sendable) {
        Task {
            if let s = try? await engine.setSettings([key: value]) {
                settings = s
                localizer.setLanguage(s.language)
                if key == "work_folder" || key == "disk_gb" { folders = try? await engine.foldersState() }
                await refreshPlans()
            }
        }
    }

    func binding<V: Sendable>(_ key: String, _ get: @escaping (EngineSettings) -> V, fallback: V) -> Binding<V> {
        Binding(get: { self.settings.map(get) ?? fallback }, set: { self.set(key, $0) })
    }

    func defaultText(_ value: String) -> String { t("nat.set.default", ["value": value]) }

    var settingsLocked: Bool { jobRunning }
}

// MARK: - General

struct GeneralSettings: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        SettingsGroup {
            SettingsRow(model.t("nat.settings.language"), description: model.t("nat.set.language_desc")) {
                CapsuleSegments(Localizer.languages.map { ($0.code, $0.name) },
                                selection: Binding(get: { model.localizer.language }, set: { model.setLanguage($0) }))
            }
            SettingsRow(model.t("nat.set.appearance"), description: model.t("nat.set.appearance_desc"),
                        defaultText: model.defaultText(model.t("nat.set.theme.system"))) {
                CapsuleSegments([("system", model.t("nat.set.theme.system")), ("light", model.t("nat.set.theme.light")),
                                 ("dark", model.t("nat.set.theme.dark"))],
                                selection: model.binding("theme", \.theme, fallback: "system"))
            }
        }
        SettingsGroup(model.t("nat.set.while_processing")) {
            SettingsRow(model.t("nat.set.notifications"), description: model.t("nat.set.notifications_desc"),
                        defaultText: model.defaultText(model.t("nat.set.on"))) {
                Toggle("", isOn: model.binding("notifications", { $0.notifications ?? true }, fallback: true))
                    .toggleStyle(.switch).labelsHidden().tint(AU.primary)
            }
            SettingsRow(model.t("nat.set.dock"), defaultText: model.defaultText(model.t("nat.set.on"))) {
                Toggle("", isOn: model.binding("dock_progress", { $0.dockProgress ?? true }, fallback: true))
                    .toggleStyle(.switch).labelsHidden().tint(AU.primary)
            }
            SettingsRow(model.t("nat.set.pause"), description: model.t("nat.set.pause_desc"),
                        defaultText: model.defaultText(model.localizer.tn("nat.set.minutes", 5))) {
                Picker("", selection: model.binding("pause_between_files", \.pauseBetweenFiles, fallback: 5)) {
                    ForEach([0, 1, 2, 5, 10, 15, 20, 30], id: \.self) { m in
                        Text(m == 0 ? model.t("nat.set.no_pause") : model.localizer.tn("nat.set.minutes", m)).tag(m)
                    }
                }
                .labelsHidden().frame(width: 130)
            }
        }
        .disabled(model.settingsLocked)
    }
}

// MARK: - Output

struct LockedNote: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        if model.settingsLocked {
            NoteView(.yellow, title: model.t("nat.set.locked_title"), text: model.t("nat.set.locked_text"))
        }
    }
}

struct OutputSettings: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        LockedNote()
        Group {
            SettingsGroup {
                SettingsRow(model.t("nat.set.height"), description: model.t("nat.set.height_desc"),
                            defaultText: model.defaultText("1080")) {
                    SnapSlider(values: [720, 1080, 1440, 2160],
                               selection: model.binding("height", \.height, fallback: 1080)) { "\($0)" }
                }
                SettingsRow(model.t("nat.set.crf"), description: model.t("nat.set.crf_desc"),
                            defaultText: model.defaultText("18")) {
                    SnapSlider(values: [14, 16, 18, 20, 22, 24],
                               selection: model.binding("crf", \.crf, fallback: 18)) { "\($0)" }
                }
                SettingsRow(model.t("nat.set.preset"), description: model.t("nat.set.preset_desc"),
                            defaultText: model.defaultText("slower")) {
                    SnapSlider(values: ["medium", "slow", "slower", "veryslow"],
                               selection: model.binding("preset", \.preset, fallback: "slower")) { $0 }
                }
            }
            SettingsGroup {
                SettingsRow(model.t("nat.set.dedup"), description: model.t("nat.set.dedup_desc"),
                            defaultText: model.defaultText(model.t("nat.set.on"))) {
                    Toggle("", isOn: model.binding("dedup", \.dedup, fallback: true))
                        .toggleStyle(.switch).labelsHidden().tint(AU.primary)
                }
            }
            SettingsGroup(model.t("nat.set.advanced")) {
                SettingsRow(model.t("nat.set.deep"), description: model.t("nat.set.deep_desc"),
                            defaultText: model.defaultText(model.t("nat.set.on"))) {
                    Toggle("", isOn: model.binding("deep_analysis", \.deepAnalysis, fallback: true))
                        .toggleStyle(.switch).labelsHidden().tint(AU.primary)
                }
                SettingsRow(model.t("nat.set.force"), description: model.t("nat.set.force_desc"),
                            defaultText: model.defaultText(model.t("nat.set.off"))) {
                    Toggle("", isOn: model.binding("force", \.force, fallback: false))
                        .toggleStyle(.switch).labelsHidden().tint(AU.primary)
                }
            }
            HStack {
                Text(model.t("nat.set.applies")).auSmall()
                Spacer()
                Button(model.t("nat.set.restore")) { restore() }.auButton(.secondary, .regular)
            }
        }
        .disabled(model.settingsLocked)
    }

    private func restore() {
        guard let d = model.defaults else { return }
        let values: [String: any Sendable] = ["height": d.height, "crf": d.crf, "preset": d.preset, "dedup": d.dedup,
                                              "deep_analysis": d.deepAnalysis, "force": d.force]
        Task {
            model.settings = (try? await model.engine.setSettings(values)) ?? model.settings
            await model.refreshPlans()
        }
    }
}

// MARK: - Calibration

struct CalibrationSettings: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        if let c = model.calibration {
            SettingsGroup {
                HStack(spacing: 10) {
                    chip(c)
                    Text(machineLine).font(.system(size: 12)).foregroundStyle(AU.text2)
                    Spacer()
                    Button(model.t("nat.btn.calibrate_again")) { model.calibrate() }
                        .auButton(c.state == .done ? .secondary : .primary, .regular)
                }
                .padding(.horizontal, 14).padding(.vertical, 12)
            }
            switch c.state {
            case .oldVersion:
                NoteView(.yellow, title: model.t("nat.set.cal_old_title"), text: model.t("nat.set.cal_old_text"))
            case .otherMac:
                NoteView(.yellow, title: model.t("nat.set.cal_other_title"),
                         text: model.t("nat.set.cal_other_text", ["chip": c.otherChip ?? "?"]))
            case .never:
                NoteView(.accent, title: model.t("nat.mac.first_title"), text: model.t("nat.mac.first_text"))
            case .done:
                EmptyView()
            }
            if c.models.contains(where: { $0.fps1080p != nil }) {
                SettingsGroup(model.t("nat.set.measured")) {
                    VStack(spacing: 8) {
                        let top = max(1, (c.models.compactMap(\.fps1080p).max() ?? 1) * 1.06)
                        ForEach(c.models.filter { $0.fps1080p != nil }) { m in
                            HStack(spacing: 10) {
                                Text(shortName(m)).font(.system(size: 12)).foregroundStyle(AU.text)
                                    .frame(width: 160, alignment: .leading)
                                AUBar((m.fps1080p ?? 0) / top, height: 6)
                                Text(model.t("nat.mac.fps", ["fps": String(format: "%.1f", m.fps1080p ?? 0)]))
                                    .font(AUFont.smallNumbers).foregroundStyle(AU.textCode)
                                    .frame(width: 64, alignment: .trailing)
                            }
                        }
                    }
                    .padding(14)
                }
            }
            Text(model.t("nat.set.cal_foot")).auSmall().fixedSize(horizontal: false, vertical: true)
        }
    }

    private var machineLine: String {
        guard let m = model.machine else { return "" }
        return [m.chip, m.memoryGb.map { "\($0) GB" }, "macOS \(m.macosVersion)"].compactMap { $0 }.joined(separator: " · ")
    }

    @ViewBuilder
    private func chip(_ c: CalibrationState) -> some View {
        switch c.state {
        case .done: StatusChip(model.t("nat.mac.cal_chip", ["when": c.date.map(model.relative) ?? ""]), tone: .green, symbol: "checkmark")
        case .oldVersion: StatusChip(model.t("nat.set.cal_chip_old"), tone: .yellow)
        case .otherMac: StatusChip(model.t("nat.set.cal_chip_other"), tone: .yellow)
        case .never: StatusChip(model.t("nat.side.cal_never").lowercased(), tone: .yellow)
        }
    }

    private func shortName(_ m: CalibrationState.ModelSpeed) -> String {
        let key = "mot.modello.\(m.key).label"
        let label = model.localizer.has(key) ? model.t(key) : m.short
        return label.hasPrefix("Real-ESRGAN ") ? String(label.dropFirst(12))
            : label.hasPrefix("Real-") ? String(label.dropFirst(5)) : label
    }
}

// MARK: - Folders

struct FolderSettings: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        LockedNote()
        Group {
            SettingsGroup {
                SettingsRow(model.t("nat.set.finished"), description: model.t("nat.set.finished_desc"),
                            defaultText: model.defaultText(model.t("nat.set.finished_default"))) {
                    Menu { Button(model.t("nat.where.next_to")) {} } label: { PopupLabel(model.t("nat.where.next_to"), width: 200) }
                        .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).frame(width: 200)
                }
                VStack(alignment: .leading, spacing: 8) {
                    SettingsRow(model.t("nat.set.work"), description: model.t("nat.set.work_desc"),
                                defaultText: model.defaultText(model.t("nat.set.work_default"))) { EmptyView() }
                        .padding(.bottom, -10)
                    HStack(spacing: 8) {
                        PathField(model.folders?.workFolder ?? "—")
                        Button(model.t("nat.btn.change")) { model.chooseWorkFolder() }.auButton(.secondary, .regular)
                    }
                    .padding(.horizontal, 14).padding(.bottom, 12)
                }
                if let f = model.folders {
                    SettingsRow(model.t("nat.set.space"), description: model.t("nat.set.space_desc"),
                                defaultText: model.defaultText("\(f.spaceRuleGb) GB")) {
                        SnapSlider(values: spaceSteps(f),
                                   selection: Binding(get: { nearest(model.settings?.diskGb ?? f.spaceRuleGb, in: spaceSteps(f)) },
                                                      set: { model.set("disk_gb", $0) })) { "\($0)" }
                    }
                }
                VStack(alignment: .leading, spacing: 8) {
                    SettingsRow(model.t("nat.set.after"), description: model.t("nat.set.after_desc"),
                                defaultText: model.defaultText(model.t("nat.set.after_default"))) {
                        Picker("", selection: model.binding("keep_work_files", { $0.keepWorkFiles ?? false }, fallback: false)) {
                            Text(model.t("nat.set.after_delete")).tag(false)
                            Text(model.t("nat.set.after_keep")).tag(true)
                        }
                        .labelsHidden().frame(width: 230)
                    }
                    if model.settings?.keepWorkFiles == true {
                        NoteView(.yellow, title: model.t("nat.set.keep_title"), text: model.t("nat.set.keep_text"))
                            .padding(.horizontal, 14).padding(.bottom, 12)
                    }
                }
            }
            HStack {
                Spacer()
                Button(model.t("nat.set.show_work")) {
                    if let f = model.folders { NSWorkspace.shared.open(URL(fileURLWithPath: f.workFolder)) }
                }
                .auButton(.secondary, .regular)
                .disabled(!(model.folders?.exists ?? false))
            }
        }
        .disabled(model.settingsLocked)
    }

    /// Up to six snapping steps from the minimum to the rule, in tens.
    private func spaceSteps(_ f: FoldersState) -> [Int] {
        let lo = f.spaceMinGb, hi = max(f.spaceMinGb + 1, f.spaceRuleGb)
        if hi - lo < 40 { return [lo, hi] }
        let step = Double(hi - lo) / 5
        var out = (0...5).map { lo + Int((Double($0) * step / 10).rounded() * 10) }
        out[5] = hi
        return Array(Set(out)).sorted()
    }

    private func nearest(_ v: Int, in steps: [Int]) -> Int {
        steps.min(by: { abs($0 - v) < abs($1 - v) }) ?? v
    }
}

// MARK: - Updates

struct UpdateSettings: View {
    @Environment(AppModel.self) private var model
    @State private var checking = false

    var body: some View {
        SettingsGroup {
            SettingsRow(model.t("nat.set.auto_check"), description: model.t("nat.set.auto_check_desc"),
                        defaultText: model.defaultText(model.t("nat.set.on"))) {
                Toggle("", isOn: model.binding("check_updates", \.checkUpdates, fallback: true))
                    .toggleStyle(.switch).labelsHidden().tint(AU.primary)
            }
            SettingsRow(model.t("nat.set.auto_install"), description: model.t("nat.set.auto_install_desc"),
                        defaultText: model.defaultText(model.t("nat.set.off"))) {
                Toggle("", isOn: model.binding("auto_install", { $0.autoInstall ?? false }, fallback: false))
                    .toggleStyle(.switch).labelsHidden().tint(AU.primary)
            }
        }
        SettingsGroup {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(statusTitle).font(.system(size: 13, weight: .medium))
                        .foregroundStyle(model.updates?.available != nil ? AU.yellowText : AU.text)
                    Text(checkedLine).font(.system(size: 12)).foregroundStyle(AU.text2)
                }
                Spacer()
                if checking { Spinner(size: 14) }
                Button(model.t("nat.set.check_now")) { check() }.auButton(.secondary, .regular).disabled(checking)
            }
            .padding(.horizontal, 14).padding(.vertical, 12)
        }
        HStack(spacing: 16) {
            UnderlineLink(model.t("nat.set.release_notes"), symbol: "arrow.up.right") {
                NSWorkspace.shared.open(URL(string: model.updates?.url ?? "https://github.com/Interstellar0verdrive/AnimeUp/releases")!)
            }
            UnderlineLink(model.t("nat.set.on_github"), symbol: "arrow.up.right") {
                NSWorkspace.shared.open(URL(string: "https://github.com/Interstellar0verdrive/AnimeUp")!)
            }
        }
    }

    private var statusTitle: String {
        if let v = model.updates?.available { return model.t("nat.set.update_available", ["version": v]) }
        if model.updates?.result == "error" { return model.t("nat.set.update_error") }
        return model.t("nat.set.up_to_date", ["version": AppModel.appVersion])
    }

    private var checkedLine: String {
        guard let c = model.updates?.checked else { return model.t("nat.set.never_checked") }
        let f = DateFormatter()
        f.locale = Locale(identifier: model.localizer.language)
        f.doesRelativeDateFormatting = true
        f.dateStyle = .medium
        f.timeStyle = .short
        return model.t("nat.set.last_checked", ["when": f.string(from: Date(timeIntervalSince1970: c))])
    }

    private func check() {
        checking = true
        Task {
            model.updates = try? await model.engine.checkUpdates()
            checking = false
        }
    }
}
