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

/// O5: the sheet when the queue ends.
struct FinishedSheet: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let l = model.finished ?? [:]
        let ok = l["succeeded"]?.array.compactMap(\.string) ?? []
        let failed = l["failed"]?.array.compactMap(\.string) ?? []
        let stopped = l["interrupted"]?.array.compactMap(\.string) ?? []
        let skipped = l["skipped"]?.array.compactMap(\.string) ?? []
        let seconds = l["seconds"]?.number ?? ((l["ended"]?.number ?? 0) - (l["started"]?.number ?? 0))
        let allGood = failed.isEmpty && stopped.isEmpty
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 12) {
                Image(systemName: allGood ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    .font(.system(size: 28)).foregroundStyle(allGood ? AU.greenText : AU.yellow)
                VStack(alignment: .leading, spacing: 2) {
                    Text(model.t(allGood ? "nat.fin.title_ok" : "nat.fin.title_some")).font(.system(size: 17, weight: .bold))
                    Text(model.t("nat.fin.time", ["time": Fmt.span(max(60, seconds))])).auSmall()
                }
            }
            VStack(alignment: .leading, spacing: 6) {
                ForEach(ok, id: \.self) { row($0, "checkmark", AU.greenText, nil) }
                ForEach(stopped, id: \.self) { row($0, "pause.fill", AU.yellowText, model.t("nat.fin.stopped")) }
                ForEach(failed, id: \.self) { row($0, "exclamationmark.octagon.fill", AU.redText, model.t("nat.fin.failed")) }
                ForEach(skipped, id: \.self) { row($0, "minus", AU.text3, model.t("nat.fin.skipped")) }
            }
            .padding(12)
            .background(RoundedRectangle(cornerRadius: AU.Radius.field).fill(AU.inset))
            Text(model.t("nat.fin.next_to")).auSmall()
            HStack {
                Spacer()
                Button(model.t("nat.fin.show_finder")) {
                    let urls = model.files.compactMap { model.job($0.id)?.output }.map { URL(fileURLWithPath: $0) }
                    if !urls.isEmpty { NSWorkspace.shared.activateFileViewerSelecting(urls) }
                }
                .auButton(.secondary, .large)
                Button(model.t("nat.btn.ok")) { model.markFinishedSeen() }.auButton(.primary, .large)
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(24)
        .frame(width: 480)
        .background(AU.bg)
    }

    private func row(_ name: String, _ symbol: String, _ color: Color, _ tag: String?) -> some View {
        HStack(spacing: 8) {
            Image(systemName: symbol).font(.system(size: 10, weight: .semibold)).foregroundStyle(color).frame(width: 14)
            Text(name).font(.system(size: 12, weight: .medium)).lineLimit(1).truncationMode(.middle)
            Spacer()
            if let tag { Text(tag).font(AUFont.smallNumbers).foregroundStyle(color) }
        }
    }
}
