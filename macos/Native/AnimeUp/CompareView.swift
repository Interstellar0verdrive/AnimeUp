import AVFoundation
import DesignSystem
import Models
import SwiftUI

/// In snapshot renders a ScrollView draws nothing: pages lay out flat instead.
private struct NoScrollKey: EnvironmentKey { static let defaultValue = false }
extension EnvironmentValues {
    var auNoScroll: Bool {
        get { self[NoScrollKey.self] }
        set { self[NoScrollKey.self] = newValue }
    }
}

struct MaybeScrollH<Content: View>: View {
    @Environment(\.auNoScroll) private var flat
    @ViewBuilder var content: () -> Content
    var body: some View {
        if flat { HStack(spacing: 0) { content() } } else { ScrollView(.horizontal, showsIndicators: false) { content() } }
    }
}

struct MaybeScroll<Content: View>: View {
    @Environment(\.auNoScroll) private var flat
    @ViewBuilder var content: () -> Content
    var body: some View {
        if flat { VStack(spacing: 0) { content() } } else { ScrollView { content() }.scrollBounceBehavior(.basedOnSize) }
    }
}

private let MONO11 = Font.system(size: 11, design: .monospaced)

/// Boards C1–C5 and E1–E8 (generators ds/compare.py, compare_sheet.py, edge.py).
struct CompareView: View {
    @Environment(AppModel.self) private var model

    private var running: Bool { model.cmp.status?.running == true }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            header
            if model.compareFiles.isEmpty {
                NoteView(.accent, title: model.t("nat.cmp.no_files_title"), text: model.t("nat.cmp.no_files"))
                Spacer()
            } else {
                stepRow
                FileStrip(disabled: running)
                switch model.cmp.step {
                case .clips: CompareClipsStep()
                case .models: CompareModelsStep()
                case .results: CompareResultsStep()
                }
            }
        }
        .padding(.top, 28)
        .padding(.horizontal, 28)
        .padding(.bottom, 24)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .ignoresSafeArea(edges: .top)
        .onAppear { model.openCompare() }
    }

    private var introKey: String {
        if running { return "nat.cmp.intro_running" }
        return model.cmp.step == .results ? "nat.cmp.intro_results" : "nat.cmp.intro"
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(model.t("nat.tab.compare")).auPageTitle()
            Text(model.t(introKey + "1") + "\n" + model.t(introKey + "2")).auBody()
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var stepRow: some View {
        HStack(spacing: 14) {
            CompareStepper()
            if running {
                Text(model.t("nat.cmp.locked")).auSmall()
            }
            Spacer()
            if model.cmp.step == .results && !running {
                Button(model.t("nat.cmp.change_test")) { model.cmp.step = .clips }.auButton(.secondary, .regular)
            }
        }
    }
}

/// The step indicator of compare.py `stepper()`.
struct CompareStepper: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let step = model.cmp.step
        let running = model.cmp.status?.running == true
        let versions = model.cmp.status?.request?.models.count ?? model.cmp.chosenModels.count
        let original = model.cmp.status?.request?.reference ?? model.cmp.includeOriginal
        HStack(spacing: 8) {
            pill(0, model.t("nat.cmp.step.0"), state(0, step), note: model.localizer.tn("nat.cmp.n_picked", model.cmp.selected.count))
            chevron
            pill(1, model.t("nat.cmp.step.1"), state(1, step),
                 note: original ? model.t("nat.cmp.original_plus", ["n": versions]) : model.localizer.tn("nat.cmp.n_models", versions))
            chevron
            pill(2, model.t("nat.cmp.step.2"), running ? "busy" : state(2, step), note: "")
        }
    }

    private var chevron: some View {
        Image(systemName: "chevron.right").font(.system(size: 8, weight: .semibold)).foregroundStyle(AU.text3)
    }

    private func state(_ i: Int, _ step: CompareState.Step) -> String {
        i < step.rawValue ? "done" : i == step.rawValue ? "now" : "next"
    }

    @ViewBuilder
    private func pill(_ i: Int, _ label: String, _ st: String, note: String) -> some View {
        HStack(spacing: 8) {
            ZStack {
                switch st {
                case "done":
                    Circle().fill(AU.greenTint)
                    Image(systemName: "checkmark").font(.system(size: 9, weight: .bold)).foregroundStyle(AU.greenText)
                case "now":
                    Circle().fill(AU.primary)
                    Text("\(i + 1)").font(.system(size: 12, weight: .semibold)).foregroundStyle(AU.onPrimary)
                case "busy":
                    Spinner(size: 20)
                default:
                    Circle().strokeBorder(AU.glassLine)
                    Text("\(i + 1)").font(.system(size: 12, weight: .semibold)).foregroundStyle(AU.text2)
                }
            }
            .frame(width: 22, height: 22)
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(label).font(.system(size: 13, weight: st == "next" ? .regular : .semibold))
                if st == "done" && !note.isEmpty { Text(note).font(MONO11) }
            }
            .foregroundStyle(st == "done" ? AU.greenText : st == "next" ? AU.text2 : AU.text)
        }
        .padding(.leading, 4).padding(.trailing, 12)
        .frame(height: 30)
        .background(Capsule().fill(st == "done" ? AU.greenBg : (st == "now" || st == "busy") ? AU.sel : .clear))
        .overlay(Capsule().strokeBorder(st == "done" ? AU.greenLine : (st == "now" || st == "busy") ? AU.softLine : AU.line))
        .contentShape(Capsule())
        .onTapGesture {
            if st == "done" && model.cmp.status?.running != true { model.cmp.step = CompareState.Step(rawValue: i) ?? .clips }
        }
    }
}

/// compare.py `filestrip()`: File to test (360 pt) | Source | Output | Full episode.
struct FileStrip: View {
    @Environment(AppModel.self) private var model
    var disabled: Bool

    var body: some View {
        let f = model.files.first { $0.id == model.cmp.fileId }
        let plan = model.plan(model.cmp.fileId ?? "")
        HStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 6) {
                Text(model.t("nat.cmp.file")).auLabel()
                Menu {
                    ForEach(model.compareFiles) { file in
                        Button(file.state == .ready ? file.name : "\(file.name) — \(model.t("nat.cmp.analysing"))") {
                            model.selectCompareFile(file.id)
                        }
                        .disabled(file.state != .ready)
                    }
                } label: {
                    PopupLabel(f?.name ?? model.t("nat.cmp.pick_file"), width: 332, height: 26, size: 12)
                }
                .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize()
                .disabled(disabled)
                .opacity(disabled ? 0.4 : 1)
            }
            .padding(.vertical, 10).padding(.horizontal, 14)
            .frame(width: 360, alignment: .leading)
            cell(model.t("nat.cmp.source"), f?.report.map { "\($0.width)×\($0.height)" } ?? "—")
            cell(model.t("nat.cmp.output"), plan.map { "\($0.outputWidth ?? 0)×\($0.outputHeight ?? 0)" } ?? "—")
            cell(model.t("nat.cmp.full_episode"), plan?.estimate.map { Fmt.estimate($0) } ?? "—")
        }
        .fixedSize(horizontal: false, vertical: true)
        .background(RoundedRectangle(cornerRadius: AU.Radius.card).fill(AU.surface))
        .overlay(RoundedRectangle(cornerRadius: AU.Radius.card).strokeBorder(AU.line))
    }

    private func cell(_ label: String, _ value: String) -> some View {
        HStack(spacing: 0) {
            Rectangle().fill(AU.line).frame(width: 1)
            VStack(alignment: .leading, spacing: 6) {
                Text(label).auLabel()
                Text(verbatim: value).font(.system(size: 15, design: .monospaced)).foregroundStyle(AU.text).frame(height: 26)
            }
            .padding(.vertical, 10).padding(.horizontal, 14)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

/// compare.py `actionbar()`.
struct ActionBar<Leading: View, Trailing: View>: View {
    var accent = false
    @ViewBuilder var leading: () -> Leading
    @ViewBuilder var trailing: () -> Trailing

    var body: some View {
        HStack(spacing: 12) {
            leading()
            Spacer(minLength: 8)
            HStack(spacing: 8) { trailing() }
        }
        .padding(.horizontal, 16).padding(.vertical, 12)
        .background(RoundedRectangle(cornerRadius: AU.Radius.card).fill(AU.surface))
        .overlay(RoundedRectangle(cornerRadius: AU.Radius.card).strokeBorder(accent ? AU.softLine : AU.line))
    }
}

/// Title + secondary text in an action bar.
struct BarText: View {
    var title: String
    var tail: String = ""
    var line: String
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("\(Text(title).fontWeight(.semibold).foregroundStyle(AU.text))\(Text(tail.isEmpty ? "" : " · " + tail).foregroundStyle(AU.text2))")
                .font(.system(size: 13))
            Text(line).auSmall()
        }
    }
}

extension AppModel {
    func kindName(_ kind: String) -> String { t("nat.cmp.kind.\(kind)") }
    func kindTests(_ kind: String) -> String { t("nat.cmp.tests.\(kind)") }
}

// MARK: - C1 clips (+ E1, E6, E7)

struct CompareClipsStep: View {
    @Environment(AppModel.self) private var model
    private let columns = Array(repeating: GridItem(.flexible(), spacing: 12), count: 4)

    var body: some View {
        let f = model.files.first { $0.id == model.cmp.fileId }
        let duration = f?.report?.duration ?? 0
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Text(model.t("nat.cmp.pick_title")).font(AUFont.sectionTitle)
                Text(model.t("nat.cmp.pick_text")).auSmall()
            }
            if f?.state != .ready {
                NoteView(.accent, title: model.t("nat.cmp.waiting_title"), text: model.t("nat.cmp.waiting"))
            } else if let err = model.cmp.scanError {
                NoteView(.red, title: model.t("nat.cmp.scan_failed"), text: err) {
                    UnderlineLink(model.t("nat.btn.show_log"), tone: .red) { model.openLog(model.configuration.logFile.path) }
                    Button(model.t("nat.btn.retry")) { model.scanClips(more: false) }.buttonStyle(AUTintedButtonStyle(.red))
                }
            } else if model.cmp.clips.isEmpty && !model.cmp.scanning {
                NoteView(.yellow, title: model.t("nat.cmp.no_clips_title"),
                         text: duration > 0 && duration < 10 ? model.t("nat.cmp.too_short", ["s": Int(duration)]) : model.t("nat.cmp.no_clips"))
            } else if model.cmp.exhausted && model.cmp.clips.count < 8 && duration < 600 && duration > 0 {
                NoteView(.yellow, title: model.localizer.tn("nat.cmp.short_file", model.cmp.clips.count),
                         text: model.t("nat.cmp.short_file_text", ["d": Fmt.span(duration).replacingOccurrences(of: "h ", with: "h ")]))
            }
            MaybeScroll {
                VStack(spacing: 14) {
                    if model.cmp.clips.isEmpty && model.cmp.scanning {
                        HStack(spacing: 8) {
                            Spinner(size: 14)
                            Text(model.cmp.scanText.isEmpty ? model.t("nat.cmp.scanning") : model.cmp.scanText).auSmall(AU.text)
                        }
                        .padding(.vertical, 40)
                    }
                    LazyVGrid(columns: columns, spacing: 12) {
                        ForEach(model.cmp.clips) { c in ClipCard(clip: c) }
                    }
                    if !model.cmp.clips.isEmpty {
                        HStack(spacing: 8) {
                            if model.cmp.scanning {
                                Spinner(size: 12)
                                Text(model.cmp.scanText.isEmpty ? model.t("nat.cmp.scanning") : model.cmp.scanText).auSmall()
                            } else if !model.cmp.exhausted {
                                Button { model.scanClips(more: true) } label: { Label(model.t("nat.cmp.find_more"), systemImage: "plus") }
                                    .auButton(.secondary, .regular)
                            }
                        }
                        .frame(maxWidth: .infinity)
                    }
                }
            }
            bar
        }
    }

    @ViewBuilder
    private var bar: some View {
        let picked = model.cmp.clips.filter { model.cmp.selected.contains($0.startFrame) }
        ActionBar {
            if model.cmp.clips.isEmpty {
                BarText(title: model.t("nat.cmp.no_clip_to_pick"), line: model.t("nat.cmp.choose_another"))
            } else if picked.isEmpty {
                BarText(title: model.t("nat.cmp.none_picked"), line: model.t("nat.cmp.tick_one"))
            } else {
                BarText(title: model.localizer.tn("nat.cmp.clips_selected", picked.count),
                        line: picked.map { "\(model.kindName($0.kind)) \($0.range)" }.joined(separator: model.t("nat.cmp.and"))
                            + " · " + model.t("nat.cmp.seconds_of_video", ["s": picked.reduce(0) { $0 + Int((Double($1.frames) / max(1, (model.files.first { $0.id == model.cmp.fileId }?.report?.fps ?? 24))).rounded()) }]))
            }
        } trailing: {
            Button { model.goToModels() } label: {
                HStack(spacing: 5) { Text(model.t("nat.cmp.next_models")); Image(systemName: "arrow.right") }
            }
            .auButton(.primary, .regular)
            .disabled(picked.isEmpty)
        }
    }
}

struct ClipCard: View {
    @Environment(AppModel.self) private var model
    var clip: CompareClips.Clip
    private var on: Bool { model.cmp.selected.contains(clip.startFrame) }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ZStack(alignment: .bottomTrailing) {
                Rectangle().fill(AU.inset)
                if let path = clip.thumbnail, let img = NSImage(contentsOfFile: path) {
                    Image(nsImage: img).resizable().aspectRatio(contentMode: .fill)
                }
                Text(verbatim: clip.range).font(.system(size: 10.5, design: .monospaced)).foregroundStyle(.white)
                    .padding(.horizontal, 6).padding(.vertical, 1)
                    .background(RoundedRectangle(cornerRadius: 4).fill(.black.opacity(0.55)))
                    .padding(6)
            }
            .frame(height: 118)
            .clipShape(RoundedRectangle(cornerRadius: 6))
            HStack(spacing: 8) {
                TriCheckbox(state: on ? .on : .off) { toggle() }
                Text(model.kindName(clip.kind)).font(.system(size: 13, weight: .semibold)).foregroundStyle(AU.text)
                Spacer(minLength: 4)
                Text(model.kindTests(clip.kind)).auSmall().lineLimit(1)
            }
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: AU.Radius.card).fill(on ? AU.soft : AU.surface))
        .overlay(RoundedRectangle(cornerRadius: AU.Radius.card).strokeBorder(on ? AU.softLine : AU.line))
        .contentShape(Rectangle())
        .onTapGesture { toggle() }
        .help(clip.reason)
    }

    private func toggle() {
        if on { model.cmp.selected.remove(clip.startFrame) } else { model.cmp.selected.insert(clip.startFrame) }
    }
}

// MARK: - C2 models (+ E2, E3, E8)

struct CompareModelsStep: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if let m = model.cmp.models {
                if model.progress.queue.running {
                    NoteView(.yellow, title: model.t("nat.cmp.gpu_busy_title"),
                             text: model.t("nat.cmp.gpu_busy_text", ["i": model.progress.queue.position ?? 1, "n": model.progress.queue.total ?? 1,
                                                                     "time": model.progress.queue.finish.map { model.clockTime($0) } ?? "—"])) {
                        Button(model.t("nat.cmp.pause_queue")) { model.command("queue.pause") }
                            .buttonStyle(AUButtonStyle(.notice, size: .small))
                    }
                } else {
                    GuideBand(sourceHeight: m.sourceHeight)
                }
                let top = max(0.1, m.models.compactMap(\.fps).max() ?? 1)
                HStack(alignment: .top, spacing: 12) {
                    ForEach(m.models) { card in ModelCard(card: card, recommended: card.key == m.recommended, topFps: top, outputHeight: m.height) }
                }
                .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 14) {
                    Toggle("", isOn: Binding(get: { model.cmp.includeOriginal }, set: { model.cmp.includeOriginal = $0 }))
                        .toggleStyle(.switch).labelsHidden().tint(AU.primary)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(model.t("nat.cmp.include_original")).font(.system(size: 13, weight: .semibold))
                        Text(model.t("nat.cmp.include_original_desc")).auSmall()
                    }
                    Spacer()
                }
                .padding(.horizontal, 16).padding(.vertical, 12)
                .background(RoundedRectangle(cornerRadius: AU.Radius.card).fill(AU.surface))
                .overlay(RoundedRectangle(cornerRadius: AU.Radius.card).strokeBorder(AU.line))
                Spacer(minLength: 0)
                bar(m)
            } else {
                HStack { Spinner(size: 14); Text(model.t("nat.cmp.loading_models")).auSmall() }
                Spacer()
            }
        }
    }

    private func bar(_ m: CompareModels) -> some View {
        let versions = model.cmp.chosenModels.count + (model.cmp.includeOriginal ? 1 : 0)
        let names = (model.cmp.includeOriginal ? [model.t("nat.cmp.the_original")] : [])
            + ["animevideov3", "cugan-denoise", "cugan", "cugan-conservative"].filter { model.cmp.chosenModels.contains($0) }
                .map { model.t("mot.modello.\($0).label") }
        let seconds = m.models.filter { model.cmp.chosenModels.contains($0.key) }.compactMap(\.clipSeconds).reduce(0, +)
            + (model.cmp.includeOriginal ? (m.referenceSeconds ?? 0) : 0)
        return ActionBar {
            if versions < 2 {
                BarText(title: model.t("nat.cmp.one_version"), line: model.t("nat.cmp.one_version_text"))
            } else {
                BarText(title: model.t("nat.cmp.clips_x_versions", ["c": m.clips, "v": versions]),
                        tail: model.t("nat.cmp.about", ["time": Self.minutes(seconds, model)]),
                        line: model.progress.queue.running ? model.t("nat.cmp.waiting_gpu")
                            : names.joined(separator: model.t("nat.cmp.and")) + model.t("nat.cmp.side_by_side"))
            }
        } trailing: {
            Button(model.t("nat.cmp.back")) { model.cmp.step = .clips }.auButton(.secondary, .regular)
            Button { model.startTest() } label: { Label(model.t("nat.cmp.start_test"), systemImage: "play.fill") }
                .auButton(.primary, .regular)
                .disabled(versions < 2 || model.cmp.chosenModels.isEmpty || model.progress.queue.running || model.calRun?.running == true)
        }
    }

    static func minutes(_ s: Double, _ model: AppModel) -> String {
        let m = max(1, Int((s / 60).rounded()))
        return model.localizer.tn("nat.cmp.minutes", m)
    }
}

/// The "Which model fits which source" box, the row of this file tinted.
struct GuideBand: View {
    @Environment(AppModel.self) private var model
    var sourceHeight: Int

    var body: some View {
        let row = sourceHeight < 380 ? 0 : sourceHeight < 560 ? 1 : 2
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Label(model.t("nat.cmp.guide_title"), systemImage: "info.circle").labelStyle(SmallIconLabel()).auLabel()
                Spacer()
                Button {
                    NSWorkspace.shared.open(URL(string: "https://interstellar0verdrive.github.io/AnimeUp/guide/")!)
                } label: {
                    HStack(spacing: 4) {
                        Text(model.t("nat.cmp.model_guide")).underline()
                        Image(systemName: "arrow.up.right").font(.system(size: 9, weight: .semibold))
                    }
                    .font(.system(size: 12, weight: .medium)).foregroundStyle(AU.primaryText)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 6).padding(.top, 2).padding(.bottom, 4)
            ForEach(0..<3, id: \.self) { i in
                HStack(alignment: .firstTextBaseline, spacing: 14) {
                    Text(model.t("nat.cmp.band\(i)")).font(.system(size: 11.5, design: .monospaced))
                        .foregroundStyle(i == row ? AU.primaryText : AU.text2).frame(width: 110, alignment: .leading)
                    Text(model.t("nat.cmp.band\(i)_model")).font(.system(size: 13, weight: .semibold)).frame(width: 260, alignment: .leading)
                    Text(model.t("nat.cmp.band\(i)_text")).auSmall()
                    Spacer(minLength: 0)
                    if i == row { StatusChip(model.t("nat.cmp.this_file"), tone: .accent) }
                }
                .padding(.horizontal, 8).padding(.vertical, 7)
                .background(RoundedRectangle(cornerRadius: 7).fill(i == row ? AU.soft : .clear))
                .overlay(RoundedRectangle(cornerRadius: 7).strokeBorder(i == row ? AU.softLine : .clear))
            }
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: AU.Radius.card).fill(AU.surface))
        .overlay(RoundedRectangle(cornerRadius: AU.Radius.card).strokeBorder(AU.line))
    }
}

struct ModelCard: View {
    @Environment(AppModel.self) private var model
    var card: CompareModels.Card
    var recommended: Bool
    var topFps: Double
    var outputHeight: Int
    private var on: Bool { model.cmp.chosenModels.contains(card.key) }
    private var disabled: Bool { card.unreachable != nil }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 8) {
                if !disabled { TriCheckbox(state: on ? .on : .off) { toggle() }.padding(.top, 2) }
                VStack(alignment: .leading, spacing: 0) {
                    Text(card.label.hasPrefix("Real-ESRGAN") ? "Real-ESRGAN" : "Real-CUGAN").auSmall(AU.text3)
                    Text(model.shortModel(card.key).replacingOccurrences(of: "CUGAN ", with: ""))
                        .font(.system(size: 14, weight: .semibold)).foregroundStyle(disabled ? AU.text3 : AU.text)
                }
            }
            chip.fixedSize()
            Text(disabled ? model.t("nat.cmp.only_2x", ["h": outputHeight]) : model.t("nat.cmp.card.\(card.key)"))
                .auSmall(disabled ? AU.text3 : AU.text2).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
            if disabled {
                Text(model.t("nat.cmp.not_available")).font(MONO11).foregroundStyle(AU.text3)
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    AUBar((card.fps ?? 0) / topFps, height: 4, fill: AU.text3)
                    HStack {
                        Text(card.fps.map { String(format: "%.1f %@", $0, model.t("nat.cmp.frames_s")) } ?? "—")
                        Spacer()
                        Text(card.estimate.map { Fmt.estimate($0) } ?? "—")
                    }
                    .font(MONO11).foregroundStyle(AU.text2)
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(RoundedRectangle(cornerRadius: AU.Radius.card).fill(on && !disabled ? AU.soft : AU.surface))
        .overlay(RoundedRectangle(cornerRadius: AU.Radius.card).strokeBorder(on && !disabled ? AU.softLine : AU.line))
        .contentShape(Rectangle())
        .onTapGesture { if !disabled { toggle() } }
    }

    @ViewBuilder
    private var chip: some View {
        if let why = card.unreachable {
            StatusChip(why, tone: .red)
        } else if card.verdict == "ok" {
            StatusChip(model.t("nat.chip.recommended"), tone: .green, symbol: "checkmark")
        } else if card.key == "animevideov3" {
            StatusChip(model.t(model.cmp.models.map { $0.sourceHeight >= 560 } == true ? "nat.cmp.tag.av3_high" : "nat.cmp.tag.av3"))
        } else {
            StatusChip(model.t("nat.cmp.tag.\(card.key)"))
        }
    }

    private func toggle() {
        if on { model.cmp.chosenModels.remove(card.key) } else { model.cmp.chosenModels.insert(card.key) }
    }
}

// MARK: - C3 running, C4 results (+ E4, E5)

struct CompareResultsStep: View {
    @Environment(AppModel.self) private var model
    @StateObject private var player = SplitPlayerController()

    var body: some View {
        let st = model.cmp.status
        if let st, st.running {
            RunningCompare(st: st)
        } else if let st, !(st.results ?? []).isEmpty || (st.state != "done" && !(st.segmenti ?? []).isEmpty) {
            results(st)
        } else if let st, st.state == "failed" || st.state == "stopped" || st.state == "interrupted" {
            VStack(alignment: .leading, spacing: 14) {
                NoteView(.red, title: model.t("nat.cmp.stopped_title"), text: (st.failures ?? []).joined(separator: "\n")) {
                    UnderlineLink(model.t("nat.btn.show_log"), tone: .red) { model.openLog(st.log) }
                    Button(model.t("nat.cmp.render_rest")) { model.renderRest() }.buttonStyle(AUTintedButtonStyle(.red))
                }
                Spacer()
            }
        } else {
            VStack { Text(model.t("nat.cmp.no_results")).auSmall(); Spacer() }
        }
    }

    /// Clip tabs: every requested clip, done or not.
    private func clipList(_ st: CompareStatus) -> [(kind: String, range: String, result: CompareStatus.Result?)] {
        let segs = st.segmenti ?? []
        var order: [(String, String)] = []
        for s in segs where !order.contains(where: { $0.1 == s.intervallo }) { order.append((s.tipo, s.intervallo)) }
        if order.isEmpty { order = (st.results ?? []).map { ($0.tipo, $0.intervallo) } }
        return order.map { o in (o.0, o.1, st.results?.first { $0.intervallo == o.1 }) }
    }

    private func results(_ st: CompareStatus) -> some View {
        let clips = clipList(st)
        let tab = min(model.cmp.clipTab, max(0, clips.count - 1))
        let r = clips[tab].result ?? st.results?.first
        let models = st.request?.models ?? []
        let stopped = st.state != "done" || clips.contains { $0.result == nil }
        return VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .bottom, spacing: 2) {
                MaybeScrollH {
                    HStack(alignment: .bottom, spacing: 2) {
                        ForEach(Array(clips.enumerated()), id: \.offset) { i, c in
                            Button { model.cmp.clipTab = i } label: {
                                HStack(alignment: .firstTextBaseline, spacing: 8) {
                                    Text(model.kindName(c.kind)).font(.system(size: 13, weight: .semibold))
                                        .foregroundStyle(i == tab ? AU.text : AU.text2)
                                    if c.result == nil { StatusChip(model.t("nat.chip.stopped"), tone: .red) }
                                    Text(verbatim: c.range).font(MONO11).foregroundStyle(AU.text2)
                                }
                                .padding(.horizontal, 16).padding(.top, 8).padding(.bottom, 9)
                                .background(UnevenRoundedRectangle(topLeadingRadius: 10, topTrailingRadius: 10).fill(i == tab ? AU.surface : .clear))
                                .overlay(UnevenRoundedRectangle(topLeadingRadius: 10, topTrailingRadius: 10)
                                    .strokeBorder(i == tab ? AU.line : .clear))
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.leading, 10)
                }
                Button { if let r { NSWorkspace.shared.open(URL(fileURLWithPath: r.cartella)) } } label: {
                    Label(model.t("nat.cmp.show_clips"), systemImage: "folder")
                }
                .auButton(.plain, .regular).padding(.bottom, 4)
            }
            HStack(alignment: .top, spacing: 14) {
                if let r { playerColumn(r) } else {
                    VStack(spacing: 8) {
                        Image(systemName: "pause.circle").font(.system(size: 28)).foregroundStyle(AU.text3)
                        Text(model.t("nat.cmp.nothing_yet")).auSmall()
                    }
                    .frame(maxWidth: .infinity, minHeight: 260)
                    .background(RoundedRectangle(cornerRadius: 8).fill(AU.inset))
                }
                Rectangle().fill(AU.line).frame(width: 1)
                VStack(alignment: .leading, spacing: 12) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(model.t("nat.cmp.tested_models")).font(.system(size: 13, weight: .semibold))
                        Text(model.t("nat.cmp.tick_note")).auSmall(AU.text3).fixedSize(horizontal: false, vertical: true)
                    }
                    MaybeScroll {
                        VStack(spacing: 12) {
                            ForEach(models, id: \.self) { key in
                                if let m = r?.modelli.first(where: { $0.chiave == key }) {
                                    ResultCard(result: m, inUse: model.plan(model.cmp.fileId ?? "")?.model == key)
                                } else {
                                    FailedCard(key: key, log: st.log)
                                }
                            }
                        }
                    }
                }
                .frame(width: 290)
            }
            .padding(14)
            .background(RoundedRectangle(cornerRadius: AU.Radius.card).fill(AU.surface))
            .overlay(RoundedRectangle(cornerRadius: AU.Radius.card).strokeBorder(AU.line))
            .padding(.bottom, 14)
            ActionBar {
                HStack(spacing: 10) {
                    if stopped {
                        StatusChip(model.t("nat.chip.stopped"), tone: .red)
                        BarText(title: model.t("nat.cmp.test_stopped"), tail: stoppedTail(clips, st),
                                line: model.t("nat.cmp.test_stopped_text"))
                    } else {
                        StatusChip(model.t("nat.chip.done"), tone: .green, symbol: "checkmark")
                        BarText(title: model.t("nat.cmp.test_ready"),
                                tail: model.localizer.tn("nat.cmp.clips_in", clips.count, ["time": Fmt.clock((st.ended ?? 0) - (st.started ?? 0))]),
                                line: model.t("nat.cmp.one_off"))
                    }
                }
            } trailing: {
                if stopped {
                    Button(model.t("nat.cmp.render_rest")) { model.renderRest() }.auButton(.secondary, .regular)
                }
                Button { model.tab = .queue; model.expanded = model.cmp.fileId } label: {
                    HStack(spacing: 5) { Text(model.t("nat.cmp.next_queue")); Image(systemName: "arrow.right") }
                }
                .auButton(.primary, .regular)
            }
        }
        .sheet(isPresented: Binding(get: { model.cmp.showUseMany }, set: { model.cmp.showUseMany = $0 })) {
            UseManySheet().environment(model).preferredColorScheme(.dark)
        }
    }

    private func stoppedTail(_ clips: [(kind: String, range: String, result: CompareStatus.Result?)], _ st: CompareStatus) -> String {
        clips.map { c in
            c.result != nil ? model.t("nat.cmp.clip_complete", ["kind": model.kindName(c.kind)])
                : model.t("nat.cmp.clip_missing", ["kind": model.kindName(c.kind)])
        }.joined(separator: ", ")
    }

    private func playerColumn(_ r: CompareStatus.Result) -> some View {
        let keys = ["original", "animevideov3", "cugan-denoise", "cugan", "cugan-conservative"].filter { r.file[$0] != nil }
        return VStack(spacing: 10) {
            HStack(spacing: 10) {
                versionPicker(keys, side: "L", selection: Binding(get: { model.cmp.left }, set: { model.cmp.left = $0 }))
                Spacer()
                Button { let l = model.cmp.left; model.cmp.left = model.cmp.right; model.cmp.right = l } label: {
                    Label(model.t("nat.cmp.swap"), systemImage: "arrow.left.arrow.right")
                }
                .auButton(.plain, .regular)
                Spacer()
                versionPicker(keys, side: "R", selection: Binding(get: { model.cmp.right }, set: { model.cmp.right = $0 }))
            }
            SplitPlayerView(controller: player)
                .frame(minHeight: 200)
                .aspectRatio(16 / 9, contentMode: .fit)
                .clipShape(RoundedRectangle(cornerRadius: 8))
            HStack(spacing: 12) {
                Button { player.toggle() } label: { Image(systemName: player.playing ? "pause.fill" : "play.fill") }
                    .buttonStyle(AUButtonStyle(.secondary, size: .regular, iconOnly: true))
                Text(Fmt.clockTenths(player.time)).font(MONO11).foregroundStyle(AU.text2)
                Slider(value: Binding(get: { player.time }, set: { player.seek($0) }), in: 0...max(0.1, player.duration))
                    .controlSize(.small).tint(AU.primary)
                Text(Fmt.clockTenths(player.duration)).font(MONO11).foregroundStyle(AU.text2)
                Button { player.oneToOne.toggle() } label: { Label("1:1", systemImage: "arrow.up.left.and.arrow.down.right") }
                    .auButton(.plain, .regular)
                    .background(Capsule().fill(player.oneToOne ? AU.sel : .clear))
            }
        }
        .frame(maxWidth: .infinity)
        .task(id: "\(r.intervallo)|\(model.cmp.left)|\(model.cmp.right)") { await load(r) }
    }

    private func versionPicker(_ keys: [String], side: String, selection: Binding<String>) -> some View {
        HStack(spacing: 8) {
            if side == "L" { SideTag(side) }
            Menu {
                ForEach(keys, id: \.self) { k in Button(versionName(k)) { selection.wrappedValue = k } }
            } label: {
                PopupLabel(versionName(selection.wrappedValue), width: 220, height: 26, size: 12)
            }
            .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize()
            if side == "R" { SideTag(side) }
        }
    }

    private func versionName(_ k: String) -> String {
        k == "original" ? model.t("nat.cmp.original") : model.t("mot.modello.\(k).label")
    }

    private func load(_ r: CompareStatus.Result) async {
        var urls: [URL?] = [nil, nil]
        for (i, key) in [model.cmp.left, model.cmp.right].enumerated() {
            guard let path = r.file[key] else { continue }
            if let mp4 = try? await model.engine.playable(path) { urls[i] = URL(fileURLWithPath: mp4) }
        }
        player.load(left: urls[0], right: urls[1])
    }
}

struct SideTag: View {
    var side: String
    init(_ side: String) { self.side = side }
    var body: some View {
        Text(side).font(.system(size: 10.5, weight: .semibold, design: .monospaced)).foregroundStyle(AU.onPrimary)
            .padding(.horizontal, 6).padding(.vertical, 1)
            .background(RoundedRectangle(cornerRadius: 4).fill(AU.primary))
    }
}

/// C3: each version appears as soon as it's ready.
struct RunningCompare: View {
    @Environment(AppModel.self) private var model
    var st: CompareStatus

    var body: some View {
        let segs = st.segmenti ?? []
        var clips: [(String, String, String)] = []   // kind, range, tc
        for s in segs where !clips.contains(where: { $0.1 == s.intervallo }) { clips.append((s.tipo, s.intervallo, s.tc)) }
        let done = st.done ?? 0
        let currentClip = done < segs.count ? segs[done].intervallo : clips.last?.1
        let total = max(1, segs.count)
        return VStack(alignment: .leading, spacing: 12) {
            MaybeScroll {
                VStack(spacing: 12) {
                    ForEach(Array(clips.enumerated()), id: \.offset) { _, c in
                        let mine = segs.enumerated().filter { $0.element.intervallo == c.1 }
                        let ready = mine.filter { $0.offset < done }.count
                        if c.1 == currentClip {
                            VStack(spacing: 0) {
                                HStack(alignment: .firstTextBaseline, spacing: 10) {
                                    Text(model.kindName(c.0)).font(.system(size: 14, weight: .semibold))
                                    Text(verbatim: c.1).font(.system(size: 12, design: .monospaced)).foregroundStyle(AU.textCode)
                                    Spacer()
                                    Text(model.t("nat.cmp.n_ready", ["i": ready, "n": mine.count])).font(MONO11).foregroundStyle(AU.primaryText)
                                }
                                .padding(.horizontal, 16).padding(.vertical, 12)
                                Rectangle().fill(AU.line).frame(height: 1)
                                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 14), count: max(2, min(3, mine.count))), spacing: 14) {
                                    ForEach(mine, id: \.offset) { item in
                                        versionTile(item.element, index: item.offset, done: done, partial: st.parziali?["\(c.0)|\(c.2)"]?[item.element.chiave])
                                    }
                                }
                                .padding(14)
                                .background(AU.inset)
                            }
                            .background(RoundedRectangle(cornerRadius: AU.Radius.card).fill(AU.surface))
                            .clipShape(RoundedRectangle(cornerRadius: AU.Radius.card))
                            .overlay(RoundedRectangle(cornerRadius: AU.Radius.card).strokeBorder(AU.line))
                        } else {
                            HStack(alignment: .firstTextBaseline, spacing: 10) {
                                Text(model.kindName(c.0)).font(.system(size: 14, weight: .semibold))
                                Text(verbatim: c.1).font(.system(size: 12, design: .monospaced)).foregroundStyle(AU.text2)
                                Spacer()
                                Text(ready == mine.count ? model.t("nat.cmp.all_ready") : model.t("nat.cmp.waiting_clip"))
                                    .font(MONO11).foregroundStyle(ready == mine.count ? AU.greenText : AU.text3)
                            }
                            .padding(.horizontal, 16).padding(.vertical, 12)
                            .overlay(RoundedRectangle(cornerRadius: AU.Radius.card).strokeBorder(AU.line))
                        }
                    }
                }
            }
            ActionBar(accent: true) {
                VStack(alignment: .leading, spacing: 8) {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(model.t("nat.cmp.testing_clips")).font(.system(size: 13, weight: .semibold))
                        Text(model.t("nat.cmp.of_whole", ["pct": Int(((st.quota ?? 0) * 100).rounded())])).auSmall()
                        Spacer()
                        Text(model.t("nat.cmp.version_of", ["i": min(done + 1, total), "n": total])).font(MONO11).foregroundStyle(AU.text2)
                    }
                    PiecedTestBar(segments: segs, done: done, fraction: st.fraction ?? 0)
                }
            } trailing: {
                Button { model.stopTest() } label: { Label(model.t("nat.run.stop"), systemImage: "stop.fill") }
                    .auButton(.destructive, .regular)
            }
        }
    }

    @ViewBuilder
    private func versionTile(_ s: CompareStatus.Segment, index: Int, done: Int, partial: String?) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            ZStack {
                if index < done, let partial, let img = NSImage(contentsOfFile: partial) {
                    Image(nsImage: img).resizable().aspectRatio(contentMode: .fill)
                } else if index < done {
                    RoundedRectangle(cornerRadius: 8).fill(AU.raised)
                    Image(systemName: "checkmark").foregroundStyle(AU.greenText)
                } else {
                    RoundedRectangle(cornerRadius: 8).strokeBorder(index == done ? AU.softLine : AU.line, style: StrokeStyle(lineWidth: 1, dash: [4, 3]))
                    VStack(spacing: 10) {
                        Text(model.t(index == done ? "nat.cmp.rendering" : "nat.cmp.waiting_clip")).font(.system(size: 13, weight: .semibold))
                        if index == done {
                            AUBar(st.fraction ?? 0, height: 6)
                            Text("\(Int(((st.fraction ?? 0) * 100).rounded()))%").font(MONO11).foregroundStyle(AU.text2)
                        }
                    }
                    .padding(.horizontal, 48)
                }
            }
            .frame(height: 170)
            .clipShape(RoundedRectangle(cornerRadius: 8))
            HStack(spacing: 6) {
                if index < done { Image(systemName: "checkmark").font(.system(size: 10, weight: .semibold)).foregroundStyle(AU.greenText) }
                Text(s.chiave == "original" ? model.t("nat.cmp.original_plain") : model.t("mot.modello.\(s.chiave).label"))
                    .font(.system(size: 12)).foregroundStyle(AU.textCode)
            }
        }
    }
}

/// The 6 pt test bar: one piece per clip, split per version by its weight.
struct PiecedTestBar: View {
    var segments: [CompareStatus.Segment]
    var done: Int
    var fraction: Double

    var body: some View {
        let clips = segments.map(\.intervallo).reduce(into: [String]()) { if !$0.contains($1) { $0.append($1) } }
        GeometryReader { g in
            HStack(spacing: 3) {
                ForEach(clips, id: \.self) { clip in
                    let mine = segments.enumerated().filter { $0.element.intervallo == clip }
                    let weight = mine.reduce(0.0) { $0 + max(0.01, $1.element.peso) }
                    let total = max(0.01, segments.reduce(0.0) { $0 + max(0.01, $1.peso) })
                    HStack(spacing: 1.5) {
                        ForEach(mine, id: \.offset) { item in
                            let f = item.offset < done ? 1 : item.offset == done ? fraction : 0
                            ZStack(alignment: .leading) {
                                Rectangle().fill(AU.trackSoft)
                                GeometryReader { gg in Rectangle().fill(AU.primary).frame(width: gg.size.width * f) }
                            }
                            .frame(width: max(2, (g.size.width - CGFloat(clips.count - 1) * 3) * item.element.peso / total - 1.5))
                        }
                    }
                    .frame(width: (g.size.width - CGFloat(clips.count - 1) * 3) * weight / total, alignment: .leading)
                    .clipShape(RoundedRectangle(cornerRadius: 3))
                }
            }
        }
        .frame(height: 6)
    }
}

struct ResultCard: View {
    @Environment(AppModel.self) private var model
    var result: CompareStatus.Result.ModelTime
    var inUse: Bool

    private var side: String? {
        model.cmp.left == result.chiave ? "L" : model.cmp.right == result.chiave ? "R" : nil
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Text(model.t("mot.modello.\(result.chiave).label")).font(.system(size: 13, weight: .semibold))
                Spacer()
                if let side { SideTag(side) }
            }
            HStack(alignment: .firstTextBaseline) {
                Text("\(Text(model.t("nat.cmp.this_clip")).foregroundStyle(AU.text2)) \(Text(Fmt.span(max(60, result.secondi))).font(.system(size: 13, weight: .semibold, design: .monospaced)))")
                Spacer()
                Text("\(Text(model.t("nat.cmp.full_episode")).foregroundStyle(AU.text2)) \(Text(Fmt.estimate(result.intero)).font(.system(size: 13, weight: .semibold, design: .monospaced)))")
            }
            .font(.system(size: 12))
            if let m = result.metriche, m.count == 2 {
                metric(model.t("nat.cmp.detail"), m[0], AU.primary)
                metric(model.t("nat.cmp.noise"), m[1], AU.yellow)
            }
            VStack(spacing: 6) {
                if inUse {
                    Label(model.t("nat.cmp.in_use"), systemImage: "checkmark").labelStyle(SmallIconLabel())
                        .font(.system(size: 12, weight: .medium)).foregroundStyle(AU.greenText)
                        .frame(maxWidth: .infinity).frame(height: 24)
                        .background(Capsule().fill(AU.greenBg)).overlay(Capsule().strokeBorder(AU.greenLine))
                } else {
                    Button(model.t("nat.cmp.use_this")) { if let id = model.cmp.fileId { model.useModel(result.chiave, for: [id]) } }
                        .auButton(.secondary, .small, fullWidth: true)
                }
                Button(model.t("nat.cmp.use_many")) { model.cmp.useKey = result.chiave; model.cmp.showUseMany = true }
                    .auButton(.secondary, .small, fullWidth: true)
            }
            .padding(.top, 4)
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 8).fill(side != nil ? AU.soft : AU.raised))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(side != nil ? AU.softLine : AU.chipLine))
    }

    /// The bar with the 100 % tick in the middle (200 % fills it).
    private func metric(_ name: String, _ value: Double?, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Text(name).font(.system(size: 12)).foregroundStyle(AU.text2)
                Spacer()
                Text(value.map { "\(Int(($0 * 100).rounded()))%" } ?? "—").font(MONO11).foregroundStyle(AU.textCode)
            }
            GeometryReader { g in
                ZStack(alignment: .leading) {
                    Capsule().fill(AU.trackSoft).frame(height: 5)
                    Capsule().fill(color).frame(width: g.size.width * min(1, (value ?? 0) / 2), height: 5)
                    Rectangle().fill(AU.text).frame(width: 2, height: 11).offset(x: g.size.width / 2 - 1)
                }
                .frame(height: 11)
            }
            .frame(height: 11)
        }
    }
}

/// E4: a version that failed on this clip.
struct FailedCard: View {
    @Environment(AppModel.self) private var model
    var key: String
    var log: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(model.t("mot.modello.\(key).label")).font(.system(size: 13, weight: .semibold)).foregroundStyle(AU.redText)
            Text(model.t("nat.cmp.render_failed")).auSmall(AU.redText).fixedSize(horizontal: false, vertical: true)
            HStack {
                Button(model.t("nat.btn.retry")) { model.renderRest() }.buttonStyle(AUTintedButtonStyle(.red))
                Spacer()
                UnderlineLink(model.t("nat.btn.show_log"), tone: .red) { model.openLog(log) }
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 8).fill(AU.redBg))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(AU.redLine))
    }
}

/// C5: Use for Multiple Files (compare_sheet.py).
struct UseManySheet: View {
    @Environment(AppModel.self) private var model
    @State private var picked: Set<String> = []

    var body: some View {
        let key = model.cmp.useKey
        let rows = model.files.filter { $0.state == .ready }
        VStack(alignment: .leading, spacing: 14) {
            Text(model.t("nat.cmp.use_many_title", ["model": model.t("mot.modello.\(key).label")])).font(.system(size: 15, weight: .semibold))
            Text(model.t("nat.cmp.use_many_text")).auSmall()
            HStack(spacing: 12) {
                TriCheckbox(state: picked.isEmpty ? .off : picked.count == rows.count ? .on : .mixed) {
                    picked = picked.isEmpty ? Set(rows.filter { model.plans[$0.id]?.model != key }.map(\.id)) : []
                }
                Text(model.t("nat.cmp.file_select_all")).frame(maxWidth: .infinity, alignment: .leading)
                Text(model.t("nat.cmp.source")).frame(width: 72, alignment: .trailing)
                Text(model.t("nat.cmp.now_after")).frame(width: 220, alignment: .trailing)
            }
            .auLabel().padding(.horizontal, 12)
            VStack(spacing: 4) {
                ForEach(rows) { f in
                    let plan = model.plans[f.id]
                    let already = plan?.model == key
                    let poor = plan?.option(key)?.verdict == "no" || plan?.option(key)?.unreachable != nil
                    HStack(spacing: 12) {
                        TriCheckbox(state: picked.contains(f.id) ? .on : .off) {
                            if picked.contains(f.id) { picked.remove(f.id) } else { picked.insert(f.id) }
                        }
                        .disabled(already || plan?.option(key)?.unreachable != nil)
                        Text(f.name).font(.system(size: 12, weight: .medium)).lineLimit(1).frame(maxWidth: .infinity, alignment: .leading)
                        Text(verbatim: f.report.map { "\($0.width)×\($0.height)" } ?? "").font(.system(size: 11.5, design: .monospaced))
                            .foregroundStyle(AU.textCode).frame(width: 72, alignment: .trailing)
                        Group {
                            if picked.contains(f.id) {
                                HStack(spacing: 6) {
                                    Text(model.shortModel(plan?.model ?? "")).foregroundStyle(AU.text3)
                                    Image(systemName: "arrow.right").font(.system(size: 8)).foregroundStyle(AU.text3)
                                    Text(model.shortModel(key)).foregroundStyle(AU.primaryText)
                                }
                                .font(.system(size: 11.5, design: .monospaced))
                            } else if already {
                                Text(model.t("nat.cmp.already_uses")).auSmall(AU.text3)
                            } else if let why = plan?.option(key)?.unreachable {
                                Text(why).auSmall(AU.redText)
                            } else if poor {
                                Label(model.t("nat.cmp.poor_fit", ["h": f.report?.height ?? 0]), systemImage: "exclamationmark.triangle.fill")
                                    .labelStyle(SmallIconLabel()).auSmall(AU.redText)
                            } else {
                                Text(model.shortModel(plan?.model ?? "")).font(.system(size: 11.5, design: .monospaced)).foregroundStyle(AU.text3)
                            }
                        }
                        .frame(width: 220, alignment: .trailing)
                    }
                    .padding(.horizontal, 12).frame(height: 36)
                    .background(RoundedRectangle(cornerRadius: 7).fill(picked.contains(f.id) ? AU.soft : poor && !already ? AU.redSoft : .clear))
                    .overlay(RoundedRectangle(cornerRadius: 7).strokeBorder(poor && !already && !picked.contains(f.id) ? AU.redLine : .clear))
                }
            }
            HStack(spacing: 8) {
                Spacer()
                Button(model.t("nat.btn.cancel")) { model.cmp.showUseMany = false }.auButton(.secondary, .regular)
                Button(model.localizer.tn("nat.cmp.use_for_n", picked.count)) {
                    model.useModel(key, for: Array(picked))
                    model.cmp.showUseMany = false
                }
                .auButton(.primary, .regular).disabled(picked.isEmpty)
            }
            .padding(.top, 6)
        }
        .padding(20)
        .frame(width: 620)
        .background(AU.bg)
        .onAppear {
            picked = Set(rows.filter { f in
                let p = model.plans[f.id]
                return p?.model != key && p?.option(key)?.verdict != "no" && p?.option(key)?.unreachable == nil
            }.map(\.id))
        }
    }
}
