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

private let MONO11 = AUTextStyle(11, mono: true)

/// Boards C1–C5 and E1–E8 (generators ds/compare.py, compare_sheet.py, edge.py).
struct CompareView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.auPageTop) private var pageTop

    private var running: Bool { model.cmp.status?.running == true }

    /// Videos there, none analysed yet, some still being analysed: nothing to test so far.
    private var waitingForAnalysis: Bool {
        !model.files.isEmpty && !model.files.contains { $0.state == .ready }
            && model.files.contains { $0.state == .analysing || $0.state == .queued }
    }

    var body: some View {
        if model.files.isEmpty || waitingForAnalysis {
            // Boards E0 and E0c: header and steps scroll together when the window is low.
            CompareEmptyView(analysing: waitingForAnalysis) { header }
                .ignoresSafeArea(edges: .top)
                .onAppear { model.openCompare() }
        } else {
            work
        }
    }

    /// With videos the title stays and only the step's content scrolls.
    private var work: some View {
        VStack(alignment: .leading, spacing: 16) {
            header
            if model.compareFiles.isEmpty {
                NoteView(.accent, title: model.t("nat.cmp.no_files_title"), text: model.t("nat.cmp.no_files"))
                Spacer()
            } else {
                stepRow
                // The results show the clips instead (boards C4, E4, E5).
                if model.cmp.step != .results || running { FileStrip(disabled: running) }
                switch model.cmp.step {
                case .clips: CompareClipsStep()
                case .models: CompareModelsStep()
                case .results: CompareResultsStep()
                }
            }
        }
        .padding(.top, pageTop)
        .padding(.horizontal, 28)
        .padding(.bottom, 28)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .ignoresSafeArea(edges: .top)
        .onAppear { model.openCompare() }
    }

    private var introKey: String {
        if running { return "nat.cmp.intro_running" }
        return model.cmp.step == .results ? "nat.cmp.intro_results" : "nat.cmp.intro"
    }

    private var header: some View {
        PageHeader(model.t("nat.tab.compare"), model.t(introKey + "1"), model.t(introKey + "2"))
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
        let notes = [model.localizer.tn("nat.cmp.n_picked", model.cmp.selected.count),
                     original ? model.t("nat.cmp.original_plus", ["n": versions]) : model.localizer.tn("nat.cmp.n_models", versions)]
        // A narrow window drops the small notes ("2 picked") before a label would wrap (31 Oct: at 780 pt
        // "Clips" broke as "Clip/s").
        ViewThatFits(in: .horizontal) {
            pills(step, running, notes)
            pills(step, running, ["", ""])
        }
        .fixedSize(horizontal: false, vertical: true)
    }

    private func pills(_ step: CompareState.Step, _ running: Bool, _ notes: [String]) -> some View {
        HStack(spacing: 8) {
            pill(0, model.t("nat.cmp.step.0"), state(0, step), note: notes[0])
            chevron
            pill(1, model.t("nat.cmp.step.1"), state(1, step), note: notes[1])
            chevron
            pill(2, model.t("nat.cmp.step.2"), running ? "busy" : state(2, step), note: "")
        }
    }

    private var chevron: some View {
        Image(systemName: "chevron.right").auFont(8, .semibold).foregroundStyle(AU.text3)
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
                    Image(systemName: "checkmark").auFont(9, .bold).foregroundStyle(AU.greenText)
                case "now":
                    Circle().fill(AU.primary)
                    Text("\(i + 1)").auFont(12, .semibold).foregroundStyle(AU.onPrimary)
                case "busy":
                    Spinner(size: 20)
                default:
                    Circle().strokeBorder(AU.glassLine)
                    Text("\(i + 1)").auFont(12, .semibold).foregroundStyle(AU.text2)
                }
            }
            .frame(width: 22, height: 22)
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(label).auFont(13, st == "next" ? .regular : .semibold)
                if st == "done" && !note.isEmpty { Text(note).auFont(MONO11) }
            }
            .foregroundStyle(st == "done" ? AU.greenText : st == "next" ? AU.text2 : AU.text)
        }
        .lineLimit(1)
        .fixedSize()
        .padding(.leading, 4).padding(.trailing, 12)
        .frame(height: 30)
        .background(Capsule().fill(st == "done" ? AU.greenBg : (st == "now" || st == "busy") ? AU.sel : .clear))
        .overlay(Capsule().strokeBorder(st == "done" ? AU.greenLine : (st == "now" || st == "busy") ? AU.softLine : AU.line))
        .contentShape(Capsule())
        .auHover(Capsule(), enabled: st == "done" && model.cmp.status?.running != true)
        .onTapGesture {
            if st == "done" && model.cmp.status?.running != true { model.cmp.step = CompareState.Step(rawValue: i) ?? .clips }
        }
    }
}

/// compare.py `filestrip()`: File to test (360 pt) | Source | Output | Full episode.
struct FileStrip: View {
    @Environment(AppModel.self) private var model
    var disabled: Bool
    @State private var narrow = false

    var body: some View {
        let f = model.files.first { $0.id == model.cmp.fileId }
        let plan = model.plan(model.cmp.fileId ?? "")
        // 360 pt for the file (board C1); less when the page is narrow, so the values stay whole.
        strip(f, plan, fileWidth: narrow ? 250 : 360)
            .frame(minWidth: 0, maxWidth: .infinity)
            .onGeometryChange(for: Bool.self) { $0.size.width < 800 } action: { narrow = $0 }
    }

    private func strip(_ f: QueueFile?, _ plan: FilePlan?, fileWidth: CGFloat) -> some View {
        HStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 6) {
                Text(model.t("nat.cmp.file")).auLabel()
                PopupMenu({
                    model.compareFiles.map { file in
                        .item(file.state == .ready ? file.name : "\(file.name) — \(model.t("nat.cmp.analysing"))",
                              checked: file.id == f?.id, enabled: file.state == .ready) { model.selectCompareFile(file.id) }
                    }
                }) {
                    PopupLabel(f?.name ?? model.t("nat.cmp.pick_file"), width: fileWidth - 28, height: 26, size: 12)
                }
                .fixedSize()
                .disabled(disabled)
                .opacity(disabled ? 0.4 : 1)
            }
            .padding(.vertical, 10).padding(.horizontal, 14)
            .frame(width: fileWidth, alignment: .leading)
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
                Text(verbatim: value).auFont(15, mono: true).foregroundStyle(AU.text).frame(height: 26)
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
        .auBox(RoundedRectangle(cornerRadius: AU.Radius.card), fill: AU.surface, line: accent ? AU.softLine : AU.line,
               padding: EdgeInsets(vertical: 12, horizontal: 16))
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
                .auFont(13)
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
    /// Four clips a row (board C1); three when the page is narrow.
    @State private var perRow = 4
    private var columns: [GridItem] { Array(repeating: GridItem(.flexible(), spacing: 12), count: perRow) }

    var body: some View {
        let f = model.files.first { $0.id == model.cmp.fileId }
        let duration = f?.report?.duration ?? 0
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Text(model.t("nat.cmp.pick_title")).auFont(AUFont.sectionTitle)
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
                    .frame(minWidth: 0, maxWidth: .infinity)
                    .onGeometryChange(for: Int.self) { $0.size.width < 860 ? 3 : 4 } action: { perRow = $0 }
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
            // The picture fills a fixed frame as an overlay: inside a ZStack it widened
            // the stack, and the time, pinned to its corner, ended up clipped away.
            Rectangle().fill(AU.inset)
                .frame(height: 118)
                .overlay {
                    if let path = clip.thumbnail, let img = NSImage(contentsOfFile: path) {
                        Image(nsImage: img).resizable().aspectRatio(contentMode: .fill)
                    }
                }
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .overlay(alignment: .bottomTrailing) {
                    Text(verbatim: clip.range).auFont(10.5, mono: true).foregroundStyle(.white)
                        .padding(.horizontal, 6).padding(.vertical, 1)
                        .background(RoundedRectangle(cornerRadius: 4).fill(.black.opacity(0.55)))
                        .padding(6)
                }
            HStack(spacing: 8) {
                TriCheckbox(state: on ? .on : .off) { toggle() }
                Text(model.kindName(clip.kind)).auFont(13, .semibold).foregroundStyle(AU.text)
                Spacer(minLength: 4)
                Text(model.kindTests(clip.kind)).auSmall().lineLimit(1)
            }
        }
        .auBox(RoundedRectangle(cornerRadius: AU.Radius.card), fill: on ? AU.soft : AU.surface, line: on ? AU.softLine : AU.line,
               padding: EdgeInsets(vertical: 10, horizontal: 10))
        .contentShape(Rectangle())
        .auHover(RoundedRectangle(cornerRadius: AU.Radius.card))
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
    @State private var modelsPerRow = 4

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if let m = model.cmp.models {
                // In a short or narrow window the cards scroll; the bar stays put.
                ViewThatFits(in: .vertical) {
                    choices(m)
                    ScrollView { choices(m) }.scrollBounceBehavior(.basedOnSize)
                }
                Spacer(minLength: 0)
                bar(m)
            } else {
                HStack { Spinner(size: 14); Text(model.t("nat.cmp.loading_models")).auSmall() }
                Spacer()
            }
        }
    }

    private func choices(_ m: CompareModels) -> some View {
        VStack(alignment: .leading, spacing: 16) {
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
            // One row of four (board C2); two rows of two when the page is narrow.
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 12, alignment: .top), count: modelsPerRow), spacing: 12) {
                ForEach(m.models) { card in ModelCard(card: card, recommended: card.key == m.recommended, topFps: top, outputHeight: m.height) }
            }
            .frame(minWidth: 0, maxWidth: .infinity)
            .onGeometryChange(for: Int.self) { $0.size.width < 860 ? 2 : 4 } action: { modelsPerRow = $0 }
            HStack(spacing: 14) {
                Toggle("", isOn: Binding(get: { model.cmp.includeOriginal }, set: { model.cmp.includeOriginal = $0 }))
                    .toggleStyle(.switch).labelsHidden().tint(AU.primary)
                VStack(alignment: .leading, spacing: 2) {
                    Text(model.t("nat.cmp.include_original")).auFont(13, .semibold)
                    Text(model.t("nat.cmp.include_original_desc")).auSmall()
                }
                Spacer()
            }
            .auBox(RoundedRectangle(cornerRadius: AU.Radius.card), fill: AU.surface, line: AU.line,
                   padding: EdgeInsets(vertical: 12, horizontal: 16))
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
                        Image(systemName: "arrow.up.right").auFont(9, .semibold)
                    }
                    .auFont(12, .medium).foregroundStyle(AU.primaryText)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 6).padding(.top, 2).padding(.bottom, 4)
            ForEach(0..<3, id: \.self) { i in
                HStack(alignment: .firstTextBaseline, spacing: 14) {
                    Text(model.t("nat.cmp.band\(i)")).auFont(11.5, mono: true)
                        .foregroundStyle(i == row ? AU.primaryText : AU.text2).frame(width: 110, alignment: .leading)
                    Text(model.t("nat.cmp.band\(i)_model")).auFont(13, .semibold).frame(width: 260, alignment: .leading)
                    Text(model.t("nat.cmp.band\(i)_text")).auSmall()
                    Spacer(minLength: 0)
                    if i == row { StatusChip(model.t("nat.cmp.this_file"), tone: .accent) }
                }
                .auBox(RoundedRectangle(cornerRadius: 7), fill: i == row ? AU.soft : .clear, line: i == row ? AU.softLine : .clear,
                       padding: EdgeInsets(vertical: 7, horizontal: 8))
            }
        }
        .auBox(RoundedRectangle(cornerRadius: AU.Radius.card), fill: AU.surface, line: AU.line,
               padding: EdgeInsets(vertical: 10, horizontal: 10))
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
                        .auFont(14, .semibold).foregroundStyle(disabled ? AU.text3 : AU.text)
                }
            }
            chip.fixedSize()
            Text(disabled ? model.t("nat.cmp.only_2x", ["h": outputHeight]) : model.t("nat.cmp.card.\(card.key)"))
                .auSmall(disabled ? AU.text3 : AU.text2).fixedSize(horizontal: false, vertical: true)
            // CSS `margin-top: auto`: the footer goes to the bottom with one 10 pt gap,
            // not the two a Spacer between spaced rows would add.
            Group {
                if disabled {
                    Text(model.t("nat.cmp.not_available")).auFont(MONO11).foregroundStyle(AU.text3)
                } else {
                    VStack(alignment: .leading, spacing: 6) {
                    AUBar((card.fps ?? 0) / topFps, height: 4, fill: AU.text3)
                    HStack {
                        Text(card.fps.map { String(format: "%.1f %@", $0, model.t("nat.cmp.frames_s")) } ?? "—")
                        Spacer()
                        Text(card.estimate.map { Fmt.estimate($0) } ?? "—")
                    }
                    .auFont(MONO11).foregroundStyle(AU.text2)
                }
                }
            }
            .frame(maxHeight: .infinity, alignment: .bottom)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .auBox(RoundedRectangle(cornerRadius: AU.Radius.card), fill: on && !disabled ? AU.soft : AU.surface, line: on && !disabled ? AU.softLine : AU.line,
               padding: EdgeInsets(vertical: 14, horizontal: 14))
        .contentShape(Rectangle())
        .auHover(RoundedRectangle(cornerRadius: AU.Radius.card), enabled: !disabled)
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
    /// The frame is too narrow for the 290 pt models column beside the player:
    /// the models go under it, and the frame scrolls.
    @State private var compact = false
    @State private var frameWidth: CGFloat = 0
    static let compactBelow: CGFloat = 780
    /// Picker row, bar and their gaps around the picture in the player column.
    static let playerControls: CGFloat = 26 + 10 + 28 + 10

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
                                    Text(model.kindName(c.kind)).auFont(13, .semibold)
                                        .foregroundStyle(i == tab ? AU.text : AU.text2)
                                    if c.result == nil { StatusChip(model.t("nat.chip.stopped"), tone: .red) }
                                    Text(verbatim: c.range).auFont(MONO11).foregroundStyle(AU.text2)
                                }
                                .padding(.horizontal, 16).padding(.top, 8).padding(.bottom, 9)
                                .background(UnevenRoundedRectangle(topLeadingRadius: 10, topTrailingRadius: 10).fill(i == tab ? AU.surface : .clear))
                                // Open at the bottom: the current tab runs into the panel under it.
                                .overlay(TabOutline(radius: 10).stroke(i == tab ? AU.line : .clear, lineWidth: 1))
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.leading, 10)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                Button { if let r { NSWorkspace.shared.open(URL(fileURLWithPath: r.cartella)) } } label: {
                    Label(model.t("nat.cmp.show_clips"), systemImage: "folder")
                }
                .auButton(.plain, .regular).padding(.bottom, 4)
            }
            // 1 pt over the panel: the current tab's fill hides the panel's top line under it.
            .padding(.bottom, -1)
            .zIndex(1)
            Group {
                if compact {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 18) {
                            playerArea(r).frame(height: frameWidth * 9 / 16 + Self.playerControls)
                            modelsHeader
                            LazyVGrid(columns: [GridItem(.adaptive(minimum: 250), spacing: 12, alignment: .top)], spacing: 12) {
                                modelCards(models, r: r, st: st)
                            }
                        }
                    }
                    .scrollBounceBehavior(.basedOnSize)
                } else {
                    HStack(alignment: .top, spacing: 14) {
                        playerArea(r)
                        VStack(alignment: .leading, spacing: 12) {
                            modelsHeader
                            MaybeScroll { VStack(spacing: 12) { modelCards(models, r: r, st: st) } }
                        }
                        // 290 pt with its rule and the 14 pt in front of it.
                        .padding(.leading, 14)
                        .overlay(alignment: .leading) { Rectangle().fill(AU.line).frame(width: 1) }
                        .frame(width: 290)
                    }
                }
            }
            // Measured on the width the page offers, not on what the content would like.
            .frame(minWidth: 0, maxWidth: .infinity)
            .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { frameWidth = $0; compact = $0 < Self.compactBelow }
            .frame(maxHeight: .infinity)
            .auBox(RoundedRectangle(cornerRadius: AU.Radius.card), fill: AU.surface, line: AU.line,
                   padding: EdgeInsets(vertical: 14, horizontal: 14))
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

    @ViewBuilder private func playerArea(_ r: CompareStatus.Result?) -> some View {
        if let r { playerColumn(r) } else {
            VStack(spacing: 8) {
                Image(systemName: "pause.circle").auFont(28).foregroundStyle(AU.text3)
                Text(model.t("nat.cmp.nothing_yet")).auSmall()
            }
            .frame(maxWidth: .infinity, minHeight: 260)
            .background(RoundedRectangle(cornerRadius: 8).fill(AU.inset))
        }
    }

    private var modelsHeader: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(model.t("nat.cmp.tested_models")).auFont(13, .semibold)
            Text(model.t("nat.cmp.tick_note")).auSmall(AU.text3).fixedSize(horizontal: false, vertical: true)
        }
    }

    @ViewBuilder private func modelCards(_ models: [String], r: CompareStatus.Result?, st: CompareStatus) -> some View {
        ForEach(models, id: \.self) { key in
            if let m = r?.modelli.first(where: { $0.chiave == key }) {
                ResultCard(result: m, inUse: model.plan(model.cmp.fileId ?? "")?.model == key)
            } else if !(st.failures ?? []).isEmpty {
                FailedCard(key: key, log: st.log)
            } else {
                PendingCard(key: key)
            }
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
                .overlay { SplitPlayerChrome(controller: player) }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .frame(minHeight: 200)
                .clipShape(RoundedRectangle(cornerRadius: 8))
            HStack(spacing: 12) {
                Button { player.toggle() } label: { Image(systemName: player.playing ? "pause.fill" : "play.fill") }
                    .buttonStyle(AUButtonStyle(.secondary, size: .regular, iconOnly: true))
                Text(Fmt.clockTenths(player.time)).auFont(MONO11).foregroundStyle(AU.text2)
                AUSlider(value: Binding(get: { player.time }, set: { player.seek($0) }), in: 0...max(0.1, player.duration), knob: 12)
                Text(Fmt.clockTenths(player.duration)).auFont(MONO11).foregroundStyle(AU.text2)
                // Board C6 (A): fit to the player, the default, or one video pixel per screen pixel.
                AUMiniSegments([
                    .init(Image(systemName: "arrow.up.left.and.arrow.down.right"),
                          help: model.t("nat.cmp.fit"), selected: !player.oneToOne) { player.oneToOne = false },
                    .init(Text("1:1").auFont(11, .semibold, mono: true), help: model.t("nat.cmp.one_to_one"),
                          selected: player.oneToOne) { player.oneToOne = true },
                ], segmentWidth: 28)
            }
        }
        .frame(maxWidth: .infinity)
        .task(id: "\(r.intervallo)|\(model.cmp.left)|\(model.cmp.right)") { await load(r) }
    }

    private func versionPicker(_ keys: [String], side: String, selection: Binding<String>) -> some View {
        HStack(spacing: 8) {
            if side == "L" { SideTag(side) }
            PopupMenu({
                keys.map { k in .item(versionName(k), checked: k == selection.wrappedValue) { selection.wrappedValue = k } }
            }) {
                PopupLabel(versionName(selection.wrappedValue), width: 220, height: 26, size: 12)
            }
            .fixedSize()
            if side == "R" { SideTag(side) }
        }
    }

    private func versionName(_ k: String) -> String {
        k == "original" ? model.t("nat.cmp.original") : model.t("mot.modello.\(k).label")
    }

    private func load(_ r: CompareStatus.Result) async {
        var urls: [URL?] = [nil, nil]
        for (i, key) in [model.cmp.left, model.cmp.right].enumerated() {
            guard let path = r.file[key] else { log.error("player: no \(key) version in this clip"); continue }
            do { urls[i] = URL(fileURLWithPath: try await model.engine.playable(path)) }
            catch { log.error("player: \(key) can't be made playable: \(error)") }
        }
        log.info("player: \(model.cmp.left) \(urls[0]?.lastPathComponent ?? "—") | \(model.cmp.right) \(urls[1]?.lastPathComponent ?? "—")")
        player.load(left: urls[0], right: urls[1])
    }
}

struct SideTag: View {
    var side: String
    init(_ side: String) { self.side = side }
    var body: some View {
        Text(side).auFont(10.5, .semibold, mono: true).foregroundStyle(AU.onPrimary)
            .padding(.horizontal, 6).padding(.vertical, 1)
            .background(RoundedRectangle(cornerRadius: 4).fill(AU.primary))
            .fixedSize()
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
                                    Text(model.kindName(c.0)).auFont(14, .semibold)
                                    Text(verbatim: c.1).auFont(12, mono: true).foregroundStyle(AU.textCode)
                                    Spacer()
                                    Text(model.t("nat.cmp.n_ready", ["i": ready, "n": mine.count])).auFont(MONO11).foregroundStyle(AU.primaryText)
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
                                Text(model.kindName(c.0)).auFont(14, .semibold)
                                Text(verbatim: c.1).auFont(12, mono: true).foregroundStyle(AU.text2)
                                Spacer()
                                Text(ready == mine.count ? model.t("nat.cmp.all_ready") : model.t("nat.cmp.waiting_clip"))
                                    .auFont(MONO11).foregroundStyle(ready == mine.count ? AU.greenText : AU.text3)
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
                        Text(model.t("nat.cmp.testing_clips")).auFont(13, .semibold)
                        Text(model.t("nat.cmp.of_whole", ["pct": Int(((st.quota ?? 0) * 100).rounded())])).auSmall()
                        Spacer()
                        Text(model.t("nat.cmp.version_of", ["i": min(done + 1, total), "n": total])
                             + (model.compareLeft.map { " · " + model.t("nat.run.left", ["t": "~ " + Fmt.span(max(60, $0))]) } ?? ""))
                            .auFont(MONO11).foregroundStyle(AU.text2)
                    }
                    VStack(alignment: .leading, spacing: 6) {
                        PiecedTestBar(segments: segs, done: done, fraction: st.fraction ?? 0)
                        PiecedTestLabels(segments: segs, done: done, fraction: st.fraction ?? 0)
                    }
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
                    // The crop fills the 16:9 tile; the tile, not the image, sets the size.
                    Color.clear.overlay { Image(nsImage: img).resizable().aspectRatio(contentMode: .fill) }
                } else if index < done {
                    RoundedRectangle(cornerRadius: 8).fill(AU.raised)
                    Image(systemName: "checkmark").foregroundStyle(AU.greenText)
                } else {
                    RoundedRectangle(cornerRadius: 8).strokeBorder(index == done ? AU.softLine : AU.line, style: StrokeStyle(lineWidth: 1, dash: [4, 3]))
                    VStack(spacing: 10) {
                        Text(model.t(index == done ? "nat.cmp.rendering" : "nat.cmp.waiting_clip")).auFont(13, .semibold)
                        if index == done {
                            AUBar(st.fraction ?? 0, height: 6)
                            Text("\(Int(((st.fraction ?? 0) * 100).rounded()))%").auFont(MONO11).foregroundStyle(AU.text2)
                        }
                    }
                    .padding(.horizontal, 48)
                }
            }
            // compare.py C3: every version as big as its clip, 16:9.
            .frame(maxWidth: .infinity)
            .aspectRatio(16 / 9, contentMode: .fit)
            .clipShape(RoundedRectangle(cornerRadius: 8))
            HStack(spacing: 6) {
                if index < done { Image(systemName: "checkmark").auFont(10, .semibold).foregroundStyle(AU.greenText) }
                Text(s.chiave == "original" ? model.t("nat.cmp.original_plain") : model.t("mot.modello.\(s.chiave).label"))
                    .auFont(12).foregroundStyle(AU.textCode)
            }
        }
    }
}

/// compare.py C3: the label under each piece of the test bar, as wide as its piece:
/// "✓ orig." done, "Motion · no-denoise 42%" running, "Dark · no-denoise" waiting.
struct PiecedTestLabels: View {
    @Environment(AppModel.self) private var model
    var segments: [CompareStatus.Segment]
    var done: Int
    var fraction: Double

    var body: some View {
        let clips = segments.map(\.intervallo).reduce(into: [String]()) { if !$0.contains($1) { $0.append($1) } }
        let total = max(0.01, segments.reduce(0.0) { $0 + max(0.01, $1.peso) })
        GeometryReader { g in
            let usable = g.size.width - CGFloat(clips.count - 1) * 3
            HStack(spacing: 3) {
                ForEach(clips, id: \.self) { clip in
                    HStack(spacing: 1.5) {
                        ForEach(segments.enumerated().filter { $0.element.intervallo == clip }, id: \.offset) { item in
                            Text(label(item.element, item.offset))
                                .auFont(10.5, mono: true)
                                .foregroundStyle(item.offset < done ? AU.greenText : item.offset == done ? AU.primaryText : AU.text3)
                                .lineLimit(1).truncationMode(.tail)
                                .frame(width: max(2, usable * max(0.01, item.element.peso) / total - 1.5), alignment: .leading)
                        }
                    }
                }
            }
        }
        .frame(height: 13)
    }

    private func label(_ s: CompareStatus.Segment, _ i: Int) -> String {
        let name = s.chiave == "original" ? model.t("nat.cmp.orig_short")
            : "\(model.kindName(s.tipo)) · \(model.shortModel(s.chiave, compact: true))"
        if i < done { return "✓ " + name }
        if i == done { return name + " \(Int((fraction * 100).rounded()))%" }
        return name
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
                Text(model.t("mot.modello.\(result.chiave).label")).auFont(13, .semibold)
                Spacer()
                if let side { SideTag(side) }
            }
            HStack(alignment: .firstTextBaseline) {
                Text("\(Text(model.t("nat.cmp.this_clip")).foregroundStyle(AU.text2)) \(Text(Fmt.span(max(60, result.secondi))).auRun(13, .semibold, mono: true))")
                Spacer()
                Text("\(Text(model.t("nat.cmp.full_episode")).foregroundStyle(AU.text2)) \(Text(Fmt.estimate(result.intero)).auRun(13, .semibold, mono: true))")
            }
            .auFont(AUTextStyle(12), runs: AUTextStyle(13, .semibold, mono: true))
            if let m = result.metriche, m.count == 2 {
                metric(model.t("nat.cmp.detail"), m[0], AU.primary)
                metric(model.t("nat.cmp.noise"), m[1], AU.yellow)
            }
            VStack(spacing: 6) {
                if inUse {
                    Label(model.t("nat.cmp.in_use"), systemImage: "checkmark").labelStyle(SmallIconLabel())
                        .auFont(12, .medium).foregroundStyle(AU.greenText)
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
        .auBox(RoundedRectangle(cornerRadius: 8), fill: side != nil ? AU.soft : AU.raised, line: side != nil ? AU.softLine : AU.chipLine,
               padding: EdgeInsets(vertical: 12, horizontal: 12))
    }

    /// The bar with the 100 % tick in the middle (200 % fills it).
    private func metric(_ name: String, _ value: Double?, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Text(name).auFont(12).foregroundStyle(AU.text2)
                Spacer()
                Text(value.map { "\(Int(($0 * 100).rounded()))%" } ?? "—").auFont(MONO11).foregroundStyle(AU.textCode)
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

/// A version not rendered yet on this clip (stopped test).
struct PendingCard: View {
    @Environment(AppModel.self) private var model
    var key: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(model.t("mot.modello.\(key).label")).auFont(13, .semibold).foregroundStyle(AU.text2)
            Text(model.t("nat.cmp.not_rendered")).auSmall(AU.text3)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 8).fill(AU.raised))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(AU.chipLine, style: StrokeStyle(lineWidth: 1, dash: [4, 3])))
    }
}

/// E4: a version that failed on this clip.
struct FailedCard: View {
    @Environment(AppModel.self) private var model
    var key: String
    var log: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(model.t("mot.modello.\(key).label")).auFont(13, .semibold).foregroundStyle(AU.redText)
            Text(model.t("nat.cmp.render_failed")).auSmall(AU.redText).fixedSize(horizontal: false, vertical: true)
            HStack {
                Button(model.t("nat.btn.retry")) { model.renderRest() }.buttonStyle(AUTintedButtonStyle(.red))
                Spacer()
                UnderlineLink(model.t("nat.btn.show_log"), tone: .red) { model.openLog(log) }
            }
        }
        .auBox(RoundedRectangle(cornerRadius: 8), fill: AU.redBg, line: AU.redLine,
               padding: EdgeInsets(vertical: 12, horizontal: 12))
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
            Text(model.t("nat.cmp.use_many_title", ["model": model.t("mot.modello.\(key).label")])).auFont(15, .semibold)
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
                        Text(f.name).auFont(12, .medium).lineLimit(1).frame(maxWidth: .infinity, alignment: .leading)
                        Text(verbatim: f.report.map { "\($0.width)×\($0.height)" } ?? "").auFont(11.5, mono: true)
                            .foregroundStyle(AU.textCode).frame(width: 72, alignment: .trailing)
                        Group {
                            if picked.contains(f.id) {
                                HStack(spacing: 6) {
                                    Text(model.shortModel(plan?.model ?? "", compact: true)).foregroundStyle(AU.text3)
                                    Image(systemName: "arrow.right").auFont(8).foregroundStyle(AU.text3)
                                    Text(model.shortModel(key, compact: true)).foregroundStyle(AU.primaryText)
                                }
                                .auFont(11.5, mono: true)
                                .lineLimit(1)
                            } else if already {
                                Text(model.t("nat.cmp.already_uses")).auSmall(AU.text3)
                            } else if let why = plan?.option(key)?.unreachable {
                                Text(why).auSmall(AU.redText)
                            } else if poor {
                                Label(model.t("nat.cmp.poor_fit", ["h": f.report?.height ?? 0]), systemImage: "exclamationmark.triangle.fill")
                                    .labelStyle(SmallIconLabel()).auSmall(AU.redText)
                            } else {
                                Text(model.shortModel(plan?.model ?? "")).auFont(11.5, mono: true).foregroundStyle(AU.text3)
                            }
                        }
                        .frame(width: 220, alignment: .trailing)
                    }
                    .frame(height: 34)
                    .auBox(RoundedRectangle(cornerRadius: 7), fill: picked.contains(f.id) ? AU.soft : poor && !already ? AU.redSoft : .clear, line: poor && !already && !picked.contains(f.id) ? AU.redLine : .clear,
                           padding: EdgeInsets(vertical: 0, horizontal: 12))
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
        // compare_sheet.py: 620 pt of content, padding 20, inside the sheet's 1 pt edge.
        .frame(width: 660)
        .background(AU.sheet)
        .onAppear {
            picked = Set(rows.filter { f in
                let p = model.plans[f.id]
                return p?.model != key && p?.option(key)?.verdict != "no" && p?.option(key)?.unreachable == nil
            }.map(\.id))
        }
    }
}

/// A tab's outline without its bottom edge: left side, the two top corners, right side.
struct TabOutline: Shape {
    var radius: CGFloat

    func path(in rect: CGRect) -> Path {
        let r = rect.insetBy(dx: 0.5, dy: 0.5)
        var p = Path()
        p.move(to: CGPoint(x: r.minX, y: rect.maxY))
        p.addLine(to: CGPoint(x: r.minX, y: r.minY + radius))
        p.addArc(center: CGPoint(x: r.minX + radius, y: r.minY + radius), radius: radius,
                 startAngle: .degrees(180), endAngle: .degrees(270), clockwise: false)
        p.addLine(to: CGPoint(x: r.maxX - radius, y: r.minY))
        p.addArc(center: CGPoint(x: r.maxX - radius, y: r.minY + radius), radius: radius,
                 startAngle: .degrees(270), endAngle: .degrees(0), clockwise: false)
        p.addLine(to: CGPoint(x: r.maxX, y: rect.maxY))
        return p
    }
}
