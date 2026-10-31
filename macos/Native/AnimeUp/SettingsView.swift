import DesignSystem
import Engine
import Models
import SwiftUI

enum SettingsTab: String, CaseIterable, Identifiable {
    // No Calibration tab: its date opens the full results (board K4) from Start
    // and the sidebar, and AnimeUp › Calibrate This Mac… starts a new one.
    case general, output, folders, updates
    var id: String { rawValue }
    var symbol: String {
        switch self {
        case .general: "gearshape"
        case .output: "slider.horizontal.3"
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
        tabs.task { model.pausedRecipe = try? await model.engine.pausedWithOtherValues() }
    }

    private var tabs: some View {
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
        // edge.py `settings_win()`: padding 20, groups 18 apart.
        VStack(alignment: .leading, spacing: 18) {
            switch tab {
            case .general: GeneralSettings()
            case .output: OutputSettings()
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

    /// "Default: …" on every row that has one, whatever the current value: it
    /// tells what the factory value is, not only where a change would go back to.
    func defaultText<T: Equatable>(_ value: String, current: T?, is factory: T) -> String? {
        defaultText(value)
    }

    var settingsLocked: Bool { jobRunning }
}

// MARK: - General

struct GeneralSettings: View {
    /// Off until the light theme exists (2.0 ships dark only).
    static let lightTheme = false
    @Environment(AppModel.self) private var model

    var body: some View {
        SettingsGroup {
            SettingsRow(model.t("nat.settings.language"), description: model.t("nat.set.language_desc")) {
                CapsuleSegments(Localizer.languages.map { ($0.code, $0.name) },
                                selection: Binding(get: { model.localizer.language }, set: { model.setLanguage($0) }))
            }
            // Appearance comes back with the light theme: 2.0 is dark only.
            if Self.lightTheme {
                SettingsRow(model.t("nat.set.appearance"), description: model.t("nat.set.appearance_desc"),
                            defaultText: model.defaultText(model.t("nat.set.theme.system"), current: model.settings?.theme, is: "system")) {
                    CapsuleSegments([("system", model.t("nat.set.theme.system")), ("light", model.t("nat.set.theme.light")),
                                     ("dark", model.t("nat.set.theme.dark"))],
                                    selection: model.binding("theme", \.theme, fallback: "system"))
                }
            }
        }
        SettingsGroup(model.t("nat.set.while_processing")) {
            SettingsRow(model.t("nat.set.notifications"), description: model.t("nat.set.notifications_desc"),
                        defaultText: model.defaultText(model.t("nat.set.on"), current: model.settings?.notifications, is: true)) {
                Toggle("", isOn: model.binding("notifications", { $0.notifications ?? true }, fallback: true))
                    .toggleStyle(.switch).labelsHidden().tint(AU.primary)
            }
            SettingsRow(model.t("nat.set.dock"), defaultText: model.defaultText(model.t("nat.set.on"), current: model.settings?.dockProgress, is: true)) {
                Toggle("", isOn: model.binding("dock_progress", { $0.dockProgress ?? true }, fallback: true))
                    .toggleStyle(.switch).labelsHidden().tint(AU.primary)
            }
            SettingsRow(model.t("nat.set.pause"), description: model.t("nat.set.pause_desc"),
                        defaultText: model.defaultText(model.localizer.tn("nat.set.minutes", 5), current: model.settings?.pauseBetweenFiles, is: 5)) {
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
        } else if let r = model.pausedRecipe {
            NoteView(.yellow, title: model.t("nat.set.paused_title", ["name": r.name ?? ""]),
                     text: model.t("nat.set.paused_text", ["values": Self.describe(r, model)]) + "\n" + model.t("nat.set.paused_new")) {
                Button(model.t("nat.set.use_its_values")) { useIts(r) }.buttonStyle(AUButtonStyle(.notice, size: .small))
            }
        }
    }

    static func describe(_ r: QueueProgress.Recipe, _ model: AppModel) -> String {
        var parts: [String] = []
        if let h = r.values["height"]?.number { parts.append("\(Int(h))p") }
        if let c = r.values["crf"]?.number { parts.append("CRF \(Int(c))") }
        if let p = r.values["preset"]?.string { parts.append(p) }
        for k in ["dedup", "denoise", "force"] {
            if case .bool(let b)? = r.values[k] { parts.append("\(k) \(b ? model.t("nat.set.on") : model.t("nat.set.off"))") }
        }
        guard parts.count > 1 else { return parts.joined() }
        return parts.dropLast().joined(separator: ", ") + model.t("nat.cmp.and") + parts.last!
    }

    private func useIts(_ r: QueueProgress.Recipe) {
        var values: [String: any Sendable] = [:]
        for (k, v) in r.values {
            switch v {
            case .number(let n): values[k] = Int(n)
            case .string(let s): values[k] = s
            case .bool(let b): values[k] = b
            default: break
            }
        }
        Task {
            if let s = try? await model.engine.setSettings(values) { model.settings = s }
            model.pausedRecipe = try? await model.engine.pausedWithOtherValues()
            await model.refreshPlans()
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
                            defaultText: model.defaultText("1080", current: model.settings?.height, is: 1080)) {
                    SnapSlider(values: [720, 1080, 1440, 2160],
                               selection: model.binding("height", \.height, fallback: 1080)) { "\($0)" }
                }
                SettingsRow(model.t("nat.set.crf"), description: model.t("nat.set.crf_desc"),
                            defaultText: model.defaultText("18", current: model.settings?.crf, is: 18)) {
                    SnapSlider(values: [14, 16, 18, 20, 22, 24],
                               selection: model.binding("crf", \.crf, fallback: 18)) { "\($0)" }
                }
                SettingsRow(model.t("nat.set.preset"), description: model.t("nat.set.preset_desc"),
                            defaultText: model.defaultText("slower", current: model.settings?.preset, is: "slower")) {
                    SnapSlider(values: ["medium", "slow", "slower", "veryslow"],
                               selection: model.binding("preset", \.preset, fallback: "slower")) { $0 }
                }
            }
            SettingsGroup {
                SettingsRow(model.t("nat.set.dedup"), description: model.t("nat.set.dedup_desc"),
                            defaultText: model.defaultText(model.t("nat.set.on"), current: model.settings?.dedup, is: true)) {
                    Toggle("", isOn: model.binding("dedup", \.dedup, fallback: true))
                        .toggleStyle(.switch).labelsHidden().tint(AU.primary)
                }
            }
            SettingsGroup(model.t("nat.set.advanced")) {
                SettingsRow(model.t("nat.set.deep"), description: model.t("nat.set.deep_desc"),
                            defaultText: model.defaultText(model.t("nat.set.on"), current: model.settings?.deepAnalysis, is: true)) {
                    Toggle("", isOn: model.binding("deep_analysis", \.deepAnalysis, fallback: true))
                        .toggleStyle(.switch).labelsHidden().tint(AU.primary)
                }
                SettingsRow(model.t("nat.set.force"), description: model.t("nat.set.force_desc"),
                            defaultText: model.defaultText(model.t("nat.set.off"), current: model.settings?.force, is: false)) {
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

// MARK: - Folders

struct FolderSettings: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        LockedNote()
        // edge.py `st_folders()`: the finished-videos default alone, then the work folder group.
        Group {
            SettingsGroup {
                SettingsRow(model.t("nat.set.finished"), description: model.t("nat.set.finished_desc"),
                            defaultText: model.defaultText(model.t("nat.set.finished_default"), current: model.folders?.finishedFolder ?? "", is: "")) {
                    FinishedFolderMenu(width: 200, height: 26, size: 12)
                }
            }
            SettingsGroup {
                // No default shown: the work folder and its space are the person's
                // disk, not a factory value to go back to.
                SettingsRow(model.t("nat.set.work"), description: model.t("nat.set.work_desc")) {
                    HStack(spacing: 8) {
                        PathField(model.folders?.workFolder ?? "—", height: 26)
                        Button(model.t("nat.btn.change")) { model.chooseWorkFolder() }.auButton(.secondary, .small)
                    }
                    .frame(width: 330)
                }
                if let f = model.folders {
                    SettingsRow(model.t("nat.set.space"), description: model.t("nat.set.space_desc"),
                                defaultText: nil) {
                        if f.tooFull {
                            BalancedParagraph(model.t("nat.where.too_full", ["free": SizeFormat.gb(f.freeGb), "volume": f.volume,
                                                                            "min": f.spaceMinGb]), style: AUFont.small)
                                .foregroundStyle(AU.yellowText)
                                .frame(width: 230, alignment: .leading)
                        } else if f.tight {
                            BalancedParagraph(model.t("nat.where.tight", ["free": SizeFormat.gb(f.freeGb), "use": f.spaceRuleGb,
                                                                          "left": SizeFormat.gb(f.leftForSystemGb)]), style: AUFont.small)
                                .foregroundStyle(AU.yellowText)
                                .frame(width: 230, alignment: .leading)
                        } else {
                            SnapSlider(values: spaceSteps(f),
                                       selection: Binding(get: { nearest(model.settings?.diskGb ?? f.spaceRuleGb, in: spaceSteps(f)) },
                                                          set: { model.set("disk_gb", $0) }), width: 230) { "\($0)" }
                        }
                    }
                }
                SettingsRow(model.t("nat.set.after"), description: model.t("nat.set.after_desc"),
                            defaultText: model.defaultText(model.t("nat.set.after_default"), current: model.settings?.keepWorkFiles, is: false)) {
                    let keep = model.settings?.keepWorkFiles == true
                    PopupMenu({
                        [.item(model.t("nat.set.after_delete"), checked: !keep) { model.set("keep_work_files", false) },
                         .item(model.t("nat.set.after_keep"), checked: keep) { model.set("keep_work_files", true) }]
                    }) {
                        PopupLabel(model.t(keep ? "nat.set.after_keep" : "nat.set.after_delete"), width: 290, height: 26, size: 12)
                    }
                    .fixedSize()
                }
            }
            if model.settings?.keepWorkFiles == true {
                NoteView(.yellow, title: model.t("nat.set.keep_title"), text: model.t("nat.set.keep_text"))
            }
            HStack {
                Spacer()
                Button {
                    if let f = model.folders { NSWorkspace.shared.open(URL(fileURLWithPath: f.workFolder)) }
                } label: { Label(model.t("nat.set.show_work"), systemImage: "folder") }
                .auButton(.plain, .regular)
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
                        defaultText: model.defaultText(model.t("nat.set.on"), current: model.settings?.checkUpdates, is: true)) {
                Toggle("", isOn: model.binding("check_updates", \.checkUpdates, fallback: true))
                    .toggleStyle(.switch).labelsHidden().tint(AU.primary)
            }
            // No "Download and install automatically" row: the app can't install itself yet, and a toggle
            // that does nothing promised it did (31 Oct). It comes back with a real in-app update.
        }
        SettingsGroup {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(statusTitle).auFont(13, .semibold)
                        .foregroundStyle(model.updates?.available != nil ? AU.yellowText : AU.text)
                    Text(checkedLine).auSmall()
                }
                Spacer()
                if checking { Spinner(size: 14) }
                Button(model.t("nat.set.check_now")) { check() }.auButton(.secondary, .regular).disabled(checking)
            }
            .padding(14)
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
        f.locale = .current
        f.doesRelativeDateFormatting = true
        f.formattingContext = .middleOfSentence     // "today", not "Today"

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
