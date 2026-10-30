import DesignSystem
import Models
import SwiftUI

/// Pieces of the running queue (boards F4–F7).
enum RunStages {
    static let order = ["extract", "dedup", "upscale", "assemble"]
    /// Each step's share of the file's time, as the engine counts the progress (coda.QUOTE)
    /// and the texts say it: "0–3%", "5–99%".
    static let shares: [String: Double] = ["extract": 0.03, "dedup": 0.02, "upscale": 0.94, "assemble": 0.01]
    /// Each step's width on the bar: wider than its time for the short ones, so even
    /// in a narrow window every step reads as a bar of its own (29 Oct).
    static let widths: [String: Double] = ["extract": 0.05, "dedup": 0.03, "upscale": 0.90, "assemble": 0.02]
}

/// The 4 pt edge bar of a row: one piece per stage, the upscale split into
/// its chunks, each as wide as its share. The stages sit 8 pt apart and the
/// chunks 3 pt, so the four steps read as bars of their own (board F4).
struct PiecedEdgeBar: View, Animatable {
    var fraction: Double
    var chunks: Int
    var color: Color
    /// The progress itself slides (RowFill.tween), so the pieces fill one after
    /// the other: animating each piece's width made two of them fill at once.
    var animatableData: Double {
        get { fraction }
        set { fraction = newValue }
    }

    static let stageGap: CGFloat = 8
    static let chunkGap: CGFloat = 3

    var body: some View {
        GeometryReader { g in
            let pieces = Self.pieces(chunks: max(1, chunks))
            let gaps = Self.gaps(chunks: max(1, chunks))
            let usable = g.size.width - gaps.reduce(0, +)
            HStack(spacing: 0) {
                ForEach(pieces.indices, id: \.self) { i in
                    let p = pieces[i]
                    let f = min(1, max(0, (fraction - p.start) / p.share))
                    ZStack(alignment: .leading) {
                        Rectangle().fill(AU.trackSoft)
                        Rectangle().fill(color).frame(width: usable * p.width * f)
                    }
                    .frame(width: usable * p.width)
                    .padding(.trailing, i < gaps.count ? gaps[i] : 0)
                }
            }
        }
        .frame(height: 4)
    }

    /// The space after each piece but the last.
    static func gaps(chunks: Int) -> [CGFloat] {
        let stages = RunStages.order.flatMap { $0 == "upscale" ? Array(repeating: $0, count: max(1, chunks)) : [$0] }
        return (0..<(stages.count - 1)).map { stages[$0] == stages[$0 + 1] ? chunkGap : stageGap }
    }

    /// Where the progress ends on a bar `width` wide, gaps included, so the row's fill ends with it.
    static func end(fraction: Double, chunks: Int, width: CGFloat) -> CGFloat {
        let pieces = pieces(chunks: max(1, chunks))
        let gaps = gaps(chunks: max(1, chunks))
        let usable = width - gaps.reduce(0, +)
        var x: CGFloat = 0
        for (i, p) in pieces.enumerated() {
            let f = min(1, max(0, (fraction - p.start) / p.share))
            x += usable * p.width * f
            guard f >= 1, i < gaps.count else { break }
            x += gaps[i]
        }
        return x
    }


    /// Every piece: where it starts and how much of the file's progress it holds
    /// (real shares), and how wide it is on the bar (widths). Within a piece the
    /// fill follows the progress, so each step fills its own bar from end to end.
    static func pieces(chunks: Int) -> [(start: Double, share: Double, width: Double)] {
        var out: [(start: Double, share: Double, width: Double)] = []
        var start = 0.0
        for stage in RunStages.order {
            let share = RunStages.shares[stage] ?? 0, width = RunStages.widths[stage] ?? 0
            let n = stage == "upscale" ? chunks : 1
            for _ in 0..<n { out.append((start, share / Double(n), width / Double(n))); start += share / Double(n) }
        }
        return out
    }
}

/// The row's soft fill: a slow wave while running, a slow pulse when paused.
struct RowFill: View, Animatable {
    enum Mode { case running, paused, done, doneWarn }
    var fraction: Double
    var mode: Mode
    /// As the bar: the progress slides, the end follows it piece by piece.
    var animatableData: Double {
        get { fraction }
        set { fraction = newValue }
    }
    /// With the bar's chunks the fill ends where the bar does, gaps included.
    var chunks: Int? = nil
    /// Board F4: 70% of a 35% fill, crossed in 3.4 s.
    static let wave: CGFloat = 280
    static let speed: CGFloat = 200
    /// The progress arrives about once a second: the end slides to it (gaps included)
    /// instead of jumping, which in the fast first steps looked jerky.
    static let tween = Animation.linear(duration: 0.8)
    @State private var clock = WaveClock()

    private func width(_ full: CGFloat) -> CGFloat {
        guard let chunks else { return full * fraction }
        return PiecedEdgeBar.end(fraction: fraction, chunks: chunks, width: full)
    }

    var body: some View {
        GeometryReader { g in
            switch mode {
            case .done: Rectangle().fill(AU.soft)
            case .doneWarn: Rectangle().fill(AU.yellowTint)
            case .paused:
                TimelineView(.animation) { ctx in
                    let t = ctx.date.timeIntervalSinceReferenceDate
                    Rectangle().fill(AU.yellowTint)
                        .opacity(0.8 + 0.2 * cos(t * 2 * .pi / 3.2))
                        .frame(width: width(g.size.width))
                }
            case .running:
                ZStack(alignment: .leading) {
                    Rectangle().fill(AU.soft)
                    // The same wave on any fill (board F4's): fixed width and speed, so a
                    // short fill doesn't squeeze it and a long one doesn't stretch it.
                    TimelineView(.animation) { ctx in
                        // Each pass keeps the length it started with: deriving the phase from the
                        // growing fill made the wave jump while the bar moved fast (29 Oct).
                        let phase = clock.phase(at: ctx.date.timeIntervalSinceReferenceDate,
                                                travel: width(g.size.width) + Self.wave, speed: Self.speed)
                        LinearGradient(colors: [AU.primary.opacity(0), AU.primary.opacity(0.09), AU.primary.opacity(0)],
                                       startPoint: .leading, endPoint: .trailing)
                            .frame(width: Self.wave)
                            .offset(x: -Self.wave + phase.travel * phase.done)
                            .opacity(sin(Double(phase.done) * .pi))
                    }
                }
                .frame(width: width(g.size.width))
                .clipped()
            }
        }
        .allowsHitTesting(false)
    }
}

/// The wave's passes: each one runs over the length the fill had when it began.
final class WaveClock {
    private var start: Double?
    private var travel: CGFloat = 0

    func phase(at t: Double, travel now: CGFloat, speed: CGFloat) -> (done: CGFloat, travel: CGFloat) {
        if start == nil || CGFloat(t - (start ?? t)) * speed >= travel {
            start = t; travel = max(now, 1)
        }
        return (min(1, CGFloat(t - (start ?? t)) * speed / travel), travel)
    }
}

extension AppModel {
    func stageName(_ stage: String?) -> String { t("nat.stage.\(stage ?? "upscale")") }

    /// "Upscaling chunk 1 of 3 · 10,900 of 11,350 frames upscaled"
    func actionLine(_ j: QueueProgress.Job) -> String {
        if j.encoding == true {
            let line = t("nat.run.action_encode", ["i": j.chunk ?? 1, "n": max(j.chunks ?? 1, j.chunk ?? 1)])
            // The share only once it's measured: a segment can't be read until it has a few clusters.
            guard let f = j.encodeFraction, f > 0 else { return line }
            return line + " · " + t("nat.run.encoded_pct", ["pct": Int((f * 100).rounded())])
        }
        switch j.stage {
        case "upscale":
            if (j.chunks ?? 0) > 1 {
                return t("nat.run.action_chunk", ["i": j.chunk ?? 1, "n": j.chunks ?? 1,
                                                 "done": Fmt.count(j.framesDone ?? 0), "total": Fmt.count(j.framesTotal ?? 0)])
            }
            return t("nat.run.action_upscale", ["done": Fmt.count(j.framesDone ?? 0), "total": Fmt.count(j.framesTotal ?? 0)])
        case "extract": return t("nat.run.action_extract", ["done": Fmt.count(j.framesDone ?? 0), "total": Fmt.count(j.framesTotal ?? 0)])
        case "dedup": return t("nat.run.action_dedup")
        default: return t("nat.run.action_assemble")
        }
    }

    /// The step in progress, under the stage line: "~ 8.1 fps · 0:56 left · 22:26 elapsed".
    /// The whole file's time left is on the right of the row (29 Oct).
    func measures(_ j: QueueProgress.Job, now: Date = .now) -> String {
        var parts: [String] = []
        if let f = j.fps { parts.append(String(format: "~ %.1f fps", f)) }
        if let l = j.stepLeft { parts.append(t("nat.run.left", ["t": Fmt.elapsed(l)])) }
        // Counted here from the step's start, not taken from each engine round: those come
        // about once a second but not on the second, and the display skipped one now and then.
        // Paused, it holds at the moment of the pause.
        if let start = j.stepStarted ?? j.started {
            let until = j.state == .paused ? (j.pausedSince ?? now.timeIntervalSince1970) : now.timeIntervalSince1970
            parts.append(t("nat.run.elapsed", ["t": Fmt.elapsed(max(0, until - start))]))
        } else if let e = j.elapsed {
            parts.append(t("nat.run.elapsed", ["t": Fmt.elapsed(e)]))
        }
        return parts.joined(separator: " · ")
    }

    /// The whole file's time left: measured once the upscale runs, before that the plan's
    /// estimate less the time already spent.
    func fileLeft(_ j: QueueProgress.Job, estimate: Double?) -> Double? {
        if let l = j.left { return l }
        guard let estimate, let e = j.elapsed else { return nil }
        return max(60, estimate - e)
    }

    /// Times follow the system's region format (the texts follow the app language).
    func clockTime(_ epoch: Double) -> String {
        Date(timeIntervalSince1970: epoch).formatted(
            Date.FormatStyle(locale: .current).hour(.twoDigits(amPM: .abbreviated)).minute(.twoDigits))
    }
}

/// F4: the stage line and the action line under a running row's header.
struct RowStageLines: View {
    @Environment(AppModel.self) private var model
    var job: QueueProgress.Job
    var estimate: Double?

    var body: some View {
        let current = RunStages.order.firstIndex(of: job.stage ?? "upscale") ?? 2
        // files2.py `stage_line()` and the action line under it (board F4).
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                // Narrow rows drop the shares, then the other steps: never a word split in two (31 Oct,
                // the steps broke as "Extracti/on" at 720–780 pt).
                ViewThatFits(in: .horizontal) {
                    stages(current, shares: true)
                    stages(current, shares: false)
                    stages(current, shares: false, onlyCurrent: true)
                }
                Spacer(minLength: 8)
                Text("\(Text(model.t("nat.run.completed")).foregroundStyle(AU.text2)) \(Text("\(Int(((job.fraction ?? 0) * 100).rounded()))%").auRun(15, .semibold, mono: true).foregroundStyle(job.state == .paused ? AU.yellowText : AU.text))")
                    .auFont(AUTextStyle(12), runs: AUTextStyle(15, .semibold, mono: true))
            }
            HStack(alignment: .firstTextBaseline, spacing: 0) {
                actionText.auFont(12).lineLimit(1)
                Rectangle().fill(AU.text3).frame(width: 1.5, height: 13).clipShape(Capsule())
                    .padding(.horizontal, 12)
                    .alignmentGuide(.firstTextBaseline) { $0[.bottom] - 2 }
                // Ticks half a second past each whole elapsed second, so timer slack either way
                // never lands on a boundary: from .now the phase was random and moved with every
                // refresh, and the count skipped a second now and then (29 Oct).
                TimelineView(.periodic(from: Date(timeIntervalSince1970: (job.stepStarted ?? job.started ?? 0) + 0.5), by: 1)) { ctx in
                    Text(model.measures(job, now: ctx.date)).auFont(AUFont.smallNumbers).foregroundStyle(AU.text2).lineLimit(1)
                }
                Spacer(minLength: 8)
                // What's left matters more than the planned duration, which stays until it's measured.
                if let left = model.fileLeft(job, estimate: estimate) {
                    Text("\(Text(model.t("nat.run.time_left")).foregroundStyle(AU.text2)) \(Text(Fmt.estimate(left)).fontWeight(.semibold).foregroundStyle(AU.text))")
                        .auFont(12)
                } else if let estimate {
                    Text("\(Text(model.t("nat.run.estimated")).foregroundStyle(AU.text2)) \(Text(Fmt.estimate(estimate)).fontWeight(.semibold).foregroundStyle(AU.text))")
                        .auFont(12)
                }
            }
        }
    }

    private func stages(_ current: Int, shares: Bool, onlyCurrent: Bool = false) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            ForEach(Array(RunStages.order.enumerated()), id: \.offset) { i, stage in
                if !onlyCurrent || i == current {
                    if i > 0 && !onlyCurrent { Text(verbatim: "→").auFont(12).foregroundStyle(AU.text3) }
                    HStack(alignment: .firstTextBaseline, spacing: 7) {
                        StageDot(kind: i < current ? .done : i == current ? .now : .next, paused: job.state == .paused)
                            .alignmentGuide(.firstTextBaseline) { $0[VerticalAlignment.center] + 4 }
                        Text(model.stageName(stage)).auFont(12, i == current ? .semibold : .regular)
                            .foregroundStyle(i < current ? AU.greenText : i == current ? (job.state == .paused ? AU.yellowText : AU.text) : AU.text3)
                        if shares { Text(Self.range(stage)).auFont(10.5, mono: true).foregroundStyle(AU.text3).opacity(0.6) }
                    }
                    .fixedSize()
                }
            }
        }
    }

    /// "Upscaling chunk 1 of 3" in semibold, the rest of the line in the secondary colour.
    private var actionText: Text {
        let line = model.actionLine(job)
        guard let cut = line.range(of: " · ") else { return Text(line).fontWeight(.semibold).foregroundStyle(AU.text) }
        return Text("\(Text(line[..<cut.lowerBound]).fontWeight(.semibold).foregroundStyle(AU.text))\(Text(line[cut.lowerBound...]).foregroundStyle(AU.text2))")
    }

    /// "0–4%", "6–96%"…
    static func range(_ stage: String) -> String {
        var start = 0.0
        for s in RunStages.order {
            let share = RunStages.shares[s] ?? 0
            if s == stage { return "\(Int((start * 100).rounded()))–\(Int(((start + share) * 100).rounded()))%" }
            start += share
        }
        return ""
    }
}

/// F6, F6b: a finished file's outcome, on top of its Processing panel: the video
/// made, the warnings the title counts, the steps' times; Redo and Show in Finder.
struct JobOutcome: View {
    @Environment(AppModel.self) private var model
    var file: QueueFile
    var job: QueueProgress.Job

    var body: some View {
        let warnings = job.warnings ?? []
        let tone: AUTone = warnings.isEmpty ? .green : .yellow
        NoteView(tone, title: warnings.isEmpty ? model.t("nat.run.job_completed") : model.localizer.tn("nat.run.job_completed_warn", warnings.count),
                 // A resumed file says so: its time is the work of all its runs, more than this queue's.
                 text: model.t((job.runs ?? 1) > 1 ? "nat.run.job_completed_runs" : "nat.run.job_completed_text",
                               ["time": FinishedSheet.duration(job.seconds ?? 0), "n": job.runs ?? 1,
                                "name": URL(fileURLWithPath: job.output ?? "").lastPathComponent]),
                 bullets: warnings, footnote: model.stageTimes(job)) {
            HStack(spacing: 8) {
                Button { model.startRedo(file.id) } label: { Label(model.t("nat.redo.button"), systemImage: "arrow.counterclockwise") }
                    .buttonStyle(AUTintedButtonStyle(tone))
                    .disabled(model.progress.queue.running)
                Button(model.t("nat.menu.show_in_finder")) {
                    if let o = job.output { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: o)]) }
                }
                .buttonStyle(AUTintedButtonStyle(tone))
            }
        }
    }
}

/// F6c: a file that failed; where it stopped, its log, the steps it finished.
struct JobFailed: View {
    @Environment(AppModel.self) private var model
    var job: QueueProgress.Job

    var body: some View {
        NoteView(.red, title: model.t("nat.run.job_failed"),
                 text: model.t("nat.run.job_failed_text", ["pct": Int(((job.fraction ?? 0) * 100).rounded()),
                                                          "stage": model.stageName(job.stage)]),
                 footnote: model.stageTimes(job)) {
            if let log = job.log {
                Button(model.t("nat.btn.show_log")) { model.openLog(log) }.buttonStyle(AUTintedButtonStyle(.red))
            }
        }
    }
}

/// F6d, F6e: a finished file put back in the Queue. Another name keeps the video
/// made; the same name asks before overwriting it, and the file waits unticked.
struct RedoNote: View {
    @Environment(AppModel.self) private var model
    var file: QueueFile
    var plan: FilePlan

    var body: some View {
        let id = file.id
        let name = plan.outputName ?? ""
        if !model.redoOverwrites(id) {
            NoteView(.accent, title: model.t("nat.redo.title"),
                     text: model.t("nat.redo.text", ["name": name]) + "\n" + model.t("nat.redo.safe")) {
                Button(model.t("nat.redo.cancel")) { model.cancelRedo(id) }.buttonStyle(AUTintedButtonStyle(.accent))
            }
        } else if model.redoNeedsAnswer(id) {
            NoteView(.yellow, title: model.t("nat.redo.ask_title"), text: model.t("nat.redo.ask_text"),
                     strong: model.t("nat.redo.ask_question")) {
                HStack(spacing: 8) {
                    Button(model.t("nat.redo.overwrite")) { model.confirmOverwrite(id) }.buttonStyle(AUTintedButtonStyle(.yellow))
                    Button(model.t("nat.redo.cancel")) { model.cancelRedo(id) }.buttonStyle(AUTintedButtonStyle(.yellow))
                }
            }
        } else {
            NoteView(.yellow, title: model.t("nat.redo.confirmed_title"), text: model.t("nat.redo.confirmed_text", ["name": name])) {
                Button(model.t("nat.redo.cancel")) { model.cancelRedo(id) }.buttonStyle(AUTintedButtonStyle(.yellow))
            }
        }
    }
}

extension AppModel {
    /// "Extraction 0:48 · Repeated frames 0:22 · Upscale 22:31 · Assemble 0:29", when recorded.
    func stageTimes(_ job: QueueProgress.Job) -> String? {
        guard let st = job.stages, !st.isEmpty else { return nil }
        let parts = RunStages.order.compactMap { k in st[k].map { "\(stageName(k)) \(Fmt.elapsed($0))" } }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }
}

/// O4: the sheet when the queue ends (edge.py).
struct FinishedSheet: View {
    @Environment(AppModel.self) private var model

    private struct Row: Identifiable {
        var id: String { name }
        var name: String
        var state: String          // done | warn | failed | stopped | skipped
        var warnings: [String] = []
        var seconds: Double?
        var file: QueueFile?
        var output: String?
    }

    private var rows: [Row] {
        let l = model.finished ?? [:]
        func names(_ k: String) -> [String] { l[k]?.array.compactMap(\.string) ?? [] }
        var out: [Row] = []
        for n in names("expected") + names("succeeded") where !out.contains(where: { $0.name == n }) {
            let f = model.files.first { $0.name == n }
            let job = f.flatMap { model.job($0.id) }
            let state: String
            if names("succeeded").contains(n) { state = (job?.warnings ?? []).isEmpty ? "done" : "warn" }
            else if names("failed").contains(n) || names("defective_outputs").contains(n) { state = "failed" }
            else if names("interrupted").contains(n) { state = "stopped" }
            else if names("skipped").contains(n) { state = "skipped" }
            else if names("already_done").contains(n) { state = "done" }
            // In no list: the launch ended (Stop All) before this file began. It used to fall into "done" (31 Oct).
            else { state = "not_started" }
            out.append(Row(name: n, state: state, warnings: job?.warnings ?? [], seconds: job?.seconds, file: f,
                           output: state == "done" || state == "warn" ? job?.output : nil))
        }
        return out
    }

    var body: some View {
        let l = model.finished ?? [:]
        let rows = rows
        let done = rows.filter { $0.state == "done" || $0.state == "warn" }.count
        let failed = rows.filter { $0.state == "failed" }.count
        let stopped = rows.filter { $0.state == "stopped" }.count
        let warned = rows.contains { $0.state == "warn" }
        let seconds = (l["ended"]?.number ?? 0) - (l["started"]?.number ?? 0)
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 10) {
                // Yellow for failures or warnings; a file stopped on purpose is not a problem.
                Image(systemName: failed + (warned ? 1 : 0) == 0 ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    .auFont(18).foregroundStyle(failed + (warned ? 1 : 0) == 0 ? AU.green : AU.yellow)
                Text(model.t("nat.fin.title")).auFont(15, .semibold)
                Spacer()
                // Formatted like the rows (minutes cut, not rounded): with one file, 7h 28m 50s and 7h 28m 29s read the same.
                Text(model.t("nat.fin.in_all", ["time": Self.duration(seconds)])).auFont(12).foregroundStyle(AU.text2)
            }
            // "N of M done; the videos are next to the originals" only when something finished.
            Text([done > 0 ? model.localizer.tn("nat.fin.summary", rows.count, ["done": done]) : nil,
                  failed > 0 ? model.localizer.tn("nat.fin.summary_bad", failed) : nil,
                  stopped > 0 ? model.localizer.tn("nat.fin.summary_stopped", stopped) : nil].compactMap { $0 }.joined(separator: " "))
                .auSmall().fixedSize(horizontal: false, vertical: true)
            VStack(spacing: 2) {
                ForEach(rows) { r in
                    // edge.py: grid minmax(0,1fr) 150px 70px, gap 12.
                    HStack(spacing: 12) {
                        VStack(alignment: .leading, spacing: 1) {
                            // The video made, with the original under it; a file that made nothing keeps its own name.
                            Text(r.output.map { ($0 as NSString).lastPathComponent } ?? r.name)
                                .auFont(12, .medium).lineLimit(1).truncationMode(.middle)
                            if r.output != nil {
                                Text(model.t("nat.fin.from", ["name": r.name])).auFont(AUFont.small).foregroundStyle(AU.text3)
                                    .lineLimit(1).truncationMode(.middle)
                            }
                            if let w = r.warnings.first { Text(w).auFont(AUFont.small).foregroundStyle(AU.yellowText).lineLimit(1) }
                            if r.state == "failed" { Text(model.t("nat.fin.failed_line")).auFont(AUFont.small).foregroundStyle(AU.redText) }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        chip(r).frame(width: 150, alignment: .leading)
                        Text(r.seconds.map { Self.duration($0) } ?? "—").auFont(11.5, mono: true)
                            .foregroundStyle(AU.text2).frame(width: 70, alignment: .trailing)
                    }
                    .padding(.horizontal, 12).padding(.vertical, 8)
                    .background(RoundedRectangle(cornerRadius: 7).fill(r.state == "failed" ? AU.redSoft : .clear))
                }
            }
            HStack(spacing: 8) {
                Button { model.openLog(model.configuration.stateFolder.appendingPathComponent("records/queue.log").path) } label: {
                    Label(model.t("nat.btn.show_log"), systemImage: "doc.text")
                }
                .auButton(.plain, .regular)
                Spacer()
                if done > 0 {
                    Button(model.t("nat.menu.show_in_finder")) {
                        // Selects the videos made (by default they sit next to the originals).
                        let urls = rows.compactMap(\.output).map { URL(fileURLWithPath: $0) }
                        if !urls.isEmpty { NSWorkspace.shared.activateFileViewerSelecting(urls) }
                    }
                    .auButton(.secondary, .regular)
                }
                Button(model.t("nat.cal.close")) { model.markFinishedSeen() }.auButton(.primary, .regular)
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 640)
        .background(AU.sheet)
    }

    @ViewBuilder
    private func chip(_ r: Row) -> some View {
        switch r.state {
        case "done": StatusChip(model.t("nat.chip.done"), tone: .green, symbol: "checkmark")
        case "warn": StatusChip(model.localizer.tn("nat.chip.done_warn", r.warnings.count), tone: .yellow, symbol: "exclamationmark.triangle.fill")
        case "failed": StatusChip(model.t("nat.chip.failed"), tone: .red)
        case "stopped": StatusChip(model.t("nat.chip.interrupted"), tone: .yellow)   // as in the Queue: resumable
        case "not_started": StatusChip(model.t("nat.fin.not_started"))
        default: StatusChip(model.t("nat.fin.skipped"))
        }
    }

    /// 24m 10s / 1h 52m
    static func duration(_ s: Double) -> String {
        let t = max(0, Int(s.rounded()))
        return t >= 3600 ? "\(t / 3600)h \(String(format: "%02d", (t % 3600) / 60))m" : "\(t / 60)m \(String(format: "%02d", t % 60))s"
    }
}

/// files2.py `dot()`: done 8 pt green, next 8 pt grey, now 10 pt in the accent with
/// a ring that breathes out (yellow and still while paused).
struct StageDot: View {
    enum Kind { case done, now, next }
    var kind: Kind
    var paused = false
    @State private var breathe = false

    var body: some View {
        switch kind {
        case .done: Circle().fill(AU.green).frame(width: 8, height: 8)
        case .next: Circle().fill(AU.text3).opacity(0.6).frame(width: 8, height: 8)
        case .now:
            Circle().fill(paused ? AU.yellow : AU.primary).frame(width: 10, height: 10)
                .background {
                    if !paused {
                        Circle().stroke(AU.primary.opacity(breathe ? 0 : 0.7), lineWidth: breathe ? 1 : 4)
                            .frame(width: breathe ? 26 : 10, height: breathe ? 26 : 10)
                    }
                }
                .frame(width: 10, height: 10)
                .onAppear {
                    withAnimation(.easeOut(duration: 1.4).repeatForever(autoreverses: false)) { breathe = true }
                }
        }
    }
}
