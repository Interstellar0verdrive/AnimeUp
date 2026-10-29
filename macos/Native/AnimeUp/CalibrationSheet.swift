import DesignSystem
import Models
import SwiftUI

/// Boards K1 (before starting, running) and K2 (failed). A run that just
/// finished shows the results sheet (K4) with the green check.
struct CalibrationSheet: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        if let run = model.calRun, !run.running, run.state == "done", run.seen != true {
            CalibrationDetailsSheet(finished: true)
                .task(id: run.ended) { await model.loadCalibrationDetails() }
        } else {
            steps
        }
    }

    private var steps: some View {
        let run = model.calRun
        return Group {
            if let run, run.running {
                running(run)
            } else if let run, run.state == "failed" {
                failed(run)
            } else {
                intro
            }
        }
        .padding(20)
        // gaps.py SHEET: 560 pt with its 1 pt line; the sheet's own edge is that line here.
        .frame(width: 558)
        .background(AU.sheet)
    }

    private func titleRow(_ symbol: String, _ color: Color, _ title: String, sub: String? = nil, right: String? = nil, rightColor: Color = AU.text2) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Image(systemName: symbol).auFont(17).foregroundStyle(color).alignmentGuide(.firstTextBaseline) { $0[.bottom] - 3 }
            Text(title).auFont(15, .bold)
            if let sub { Text(sub).auFont(12).foregroundStyle(AU.text2) }
            Spacer()
            if let right { Text(right).auFont(12, mono: true).foregroundStyle(rightColor) }
        }
    }

    // K1, before starting
    private var intro: some View {
        VStack(alignment: .leading, spacing: 14) {
            titleRow("info.circle", AU.primaryText, model.t("nat.cal.title"),
                     right: model.calibration?.date.map { model.t("nat.cal.last_done", ["when": model.relative($0)]) })
            Text(model.t("nat.cal.k1_intro1") + "\n" + model.t("nat.cal.k1_intro2")).auSmall()
            HStack(spacing: 8) {
                tile("gauge.medium", model.t("nat.cal.tile1"), model.t("nat.cal.tile1_text"))
                tile("film", model.t("nat.cal.tile2"), model.t("nat.cal.tile2_text"))
                tile("shippingbox", model.t("nat.cal.tile3"), model.t("nat.cal.tile3_text"))
            }
            NoteView(.yellow, title: model.t("nat.cal.heavy_title"), text: model.t("nat.cal.heavy_text"))
            HStack(spacing: 8) {
                Spacer()
                Button(model.t("nat.cal.not_now")) { model.closeCalibration() }.auButton(.secondary, .regular)
                    .keyboardShortcut(.cancelAction)
                Button(model.t("nat.cal.start")) { model.startCalibration() }.auButton(.primary, .regular)
                    .keyboardShortcut(.defaultAction)
            }
        }
    }

    private func tile(_ symbol: String, _ title: String, _ text: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Image(systemName: symbol).auFont(12).foregroundStyle(AU.text2).padding(.bottom, 6)
            Text(title).auFont(12, .semibold)
            Text(text).auSmall().fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, minHeight: 100, alignment: .topLeading)
        .auBox(RoundedRectangle(cornerRadius: 8), fill: AU.surface, line: AU.line,
               padding: EdgeInsets(vertical: 12, horizontal: 12))
    }

    /// The board's rows: extraction, repeated frames, one per model with its
    /// scales, x265, save. Each groups some of the engine's steps.
    struct StepGroup: Identifiable {
        var id: String
        var title: String
        var steps: [Int]
    }

    static func groups(_ steps: [String], saveTitle: String, titles: [String: String] = [:]) -> [StepGroup] {
        var out: [StepGroup] = []
        func add(_ id: String, _ title: String, _ i: Int) {
            if let k = out.firstIndex(where: { $0.id == id }) { out[k].steps.append(i) }
            else { out.append(StepGroup(id: id, title: title, steps: [i])) }
        }
        var scales: [String: [String]] = [:]
        for (i, raw) in steps.enumerated() {
            let s = raw.lowercased()
            if s.hasPrefix("upscale ") {
                var rest = String(raw.dropFirst(8))
                if rest.hasPrefix("1080p ") { rest = String(rest.dropFirst(6)) }
                var scale = ""
                if let r = rest.range(of: " x", options: .backwards) {
                    scale = String(rest[r.upperBound...]); rest = String(rest[..<r.lowerBound])
                }
                if !scale.isEmpty && !(scales[rest] ?? []).contains(scale) { scales[rest, default: []].append(scale) }
                add("m:" + rest, rest, i)
            } else if s.contains("x265") || s.contains("encod") {
                add("x265", titles["x265"] ?? "x265 encoding", i)
            } else if s.contains("dedup") || s.contains("repeated") {
                add("dedup", titles["dedup"] ?? "Repeated frames scan", i)
            } else {
                add("extract", titles["extract"] ?? "Frame extraction", i)
            }
        }
        for k in out.indices where out[k].id.hasPrefix("m:") {
            let sc = (scales[out[k].title] ?? []).sorted().map { "\($0)×" }
            let list = sc.joined(separator: ", ")
            out[k].title += " · " + list
        }
        // Engine order: each model with its 1080p step, then x265 and the repeated-frames scan.
        out.sort { ($0.steps.first ?? 0) < ($1.steps.first ?? 0) }
        out.append(StepGroup(id: "save", title: saveTitle, steps: []))
        return out
    }

    private func checklist(_ run: CalibrationRun, failedAt: Int? = nil) -> some View {
        let index = run.index ?? 0
        let finished = run.state == "done"
        let groups = Self.groups(run.steps, saveTitle: model.t("nat.cal.save_results"),
                                 titles: ["extract": model.t("nat.cal.row_extract"), "dedup": model.t("nat.cal.row_dedup"), "x265": model.t("nat.cal.row_x265")])
        let starts = run.stepStarted ?? []
        func duration(_ g: StepGroup) -> Double? {
            var total = 0.0, known = false
            for i in g.steps {
                guard i < starts.count, let a = starts[i] else { continue }
                let b = (i + 1 < starts.count ? starts[i + 1] : nil) ?? (finished ? run.ended : nil)
                guard let b else { continue }
                total += max(0, b - a); known = true
            }
            return known ? total : nil
        }
        let visible = failedAt == nil ? groups : groups.filter { g in g.steps.contains { $0 <= (failedAt ?? 0) } }
        return VStack(spacing: 0) {
            ForEach(Array(visible.enumerated()), id: \.element.id) { n, g in
                if n > 0 { Rectangle().fill(AU.line).frame(height: 1) }
                let state: String = {
                    if let f = failedAt, g.steps.contains(f) { return "failed" }
                    if finished { return "done" }
                    if g.steps.contains(index) { return "running" }
                    // The engine runs a model's steps one after another: a row behind the index is done.
                    if g.steps.contains(where: { $0 < index }) { return "done" }
                    return "next"
                }()
                HStack(spacing: 10) {
                    Group {
                        switch state {
                        case "done":
                            Image(systemName: "checkmark").auFont(8, .bold).foregroundStyle(AU.greenText)
                                .frame(width: 18, height: 18).overlay(Circle().strokeBorder(AU.greenLine))
                        case "running": Spinner(size: 17)
                        case "failed":
                            Image(systemName: "xmark").auFont(7, .bold).foregroundStyle(AU.redText)
                                .frame(width: 18, height: 18).overlay(Circle().strokeBorder(AU.redLine))
                        default: Circle().strokeBorder(AU.glassLine).frame(width: 18, height: 18)
                        }
                    }
                    .frame(width: 18)
                    Text(g.title).auFont(12.5, state == "running" || state == "failed" ? .semibold : .regular)
                        .foregroundStyle(state == "failed" ? AU.redText : state == "next" ? AU.text2 : AU.text)
                    Spacer()
                    if state == "running" {
                        let within = Double(g.steps.filter { $0 < index }.count) / Double(max(1, g.steps.count))
                        AUBar(within + (run.fraction ?? 0) / Double(max(1, g.steps.count))).frame(width: 90)
                    }
                    if state == "failed" { StatusChip(model.t("nat.chip.stopped"), tone: .red) }
                    if state == "done", let d = duration(g) {
                        Text(Fmt.elapsed(d)).auFont(11, mono: true).foregroundStyle(AU.text2)
                    }
                }
                .padding(.horizontal, 14).frame(height: 34)
                .background(state == "running" ? AU.soft : state == "failed" ? AU.redSoft : .clear)
            }
        }
        .background(RoundedRectangle(cornerRadius: 8).fill(AU.surface))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(AU.line))
    }

    // K1, running
    private func running(_ run: CalibrationRun) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(model.t("nat.cal.title_running")).auFont(15, .semibold)
                let gs = Self.groups(run.steps, saveTitle: "")
                Text(model.t("nat.cal.step_left", ["i": (gs.firstIndex { $0.steps.contains(run.index ?? 0) } ?? 0) + 1, "n": gs.count,
                                                   "t": Fmt.span(max(60, run.left ?? 60))]))
                    .auFont(12).foregroundStyle(AU.text2)
                Spacer()
                Text("\(Int(((run.fraction ?? 0) * 100).rounded()))%").auFont(12, mono: true).foregroundStyle(AU.primaryText)
                    // Over the rows' right column (their times), not the box's edge.
                    .padding(.trailing, 14)
            }
            checklist(run)
            HStack(spacing: 8) {
                Button { model.stopCalibration() } label: { Label(model.t("nat.run.stop"), systemImage: "stop.fill") }
                    .auButton(.destructive, .regular)
                Spacer()
                Button(model.t("nat.cal.close")) { model.closeCalibration() }.auButton(.primary, .regular)
                    .keyboardShortcut(.defaultAction)
            }
            Text(model.t("nat.cal.close_note")).auSmall().fixedSize(horizontal: false, vertical: true)
        }
    }

    // K2, failed
    private func failed(_ run: CalibrationRun) -> some View {
        let at = min(run.index ?? 0, max(0, run.steps.count - 1))
        return VStack(alignment: .leading, spacing: 14) {
            titleRow("exclamationmark.octagon.fill", AU.redText, model.t("nat.cal.failed"))
            Text(model.t("nat.cal.failed_text", ["step": Self.groups(run.steps, saveTitle: "", titles: ["extract": model.t("nat.cal.row_extract"), "dedup": model.t("nat.cal.row_dedup"), "x265": model.t("nat.cal.row_x265")]).first { $0.steps.contains(at) }?.title ?? "?"]) + "\n" + model.t("nat.cal.nothing_saved"))
                .auSmall()
            checklist(run, failedAt: at)
            HStack(spacing: 8) {
                UnderlineLink(model.t("nat.btn.show_log"), tone: .red) { model.openLog(run.log) }
                Spacer()
                Button(model.t("nat.cal.close")) { model.closeCalibration() }.auButton(.secondary, .regular)
                Button(model.t("nat.btn.retry")) { model.startCalibration() }.auButton(.primary, .regular)
            }
        }
    }
}
