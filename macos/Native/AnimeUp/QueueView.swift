import DesignSystem
import Models
import SwiftUI
import UniformTypeIdentifiers

/// Boards F1, F2 (and the analysis part of F3): the Queue tab.
struct QueueView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.auPageTop) private var pageTop
    @State private var targeted = false
    @State private var compact = false

    var body: some View {
        VStack(spacing: 0) {
            if model.files.isEmpty {
                // Board F0: the page explains itself instead of an empty list.
                QueueEmptyView { QueueTitle(button: false) }
            } else {
            ScrollView {
                QueueContent()
                    .onGeometryChange(for: Bool.self) { $0.size.width < QueueColumns.compactBelow } action: { compact = $0 }
                    .environment(\.queueCompact, compact)
                    .padding(.top, pageTop)
                    .padding(.horizontal, 28)
                    .padding(.bottom, 16)
            }
            .scrollBounceBehavior(.basedOnSize)
            .overlay(alignment: .bottom) {
                // The list fades into the page over its last 16 pt, then 12 pt of page before the
                // action bar (board F4). At rest its own 16 pt bottom padding is under the fade.
                LinearGradient(colors: [AU.bg.opacity(0), AU.bg], startPoint: .top, endPoint: .bottom)
                    .frame(height: 16)
                    .allowsHitTesting(false)
            }
            QueueActionBar().padding(.horizontal, 28).padding(.top, 12).padding(.bottom, 28)
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
    // files2.py grid: 18px minmax(0,1fr) 78px 56px 150px 172px 130px 22px, gap 12, padding 0 12 0 14.
    static let check: CGFloat = 18
    static let resolution: CGFloat = 78
    static let length: CGFloat = 56
    static let status: CGFloat = 150
    static let model: CGFloat = 172
    static let time: CGFloat = 130
    /// Board F8: below this list width Resolution and Length join the second
    /// line and Time narrows, so the file name keeps about 300 pt.
    static let compactBelow: CGFloat = 1000
    static let compactTime: CGFloat = 70
    static func time(_ compact: Bool) -> CGFloat { compact ? compactTime : time }
    static let chevron: CGFloat = 22
    static let leading: CGFloat = 14
    static let trailing: CGFloat = 12
    /// A row's height inside its 1 pt frame.
    static let rowHeight: CGFloat = 54
    /// Width of the drawer's last column, so it starts under the Model column:
    /// from the model's left edge to the row's outer edge, less the row's 1 pt
    /// frame and the drawer's 16 pt padding.
    static func panelLast(_ compact: Bool) -> CGFloat {
        (1 + trailing + chevron + 12 + time(compact) + 12 + model) - (1 + 16)
    }
}

struct QueueContent: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        // files2.py `.main` gap 16; rows 10 apart.
        VStack(alignment: .leading, spacing: 16) {
            QueueTitle(button: true)
            QueueSummary()
            QueueHeader()
            VStack(spacing: 10) {
                ForEach(model.files) { file in
                    QueueRow(file: file)
                }
            }
        }
    }
}

/// The page title and its intro; Add Videos… on the right once there is a list.
struct QueueTitle: View {
    @Environment(AppModel.self) private var model
    var button: Bool

    var body: some View {
        PageHeader(model.t("nat.tab.queue"), model.t("nat.queue.intro1"), model.t("nat.queue.intro2")) {
            if button {
                Button { model.openVideos() } label: { Label(model.t("nat.queue.add"), systemImage: "plus") }
                    .auButton(.secondary, .regular)
                    .padding(.bottom, 2)
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
            // In a narrow window the chips that say least go first.
            ViewThatFits(in: .horizontal) {
                facts(files.count, length, hd: hd, sd: sd, warned: warned)
                facts(files.count, length, hd: 0, sd: 0, warned: warned)
                facts(files.count, length, hd: 0, sd: 0, warned: 0)
            }
            Spacer(minLength: 8)
            Button { model.reanalyse(nil) } label: { Label(model.t("nat.queue.reanalyse_all"), systemImage: "arrow.clockwise") }
                .auButton(.plain, .small)
        }
    }

    private func facts(_ count: Int, _ length: Double, hd: Int, sd: Int, warned: Int) -> some View {
        HStack(spacing: 8) {
            Text("\(Text(model.localizer.tn("nat.queue.files", count)).fontWeight(.semibold).foregroundStyle(AU.text)) · \(model.t("nat.queue.of_video", ["span": Fmt.span(length)]))")
                .auFont(12).foregroundStyle(AU.text2).fixedSize()
            if hd > 0 { StatusChip("\(hd) ≥ 720p") }
            if sd > 0 { StatusChip(model.t("nat.queue.below720", ["n": sd])) }
            if warned > 0 {
                StatusChip(model.localizer.tn("nat.queue.files_warnings", warned), tone: .yellow,
                           symbol: "exclamationmark.triangle.fill")
            }
        }
    }
}

struct QueueHeader: View {
    @Environment(AppModel.self) private var model
    @Environment(\.queueCompact) private var compact

    var body: some View {
        HStack(spacing: 12) {
            TriCheckbox(state: tickState) {
                if tickState == .on { model.unticked = Set(model.files.map(\.id)) } else { model.unticked = [] }
            }
            .frame(width: QueueColumns.check)
            .disabled(model.progress.queue.running)
            Text(compact ? model.t("nat.col.file_compact") : model.t("nat.col.file")).frame(maxWidth: .infinity, alignment: .leading)
            if !compact {
                Text(model.t("nat.col.resolution")).frame(width: QueueColumns.resolution, alignment: .trailing)
                Text(model.t("nat.col.length")).frame(width: QueueColumns.length, alignment: .center)
            }
            Text(model.t("nat.col.status")).frame(width: QueueColumns.status, alignment: .leading)
            HStack {
                Text(model.t("nat.col.model"))
                Spacer()
                PopupMenu({
                    ["animevideov3", "cugan-denoise", "cugan", "cugan-conservative"].map { key in
                        // The whole queue's time with that model, in grey on the right (as in K4c).
                        .item(model.shortModel(key), detail: model.sameForAllEstimate(key).map(Fmt.estimate)) {
                            model.sameForAll(key)
                        }
                    }
                }) {
                    HStack(spacing: 3) {
                        Text(model.t("nat.col.same_for_all"))
                        Image(systemName: "chevron.down").auFont(8, .semibold)
                    }
                    .foregroundStyle(AU.text2)
                    .padding(.horizontal, 4).padding(.vertical, 2)
                }
                .fixedSize()
                .disabled(model.plans.isEmpty)
            }
            .frame(width: QueueColumns.model)
            Text(model.t("nat.col.time")).frame(width: QueueColumns.time(compact), alignment: .trailing)
            Color.clear.frame(width: QueueColumns.chevron)
        }
        .auLabel()
        .padding(.leading, QueueColumns.leading)
        .padding(.trailing, QueueColumns.trailing)
    }

    private var tickState: TriCheckbox.State {
        if model.progress.queue.running { return .unavailable }
        let ready = model.files.filter { $0.state == .ready && !model.jobBlocksTick($0.id) }
        let n = ready.filter { model.isTicked($0) }.count
        if n == 0 { return .off }
        return n == ready.count ? .on : .mixed
    }
}

/// DS3 checkbox: on, off, mixed.
struct TriCheckbox: View {
    /// files2.py `cbx()`: on, off, mixed; locked = ticked but fixed (in a running queue);
    /// unavailable = can't be ticked yet (analysing, out of the run).
    enum State { case on, off, mixed, locked, unavailable }
    var state: State
    var action: () -> Void
    @Environment(\.isEnabled) private var enabled

    var body: some View {
        Button(action: action) {
            ZStack {
                switch state {
                case .off:
                    RoundedRectangle(cornerRadius: 4).fill(AU.control)
                    RoundedRectangle(cornerRadius: 4).strokeBorder(AU.boxLine)
                case .on, .mixed:
                    RoundedRectangle(cornerRadius: 4).fill(AU.primary)
                    if state == .on {
                        Image(systemName: "checkmark").auFont(9, .bold).foregroundStyle(AU.onPrimary)
                    } else {
                        RoundedRectangle(cornerRadius: 1).fill(AU.onPrimary).frame(width: 8, height: 2)
                    }
                case .locked:
                    RoundedRectangle(cornerRadius: 4).fill(AU.raised)
                    RoundedRectangle(cornerRadius: 4).strokeBorder(AU.glassLine)
                    Image(systemName: "checkmark").auFont(9, .bold).foregroundStyle(AU.text3)
                case .unavailable:
                    RoundedRectangle(cornerRadius: 4).strokeBorder(AU.glassLine).opacity(0.5)
                }
            }
            .frame(width: 15, height: 15)
        }
        .buttonStyle(.plain)
        // Locked and unavailable carry their own look; the others fade when disabled.
        .opacity(enabled || state == .locked || state == .unavailable ? 1 : 0.4)
    }
}

// MARK: - Row

struct QueueRow: View {
    @Environment(AppModel.self) private var model
    @Environment(\.undoManager) private var undo
    @Environment(\.queueCompact) private var compact
    var file: QueueFile

    private var open: Bool { model.openRows.contains(file.id) }
    private var job: QueueProgress.Job? { model.job(file.id) }
    /// While a queue runs, rows that aren't part of it (board "out" state).
    private var outOfRun: Bool {
        model.progress.queue.running && !(model.progress.queue.ids ?? []).contains(file.id) && job?.state != .done
    }
    private var inRun: Bool { model.progress.queue.running && (model.progress.queue.ids ?? []).contains(file.id) }

    private var fillMode: RowFill.Mode? {
        switch job?.state {
        case .running: .running
        case .paused: .paused
        case .done where model.isRedo(file.id): nil
        case .done: (job?.warnings ?? []).isEmpty ? .done : .doneWarn
        default: nil
        }
    }

    private var borderColor: Color {
        switch job?.state {
        case .running: AU.softLine
        case .paused: AU.yellowLine
        case .done where model.isRedo(file.id): AU.line
        case .done: (job?.warnings ?? []).isEmpty ? AU.greenLine : AU.yellowLine
        case .interrupted: job?.defective == true ? AU.redLine : AU.line
        default: AU.line
        }
    }
    private var selected: Bool { model.selection.contains(file.id) }

    /// Ticked and fixed while its queue runs; not tickable while analysed.
    private var tickState: TriCheckbox.State {
        if model.progress.queue.running, (model.progress.queue.ids ?? []).contains(file.id) { return .locked }
        if file.state == .analysing || file.state == .queued { return .unavailable }
        return model.isTicked(file) ? .on : .off
    }

    var body: some View {
        VStack(spacing: 0) {
            VStack(spacing: 0) {
                header
                if let j = job, j.state == .running || j.state == .paused {
                    RowStageLines(job: j, estimate: model.plan(file.id)?.estimate)
                        .padding(.leading, QueueColumns.leading + QueueColumns.check + 12)
                        .padding(.trailing, QueueColumns.trailing)
                        .padding(.bottom, 10)
                    PiecedEdgeBar(fraction: j.fraction ?? 0, chunks: j.chunks ?? 1,
                                  color: j.state == .paused ? AU.yellow : AU.primary)
                        .animation(RowFill.tween, value: j.fraction ?? 0)
                }
            }
            // The strip (the row, its stage lines and its bar) is what opens and closes
            // the drawer, and what lights up under the pointer; the drawer itself never does.
            // A click on it that isn't a control toggles, like the chevron; ⌘ and ⇧ still
            // select rows (Delete, the menu).
            .contentShape(Rectangle())
            .onTapGesture { click() }
            .auHover(Rectangle(), enabled: !outOfRun)
            .background(alignment: .leading) {
                if let mode = fillMode {
                    GeometryReader { g in
                        RowFill(fraction: (mode == .running || mode == .paused) ? (job?.fraction ?? 0) : 1, mode: mode,
                                chunks: mode == .running || mode == .paused ? job?.chunks ?? 1 : nil)
                            .animation(RowFill.tween, value: job?.fraction ?? 0)
                            .frame(width: g.size.width, height: g.size.height)
                    }
                }
            }
            if open {
                // The drawer fills the row to its edges, with one 16 pt padding: a frame
                // inside the frame took room for nothing (29 Oct).
                FilePanel(file: file)
            }
        }
        // The row is a CSS border-box: everything sits inside its 1 pt frame.
        .padding(1)
        .background {
            ZStack(alignment: .topLeading) {
                RoundedRectangle(cornerRadius: AU.Radius.card).fill(job?.state == .interrupted && job?.defective == true ? AU.redSoft : AU.surface)
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
        .clipShape(RoundedRectangle(cornerRadius: AU.Radius.card))
        .overlay(RoundedRectangle(cornerRadius: AU.Radius.card)
            .strokeBorder(selected ? AU.primary : borderColor, lineWidth: selected ? 1.5 : 1))
        .contentShape(RoundedRectangle(cornerRadius: AU.Radius.card))
        .opacity(outOfRun ? 0.45 : 1)
        .disabled(outOfRun)
        .contextMenu { menu }
    }

    private var header: some View {
        HStack(spacing: 12) {
            TriCheckbox(state: tickState) {
                if model.unticked.contains(file.id) { model.unticked.remove(file.id) } else { model.unticked.insert(file.id) }
            }
            .frame(width: QueueColumns.check)
            .disabled(file.state != .ready || model.progress.queue.running || model.jobBlocksTick(file.id))
            VStack(alignment: .leading, spacing: 5) {
                Text(file.name).auFont(12.5, .medium).foregroundStyle(AU.text)
                    .lineLimit(1).truncationMode(.middle)
                HStack(spacing: 5) {
                    // Analysis warnings until the file is processed; then only the result's (rule of 28/10).
                    if !file.warnings.isEmpty && file.state == .ready && job == nil {
                        Label(model.localizer.tn("nat.queue.n_warnings", file.warnings.count),
                              systemImage: "exclamationmark.triangle.fill")
                            .labelStyle(SmallIconLabel()).foregroundStyle(AU.yellowText)
                        Text("·")
                    }
                    if compact, let facts = resolutionAndLength {
                        Text(verbatim: facts).auFont(11, mono: true).foregroundStyle(AU.text2).fixedSize()
                        Text("·")
                    }
                    if compact, job?.state == .interrupted, job?.defective != true, let key = model.plan(file.id)?.model {
                        Text(model.shortModel(key)).foregroundStyle(AU.text2).fixedSize()
                        Text("·")
                    }
                    Text(detailLine).lineLimit(1).truncationMode(.tail)
                }
                .auFont(11).foregroundStyle(AU.text3)
                // The fixed pieces of this line never widen the row: what doesn't fit is cut.
                .frame(minWidth: 0, maxWidth: .infinity, alignment: .leading)
                .clipped()
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if !compact {
                Text(verbatim: file.report.map { r -> String in "\(r.width)×\(r.height)" } ?? "—")
                    .auFont(AUFont.numbers).foregroundStyle(AU.textCode)
                    .frame(width: QueueColumns.resolution, alignment: .trailing)
                Text(verbatim: file.report.map { Fmt.clock($0.duration) } ?? "—")
                    .auFont(AUFont.numbers).foregroundStyle(AU.textCode)
                    // Centred, so its gaps to Resolution and Status match.
                    .frame(width: QueueColumns.length, alignment: .center)
            }
            HStack { statusChip; Spacer(minLength: 0) }.frame(width: QueueColumns.status)
            modelColumn.frame(width: QueueColumns.model, alignment: .leading)
            timeColumn.frame(width: QueueColumns.time(compact), alignment: .trailing)
            Button { toggle() } label: {
                Image(systemName: open ? "chevron.up" : "chevron.down").auFont(11, .semibold)
                    .foregroundStyle(AU.text2).frame(width: QueueColumns.chevron, height: 24)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
        .padding(.leading, QueueColumns.leading)
        .padding(.trailing, QueueColumns.trailing)
        .frame(height: QueueColumns.rowHeight)
    }

    /// "854×480 · 23:41": the two columns that join the second line when compact.
    private var resolutionAndLength: String? {
        file.report.map { "\($0.width)×\($0.height) · \(Fmt.clock($0.duration))" }
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
        if let r = job?.recipe, job?.state == .interrupted {
            var own: [String] = []
            if let h = r.values["height"]?.number { own.append("\(Int(h))p") }
            if let c = r.values["crf"]?.number { own.append("CRF \(Int(c))") }
            if let p = r.values["preset"]?.string { own.append(p) }
            if !own.isEmpty { parts.append(model.t("nat.queue.own_settings", ["values": own.joined(separator: " · ")])) }
        }
        if file.state == .missing { parts = [model.t("nat.files.missing_file")] }
        return parts.joined(separator: " · ")
    }

    @ViewBuilder
    private var statusChip: some View {
        // Once the run is over, files it never launched show their ready state again (F6).
        if let j = job, !(j.state == .queued && !model.progress.queue.running) {
            switch j.state {
            case .running: StatusChip(model.t("nat.chip.in_progress"), tone: .accent)
            case .paused: StatusChip(model.t("nat.chip.paused"), tone: .yellow, symbol: "pause.fill")
            case .queued:
                if j.starting == true {
                    StatusChip(model.t("nat.chip.starting"), tone: .accent)
                } else if let until = model.progress.queue.restingUntil, model.nextQueuedId == file.id {
                    StatusChip(model.t("nat.chip.next", ["time": model.clockTime(until)]), tone: .accent)
                } else {
                    StatusChip(model.t("nat.chip.queued"))
                }
            case .done:
                if model.isRedo(file.id) {
                    StatusChip(model.t("nat.chip.to_redo"), tone: .accent, symbol: "arrow.counterclockwise")
                } else if (j.warnings ?? []).isEmpty {
                    StatusChip(model.t("nat.chip.done"), tone: .green, symbol: "checkmark")
                } else {
                    StatusChip(model.localizer.tn("nat.chip.done_warn", j.warnings?.count ?? 0), tone: .yellow,
                               symbol: "exclamationmark.triangle.fill")
                }
            case .interrupted:
                if j.defective == true { StatusChip(model.t("nat.chip.failed"), tone: .red, symbol: "exclamationmark.octagon.fill") }
                else { StatusChip(model.t("nat.chip.interrupted"), tone: .yellow) }
            }
        } else {
            plainStatusChip
        }
    }

    @ViewBuilder
    private var plainStatusChip: some View {
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
        // A finished file keeps its model, unless it's put back in the Queue (Redo).
        if inRun || job?.state == .done && !model.isRedo(file.id), let key = model.plan(file.id)?.model {
            PopupLabel(model.shortModel(key), width: QueueColumns.model).opacity(0.5)
        } else if compact, let j = job, j.state == .interrupted, j.defective != true {
            // Narrow: Resume and Discard move here from the Time column; the model,
            // which can't change, goes to the second line.
            resumeDiscard
        } else if job?.state == .interrupted, let key = model.plan(file.id)?.model {
            // F6: an interrupted file keeps its model (it resumes with its own settings).
            PopupLabel(model.shortModel(key), width: QueueColumns.model)
        } else if file.state == .ready, let p = model.plan(file.id), let current = p.model {
            PopupMenu({
                (p.models ?? []).map { opt in
                    .item(optionLabel(opt), detail: opt.unreachable == nil ? opt.estimate.map(Fmt.estimate) : nil,
                          checked: opt.key == current, enabled: opt.unreachable == nil) {
                        model.chooseModel(opt.key, for: [file.id])
                    }
                }
            }) {
                PopupLabel(model.shortModel(current), width: QueueColumns.model)
            }
            .help(p.reason ?? "")
        } else {
            Text(file.state == .ready ? "—" : model.t("nat.queue.after_analysis"))
                .auFont(12).foregroundStyle(AU.text2)
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
        return label
    }

    private var resumeDiscard: some View {
        HStack(spacing: 6) {
            Button(model.t("nat.run.resume")) { model.command("job.resume", id: file.id) }.auButton(.secondary, .small)
                .disabled(model.progress.queue.running)
            Button(model.t("nat.run.discard")) { model.confirmDiscard(file.id) }.auButton(.destructive, .small)
                .disabled(model.progress.queue.running)
        }
        .fixedSize()
    }

    @ViewBuilder
    private var timeColumn: some View {
        if let j = job, j.state == .running || j.state == .paused {
            Button { model.confirmStop(file.id) } label: { Label(model.t("nat.run.stop"), systemImage: "stop.fill") }
                .auButton(.secondary, .small)
        } else if let j = job, j.state == .done, !model.isRedo(file.id) {
            // As the boards and the summary sheet: "24m 10s", "7h 28m".
            Text(verbatim: FinishedSheet.duration(j.seconds ?? 0)).auFont(AUFont.numbers).foregroundStyle(AU.textCode)
        } else if let j = job, j.state == .interrupted, j.defective == true {
            // F6: a failed file says where it stopped; it's tried again from the list.
            Text(model.t("nat.run.stopped_at", ["pct": Int(((j.fraction ?? 0) * 100).rounded())]))
                .auFont(11.5, mono: true).foregroundStyle(AU.redText)
                .lineLimit(1).fixedSize()
        } else if let j = job, j.state == .interrupted {
            // F6: Resume and Discard in the Time column, next to the model.
            // Narrow: they sit in the model column; the column keeps its width.
            if compact { Color.clear.frame(height: 1) } else { resumeDiscard }
        } else if let p = model.plan(file.id), let e = p.estimate {
            // No info icon (too small to be worth it); the range stays in the tooltip.
            Text(verbatim: Fmt.estimate(e)).auFont(AUFont.numbers).foregroundStyle(AU.textCode)
                .lineLimit(1).fixedSize()
                .help(model.t("nat.queue.range", ["best": Fmt.span(p.estimateBest ?? e), "worst": Fmt.span(p.estimateWorst ?? e)]))
        } else {
            Text(verbatim: "—").auFont(AUFont.numbers).foregroundStyle(AU.text2)
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
            if open { model.openRows.remove(file.id) } else { model.openRows.insert(file.id) }
        }
    }

    private func click() {
        let flags = NSEvent.modifierFlags
        if !flags.contains(.command) && !flags.contains(.shift) {
            model.selection = []
            toggle()
        } else if flags.contains(.command) {
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
    @Environment(\.queueCompact) private var compact
    var file: QueueFile

    var body: some View {
        @Bindable var m = model
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 8) {
                // Board F1: the DS capsule segments, not the system's segmented control.
                CapsuleSegments([(PanelTab.processing, model.t("nat.panel.processing")),
                                 (PanelTab.analysis, model.t("nat.panel.analysis"))],
                                selection: Binding(get: { model.panelTab(for: file.id) },
                                                   set: { m.panelTabs[file.id] = $0 }))
                    .fixedSize()
                Spacer()
                // The dedup chip starts under the Model column, like the last group below.
                HStack(spacing: 8) {
                    dedup
                    Spacer(minLength: 0)
                    // Not for a finished file: its source hasn't changed (F6). Back for a redo (F6d).
                    if model.job(file.id)?.state != .done || model.isRedo(file.id) {
                        Button { model.reanalyse([file.id]) } label: { Label(model.t("nat.menu.reanalyse"), systemImage: "arrow.clockwise") }
                            .auButton(.secondary, .small)
                            .disabled(file.state == .analysing || model.job(file.id) != nil && model.progress.queue.running)
                    }
                }
                .frame(width: QueueColumns.panelLast(compact))
            }
            // Both tabs are laid out, the hidden one keeps the panel as tall as the taller of the two.
            let tab = model.panelTab(for: file.id)
            // The shown tab sits on top, so nothing hidden lies over its controls.
            ZStack(alignment: .topLeading) {
                if tab == .processing {
                    analysisTab.hidden().accessibilityHidden(true)
                    processingTab
                } else {
                    processingTab.hidden().accessibilityHidden(true)
                    analysisTab
                }
            }
        }
        .padding(16)
        .background(AU.inset)
    }

    @ViewBuilder
    private var processingTab: some View {
        if let j = model.job(file.id), j.state == .running || j.state == .paused {
            if let p = model.plan(file.id) { ProcessingPanel(file: file, plan: p) }
        } else if let j = model.job(file.id), j.state == .done, let p = model.plan(file.id) {
            // F6–F6e: the outcome (or the redo) on top of the same groups as while it ran.
            if model.isRedo(file.id) {
                ProcessingPanel(file: file, plan: p) { RedoNote(file: file, plan: p) }
            } else {
                ProcessingPanel(file: file, plan: p, made: j.output) { JobOutcome(file: file, job: j) }
            }
        } else if let j = model.job(file.id), j.state == .interrupted, j.defective == true, let p = model.plan(file.id) {
            ProcessingPanel(file: file, plan: p) { JobFailed(job: j) }
        } else if let p = model.plan(file.id), p.model != nil {
            ProcessingPanel(file: file, plan: p)
        } else if let p = model.plan(file.id), let e = p.error {
            NoteView(.red, title: model.t("nat.chip.cant_process"), text: e)
        } else {
            Text(model.t("nat.panel.waiting")).auSmall()
        }
    }

    @ViewBuilder
    private var analysisTab: some View {
        if let r = file.report {
            analysis(r)
        } else if file.state == .failed {
            NoteView(.red, title: model.t("nat.panel.failed"), text: file.error ?? "")
        } else {
            Text(model.t("nat.panel.waiting")).auSmall()
        }
    }

    @ViewBuilder
    private var dedup: some View {
        if let d = file.report?.dedupMeasured {
            let pct = Int((d * 100).rounded())
            // In a narrow Queue the last column is too short for the whole chip and Re-analyse.
            ViewThatFits(in: .horizontal) {
                StatusChip(model.t("nat.panel.dedup_measured", ["pct": pct]), tone: .green, symbol: "checkmark")
                StatusChip("dedup \(pct)%", tone: .green, symbol: "checkmark")
            }
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
        VStack(alignment: .leading, spacing: PanelRows.gap) {
            if compact {
                // Board D6: Tracks under Timing and Image, on their columns.
                HStack(alignment: .top, spacing: 32) {
                    DataGroup(title: model.t("nat.panel.timing"), items: timingItems(r))
                    DataGroup(title: model.t("nat.panel.image"), items: imageItems(r))
                }
                .panelRowScope()
                DataGroup(title: model.t("nat.panel.tracks"), items: trackItems(r), wide: true)
            } else {
                HStack(alignment: .top, spacing: 32) {
                    DataGroup(title: model.t("nat.panel.timing"), items: timingItems(r))
                    DataGroup(title: model.t("nat.panel.image"), items: imageItems(r))
                    DataGroup(title: model.t("nat.panel.tracks"), items: trackItems(r))
                        .frame(width: QueueColumns.panelLast(compact))
                }
                .panelRowScope()
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

    private func timingItems(_ r: FileReport) -> [(String, String, Bool)] {
        [
            (model.t("nat.panel.frame_rate"), r.fpsText.map { "\($0) (\(r.fpsFraction ?? ""))" } ?? "—", false),
            (model.t("nat.panel.timebase"), r.timebaseLabel, r.timebase != "cfr"),
            (model.t("nat.panel.frames"), Fmt.count(r.frames), false),
            (model.t("nat.panel.duration"), Fmt.clockTenths(r.duration), false),
            (model.t("nat.panel.bitrate"), bitrate(r), false),
            (model.t("nat.panel.size"), file.size.map(Fmt.bytes) ?? "—", false),
        ]
    }

    private func imageItems(_ r: FileReport) -> [(String, String, Bool)] {
        [
            (model.t("nat.panel.geometry"), "\(r.width)×\(r.height)", false),
            (model.t("nat.panel.pixels"), r.anamorphic ? "SAR \(r.sar)" : model.t("nat.panel.square"), r.anamorphic),
            (model.t("nat.panel.format"), "\(r.pixFmt) · \(r.bitDepth) bit", false),
            (model.t("nat.panel.colour"), colour(r), r.colorSpace == nil),
            (model.t("nat.panel.codec"), r.codecLabel, false),
            (model.t("nat.panel.primaries"), primaries(r), false),
        ]
    }

    private func trackItems(_ r: FileReport) -> [(String, String, Bool)] {
        [
            (model.t("nat.panel.audio"), r.audioTracks > 0 ? "\(r.audioTracks)" : "—", false),
            (model.t("nat.panel.subtitles"), r.subtitleTracks > 0 ? "\(r.subtitleTracks) · \(r.subtitleCodecs.joined(separator: ", "))" : "—",
             r.subtitleCodecs.contains("mov_text")),
            (model.t("nat.panel.chapters"), r.chapters > 0 ? "\(r.chapters)" : "—", false),
            (model.t("nat.panel.fields"), fields(r), r.fields != nil && r.fields != "progressivo"),
            (model.t("nat.panel.container"), container(r), false),
        ]
    }

    private func colour(_ r: FileReport) -> String {
        guard let cs = r.colorSpace, cs != "unknown" else { return model.t("nat.panel.not_declared") }
        return cs.uppercased().replacingOccurrences(of: "BT", with: "BT.")
    }

    /// The average over the whole file, from its size and length: "3.9 Mb/s".
    private func bitrate(_ r: FileReport) -> String {
        guard let size = file.size, r.duration > 0 else { return "—" }
        return String(format: "%.1f Mb/s", Double(size) * 8 / r.duration / 1_000_000)
    }

    /// ffprobe names a family ("mov,mp4,m4a,3gp,3g2,mj2", "matroska,webm"): the file's own kind of it.
    private func container(_ r: FileReport) -> String {
        let family = r.container.lowercased().split(separator: ",").map(String.init)
        let ext = (file.path as NSString).pathExtension.lowercased()
        if family.contains("matroska") { return ext == "webm" ? "WebM" : "MKV" }
        if family.contains(ext) || (ext == "m4v" && family.contains("mp4")) { return ext.uppercased() }
        return (family.first ?? r.container).uppercased()
    }

    /// "BT.709 · BT.709", or a dash when the file declares neither.
    private func primaries(_ r: FileReport) -> String {
        func name(_ v: String?) -> String? {
            guard let v, !v.isEmpty, v != "unknown" else { return nil }
            return v.uppercased().replacingOccurrences(of: "BT", with: "BT.")
        }
        let parts = [name(r.colorPrimaries), name(r.colorTransfer)].compactMap { $0 }
        return parts.isEmpty ? "—" : parts.joined(separator: " · ")
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

/// The panel's groups share their rows: a row is as tall as its tallest
/// cell in any group, so the second row starts at the same height everywhere.
enum PanelRows {
    static let gap: CGFloat = 16

    struct Heights: PreferenceKey {
        static let defaultValue: [Int: CGFloat] = [:]
        static func reduce(value: inout [Int: CGFloat], nextValue: () -> [Int: CGFloat]) {
            value.merge(nextValue(), uniquingKeysWith: max)
        }
    }

    struct Key: EnvironmentKey { static let defaultValue: [Int: CGFloat] = [:] }

    /// Measures a cell before its minimum height, so a row can shrink again when the panel widens.
    struct Cell: ViewModifier {
        @Environment(\.panelRowHeights) private var heights
        var row: Int
        func body(content: Content) -> some View {
            content
                .background(GeometryReader { g in Color.clear.preference(key: Heights.self, value: [row: g.size.height]) })
                .frame(minHeight: heights[row], alignment: .top)
        }
    }

    /// Collects the heights of one panel's cells and hands them back to its cells.
    struct Scope: ViewModifier {
        @State private var heights: [Int: CGFloat] = [:]
        func body(content: Content) -> some View {
            content
                .environment(\.panelRowHeights, heights)
                .onPreferenceChange(Heights.self) { heights = $0 }
                .transformPreference(Heights.self) { $0 = [:] }
        }
    }
}

extension EnvironmentValues {
    var panelRowHeights: [Int: CGFloat] {
        get { self[PanelRows.Key.self] }
        set { self[PanelRows.Key.self] = newValue }
    }
}

extension View {
    func panelRow(_ row: Int) -> some View { modifier(PanelRows.Cell(row: row)) }
    func panelRowScope() -> some View { modifier(PanelRows.Scope()) }
}

/// DS4 "Data group": a title with a rule, then label-over-value pairs in two columns.
struct DataGroup: View {
    var title: String
    var items: [(String, String, Bool)]
    /// A control in place of an item's value (the Height menu), by index.
    var controls: [Int: AnyView] = [:]
    /// Board D6: in a narrow Queue the third group goes under the other two, across both,
    /// its items on their four columns.
    var wide = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            DataGroupTitle(title)
            if wide {
                HStack(alignment: .top, spacing: 32) {
                    grid(columns: 4, from: 0)
                    grid(columns: 4, from: 2)
                }
                .panelRowScope()
            } else {
                grid(columns: 2, from: 0)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// Two columns of items: every `columns` items a row, starting at `from` within each.
    private func grid(columns: Int, from: Int) -> some View {
        Grid(alignment: .topLeading, horizontalSpacing: 16, verticalSpacing: PanelRows.gap) {
            ForEach(0..<(items.count + columns - 1) / columns, id: \.self) { row in
                GridRow {
                    ForEach(0..<2, id: \.self) { col in
                        let i = row * columns + from + col
                        if i < items.count {
                            cell(i).panelRow(row)
                        } else {
                            Color.clear.frame(height: 0)
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func cell(_ i: Int) -> some View {
        VStack(alignment: .leading, spacing: controls[i] == nil ? 2 : 4) {
            Text(items[i].0).auFont(11).foregroundStyle(AU.text3)
            if let control = controls[i] {
                control
            } else {
                Text(verbatim: items[i].1).auFont(AUFont.numbers)
                    .foregroundStyle(items[i].2 ? AU.yellowText : AU.text)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// A data group's title over its rule.
struct DataGroupTitle: View {
    var title: String
    init(_ title: String) { self.title = title }
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).auFont(12.5, .semibold).foregroundStyle(AU.text)
            Rectangle().fill(AU.line).frame(height: 1)
        }
    }
}

// MARK: - Processing panel (F3)

struct ProcessingPanel<Outcome: View>: View {
    @Environment(AppModel.self) private var model
    @Environment(\.queueCompact) private var compact
    var file: QueueFile
    var plan: FilePlan
    /// The video made, for a finished file: its name, not the plan's.
    var made: String? = nil
    /// F6–F6e: the outcome or the redo, above the groups.
    @ViewBuilder var outcome: () -> Outcome

    var body: some View {
        VStack(alignment: .leading, spacing: PanelRows.gap) {
            outcome()
            if compact {
                // Board D6: Output file under Job and Encoding, on their columns.
                HStack(alignment: .top, spacing: 32) {
                    jobGroup
                    encodingGroup
                }
                .panelRowScope()
                outputGroupWide
            } else {
                HStack(alignment: .top, spacing: 32) {
                    jobGroup
                    encodingGroup
                    outputGroup.frame(width: QueueColumns.panelLast(compact))
                }
                .panelRowScope()
            }
            ForEach((plan.warnings ?? []), id: \.self) { w in NoteView(.yellow, text: w) }
        }
    }

    // Board F4b: Height and Output first, then the model, then the split in two items.
    private var jobGroup: some View {
        DataGroup(title: model.t("nat.plan.job"), items: [
            (model.t("nat.plan.height"), "", false),
            (model.t("nat.plan.output"), "\(plan.outputWidth ?? 0)×\(plan.outputHeight ?? 0)", false),
            (model.t("nat.col.model"), model.shortModel(plan.model ?? ""), plan.verdict == "no"),
            (model.t("nat.plan.pipeline"), pipeline, false),
            // Yellow only when a tight disk made more chunks, and only before the file is made.
            (model.t("nat.plan.split"), model.localizer.tn("nat.plan.split_n", plan.chunks ?? 1),
             plan.chunksTight == true && model.job(file.id)?.state != .done),
            (model.t("nat.plan.chunk_size"), model.t("nat.plan.chunk_frames", ["frames": Fmt.count(chunkSize)]), false),
        ], controls: [0: AnyView(heightMenu)])
    }

    private var encodingGroup: some View {
        DataGroup(title: model.t("nat.plan.encoding"), items: [
            (model.t("nat.plan.codec"), "\((plan.codec ?? "").replacingOccurrences(of: "lib", with: "").replacingOccurrences(of: "x265", with: "hevc")) \(plan.pixFmt ?? "")", false),
            ("CRF", "\(plan.crf ?? 18)", false),
            (model.t("nat.plan.preset"), plan.preset ?? "", false),
            (model.t("nat.plan.restoration"), (plan.restoration ?? []).isEmpty ? model.t("nat.plan.none") : (plan.restoration ?? []).joined(separator: ", "), false),
            (model.t("nat.plan.av"), audioSubtitles, false),
            (model.t("nat.plan.colour"), model.t("nat.plan.tagged", ["c": colour]), false),
        ])
    }

    /// Frames in each chunk; the last one is what's left over.
    private var chunkSize: Int {
        if let c = plan.chunkSize, c > 0 { return min(c, plan.frames ?? c) }
        let n = max(1, plan.chunks ?? 1)
        return ((plan.frames ?? 0) + n - 1) / n
    }

    /// Audio and subtitles are copied; mov_text can't go into an MKV and becomes SRT.
    private var audioSubtitles: String {
        (file.report?.subtitleCodecs ?? []).contains("mov_text") ? model.t("nat.plan.av_srt") : model.t("nat.plan.av_copied")
    }

    /// The colour written in the output: the source's, or the convention for its height (plan.py).
    private var colour: String {
        let declared = file.report?.colorSpace.flatMap { $0 == "unknown" ? nil : $0 }
        let space = declared ?? ((file.report?.height ?? 0) >= 720 ? "bt709" : "smpte170m")
        switch space {
        case "smpte170m", "bt470bg", "bt601": return "BT.601"
        default: return space.uppercased().replacingOccurrences(of: "BT", with: "BT.")
        }
    }

    private var heightMenu: some View {
        PopupMenu({
            [.item(model.t("nat.plan.height_default", ["h": model.settings?.height ?? 1080]),
                   checked: plan.heightIsDefault ?? true) { model.chooseHeight(nil, for: file.id) },
             .separator]
            + [720, 1080, 1440, 2160].map { h in
                .item("\(h)", checked: !(plan.heightIsDefault ?? true) && plan.height == h) { model.chooseHeight(h, for: file.id) }
            }
        }) {
            PopupLabel((plan.heightIsDefault ?? true) ? model.t("nat.plan.height_default", ["h": plan.height ?? 1080])
                       : "\(plan.height ?? 1080)", width: 152)
        }
        .fixedSize()
        // An interrupted file resumes with the settings it started with.
        .disabled(model.progress.queue.running || model.job(file.id)?.state == .interrupted
                  || model.job(file.id)?.state == .done && !model.isRedo(file.id))
    }

    private var pipeline: String {
        var s = "\(model.shortModel(plan.model ?? "").components(separatedBy: " ").first ?? "") \(plan.scale ?? 2)×"
        if let d = plan.downscale, d > 1.001 { s += " → downscale \(String(format: "%.2f", d)):1" }
        return s
    }

    private var outputGroup: some View {
        VStack(alignment: .leading, spacing: 12) {
            DataGroupTitle(model.t("nat.plan.output_file"))
            VStack(alignment: .leading, spacing: PanelRows.gap) {
                nameCell.panelRow(0)
                folderCell.panelRow(1)
                logCell.panelRow(2)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// Board D6: in a narrow Queue, under Job and Encoding: the name across Job,
    /// the folder and the log on Encoding's two columns.
    private var outputGroupWide: some View {
        VStack(alignment: .leading, spacing: 12) {
            DataGroupTitle(model.t("nat.plan.output_file"))
            HStack(alignment: .top, spacing: 32) {
                nameCell
                HStack(alignment: .top, spacing: 16) {
                    folderCell
                    logCell
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var nameCell: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(model.t("nat.plan.name")).auFont(11).foregroundStyle(AU.text3)
            Text(verbatim: made.map { ($0 as NSString).lastPathComponent } ?? plan.outputName ?? "")
                .auFont(AUFont.numbers).foregroundStyle(AU.text)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var folderCell: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(model.t("nat.plan.folder")).auFont(11).foregroundStyle(AU.text3)
            // Fixed when the file entered the Queue (as HandBrake does).
            if plan.outputNextToSource == false, let folder = plan.outputFolder {
                Text(verbatim: (folder as NSString).abbreviatingWithTildeInPath).auFont(AUFont.numbers).foregroundStyle(AU.text)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                Text(model.t("nat.plan.next_to")).auFont(AUFont.numbers).foregroundStyle(AU.text)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// The log exists once the file has started (board F4b); until then its column stays empty.
    @ViewBuilder private var logCell: some View {
        if let log = model.job(file.id)?.log, !model.isRedo(file.id) {
            VStack(alignment: .leading, spacing: 2) {
                Text(model.t("nat.plan.log")).auFont(11).foregroundStyle(AU.text3)
                UnderlineLink(model.t("nat.btn.show_log"), tone: .neutral) { model.openLog(log) }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            Color.clear.frame(maxWidth: .infinity, maxHeight: 0)
        }
    }
}

extension ProcessingPanel where Outcome == EmptyView {
    init(file: QueueFile, plan: FilePlan) {
        self.init(file: file, plan: plan, outcome: { EmptyView() })
    }
}

// MARK: - Action bar

struct QueueActionBar: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        if model.progress.queue.running { RunningBar() } else { idle }
    }

    private var calibrationNote: String {
        if let w = model.calibratedWhen {
            return model.t("nat.queue.calibrated_note", ["when": model.relative(Date(timeIntervalSince1970: w))])
        }
        return model.t("nat.queue.factory_note")
    }

    @ViewBuilder
    private var idle: some View {
        let n = model.files.filter { model.isTicked($0) }.count
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 4) {
                    // F6e: nothing ticked while a redo waits for Overwrite or Don't Redo.
                    let waiting = n == 0 && model.files.contains { model.redoNeedsAnswer($0.id) }
                    Text("\(Text(model.localizer.tn("nat.queue.selected", n)).fontWeight(.semibold).foregroundStyle(AU.text)) · \(waiting ? model.t("nat.queue.waiting_answer") : model.t("nat.queue.estimate", ["time": Fmt.span(model.selectionEstimate)]))")
                        .auFont(13).foregroundStyle(AU.text2)
                    Image(systemName: "info.circle").auFont(10).foregroundStyle(AU.text3)
                        .help(model.t("nat.queue.estimate_help"))
                }
                Text(model.t("nat.queue.estimate_note") + " · " + calibrationNote).auFont(12).foregroundStyle(AU.text2)
            }
            Spacer()
            Button { model.startQueue() } label: { Label(model.t("nat.queue.start"), systemImage: "play.fill") }
                .auButton(.primary, .regular)
                .disabled(model.queueTicked.isEmpty || model.calRun?.running == true)
        }
        .auBox(RoundedRectangle(cornerRadius: AU.Radius.card), fill: AU.surface, line: AU.line,
               padding: EdgeInsets(vertical: 12, horizontal: 16))
    }
}


/// The action bar while the queue runs (F4, F5, F7).
struct RunningBar: View {
    @Environment(AppModel.self) private var model

    /// "Queue: 1 completed · 1 processing · 2 waiting · estimated time left ~ 2h 10m · expected finish 18:40"
    private func queueLine(done: Int, waiting: Int, q: QueueProgress.Queue) -> String {
        var parts = [model.t("nat.run.q_completed", ["n": done]), model.t("nat.run.q_processing"),
                     model.t("nat.run.q_waiting", ["n": waiting])]
        if let lo = q.leftMin, let hi = q.leftMax {
            parts.append(model.t("nat.run.q_left", ["t": Fmt.estimate((lo + hi) / 2)]))
        }
        if let f = q.finish { parts.append(model.t("nat.run.q_finish", ["time": model.clockTime(f)])) }
        return model.t("nat.run.q_prefix") + " " + parts.joined(separator: " · ")
    }

    var body: some View {
        let q = model.progress.queue
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                if let until = q.restingUntil {
                    TimelineView(.periodic(from: .now, by: 1)) { ctx in
                        Label {
                            Text(model.t("nat.run.rest_line", ["i": min(q.position ?? 1, q.total ?? 1), "n": q.total ?? 1,
                                                              "t": Fmt.elapsed(until - ctx.date.timeIntervalSince1970)]))
                        } icon: { Image(systemName: "cup.and.saucer") }
                        .labelStyle(SmallIconLabel())
                            .auFont(13, .semibold).foregroundStyle(AU.text)
                    }
                    Text(model.t("nat.run.rest_note")).auFont(12).foregroundStyle(AU.text2)
                } else {
                    let waiting = (q.ids ?? []).filter { model.job($0)?.state == .queued }.count
                    let done = (q.ids ?? []).filter { model.job($0)?.state == .done || model.job($0)?.state == .interrupted }.count
                    Text(model.t(q.paused ? "nat.run.paused_line" : "nat.run.processing_line", ["i": q.position ?? 1, "n": q.total ?? 1])
                         + (waiting > 0 ? " · " + model.localizer.tn("nat.run.waiting_files", waiting) : ""))
                        .auFont(13, .semibold).foregroundStyle(q.paused ? AU.yellowText : AU.text)
                    Text(queueLine(done: done, waiting: waiting, q: q)).auFont(12).foregroundStyle(AU.text2)
                }
            }
            Spacer()
            if q.resting {
                Button { model.command("queue.startNow") } label: { Label(model.t("nat.run.start_now"), systemImage: "play.fill") }
                    .auButton(.secondary, .regular)
            } else if q.paused {
                Button { model.command("queue.resume") } label: { Label(model.t("nat.run.resume"), systemImage: "play.fill") }
                    .auButton(.secondary, .regular)
            } else {
                Button { model.command("queue.pause") } label: { Label(model.t("nat.run.pause"), systemImage: "pause.fill") }
                    .auButton(.secondary, .regular)
            }
            Button { model.confirmStopAll() } label: { Label(model.t("nat.run.stop_all"), systemImage: "stop.fill") }
                .auButton(.destructive, .regular)
        }
        .auBox(RoundedRectangle(cornerRadius: AU.Radius.card), fill: q.paused ? AU.yellowBg : AU.soft, line: q.paused ? AU.yellowLine : AU.softLine,
               padding: EdgeInsets(vertical: 12, horizontal: 16))
    }
}

extension EnvironmentValues {
    /// The Queue is narrower than `QueueColumns.compactBelow` (board F8).
    @Entry var queueCompact = false
}
