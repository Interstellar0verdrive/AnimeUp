import DesignSystem
import Models
import SwiftUI

/// Board K4: every number of this Mac's calibration. Overview says what it
/// means (an episode's time, each model and scale as before/now dots); All
/// numbers lists them. The menu next to the tabs picks what both compare with:
/// an earlier calibration or the factory numbers.
struct CalibrationDetailsSheet: View {
    @Environment(AppModel.self) private var model
    /// Shown by the calibration sheet as a run ends: the green check, and
    /// closing marks the run as seen.
    var finished = false
    @State private var allNumbers = false
    @State private var baseID: String?

    var body: some View {
        Group {
            if let d = model.calDetails, let now = d.calibrations.first {
                content(d, now: now, base: base(d))
            } else {
                Text("—").padding(40)
            }
        }
        // Text and boxes on the same 20 pt edges; inside a box, its rows 14 pt in.
        .padding(20)
        .frame(width: 698)
        .background(AU.sheet)
    }

    /// The factory numbers by default; an earlier calibration when picked in the menu.
    private func base(_ d: CalibrationDetails) -> CalibrationDetails.Entry {
        if let id = baseID, let e = d.calibrations.dropFirst().first(where: { $0.id == id }) { return e }
        return d.factory
    }

    private func content(_ d: CalibrationDetails, now: CalibrationDetails.Entry, base: CalibrationDetails.Entry) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            header(d, now: now, base: base)
            // Both views in place, the hidden one transparent: the sheet keeps the
            // height of the taller and doesn't resize under the tabs.
            ZStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 14) {
                    summary(now: now, base: base, factory: d.factory)
                    episode(d, now: now, base: base)
                    dots(now: now, base: base)
                    tiles(now: now, base: base, factory: d.factory)
                }
                .opacity(allNumbers ? 0 : 1)
                .allowsHitTesting(!allNumbers)
                table(d, now: now, base: base)
                    .opacity(allNumbers ? 1 : 0)
                    .allowsHitTesting(allNumbers)
            }
            HStack(alignment: .center, spacing: 8) {
                // Both notes in place too: one or two lines, the footer keeps its height.
                ZStack(alignment: .leading) {
                    Text(model.t("nat.cald.note"))
                        .auSmall().fixedSize(horizontal: false, vertical: true)
                        .opacity(allNumbers ? 0 : 1)
                    Text(base.isFactory ? model.t("nat.cald.all_note_factory")
                         : model.t("nat.cald.all_note", ["date": baseName(base)]))
                        .auSmall().fixedSize(horizontal: false, vertical: true)
                        .opacity(allNumbers ? 1 : 0)
                }
                Spacer(minLength: 12)
                Button(model.t("nat.btn.calibrate_again")) {
                    if finished {
                        model.startCalibration()
                    } else {
                        model.showCalibrationDetails = false
                        model.calibrate()
                    }
                }
                .auButton(.secondary, .regular)
                Button(model.t("nat.cal.close")) {
                    if finished { model.closeCalibration() } else { model.showCalibrationDetails = false }
                }
                    .auButton(.primary, .regular)
                    .keyboardShortcut(.defaultAction)
            }
        }
    }

    // MARK: header

    private func header(_ d: CalibrationDetails, now: CalibrationDetails.Entry, base: CalibrationDetails.Entry) -> some View {
        HStack(alignment: .center, spacing: 8) {
            // At the end of a run the green check; opened later, from the date,
            // the calibration's symbol.
            // As tall as the title and the date together.
            Image(systemName: finished ? "checkmark.circle.fill" : "gauge.medium").auFont(28)
                .foregroundStyle(finished ? AU.green : AU.primaryText)
                .frame(width: 34).padding(.trailing, 2)
            VStack(alignment: .leading, spacing: 2) {
                Text(model.t("nat.cald.title")).auFont(15, .semibold)
                Text(now.date.map(model.dateTime) ?? "").auSmall()
            }
            Spacer(minLength: 12)
            AUMiniSegments([
                .init(Text(model.t("nat.cald.overview")), help: model.t("nat.cald.overview"), selected: !allNumbers) { allNumbers = false },
                .init(Text(model.t("nat.cald.all")), help: model.t("nat.cald.all"), selected: allNumbers) { allNumbers = true },
            ])
            PopupMenu({
                var items: [AUMenuItem] = [.item(model.t("nat.cald.factory"), checked: base.isFactory) { baseID = d.factory.id }]
                let earlier = d.calibrations.dropFirst()
                if !earlier.isEmpty { items.append(.separator) }
                for e in earlier {
                    items.append(.item(baseName(e), detail: e.version.map { "AnimeUp \($0)" },
                                       checked: e.id == base.id) { baseID = e.id })
                }
                return items
            }) {
                HStack(spacing: 6) {
                    Text(model.t("nat.cald.vs")).foregroundStyle(AU.text2)
                    Text(base.isFactory ? model.t("nat.cald.factory_short") : baseName(base)).foregroundStyle(AU.text)
                    Image(systemName: "chevron.up.chevron.down").auFont(8).foregroundStyle(AU.text2)
                }
                .auFont(12)
                .padding(.leading, 10).padding(.trailing, 8)
                .frame(height: 26)
                .background(RoundedRectangle(cornerRadius: 7).fill(AU.glass))
                .overlay(RoundedRectangle(cornerRadius: 7).strokeBorder(AU.glassLine))
                .fixedSize()
            }
            .help(model.t("nat.cald.vs_help"))
        }
    }

    private func baseName(_ e: CalibrationDetails.Entry) -> String {
        e.isFactory ? model.t("nat.cald.factory") : e.date.map(model.dateOnly) ?? "?"
    }

    private func name(_ key: String) -> String { model.t("mot.modello.\(key).label") }

    // MARK: overview

    /// The mean of now / base over every model at 2x.
    private func ratio(_ now: CalibrationDetails.Entry, _ base: CalibrationDetails.Entry) -> Double? {
        let r = now.models.compactMap { m -> Double? in
            guard let a = base.model(m.key)?.fps["2"] ?? nil, let b = m.fps["2"] ?? nil, a > 0 else { return nil }
            return b / a
        }
        return r.isEmpty ? nil : r.reduce(0, +) / Double(r.count)
    }

    private func summary(now: CalibrationDetails.Entry, base: CalibrationDetails.Entry, factory: CalibrationDetails.Entry) -> some View {
        var parts: [String] = []
        if let r = ratio(now, base) {
            let than = base.isFactory ? model.t("nat.cald.than_factory") : model.t("nat.cald.than_date", ["date": baseName(base)])
            if r >= 1 {
                parts.append(model.t("nat.cald.faster", ["pct": Int(((r - 1) * 100).rounded()), "than": than,
                                                         "est": Int(((1 - 1 / r) * 100).rounded())]))
            } else {
                parts.append(model.t("nat.cald.slower", ["pct": Int(((1 - r) * 100).rounded()), "than": than,
                                                         "est": Int(((1 / r - 1) * 100).rounded())]))
            }
        }
        if !base.isFactory, let f = ratio(now, factory) {
            parts.append(model.t("nat.cald.vs_factory", ["x": String(format: "%.1f", f)]))
        }
        return Text(parts.joined(separator: " ")).auSmall().fixedSize(horizontal: false, vertical: true)
            .padding(.top, 4)
    }

    private func legend(_ base: CalibrationDetails.Entry, bars: Bool) -> some View {
        HStack(spacing: 12) {
            HStack(spacing: 5) {
                if bars { RoundedRectangle(cornerRadius: 3).fill(AU.text3.opacity(0.55)).frame(width: 14, height: 8) }
                else { Circle().strokeBorder(AU.text3, lineWidth: 1.5).frame(width: 8, height: 8) }
                Text(base.isFactory ? model.t("nat.cald.factory_short") : baseName(base))
            }
            HStack(spacing: 5) {
                if bars { RoundedRectangle(cornerRadius: 3).fill(AU.primary).frame(width: 14, height: 8) }
                else { Circle().fill(AU.primary).frame(width: 8, height: 8) }
                Text(model.t("nat.cald.now"))
            }
        }
        .auSmall()
    }

    private func box<C: View>(@ViewBuilder _ c: () -> C) -> some View {
        VStack(spacing: 0, content: c)
            // The box's 1 pt line sits on the first and last rows: 1 pt more inside.
            .padding(.vertical, 1)
            .background(RoundedRectangle(cornerRadius: 10).fill(AU.surface))
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(AU.line))
    }

    private func change(_ a: Double?, _ b: Double?, lowerIsBetter: Bool = false) -> (String, Color) {
        guard let a, let b, a > 0 else { return ("", AU.text3) }
        let d = Int(((b / a - 1) * 100).rounded())
        let better = lowerIsBetter ? d < 0 : d > 0
        return ((d >= 0 ? "+" : "−") + "\(abs(d))%", better ? AU.greenText : d == 0 ? AU.text2 : AU.redText)
    }

    /// The reference episode, before and now: two bars from zero on an hour axis.
    private func episode(_ d: CalibrationDetails, now: CalibrationDetails.Entry, base: CalibrationDetails.Entry) -> some View {
        let rows = now.models.compactMap { m -> (String, Double, Double?)? in
            guard let b = m.episodeSeconds else { return nil }
            return (m.key, b, base.model(m.key)?.episodeSeconds)
        }
        let hours = max(1, Int((rows.map { max($0.1, $0.2 ?? 0) }.max() ?? 3600) / 3600) + 1)
        let changeWidth = Self.monoWidth(rows.map { change($0.2, $0.1, lowerIsBetter: true).0 }, size: 11.5)
        let span = Double(hours) * 3600
        return VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(model.t("nat.cald.episode", ["min": d.episodeMinutes, "h": d.episodeHeight])).auLabel()
                Spacer(minLength: 8)
                legend(base, bars: true)
            }
            .padding(.horizontal, 14)
            box {
                ForEach(Array(rows.enumerated()), id: \.offset) { i, r in
                    if i > 0 { Rectangle().fill(AU.line).frame(height: 1) }
                    HStack(spacing: 12) {
                        Text(name(r.0)).auFont(12.5).lineLimit(1).frame(width: Self.nameWidth, alignment: .leading)
                        GeometryReader { g in
                            VStack(alignment: .leading, spacing: 3) {
                                RoundedRectangle(cornerRadius: 3).fill(AU.text3.opacity(0.55))
                                    .frame(width: g.size.width * min(1, (r.2 ?? 0) / span), height: 8)
                                    .opacity(r.2 == nil ? 0 : 1)
                                RoundedRectangle(cornerRadius: 3).fill(AU.primary)
                                    .frame(width: g.size.width * min(1, r.1 / span), height: 8)
                            }
                            .frame(maxHeight: .infinity)
                        }
                        .frame(height: 19)
                        HStack(spacing: Self.changeGap) {
                            HStack(spacing: 5) {
                                if let a = r.2 { Text(Fmt.span(a)).foregroundStyle(AU.text3); Text("→").foregroundStyle(AU.text3) }
                                Text(Fmt.span(r.1)).foregroundStyle(AU.text)
                            }
                            let c = change(r.2, r.1, lowerIsBetter: true)
                            Text(c.0).foregroundStyle(c.1).frame(width: changeWidth, alignment: .trailing)
                        }
                        .auFont(11.5, mono: true).lineLimit(1)
                        .frame(width: Self.episodeValues, alignment: .trailing)
                    }
                    .padding(.horizontal, 14).frame(height: 38)
                }
                axis((0...hours).map { (Double($0) / Double(hours), "\($0)h") }, values: Self.episodeValues)
            }
        }
    }

    /// The two charts' columns: the name, the plot, the numbers on the right
    /// (an episode's two times and change need more room than a speed and its change).
    private static let nameWidth: CGFloat = 200
    private static let episodeValues: CGFloat = 150
    /// Between a number and its change, in both charts.
    private static let changeGap: CGFloat = 7

    /// The widest of these strings in the monospaced figures, so a column is
    /// exactly as wide as its longest value and the plot takes the rest.
    private static func monoWidth(_ texts: [String], size: CGFloat) -> CGFloat {
        let font = NSFont.monospacedSystemFont(ofSize: size, weight: .regular)
        return ceil(texts.map { ($0 as NSString).size(withAttributes: [.font: font]).width }.max() ?? 0)
    }

    private func axis(_ ticks: [(Double, String)], values: CGFloat) -> some View {
        HStack(spacing: 12) {
            Color.clear.frame(width: Self.nameWidth, height: 1)
            GeometryReader { g in
                ForEach(Array(ticks.enumerated()), id: \.offset) { _, t in
                    Text(t.1).auFont(10, mono: true).foregroundStyle(AU.text3)
                        .fixedSize()
                        .position(x: g.size.width * t.0, y: 6)
                }
            }
            .frame(height: 12)
            Color.clear.frame(width: values, height: 1)
        }
        .padding(.horizontal, 14).padding(.top, 2).padding(.bottom, 8)
    }

    /// Each model and scale: hollow for the comparison, filled for now.
    private func dots(now: CalibrationDetails.Entry, base: CalibrationDetails.Entry) -> some View {
        let rows: [(String, Double?, Double)] = now.models.flatMap { m in
            ["2", "3", "4"].compactMap { k -> (String, Double?, Double)? in
                guard let b = m.fps[k] ?? nil else { return nil }
                return ("\(name(m.key)) · \(k)×", base.model(m.key)?.fps[k] ?? nil, b)
            }
        }
        let top = max(2, ((rows.map { max($0.2, $0.1 ?? 0) }.max() ?? 2) / 2).rounded(.up) * 2)
        let ticks = stride(from: 0.0, through: top, by: top > 10 ? 4 : 2).map { ($0 / top, String(format: "%.0f", $0)) }
        let speedWidth = Self.monoWidth(rows.map { String(format: "%.1f", $0.2) }, size: 11)
        let changeWidth = Self.monoWidth(rows.map { change($0.1, $0.2).0 }, size: 11)
        let values = speedWidth + Self.changeGap + changeWidth
        // The plot as far from the numbers on its right as from the longest name
        // on its left: the name column is wider than the names.
        let font = NSFont.systemFont(ofSize: 11.5)
        let longest = ceil(rows.map { ($0.0 as NSString).size(withAttributes: [.font: font]).width }.max() ?? Self.nameWidth)
        let rightGap = max(0, Self.nameWidth - longest)
        return VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(model.t("nat.cald.dots")).auLabel()
                Spacer(minLength: 8)
                legend(base, bars: false)
            }
            .padding(.horizontal, 14)
            box {
                VStack(spacing: 0) {
                    ForEach(Array(rows.enumerated()), id: \.offset) { _, r in
                        HStack(spacing: 12) {
                            Text(r.0).auFont(11.5).foregroundStyle(AU.text2).lineLimit(1)
                                .frame(width: Self.nameWidth, alignment: .leading)
                            GeometryReader { g in
                                let w = g.size.width
                                ZStack(alignment: .leading) {
                                    Rectangle().fill(AU.line).frame(height: 1)
                                    if let a = r.1 {
                                        Rectangle().fill(AU.softLine)
                                            .frame(width: abs(r.2 - a) / top * w, height: 2)
                                            .offset(x: min(a, r.2) / top * w)
                                        Circle().fill(AU.surface).overlay(Circle().strokeBorder(AU.text3, lineWidth: 1.5))
                                            .frame(width: 8, height: 8).offset(x: a / top * w - 4)
                                    }
                                    Circle().fill(AU.primary).frame(width: 8, height: 8).offset(x: r.2 / top * w - 4)
                                }
                                .frame(maxHeight: .infinity)
                            }
                            .frame(height: 10)
                            .padding(.trailing, rightGap)
                            // The speed right after the plot; its change on the right edge,
                            // like the episode's above.
                            HStack(spacing: Self.changeGap) {
                                Text(String(format: "%.1f", r.2)).foregroundStyle(AU.text)
                                    .frame(width: speedWidth, alignment: .trailing)
                                let c = change(r.1, r.2)
                                Text(c.0).foregroundStyle(c.1)
                                    .frame(width: changeWidth, alignment: .trailing)
                            }
                            .auFont(11, mono: true).lineLimit(1)
                            .frame(width: values)
                        }
                        .frame(height: 25)
                    }
                }
                .padding(.horizontal, 14).padding(.top, 8)
                axis(ticks, values: values + rightGap)
            }
        }
    }

    /// Frames and encoding at a glance: the steps around the upscale, and the save threads.
    private func tiles(now: CalibrationDetails.Entry, base: CalibrationDetails.Entry, factory: CalibrationDetails.Entry) -> some View {
        func ref(_ k: KeyPath<CalibrationDetails.Entry, Double?>) -> Double? { base[keyPath: k] ?? factory[keyPath: k] }
        let fps = { (v: Double?) in v.map { "\(num($0)) fps" } ?? "—" }
        let items: [(String, String, (String, Color))] = [
            (model.t("nat.cal.row_extract"), fps(now.extractionFps), change(ref(\.extractionFps), now.extractionFps)),
            (model.t("nat.cald.tile_dedup"), fps(now.dedupFps), change(ref(\.dedupFps), now.dedupFps)),
            (model.t("nat.cald.x265"), fps(now.encodingFps), change(ref(\.encodingFps), now.encodingFps)),
            (model.t("nat.cald.threads"), now.saveThreads.map(String.init) ?? "—",
             (now.saveThreads.flatMap { n in (base.saveThreads ?? factory.saveThreads).map { n - $0 } }
                .map { ($0 >= 0 ? "+" : "−") + "\(abs($0))" } ?? "", AU.text2)),
        ]
        return VStack(alignment: .leading, spacing: 6) {
            Text(model.t("nat.cald.frames")).auLabel().padding(.horizontal, 14)
            HStack(spacing: 8) {
                ForEach(Array(items.enumerated()), id: \.offset) { _, it in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(it.0).auFont(11).foregroundStyle(AU.text2).lineLimit(1).minimumScaleFactor(0.85)
                        HStack(alignment: .firstTextBaseline, spacing: 6) {
                            Text(it.1).auFont(14, .semibold, mono: true).foregroundStyle(AU.text)
                            Text(it.2.0).auFont(11, mono: true).foregroundStyle(it.2.1)
                        }
                    }
                    .padding(.horizontal, 14).padding(.vertical, 9)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 10).fill(AU.surface))
                    .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(AU.line))
                }
            }
        }
    }

    // MARK: all numbers

    private func num(_ v: Double?) -> String {
        guard let v else { return "—" }
        return v < 20 ? String(format: "%.1f", v) : String(format: "%.0f", v)
    }

    private struct Row {
        var label: String
        var factory: String
        var base: String
        var now: String
        var change: (String, Color)
        var note: String? = nil
    }

    private func table(_ d: CalibrationDetails, now: CalibrationDetails.Entry, base: CalibrationDetails.Entry) -> some View {
        let f = d.factory
        let showBase = !base.isFactory
        func row(_ label: String, _ fv: Double?, _ bv: Double?, _ nv: Double?) -> Row {
            Row(label: label, factory: num(fv), base: num(bv), now: num(nv), change: change(showBase ? (bv ?? fv) : fv, nv))
        }
        var up: [Row] = []
        for m in now.models {
            for k in ["2", "3", "4"] {
                let label = "\(name(m.key)) · \(k)×"
                if m.borrowed.contains(Int(k) ?? 0) {
                    up.append(Row(label: label, factory: "", base: "", now: "", change: ("", AU.text3), note: model.t("nat.cald.borrowed")))
                } else if let nv = m.fps[k] ?? nil {
                    up.append(row(label, f.model(m.key)?.fps[k] ?? nil, base.model(m.key)?.fps[k] ?? nil, nv))
                }
            }
        }
        let big = now.models.map { m in row("\(name(m.key)) · 2×", f.model(m.key)?.bigFps, base.model(m.key)?.bigFps, m.bigFps) }
        var other = [row(model.t("nat.cal.row_extract"), f.extractionFps, base.extractionFps, now.extractionFps),
                     row(model.t("nat.cal.row_dedup"), f.dedupFps, base.dedupFps, now.dedupFps),
                     row(model.t("nat.cald.x265"), f.encodingFps, base.encodingFps, now.encodingFps)]
        let threads = { (v: Int?) in v.map(String.init) ?? "—" }
        let tb = showBase ? base.saveThreads ?? f.saveThreads : f.saveThreads
        other.append(Row(label: model.t("nat.cald.threads"), factory: threads(f.saveThreads), base: threads(base.saveThreads),
                         now: threads(now.saveThreads),
                         change: (now.saveThreads.flatMap { n in tb.map { n - $0 } }.map { ($0 >= 0 ? "+" : "−") + "\(abs($0))" } ?? "", AU.text2)))
        return VStack(alignment: .leading, spacing: 16) {
            group(columns(showBase: showBase, base: base, label: model.t("nat.cald.up")), up, showBase: showBase)
            group(Text(model.t("nat.cald.big")).auLabel(), big, showBase: showBase)
            group(Text(model.t("nat.cald.frames")).auLabel(), other, showBase: showBase)
        }
    }

    private func columns(showBase: Bool, base: CalibrationDetails.Entry, label: String) -> some View {
        HStack(spacing: 10) {
            Text(label).frame(maxWidth: .infinity, alignment: .leading)
            Text(model.t("nat.cald.factory_short")).frame(width: 70, alignment: .trailing)
            if showBase { Text(baseName(base)).lineLimit(1).frame(width: 90, alignment: .trailing) }
            Text(model.t("nat.cald.now_col")).frame(width: 60, alignment: .trailing)
            Text(model.t("nat.cald.change")).frame(width: 70, alignment: .trailing)
        }
        .auLabel()
    }

    private func group(_ title: some View, _ rows: [Row], showBase: Bool) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            title.padding(.horizontal, 14)
            box {
                ForEach(Array(rows.enumerated()), id: \.offset) { i, r in
                    if i > 0 { Rectangle().fill(AU.line).frame(height: 1) }
                    HStack(spacing: 10) {
                        Text(r.label).auFont(12.5).lineLimit(1).frame(maxWidth: .infinity, alignment: .leading)
                        if let note = r.note {
                            Text(note).auFont(11).italic().foregroundStyle(AU.text3).lineLimit(1)
                        } else {
                            Group {
                                Text(r.factory).foregroundStyle(AU.text3).frame(width: 70, alignment: .trailing)
                                if showBase { Text(r.base).foregroundStyle(AU.text3).frame(width: 90, alignment: .trailing) }
                                Text(r.now).foregroundStyle(AU.text).frame(width: 60, alignment: .trailing)
                                Text(r.change.0).foregroundStyle(r.change.1).frame(width: 70, alignment: .trailing)
                            }
                            .auFont(11.5, mono: true)
                        }
                    }
                    .padding(.horizontal, 14).frame(height: 27)
                }
            }
        }
    }
}
