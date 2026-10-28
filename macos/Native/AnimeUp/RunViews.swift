import DesignSystem
import Models
import SwiftUI

/// Pieces of the running queue (boards F4–F7).
enum RunStages {
    static let order = ["extract", "dedup", "upscale", "assemble"]
    static let shares: [String: Double] = ["extract": 0.04, "dedup": 0.02, "upscale": 0.90, "assemble": 0.04]
}

/// The 4 pt edge bar of a row: one piece per stage, the upscale split into
/// its chunks, 3 pt apart, each as wide as its share.
struct PiecedEdgeBar: View {
    var fraction: Double
    var chunks: Int
    var color: Color

    var body: some View {
        GeometryReader { g in
            let pieces = Self.pieces(chunks: max(1, chunks))
            let gaps = CGFloat(pieces.count - 1) * 3
            let usable = g.size.width - gaps
            HStack(spacing: 3) {
                ForEach(pieces.indices, id: \.self) { i in
                    let (start, share) = pieces[i]
                    let f = min(1, max(0, (fraction - start) / share))
                    ZStack(alignment: .leading) {
                        Rectangle().fill(AU.trackSoft)
                        Rectangle().fill(color).frame(width: usable * share * f)
                    }
                    .frame(width: usable * share)
                }
            }
        }
        .frame(height: 4)
    }

    /// (start, share) of every piece, in fractions of the whole file.
    static func pieces(chunks: Int) -> [(Double, Double)] {
        var out: [(Double, Double)] = []
        var start = 0.0
        for stage in RunStages.order {
            let share = RunStages.shares[stage] ?? 0
            if stage == "upscale" {
                for _ in 0..<chunks { out.append((start, share / Double(chunks))); start += share / Double(chunks) }
            } else {
                out.append((start, share)); start += share
            }
        }
        return out
    }
}

/// The row's soft fill: a slow wave while running, a slow pulse when paused.
struct RowFill: View {
    enum Mode { case running, paused, done, doneWarn }
    var fraction: Double
    var mode: Mode

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
                        .frame(width: g.size.width * fraction)
                }
            case .running:
                ZStack(alignment: .leading) {
                    Rectangle().fill(AU.soft)
                    TimelineView(.animation) { ctx in
                        let phase = ctx.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 3.4) / 3.4
                        let w = g.size.width * fraction
                        LinearGradient(colors: [AU.primary.opacity(0), AU.primary.opacity(0.09), AU.primary.opacity(0)],
                                       startPoint: .leading, endPoint: .trailing)
                            .frame(width: w * 0.7)
                            .offset(x: -w * 0.7 + w * 1.7 * phase)
                            .opacity(sin(phase * .pi))
                    }
                }
                .frame(width: g.size.width * fraction)
                .clipped()
            }
        }
        .allowsHitTesting(false)
    }
}

extension AppModel {
    func stageName(_ stage: String?) -> String { t("nat.stage.\(stage ?? "upscale")") }

    /// "Upscaling chunk 1 of 3 · 10,900 of 11,350 frames upscaled"
    func actionLine(_ j: QueueProgress.Job) -> String {
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

    /// "~ 8.1 fps · 0:56 left · 22:26 elapsed"
    func measures(_ j: QueueProgress.Job) -> String {
        var parts: [String] = []
        if let f = j.fps { parts.append(String(format: "~ %.1f fps", f)) }
        if let l = j.left { parts.append(t("nat.run.left", ["t": Fmt.elapsed(l)])) }
        if let e = j.elapsed { parts.append(t("nat.run.elapsed", ["t": Fmt.elapsed(e)])) }
        return parts.joined(separator: " · ")
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
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                ForEach(Array(RunStages.order.enumerated()), id: \.offset) { i, stage in
                    if i > 0 { Image(systemName: "arrow.right").font(.system(size: 8)).foregroundStyle(AU.text3) }
                    HStack(spacing: 5) {
                        Circle().fill(i < current ? AU.green : i == current ? (job.state == .paused ? AU.yellow : AU.primary) : AU.text3)
                            .frame(width: 7, height: 7)
                        Text(model.stageName(stage)).font(.system(size: 12, weight: i == current ? .semibold : .regular))
                            .foregroundStyle(i < current ? AU.greenText : i == current ? AU.text : AU.text3)
                        Text(Self.range(stage)).font(.system(size: 10, design: .monospaced)).foregroundStyle(AU.text3)
                    }
                }
                Spacer(minLength: 8)
                Text("\(Text(model.t("nat.run.completed")).foregroundStyle(AU.text2)) \(Text("\(Int(((job.fraction ?? 0) * 100).rounded()))%").font(.system(size: 13, weight: .bold)).foregroundStyle(job.state == .paused ? AU.yellowText : AU.text))")
                    .font(.system(size: 12))
            }
            HStack(spacing: 8) {
                Text(model.actionLine(job)).font(.system(size: 12, weight: .medium)).foregroundStyle(AU.text)
                    .lineLimit(1)
                Rectangle().fill(AU.text3).frame(width: 1, height: 11)
                Text(model.measures(job)).font(AUFont.smallNumbers).foregroundStyle(AU.text2).lineLimit(1)
                Spacer(minLength: 8)
                if let estimate {
                    Text("\(Text(model.t("nat.run.estimated")).foregroundStyle(AU.text2)) \(Text(Fmt.estimate(estimate)).fontWeight(.semibold))")
                        .font(.system(size: 12))
                }
            }
        }
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

/// F6: a finished file's Processing panel.
struct JobCompleted: View {
    @Environment(AppModel.self) private var model
    var file: QueueFile
    var job: QueueProgress.Job

    var body: some View {
        let warnings = job.warnings ?? []
        VStack(alignment: .leading, spacing: 12) {
            NoteView(warnings.isEmpty ? .green : .yellow, title: model.t("nat.run.job_completed"),
                     text: model.t("nat.run.job_completed_text", ["time": Fmt.span(job.seconds ?? 0),
                                                                 "name": URL(fileURLWithPath: job.output ?? "").lastPathComponent])) {
                Button(model.t("nat.menu.show_in_finder")) {
                    if let o = job.output { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: o)]) }
                }
                .buttonStyle(AUTintedButtonStyle(warnings.isEmpty ? .green : .yellow))
            }
            ForEach(warnings, id: \.self) { NoteView(.yellow, text: $0) }
        }
    }
}

/// O5: the sheet when the queue ends (edge.py).
struct FinishedSheet: View {
    @Environment(AppModel.self) private var model

    private struct Row: Identifiable {
        var id: String { name }
        var name: String
        var state: String          // done | warn | failed | stopped | skipped
        var warnings: [String] = []
        var seconds: Double?
        var file: QueueFile?
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
            else { state = "done" }
            out.append(Row(name: n, state: state, warnings: job?.warnings ?? [], seconds: job?.seconds, file: f))
        }
        return out
    }

    var body: some View {
        let l = model.finished ?? [:]
        let rows = rows
        let done = rows.filter { $0.state == "done" || $0.state == "warn" }.count
        let bad = rows.filter { $0.state == "failed" || $0.state == "stopped" }.count
        let seconds = (l["ended"]?.number ?? 0) - (l["started"]?.number ?? 0)
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 10) {
                Image(systemName: bad == 0 ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    .font(.system(size: 18)).foregroundStyle(bad == 0 ? AU.green : AU.yellow)
                Text(model.t("nat.fin.title")).font(.system(size: 15, weight: .semibold))
                Spacer()
                Text(model.t("nat.fin.in_all", ["time": Fmt.span(max(60, seconds))])).font(.system(size: 12)).foregroundStyle(AU.text2)
            }
            Text(model.t("nat.fin.summary", ["done": done, "n": rows.count])
                 + (bad > 0 ? " " + model.localizer.tn("nat.fin.summary_bad", bad) : ""))
                .auSmall().fixedSize(horizontal: false, vertical: true)
            VStack(spacing: 2) {
                ForEach(rows) { r in
                    HStack(spacing: 12) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(r.name).font(.system(size: 12, weight: .medium)).lineLimit(1).truncationMode(.middle)
                            if let w = r.warnings.first { Text(w).font(.system(size: 12)).foregroundStyle(AU.yellowText).lineLimit(1) }
                            if r.state == "failed" { Text(model.t("nat.fin.failed_line")).font(.system(size: 12)).foregroundStyle(AU.redText) }
                        }
                        Spacer()
                        chip(r)
                        Text(r.seconds.map { Self.duration($0) } ?? "—").font(.system(size: 11.5, design: .monospaced))
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
                Button(model.t("nat.menu.show_in_finder")) {
                    let urls = rows.compactMap { $0.file.flatMap { model.job($0.id)?.output } }.map { URL(fileURLWithPath: $0) }
                    if !urls.isEmpty { NSWorkspace.shared.activateFileViewerSelecting(urls) }
                }
                .auButton(.secondary, .regular)
                Button(model.t("nat.cal.close")) { model.markFinishedSeen() }.auButton(.primary, .regular)
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 640)
        .background(AU.bg)
    }

    @ViewBuilder
    private func chip(_ r: Row) -> some View {
        switch r.state {
        case "done": StatusChip(model.t("nat.chip.done"), tone: .green, symbol: "checkmark")
        case "warn": StatusChip(model.localizer.tn("nat.chip.done_warn", r.warnings.count), tone: .yellow, symbol: "exclamationmark.triangle.fill")
        case "failed": StatusChip(model.t("nat.chip.failed"), tone: .red)
        case "stopped": StatusChip(model.t("nat.chip.stopped"), tone: .red)
        default: StatusChip(model.t("nat.fin.skipped"))
        }
    }

    /// 24m 10s / 1h 52m
    static func duration(_ s: Double) -> String {
        let t = Int(s.rounded())
        return t >= 3600 ? "\(t / 3600)h \(String(format: "%02d", (t % 3600) / 60))m" : "\(t / 60)m \(String(format: "%02d", t % 60))s"
    }
}
