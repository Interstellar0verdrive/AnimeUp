import DesignSystem
import Models
import SwiftUI
import UniformTypeIdentifiers

/// Boards F1, F2 (and the analysis part of F3): the Queue tab.
struct QueueView: View {
    @Environment(AppModel.self) private var model
    @State private var targeted = false

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                QueueContent()
                    .padding(.top, 28)
                    .padding(.horizontal, 28)
                    .padding(.bottom, 16)
            }
            .scrollBounceBehavior(.basedOnSize)
            if !model.files.isEmpty {
                QueueActionBar().padding(.horizontal, 28).padding(.bottom, 24)
            }
        }
        .ignoresSafeArea(edges: .top)
        .overlay {
            if targeted {
                RoundedRectangle(cornerRadius: AU.Radius.card).strokeBorder(AU.primary, style: StrokeStyle(lineWidth: 2, dash: [6, 4]))
                    .padding(12).allowsHitTesting(false)
            }
        }
        .onDrop(of: [.fileURL], isTargeted: $targeted) { providers in
            Task { @MainActor in model.add(await loadURLs(providers)) }
            return true
        }
        .onDeleteCommand { model.removeWithUndo(model.selection) }
    }
}

@MainActor
func loadURLs(_ providers: [NSItemProvider]) async -> [URL] {
    var urls: [URL] = []
    for p in providers {
        if let data = try? await p.loadItem(forTypeIdentifier: UTType.fileURL.identifier) as? Data,
           let url = URL(dataRepresentation: data, relativeTo: nil) {
            urls.append(url)
        } else if let url = try? await p.loadItem(forTypeIdentifier: UTType.fileURL.identifier) as? URL {
            urls.append(url)
        }
    }
    return urls
}

/// Column widths shared by the header and the rows.
enum QueueColumns {
    static let check: CGFloat = 18
    static let resolution: CGFloat = 86
    static let length: CGFloat = 54
    static let status: CGFloat = 150
    static let model: CGFloat = 172
    static let time: CGFloat = 84
    static let chevron: CGFloat = 20
}

struct QueueContent: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .bottom) {
                VStack(alignment: .leading, spacing: 6) {
                    Text(model.t("nat.tab.queue")).auPageTitle()
                    Text(model.t("nat.queue.intro1") + "\n" + model.t("nat.queue.intro2")).auBody()
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
                Button { model.openVideos() } label: { Label(model.t("nat.queue.add"), systemImage: "plus") }
                    .auButton(.secondary, .regular)
            }
            if model.files.isEmpty {
                DropZone(title: model.t("nat.add.drop"), buttonTitle: model.t("nat.add.open"), primary: true,
                         onOpen: { model.openVideos() }, onDrop: { model.add($0) })
                    .frame(height: 300)
            } else {
                QueueSummary()
                QueueHeader()
                VStack(spacing: 8) {
                    ForEach(model.files) { file in
                        QueueRow(file: file)
                    }
                }
            }
        }
    }
}

// MARK: - Summary strip and header

struct QueueSummary: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let files = model.files
        let length = files.compactMap { $0.report?.duration }.reduce(0, +)
        let hd = files.filter { ($0.report?.height ?? 0) >= 720 }.count
        let sd = files.filter { $0.report != nil && ($0.report?.height ?? 0) < 720 }.count
        let warned = model.warningCount
        HStack(spacing: 8) {
            Text("\(Text(model.localizer.tn("nat.queue.files", files.count)).fontWeight(.semibold).foregroundStyle(AU.text)) · \(model.t("nat.queue.of_video", ["span": Fmt.span(length)]))")
                .font(.system(size: 12)).foregroundStyle(AU.text2)
            if hd > 0 { StatusChip("\(hd) ≥ 720p") }
            if sd > 0 { StatusChip(model.t("nat.queue.below720", ["n": sd])) }
            if warned > 0 {
                StatusChip(model.localizer.tn("nat.queue.files_warnings", warned), tone: .yellow,
                           symbol: "exclamationmark.triangle.fill")
            }
            Spacer()
            Button { model.reanalyse(nil) } label: { Label(model.t("nat.queue.reanalyse_all"), systemImage: "arrow.clockwise") }
                .auButton(.plain, .small)
        }
    }
}

struct QueueHeader: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        HStack(spacing: 12) {
            TriCheckbox(state: tickState) {
                if tickState == .on { model.unticked = Set(model.files.map(\.id)) } else { model.unticked = [] }
            }
            .frame(width: QueueColumns.check)
            Text(model.t("nat.col.file")).frame(maxWidth: .infinity, alignment: .leading)
            Text(model.t("nat.col.resolution")).frame(width: QueueColumns.resolution, alignment: .trailing)
            Text(model.t("nat.col.length")).frame(width: QueueColumns.length, alignment: .trailing)
            Text(model.t("nat.col.status")).frame(width: QueueColumns.status, alignment: .leading)
            HStack {
                Text(model.t("nat.col.model"))
                Spacer()
                Menu {
                    ForEach(["animevideov3", "cugan-denoise", "cugan", "cugan-conservative"], id: \.self) { key in
                        Button(model.shortModel(key)) { model.sameForAll(key) }
                    }
                } label: {
                    HStack(spacing: 3) {
                        Text(model.t("nat.col.same_for_all"))
                        Image(systemName: "chevron.down").font(.system(size: 8, weight: .semibold))
                    }
                    .foregroundStyle(AU.text2)
                }
                .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize()
                .disabled(model.plans.isEmpty)
            }
            .frame(width: QueueColumns.model)
            Text(model.t("nat.col.time")).frame(width: QueueColumns.time, alignment: .trailing)
            Color.clear.frame(width: QueueColumns.chevron)
        }
        .auLabel()
        .padding(.horizontal, 15)
    }

    private var tickState: TriCheckbox.State {
        let ready = model.files.filter { $0.state == .ready }
        let n = ready.filter { model.isTicked($0) }.count
        if n == 0 { return .off }
        return n == ready.count ? .on : .mixed
    }
}

/// DS3 checkbox: on, off, mixed.
struct TriCheckbox: View {
    enum State { case on, off, mixed }
    var state: State
    var action: () -> Void
    @Environment(\.isEnabled) private var enabled

    var body: some View {
        Button(action: action) {
            ZStack {
                if state == .off {
                    RoundedRectangle(cornerRadius: 4).fill(AU.control)
                    RoundedRectangle(cornerRadius: 4).strokeBorder(AU.boxLine)
                } else {
                    RoundedRectangle(cornerRadius: 4).fill(AU.primary)
                    if state == .on {
                        Image(systemName: "checkmark").font(.system(size: 9, weight: .bold)).foregroundStyle(AU.onPrimary)
                    } else {
                        RoundedRectangle(cornerRadius: 1).fill(AU.onPrimary).frame(width: 7, height: 2)
                    }
                }
            }
            .frame(width: 15, height: 15)
        }
        .buttonStyle(.plain)
        .opacity(enabled ? 1 : 0.4)
    }
}

// MARK: - Row

struct QueueRow: View {
    @Environment(AppModel.self) private var model
    @Environment(\.undoManager) private var undo
    var file: QueueFile

    private var open: Bool { model.expanded == file.id }
    private var selected: Bool { model.selection.contains(file.id) }

    var body: some View {
        VStack(spacing: 0) {
            header
            if open {
                FilePanel(file: file)
                    .padding(.horizontal, 12)
                    .padding(.bottom, 12)
            }
        }
        .background {
            ZStack {
                RoundedRectangle(cornerRadius: AU.Radius.card).fill(AU.surface)
                if file.state == .analysing {
                    SlidingLight().clipShape(RoundedRectangle(cornerRadius: AU.Radius.card))
                }
            }
        }
        .overlay(alignment: .bottom) {
            if file.state == .analysing && !open {
                SlidingEdge().frame(height: 3).clipShape(RoundedRectangle(cornerRadius: AU.Radius.card))
            }
        }
        .overlay(RoundedRectangle(cornerRadius: AU.Radius.card)
            .strokeBorder(selected ? AU.primary : AU.line, lineWidth: selected ? 1.5 : 1))
        .contentShape(RoundedRectangle(cornerRadius: AU.Radius.card))
        .onTapGesture { click() }
        .contextMenu { menu }
    }

    private var header: some View {
        HStack(spacing: 12) {
            TriCheckbox(state: model.isTicked(file) ? .on : .off) {
                if model.unticked.contains(file.id) { model.unticked.remove(file.id) } else { model.unticked.insert(file.id) }
            }
            .frame(width: QueueColumns.check)
            .disabled(file.state != .ready)
            VStack(alignment: .leading, spacing: 5) {
                Text(file.name).font(.system(size: 12.5, weight: .medium)).foregroundStyle(AU.text)
                    .lineLimit(1).truncationMode(.middle)
                HStack(spacing: 5) {
                    if !file.warnings.isEmpty && file.state == .ready {
                        Label(model.localizer.tn("nat.queue.n_warnings", file.warnings.count),
                              systemImage: "exclamationmark.triangle.fill")
                            .labelStyle(SmallIconLabel()).foregroundStyle(AU.yellowText)
                        Text("·")
                    }
                    Text(detailLine).lineLimit(1).truncationMode(.tail)
                }
                .font(.system(size: 11)).foregroundStyle(AU.text3)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            Text(verbatim: file.report.map { r -> String in "\(r.width)×\(r.height)" } ?? "—")
                .font(AUFont.numbers).foregroundStyle(AU.textCode)
                .frame(width: QueueColumns.resolution, alignment: .trailing)
            Text(verbatim: file.report.map { Fmt.clock($0.duration) } ?? "—")
                .font(AUFont.numbers).foregroundStyle(AU.textCode)
                .frame(width: QueueColumns.length, alignment: .trailing)
            HStack { statusChip; Spacer(minLength: 0) }.frame(width: QueueColumns.status)
            modelColumn.frame(width: QueueColumns.model, alignment: .leading)
            timeColumn.frame(width: QueueColumns.time, alignment: .trailing)
            Button { toggle() } label: {
                Image(systemName: open ? "chevron.up" : "chevron.down").font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(AU.text2).frame(width: QueueColumns.chevron, height: 24)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
        .padding(.leading, 15)
        .padding(.trailing, 14)
        .frame(height: 54)
        .contentShape(Rectangle())
        .onTapGesture(count: 2) { toggle() }
    }

    /// "H.264 · 655 MB · 23.976 VFR · 8 bit 4:2:0 · 1 audio, 2 subs · dedup 18%"
    private var detailLine: String {
        var parts: [String] = []
        if let r = file.report {
            parts.append(r.codecLabel)
        }
        if let size = file.size { parts.append(Fmt.bytes(size)) }
        if let r = file.report {
            if let fps = r.fpsText { parts.append("\(fps) \(r.timebaseLabel)") }
            parts.append(r.chroma == "?" ? "\(r.bitDepth) bit" : "\(r.bitDepth) bit \(r.chroma)")
            if let cs = r.colorSpace, cs != "unknown" { parts.append(cs.uppercased().replacingOccurrences(of: "BT", with: "BT.")) }
            var tracks = model.localizer.tn("nat.queue.audio", r.audioTracks)
            if r.subtitleTracks > 0 { tracks += ", " + model.localizer.tn("nat.queue.subs", r.subtitleTracks) }
            parts.append(tracks)
            if let d = r.dedupMeasured { parts.append("dedup \(Int((d * 100).rounded()))%") }
        }
        if file.state == .failed, let e = file.error { parts.append(e) }
        if file.state == .missing { parts = [model.t("nat.files.missing_file")] }
        return parts.joined(separator: " · ")
    }

    @ViewBuilder
    private var statusChip: some View {
        switch file.state {
        case .analysing:
            TimelineView(.periodic(from: .now, by: 1)) { ctx in
                StatusChip(model.t("nat.chip.analysing", ["elapsed": Fmt.elapsed(ctx.date.timeIntervalSince1970 - (file.analysisStarted ?? ctx.date.timeIntervalSince1970))]),
                           tone: .accent)
            }
        case .queued: StatusChip(model.t("nat.chip.awaiting"))
        case .ready:
            if let p = model.plan(file.id) {
                if p.error != nil && p.model == nil {
                    StatusChip(model.t("nat.chip.cant_process"), tone: .red).help(p.error ?? "")
                } else {
                    switch p.verdict {
                    case "ok": StatusChip(model.t("nat.chip.recommended"), tone: .green, symbol: "checkmark")
                    case "verifica": StatusChip(model.t("nat.chip.worth_checking"), tone: .yellow)
                    case "no": StatusChip(model.t("nat.chip.not_recommended"), tone: .red)
                    default: StatusChip(model.t("nat.chip.your_choice"))
                    }
                }
            } else {
                StatusChip(model.t("nat.chip.ready"), tone: .green, symbol: "checkmark")
            }
        case .failed: StatusChip(model.t("nat.chip.unreadable"), tone: .red, symbol: "exclamationmark.octagon.fill")
        case .missing: StatusChip(model.t("nat.chip.missing"), tone: .red)
        }
    }

    @ViewBuilder
    private var modelColumn: some View {
        if file.state == .ready, let p = model.plan(file.id), let current = p.model {
            Menu {
                ForEach(p.models ?? []) { opt in
                    Button { model.chooseModel(opt.key, for: [file.id]) } label: {
                        Text(optionLabel(opt))
                    }
                    .disabled(opt.unreachable != nil)
                }
            } label: {
                PopupLabel(model.shortModel(current), width: QueueColumns.model)
            }
            .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden)
            .help(p.reason ?? "")
        } else {
            Text(file.state == .ready ? "—" : model.t("nat.queue.after_analysis"))
                .font(.system(size: 12)).foregroundStyle(AU.text2)
        }
    }

    private func optionLabel(_ opt: FilePlan.ModelOption) -> String {
        var label = model.shortModel(opt.key)
        if let why = opt.unreachable { return label + " — " + why }
        switch opt.verdict {
        case "ok": label += " · " + model.t("nat.chip.recommended")
        case "verifica": label += " · " + model.t("nat.chip.worth_checking")
        case "no": label += " · " + model.t("nat.chip.not_recommended")
        default: break
        }
        if let e = opt.estimate { label += "   " + Fmt.estimate(e) }
        return label
    }

    @ViewBuilder
    private var timeColumn: some View {
        if let p = model.plan(file.id), let e = p.estimate {
            HStack(spacing: 4) {
                Text(verbatim: Fmt.estimate(e)).font(AUFont.numbers).foregroundStyle(AU.textCode)
                    .lineLimit(1).fixedSize()
                Image(systemName: "info.circle").font(.system(size: 9)).foregroundStyle(AU.text3)
            }
            .help(model.t("nat.queue.range", ["best": Fmt.span(p.estimateBest ?? e), "worst": Fmt.span(p.estimateWorst ?? e)]))
        } else {
            Text(verbatim: "—").font(AUFont.numbers).foregroundStyle(AU.text2)
        }
    }

    @ViewBuilder
    private var menu: some View {
        let ids = selected && model.selection.count > 1 ? model.selection : [file.id]
        Button(model.t("nat.menu.show_in_finder")) { model.showInFinder(ids) }
        Button(model.t("nat.menu.reanalyse")) { model.reanalyse(Array(ids)) }
        Divider()
        Button(model.t("nat.menu.remove")) { model.removeWithUndo(ids, undo: undo) }
            .keyboardShortcut(.delete, modifiers: [])
    }

    private func toggle() {
        withAnimation(.easeOut(duration: 0.18)) {
            model.expanded = open ? nil : file.id
        }
    }

    private func click() {
        let flags = NSEvent.modifierFlags
        if flags.contains(.command) {
            if selected { model.selection.remove(file.id) } else { model.selection.insert(file.id) }
        } else if flags.contains(.shift), let anchor = model.selection.first,
                  let a = model.files.firstIndex(where: { $0.id == anchor }),
                  let b = model.files.firstIndex(where: { $0.id == file.id }) {
            model.selection = Set(model.files[min(a, b)...max(a, b)].map(\.id))
        } else {
            model.selection = [file.id]
        }
    }
}

extension AppModel {
    /// Remove from List (⌫), undoable with ⌘Z.
    func removeWithUndo(_ ids: Set<String>, undo: UndoManager? = nil) {
        guard !ids.isEmpty else { return }
        remove(ids)
        let manager = undo ?? NSApp.keyWindow?.undoManager
        manager?.registerUndo(withTarget: self) { model in model.undoRemove() }
        manager?.setActionName(t("nat.menu.remove"))
    }
}

/// A light sliding across an analysing row.
struct SlidingLight: View {
    var body: some View {
        TimelineView(.animation) { ctx in
            GeometryReader { g in
                let phase = ctx.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 1.8) / 1.8
                LinearGradient(colors: [.clear, AU.soft, .clear], startPoint: .leading, endPoint: .trailing)
                    .frame(width: g.size.width * 0.3)
                    .offset(x: -g.size.width * 0.3 + g.size.width * 1.3 * phase)
            }
        }
        .allowsHitTesting(false)
    }
}

struct SlidingEdge: View {
    var body: some View {
        TimelineView(.animation) { ctx in
            GeometryReader { g in
                let phase = ctx.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 1.8) / 1.8
                Rectangle().fill(AU.primary)
                    .frame(width: g.size.width * 0.3)
                    .offset(x: -g.size.width * 0.3 + g.size.width * 1.3 * phase)
            }
        }
        .allowsHitTesting(false)
    }
}

// MARK: - Panel

struct FilePanel: View {
    @Environment(AppModel.self) private var model
    var file: QueueFile

    var body: some View {
        @Bindable var m = model
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 8) {
                Picker("", selection: $m.panelTab) {
                    Text(model.t("nat.panel.analysis")).tag(PanelTab.analysis)
                    Text(model.t("nat.panel.processing")).tag(PanelTab.processing)
                }
                .pickerStyle(.segmented).labelsHidden().fixedSize()
                Spacer()
                dedup
                Button { model.reanalyse([file.id]) } label: { Label(model.t("nat.menu.reanalyse"), systemImage: "arrow.clockwise") }
                    .auButton(.secondary, .small)
                    .disabled(file.state == .analysing)
            }
            if model.panelTab == .processing {
                if let p = model.plan(file.id), p.model != nil {
                    ProcessingPanel(file: file, plan: p)
                } else if let p = model.plan(file.id), let e = p.error {
                    NoteView(.red, title: model.t("nat.chip.cant_process"), text: e)
                } else {
                    Text(model.t("nat.panel.waiting")).auSmall()
                }
            } else if let r = file.report {
                analysis(r)
            } else if file.state == .failed {
                NoteView(.red, title: model.t("nat.panel.failed"), text: file.error ?? "")
            } else {
                Text(model.t("nat.panel.waiting")).auSmall()
            }
        }
        .padding(16)
        .background(RoundedRectangle(cornerRadius: AU.Radius.field).fill(AU.inset))
    }

    @ViewBuilder
    private var dedup: some View {
        if let d = file.report?.dedupMeasured {
            StatusChip(model.t("nat.panel.dedup_measured", ["pct": Int((d * 100).rounded())]), tone: .green, symbol: "checkmark")
        } else if file.state == .analysing && (file.deep ?? false) {
            StatusChip(model.t("nat.panel.dedup_measuring"), tone: .accent)
        } else if file.dedupUnmeasurable == true {
            StatusChip(model.t("nat.panel.dedup_short"))
                .help(model.t("nat.panel.dedup_short_help"))
        } else if file.state == .ready && !(model.settings?.deepAnalysis ?? true) {
            Button(model.t("nat.panel.deep")) { model.deepAnalysis(file.id) }.auButton(.secondary, .small)
        }
    }

    private func analysis(_ r: FileReport) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .top, spacing: 32) {
                DataGroup(title: model.t("nat.panel.timing"), items: [
                    (model.t("nat.panel.frame_rate"), r.fpsText.map { "\($0) (\(r.fpsFraction ?? ""))" } ?? "—", false),
                    (model.t("nat.panel.timebase"), r.timebaseLabel, r.timebase != "cfr"),
                    (model.t("nat.panel.frames"), Fmt.count(r.frames), false),
                    (model.t("nat.panel.duration"), Fmt.clockTenths(r.duration), false),
                ])
                DataGroup(title: model.t("nat.panel.image"), items: [
                    (model.t("nat.panel.geometry"), "\(r.width)×\(r.height)", false),
                    (model.t("nat.panel.pixels"), r.anamorphic ? "SAR \(r.sar)" : model.t("nat.panel.square"), r.anamorphic),
                    (model.t("nat.panel.format"), "\(r.pixFmt) · \(r.bitDepth) bit", false),
                    (model.t("nat.panel.colour"), colour(r), r.colorSpace == nil),
                ])
                DataGroup(title: model.t("nat.panel.tracks"), items: [
                    (model.t("nat.panel.audio"), r.audioTracks > 0 ? "\(r.audioTracks)" : "—", false),
                    (model.t("nat.panel.subtitles"), r.subtitleTracks > 0 ? "\(r.subtitleTracks) · \(r.subtitleCodecs.joined(separator: ", "))" : "—",
                     r.subtitleCodecs.contains("mov_text")),
                    (model.t("nat.panel.chapters"), r.chapters > 0 ? "\(r.chapters)" : "—", false),
                    (model.t("nat.panel.fields"), fields(r), r.fields != nil && r.fields != "progressivo"),
                ])
            }
            if file.state == .analysing {
                TimelineView(.periodic(from: .now, by: 1)) { ctx in
                    Text(model.t("nat.panel.analysing_note", ["elapsed": Fmt.elapsed(ctx.date.timeIntervalSince1970 - (file.analysisStarted ?? ctx.date.timeIntervalSince1970))]))
                        .auSmall()
                }
            }
            ForEach(r.warnings, id: \.self) { w in
                NoteView(.yellow, text: w)
            }
        }
    }

    private func colour(_ r: FileReport) -> String {
        guard let cs = r.colorSpace, cs != "unknown" else { return model.t("nat.panel.not_declared") }
        return cs.uppercased().replacingOccurrences(of: "BT", with: "BT.")
    }

    private func fields(_ r: FileReport) -> String {
        switch r.fields {
        case "progressivo": model.t("nat.panel.progressive")
        case "interlacciato": model.t("nat.panel.interlaced")
        case "telecine": "telecine"
        case nil: "—"
        default: model.t("nat.panel.undetermined")
        }
    }
}

/// DS4 "Data group": a title with a rule, then label-over-value pairs in two columns.
struct DataGroup: View {
    var title: String
    var items: [(String, String, Bool)]

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 6) {
                Text(title).font(.system(size: 12.5, weight: .semibold)).foregroundStyle(AU.text)
                Rectangle().fill(AU.line).frame(height: 1)
            }
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 10) {
                ForEach(0..<(items.count + 1) / 2, id: \.self) { row in
                    GridRow {
                        ForEach(0..<2, id: \.self) { col in
                            let i = row * 2 + col
                            if i < items.count {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(items[i].0).font(.system(size: 11)).foregroundStyle(AU.text3)
                                    Text(verbatim: items[i].1).font(AUFont.numbers)
                                        .foregroundStyle(items[i].2 ? AU.yellowText : AU.text)
                                        .lineLimit(2)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

// MARK: - Processing panel (F3)

struct ProcessingPanel: View {
    @Environment(AppModel.self) private var model
    var file: QueueFile
    var plan: FilePlan

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .top, spacing: 32) {
                DataGroup(title: model.t("nat.plan.job"), items: [
                    (model.t("nat.col.model"), model.shortModel(plan.model ?? ""), plan.verdict == "no"),
                    (model.t("nat.plan.pipeline"), pipeline, false),
                    (model.t("nat.plan.output"), "\(plan.outputWidth ?? 0)×\(plan.outputHeight ?? 0)", false),
                    (model.t("nat.plan.chunks"), model.t("nat.plan.chunks_of", ["n": plan.chunks ?? 1, "frames": Fmt.count(plan.frames ?? 0)]), (plan.chunks ?? 1) > 3),
                ])
                DataGroup(title: model.t("nat.plan.encoding"), items: [
                    (model.t("nat.plan.codec"), "\((plan.codec ?? "").replacingOccurrences(of: "lib", with: "").replacingOccurrences(of: "x265", with: "hevc")) \(plan.pixFmt ?? "")", false),
                    ("CRF", "\(plan.crf ?? 18)", false),
                    (model.t("nat.plan.preset"), plan.preset ?? "", false),
                    (model.t("nat.plan.restoration"), (plan.restoration ?? []).isEmpty ? model.t("nat.plan.none") : (plan.restoration ?? []).joined(separator: ", "), false),
                ])
                outputGroup
            }
            ForEach((plan.warnings ?? []), id: \.self) { w in NoteView(.yellow, text: w) }
        }
    }

    private var pipeline: String {
        var s = "\(model.shortModel(plan.model ?? "").components(separatedBy: " ").first ?? "") \(plan.scale ?? 2)×"
        if let d = plan.downscale, d > 1.001 { s += " → downscale \(String(format: "%.2f", d)):1" }
        return s
    }

    private var outputGroup: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 6) {
                Text(model.t("nat.plan.output_file")).font(.system(size: 12.5, weight: .semibold)).foregroundStyle(AU.text)
                Rectangle().fill(AU.line).frame(height: 1)
            }
            VStack(alignment: .leading, spacing: 4) {
                Text(model.t("nat.plan.height")).font(.system(size: 11)).foregroundStyle(AU.text3)
                Menu {
                    Button(model.t("nat.plan.height_default", ["h": model.settings?.height ?? 1080])) { model.chooseHeight(nil, for: file.id) }
                    Divider()
                    ForEach([720, 1080, 1440, 2160], id: \.self) { h in
                        Button("\(h)") { model.chooseHeight(h, for: file.id) }
                    }
                } label: {
                    PopupLabel((plan.heightIsDefault ?? true) ? model.t("nat.plan.height_default", ["h": plan.height ?? 1080])
                               : "\(plan.height ?? 1080)", width: 160)
                }
                .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize()
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(model.t("nat.plan.name")).font(.system(size: 11)).foregroundStyle(AU.text3)
                Text(verbatim: plan.outputName ?? "").font(AUFont.numbers).foregroundStyle(AU.text)
                    .fixedSize(horizontal: false, vertical: true)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(model.t("nat.plan.folder")).font(.system(size: 11)).foregroundStyle(AU.text3)
                Text(model.t("nat.plan.next_to")).font(AUFont.numbers).foregroundStyle(AU.text)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

// MARK: - Action bar

struct QueueActionBar: View {
    @Environment(AppModel.self) private var model

    private var calibrationNote: String {
        if let w = model.calibratedWhen {
            return model.t("nat.queue.calibrated_note", ["when": model.relative(Date(timeIntervalSince1970: w))])
        }
        return model.t("nat.queue.factory_note")
    }

    var body: some View {
        let n = model.files.filter { model.isTicked($0) }.count
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 4) {
                    Text("\(Text(model.localizer.tn("nat.queue.selected", n)).fontWeight(.semibold).foregroundStyle(AU.text)) · \(model.t("nat.queue.estimate", ["time": Fmt.span(model.selectionEstimate)]))")
                        .font(.system(size: 13)).foregroundStyle(AU.text2)
                    Image(systemName: "info.circle").font(.system(size: 10)).foregroundStyle(AU.text3)
                        .help(model.t("nat.queue.estimate_help"))
                }
                Text(model.t("nat.queue.estimate_note") + " · " + calibrationNote).font(.system(size: 12)).foregroundStyle(AU.text2)
            }
            Spacer()
            Button { } label: { Label(model.t("nat.queue.start"), systemImage: "play.fill") }
                .auButton(.primary, .regular)
                .disabled(true)
                .help(model.t("nat.queue.start_later"))
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(RoundedRectangle(cornerRadius: AU.Radius.card).fill(AU.surface))
        .overlay(RoundedRectangle(cornerRadius: AU.Radius.card).strokeBorder(AU.line))
    }
}
