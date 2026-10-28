import DesignSystem
import Models
import SwiftUI

/// Boards K1 (before starting, running) and K2 (finished, failed).
struct CalibrationSheet: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let run = model.calRun
        Group {
            if let run, run.running {
                running(run)
            } else if let run, run.state == "done", run.seen != true {
                finished(run)
            } else if let run, run.state == "failed" {
                failed(run)
            } else {
                intro
            }
        }
        .padding(20)
        .frame(width: 540)
        .background(AU.bg)
    }

    private func titleRow(_ symbol: String, _ color: Color, _ title: String, sub: String? = nil, right: String? = nil, rightColor: Color = AU.text2) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Image(systemName: symbol).font(.system(size: 17)).foregroundStyle(color).alignmentGuide(.firstTextBaseline) { $0[.bottom] - 3 }
            Text(title).font(.system(size: 15, weight: .semibold))
            if let sub { Text(sub).font(.system(size: 12)).foregroundStyle(AU.text2) }
            Spacer()
            if let right { Text(right).font(.system(size: 12, design: .monospaced)).foregroundStyle(rightColor) }
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
            Image(systemName: symbol).font(.system(size: 12)).foregroundStyle(AU.text2).padding(.bottom, 6)
            Text(title).font(.system(size: 12, weight: .semibold))
            Text(text).auSmall().fixedSize(horizontal: false, vertical: true)
        }
        .padding(12)
        .frame(maxWidth: .infinity, minHeight: 100, alignment: .topLeading)
        .background(RoundedRectangle(cornerRadius: 8).fill(AU.surface))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(AU.line))
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
        // Engine order: the repeated-frames scan runs last, so it stays there.
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
                    // A model's 1080p step runs later: its row is done until then.
                    if g.steps.contains(where: { $0 < index }) { return "done" }
                    return "next"
                }()
                HStack(spacing: 10) {
                    Group {
                        switch state {
                        case "done":
                            Image(systemName: "checkmark").font(.system(size: 8, weight: .bold)).foregroundStyle(AU.greenText)
                                .frame(width: 18, height: 18).overlay(Circle().strokeBorder(AU.greenLine))
                        case "running": Spinner(size: 17)
                        case "failed":
                            Image(systemName: "xmark").font(.system(size: 7, weight: .bold)).foregroundStyle(AU.redText)
                                .frame(width: 18, height: 18).overlay(Circle().strokeBorder(AU.redLine))
                        default: Circle().strokeBorder(AU.glassLine).frame(width: 18, height: 18)
                        }
                    }
                    .frame(width: 18)
                    Text(g.title).font(.system(size: 12.5, weight: state == "running" || state == "failed" ? .semibold : .regular))
                        .foregroundStyle(state == "failed" ? AU.redText : state == "next" ? AU.text2 : AU.text)
                    Spacer()
                    if state == "running" {
                        let within = Double(g.steps.filter { $0 < index }.count) / Double(max(1, g.steps.count))
                        AUBar(within + (run.fraction ?? 0) / Double(max(1, g.steps.count))).frame(width: 90)
                    }
                    if state == "failed" { StatusChip(model.t("nat.chip.stopped"), tone: .red) }
                    if state == "done", let d = duration(g) {
                        Text(Fmt.elapsed(d)).font(.system(size: 11, design: .monospaced)).foregroundStyle(AU.text2)
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
                Text(model.t("nat.cal.title_running")).font(.system(size: 15, weight: .semibold))
                let gs = Self.groups(run.steps, saveTitle: "")
                Text(model.t("nat.cal.step_left", ["i": (gs.firstIndex { $0.steps.contains(run.index ?? 0) } ?? 0) + 1, "n": gs.count,
                                                   "t": Fmt.span(max(60, run.left ?? 60))]))
                    .font(.system(size: 12)).foregroundStyle(AU.text2)
                Spacer()
                Text("\(Int(((run.fraction ?? 0) * 100).rounded()))%").font(.system(size: 12, design: .monospaced)).foregroundStyle(AU.primaryText)
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

    // K2, finished
    private func finished(_ run: CalibrationRun) -> some View {
        let rows = run.table.filter { $0.now != nil }
        let factory = Dictionary(uniqueKeysWithValues: (model.calibration?.models ?? []).map { ($0.key, $0.factoryFps1080p) })
        let changes = rows.compactMap { r -> Double? in
            guard let n = r.now, let b = r.before ?? factory[r.key] ?? nil, b > 0 else { return nil }
            return 1 - b / n          // how much shorter the estimates get
        }
        let mean = changes.isEmpty ? 0 : changes.reduce(0, +) / Double(changes.count)
        let firstTime = rows.allSatisfy { $0.before == nil }
        return VStack(alignment: .leading, spacing: 14) {
            titleRow("checkmark.circle.fill", AU.green, model.t("nat.cal.title_done"),
                     right: run.ended.flatMap { e in run.started.map { Fmt.span(max(60, e - $0)) } })
            Text((mean >= 0 ? model.t("nat.cal.faster", ["pct": Int((abs(mean) * 100).rounded())])
                  : model.t("nat.cal.slower", ["pct": Int((abs(mean) * 100).rounded())])) + "\n" + model.t("nat.cal.saved"))
                .auSmall()
            VStack(spacing: 0) {
                HStack {
                    Text(model.t("nat.cal.measured")).frame(maxWidth: .infinity, alignment: .leading)
                    Text(model.t("nat.cal.before_col")).frame(width: 80, alignment: .trailing)
                    Text(model.t("nat.cal.now_col")).frame(width: 80, alignment: .trailing)
                    Text(model.t("nat.cal.change_col")).frame(width: 70, alignment: .trailing)
                }
                .auLabel().padding(.horizontal, 14).padding(.vertical, 8)
                ForEach(rows) { r in
                    let before = r.before ?? factory[r.key] ?? nil
                    Rectangle().fill(AU.line).frame(height: 1)
                    HStack {
                        Text("\(model.shortModel(r.key)) · 2×").font(.system(size: 12)).frame(maxWidth: .infinity, alignment: .leading)
                        Text(before.map { String(format: "%.1f", $0) } ?? "—").foregroundStyle(AU.text2).frame(width: 80, alignment: .trailing)
                        Text(r.now.map { String(format: "%.1f", $0) } ?? "—").fontWeight(.semibold).frame(width: 80, alignment: .trailing)
                        Text(change(before, r.now)).foregroundStyle((r.now ?? 0) >= (before ?? 0) ? AU.greenText : AU.redText)
                            .frame(width: 70, alignment: .trailing)
                    }
                    .font(.system(size: 12, design: .monospaced))
                    .padding(.horizontal, 14).frame(height: 28)
                }
            }
            .background(RoundedRectangle(cornerRadius: 8).fill(AU.surface))
            .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(AU.line))
            HStack {
                if firstTime { Text(model.t("nat.cal.first_compare")).auSmall() }
                Spacer()
                Button(model.t("nat.cal.close")) { model.closeCalibration() }.auButton(.primary, .regular)
                    .keyboardShortcut(.defaultAction)
            }
        }
    }

    private func change(_ b: Double?, _ n: Double?) -> String {
        guard let b, let n, b > 0 else { return "—" }
        return String(format: "%+.0f%%", (n / b - 1) * 100)
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
