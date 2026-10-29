import DesignSystem
import Models
import SwiftUI

/// Boards S1 (first launch, not calibrated) and S2 (ready): the title and
/// four cards, with the engine's real data.
struct StartView: View {

    var body: some View {
        GeometryReader { geo in
            // No scroll view while everything fits (the usual window size);
            // a scroll view only below that.
            ViewThatFits(in: .vertical) {
                StartContent(fill: true)
                ScrollView { StartContent(fill: false) }
            }
        }
        .ignoresSafeArea(edges: .top)
    }

}

/// The title, the intro and the four cards.
struct StartContent: View {
    /// Below this content width the four cards go in one column.
    static let oneColumnBelow: CGFloat = 920
    @Environment(AppModel.self) private var model
    @Environment(\.auPageTop) private var pageTop
    /// Stretch the cards to the window's height (when everything fits without scrolling).
    var fill: Bool

    @State private var oneColumn = false

    private var calibrated: Bool { model.calibration?.isCalibrated ?? false }

    var body: some View { content }

    private var content: some View {
        VStack(alignment: .leading, spacing: 18) {
            PageHeader(model.t(calibrated || model.status != .ready ? "nat.start.title" : "nat.start.welcome"),
                       model.t("nat.start.intro1"), model.t("nat.start.intro2"))
            if model.status == .ready {
                GridLayout(gap: 14, leftShare: 1.15 / 2.15, fill: fill, oneColumnBelow: Self.oneColumnBelow) {
                    if model.files.isEmpty { AddVideosCard() } else { YourVideosCard() }
                    WhereFilesGoCard(oneColumn: oneColumn)
                    ThisMacCard()
                    HowABatchGoesCard()
                }
            } else {
                EngineStatusView().frame(maxHeight: fill ? .infinity : nil)
            }
        }
        .padding(.top, pageTop)
        .padding(.horizontal, 28)
        .onGeometryChange(for: Bool.self) { $0.size.width - 56 < Self.oneColumnBelow } action: { oneColumn = $0 }
        .padding(.bottom, 28)
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }

}

/// Two columns (1.15 : 1) and two rows of equal height, 14 pt apart; in a
/// narrow window the cards go one under the other, at their own height.
struct GridLayout: Layout {
    var gap: CGFloat
    var leftShare: CGFloat
    /// Take the height offered (what the window leaves under the title), with two
    /// equal rows if they fit. Measured, never estimated: an estimate a few points
    /// off made the page scroll by those few points.
    var fill: Bool
    /// Below this width the two columns would squeeze the cards' content.
    var oneColumnBelow: CGFloat = 0

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? 900
        if width < oneColumnBelow {
            let heights = subviews.map { $0.sizeThatFits(ProposedViewSize(width: width, height: nil)).height }
            return CGSize(width: width, height: heights.reduce(0, +) + gap * CGFloat(max(0, subviews.count - 1)))
        }
        let (left, right) = widths(width)
        let rows = rowHeights(subviews, left: left, right: right)
        let natural = rows.0 + rows.1 + gap
        let offered = proposal.height.flatMap { $0.isFinite ? $0 : nil } ?? 0
        let height = fill ? max(natural, offered) : natural
        return CGSize(width: width, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        if bounds.width < oneColumnBelow {
            var y = bounds.minY
            for view in subviews {
                let h = view.sizeThatFits(ProposedViewSize(width: bounds.width, height: nil)).height
                view.place(at: CGPoint(x: bounds.minX, y: y), proposal: ProposedViewSize(width: bounds.width, height: h))
                y += h + gap
            }
            return
        }
        let (left, right) = widths(bounds.width)
        let rows = rowHeights(subviews, left: left, right: right)
        var top = rows.0, bottom = rows.1
        do {
            // Equal rows when there's room; never shorter than the content.
            let each = (bounds.height - gap) / 2
            if each >= max(top, bottom) {
                top = each; bottom = each
            } else {
                let spare = max(0, bounds.height - gap - top - bottom)
                top += spare / 2; bottom += spare / 2
            }
        }
        let frames = [
            CGRect(x: bounds.minX, y: bounds.minY, width: left, height: top),
            CGRect(x: bounds.minX + left + gap, y: bounds.minY, width: right, height: top),
            CGRect(x: bounds.minX, y: bounds.minY + top + gap, width: left, height: bottom),
            CGRect(x: bounds.minX + left + gap, y: bounds.minY + top + gap, width: right, height: bottom),
        ]
        for (view, frame) in zip(subviews, frames) {
            view.place(at: frame.origin, proposal: ProposedViewSize(frame.size))
        }
    }

    private func widths(_ total: CGFloat) -> (CGFloat, CGFloat) {
        let left = ((total - gap) * leftShare).rounded()
        return (left, total - gap - left)
    }

    private func rowHeights(_ subviews: Subviews, left: CGFloat, right: CGFloat) -> (CGFloat, CGFloat) {
        func h(_ i: Int, _ w: CGFloat) -> CGFloat {
            i < subviews.count ? subviews[i].sizeThatFits(ProposedViewSize(width: w, height: nil)).height : 0
        }
        return (max(h(0, left), h(1, right)), max(h(2, left), h(3, right)))
    }
}

// MARK: - Add videos

struct AddVideosCard: View {
    @Environment(AppModel.self) private var model
    static let formats = [".mkv", ".mp4", ".mov", ".avi", ".m4v", ".ts", ".webm"]

    var body: some View {
        Card {
            CardTitle(model.t("nat.add.title"), symbol: "film")
            DropZone(title: model.t("nat.add.drop"), buttonTitle: model.t("nat.add.open"),
                     primary: model.calibration?.isCalibrated ?? false,
                     onOpen: { model.openVideos() }, onDrop: { model.receive($0) })
                .frame(minHeight: 150)
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 6) {
                    Text(model.t("nat.add.formats")).auLabel().padding(.trailing, 4)
                    ForEach(Self.formats, id: \.self) { StatusChip($0) }
                }
                if let n = model.lastReceived {
                    HintLine(text: model.localizer.tn("nat.add.received", n), symbol: "checkmark", color: AU.greenText)
                } else {
                    HintLine(text: model.t("nat.add.not_handled"), symbol: "info.circle")
                }
            }
        }
    }
}

/// The popup menu look of the boards: control fill, glass line, chevron.
struct PopupLabel: View {
    var title: String
    var width: CGFloat
    var height: CGFloat
    var size: CGFloat
    init(_ title: String, width: CGFloat = 280, height: CGFloat = 28, size: CGFloat = 13) {
        self.title = title; self.width = width; self.height = height; self.size = size
    }

    var body: some View {
        HStack {
            Text(title).auFont(size, size < 13 ? .medium : .regular).foregroundStyle(AU.text).lineLimit(1)
            Spacer()
            Image(systemName: "chevron.down").auFont(9, .semibold).foregroundStyle(AU.text2)
        }
        .padding(.leading, 12)
        .padding(.trailing, 10)
        // The width asked for, or down to 160 pt when its column is narrower.
        .frame(minWidth: min(width, 160), idealWidth: width, maxWidth: width, minHeight: height, maxHeight: height)
        .background(RoundedRectangle(cornerRadius: AU.Radius.field).fill(AU.control))
        .overlay(RoundedRectangle(cornerRadius: AU.Radius.field).strokeBorder(AU.glassLine, lineWidth: 1))
        .contentShape(Rectangle())
    }
}

/// A small icon before a sentence that wraps, its lines balanced (a hint under
/// a card's content): unlike `SmallIconLabel`, it never widens its card.
struct HintLine: View {
    var text: String
    var symbol: String
    var color: Color = AU.text3

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Image(systemName: symbol).auFont(11)
            BalancedParagraph(text, style: AUFont.small)
        }
        .foregroundStyle(color)
    }
}

struct SmallIconLabel: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 6) {
            configuration.icon.auFont(11)
            configuration.title
        }
        // A status label ("2 warnings") stays on one line; the text after it gives way.
        .lineLimit(1)
        .fixedSize()
    }
}

// MARK: - Your videos (S2b)

struct YourVideosCard: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let files = model.files
        let length = files.compactMap { $0.report?.duration }.reduce(0, +)
        Card {
            CardTitle(model.t("nat.start.your_videos"), symbol: "film") {
                Text(summary(files.count, length)).auSmall()
            }
            MaybeScroll {
                VStack(spacing: 0) {
                    // Lines between the rows and one under the last: with few files the
                    // list ends with a line instead of running into the empty box.
                    ForEach(Array(files.enumerated()), id: \.element.id) { i, f in
                        if i > 0 { Rectangle().fill(AU.line).frame(height: 1) }
                        Button { model.tab = .queue; model.expanded = f.id; model.panelTabs[f.id] = .analysis } label: {
                            HStack(spacing: 8) {
                                icon(f).frame(width: 16)
                                Text(f.name).auFont(12, .medium).foregroundStyle(AU.text)
                                    .lineLimit(1).truncationMode(.middle)
                                Spacer(minLength: 4)
                                if !f.warnings.isEmpty {
                                    StatusChip(model.localizer.tn("nat.queue.n_warnings", f.warnings.count), tone: .yellow,
                                               symbol: "exclamationmark.triangle.fill")
                                }
                                Text(f.report.map { Fmt.clock($0.duration) } ?? "—").auFont(AUFont.smallNumbers)
                                    .foregroundStyle(AU.textCode).frame(width: 50, alignment: .trailing)
                            }
                            .padding(.horizontal, 8).padding(.vertical, 5)
                            .contentShape(Rectangle())
                            .auHover(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                    Rectangle().fill(AU.line).frame(height: 1)
                }
                .padding(.vertical, 2)
            }
            .frame(height: 150, alignment: .top)
            .clipped()
            .mask(LinearGradient(stops: [.init(color: .black, location: 0.72), .init(color: .clear, location: 1)],
                                 startPoint: .top, endPoint: .bottom))
            .background(RoundedRectangle(cornerRadius: AU.Radius.field).fill(AU.inset))
            .overlay(RoundedRectangle(cornerRadius: AU.Radius.field).strokeBorder(AU.line))
            Text(model.t("nat.start.click_report")).auSmall(AU.text3).padding(.top, -6)
            // The drop area of the other pages (E0b, F0), side by side: the same look
            // wherever more videos can be dropped.
            DropZone(title: model.t("nat.empty.drop_more"), buttonTitle: model.t("nat.add.open"), primary: false,
                     axis: .horizontal,
                     onOpen: { model.openVideos() }, onDrop: { model.receive($0) })
                .frame(maxHeight: .infinity)
            HStack(spacing: 8) {
                Text(model.analysingCount > 0 ? model.t("nat.start.analysing_left", ["n": model.analysingCount])
                     : model.warningCount > 0 ? model.t("nat.start.all_analysed_warn") : model.t("nat.start.all_analysed"))
                    .auSmall()
                Spacer()
                Button { model.tab = .compare } label: {
                    HStack(spacing: 5) { Text(model.t("nat.start.next_compare")); Image(systemName: "arrow.right") }
                }
                .auButton(.primary, .regular)
                .disabled(!model.files.contains { $0.state == .ready })
            }
        }
    }

    private func summary(_ n: Int, _ length: Double) -> String {
        var parts = [model.localizer.tn("nat.queue.files", n), Fmt.span(length)]
        if model.warningCount > 0 { parts.append(model.localizer.tn("nat.queue.warnings", model.warningCount)) }
        return parts.joined(separator: " · ")
    }

    @ViewBuilder
    private func icon(_ f: QueueFile) -> some View {
        // Grey: analysed, ready for the Queue; green only once its video is made (29 Oct).
        let job = model.job(f.id)?.state
        switch f.state {
        case .ready where job == .done: Image(systemName: "checkmark").auFont(10, .semibold).foregroundStyle(AU.greenText)
        case .ready where job == .running || job == .paused: Spinner(size: 10)
        case .ready: Image(systemName: "checkmark").auFont(10, .semibold).foregroundStyle(AU.text3)
        case .analysing: Spinner(size: 10)
        case .queued: Circle().strokeBorder(AU.glassLine).frame(width: 10, height: 10)
        case .failed, .missing: Image(systemName: "exclamationmark.octagon.fill").auFont(10).foregroundStyle(AU.redText)
        }
    }
}

// MARK: - Where files go

struct WhereFilesGoCard: View {
    @Environment(AppModel.self) private var model
    /// The cards in one column: the card is short and wide, so the folders go side
    /// by side. Beside another card (two columns) it stays a column, however wide.
    var oneColumn = false
    @State private var space: Double = 0
    @State private var editing = false
    @State private var wide = false

    var body: some View {
        Card(spacing: 22) {
            CardTitle(model.t("nat.where.title"), symbol: "folder").padding(.bottom, -6)
            // A wide card in one column puts the two folders side by side instead of
            // leaving the half beside the menu empty.
            if wide && oneColumn {
                // The space belongs to the work folder: in its column, right under it.
                HStack(alignment: .top, spacing: 24) {
                    finished.frame(maxWidth: .infinity, alignment: .leading)
                    VStack(alignment: .leading, spacing: 22) {
                        work
                        spaceRow
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            } else {
                finished
                work
                spaceRow
            }
            // At the bottom when the row is taller than the card; right under the rest when
            // the cards are in one column (a spacer would add a second 22 pt gap there).
            HintLine(text: model.t("nat.where.settings"), symbol: "gearshape")
                .frame(maxHeight: .infinity, alignment: .bottomLeading)
        }
        .onGeometryChange(for: Bool.self) { $0.size.width >= 600 } action: { wide = $0 }
    }

    private var finished: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(model.t("nat.where.finished")).auLabel()
            // The boards' 280 pt, about half the work folder's path field below.
            FinishedFolderMenu(width: 280)
            Text(model.t("nat.where.or_pick")).auSmall()
        }
    }

    private var work: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(model.t("nat.where.work")).auLabel()
            HStack(spacing: 8) {
                PathField(model.folders.map { displayPath($0.workFolder) } ?? "—")
                Button(model.t("nat.btn.change")) { model.chooseWorkFolder() }.auButton(.secondary, .regular)
            }
            if let f = model.folders, !f.reachable {
                Text(model.t("nat.where.unreachable")).auSmall(AU.yellowText)
            }
        }
    }

    @ViewBuilder
    private var spaceRow: some View {
        if let f = model.folders, f.tooFull {
            VStack(alignment: .leading, spacing: 6) {
                Text(model.t("nat.where.space")).auLabel()
                HintLine(text: model.t("nat.where.too_full", ["free": SizeFormat.gb(f.freeGb), "volume": f.volume, "min": f.spaceMinGb]),
                         symbol: "exclamationmark.triangle.fill", color: AU.yellowText)
            }
        } else if let f = model.folders, f.tight {
            // Nothing to choose between 50 and 51 GB: say how full the disk is.
            VStack(alignment: .leading, spacing: 6) {
                Text(model.t("nat.where.space")).auLabel()
                HintLine(text: tightText(f), symbol: "exclamationmark.triangle.fill", color: AU.yellowText)
            }
        } else if let f = model.folders {
            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .firstTextBaseline) {
                    Text(model.t("nat.where.space")).auLabel()
                    Spacer()
                    Text("\(Text("\(Int(space)) GB").foregroundStyle(AU.text)) \(model.t("nat.where.of_free", ["free": SizeFormat.gb(f.freeGb)]))")
                        .foregroundStyle(AU.text3)
                        .auFont(AUFont.smallNumbers)
                }
                AUSlider(value: Binding(get: { space }, set: { space = $0.rounded() }),
                         in: Double(f.spaceMinGb)...Double(max(f.spaceMinGb + 1, f.spaceRuleGb))) {
                    editing = $0; if !$0 { model.setSpace(Int(space)) }
                }
                BalancedParagraph(model.t("nat.where.space_note"), style: AUFont.small).foregroundStyle(AU.text2)
            }
            .onAppear { space = Double(model.settings?.diskGb ?? f.spaceSettingGb) }
            .onChange(of: model.settings?.diskGb) { _, new in if !editing, let new { space = Double(new) } }
        }
    }

    private func tightText(_ f: FoldersState) -> String {
        model.t("nat.where.tight", ["free": SizeFormat.gb(f.freeGb), "use": f.spaceRuleGb,
                                    "left": SizeFormat.gb(f.leftForSystemGb)])
    }

    /// "~/Movies/AnimeUp Jobs/" like the boards: home shortened, trailing slash.
    private func displayPath(_ path: String) -> String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let short = path.hasPrefix(home) ? "~" + path.dropFirst(home.count) : path
        return short.hasSuffix("/") ? short : short + "/"
    }
}

// MARK: - This Mac

struct ThisMacCard: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Card {
            CardTitle(model.t("nat.mac.title"), symbol: "gauge.medium")
            if let m = model.machine { ValueStrip(strip(m)) }
            calibration
            tools.frame(maxHeight: .infinity, alignment: .bottomLeading)
        }
    }

    private func strip(_ m: MachineInfo) -> [ValueStrip.Item] {
        [
            .init(symbol: "cpu", value: m.chipShort, label: model.t("nat.mac.cpu", ["n": m.cpuCores.map(String.init) ?? "?"])),
            .init(symbol: "square.grid.3x3", value: model.t("nat.mac.gpu_value", ["n": m.gpuCores.map(String.init) ?? "?"]),
                  label: model.t("nat.mac.gpu")),
            .init(symbol: "memorychip", value: m.memoryGb.map { "\($0) GB" } ?? "—", label: model.t("nat.mac.memory")),
            .init(symbol: "apple.logo", value: shortVersion(m.macosVersion),
                  label: m.macosName.isEmpty ? "macOS" : model.t("nat.mac.macos", ["name": m.macosName])),
        ]
    }

    private func shortVersion(_ v: String) -> String {
        v.split(separator: ".").prefix(2).joined(separator: ".")
    }

    @ViewBuilder
    private var calibration: some View {
        if let c = model.calibration {
            let running = c.running || model.calRun?.running == true
            if running && c.state == .done {
                // Recalibrating: the numbers so far stay, the date gives way to the run.
                speeds(c, running: true)
            } else if running {
                NoteView(.accent, text: model.t("nat.mac.running"))
            } else {
                switch c.state {
                case .done:
                    speeds(c)
                case .never:
                    NoteView(.accent, title: model.t("nat.mac.first_title"), text: model.t("nat.mac.first_text"),
                             centred: true) {
                        Button(model.t("nat.btn.calibrate")) { model.calibrate() }.auButton(.primary, .regular)
                    }
                case .oldVersion, .otherMac:
                    NoteView(.yellow,
                             title: model.t(c.state == .oldVersion ? "nat.mac.old_title" : "nat.mac.other_title"),
                             text: c.state == .oldVersion ? model.t("nat.mac.old_text")
                                 : model.t("nat.mac.other_text", ["chip": c.otherChip ?? "?"]),
                             centred: true) {
                        Button(model.t("nat.btn.calibrate_again")) { model.calibrate() }.auButton(.notice, .regular)
                    }
                }
            }
        }
    }

    private func speeds(_ c: CalibrationState, running: Bool = false) -> some View {
        // Board K3: every model, by its full name.
        let rows = c.models.filter { $0.fps1080p != nil }
        let top = max(1, (rows.compactMap(\.fps1080p).max() ?? 1) * 1.06)
        return VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Text(model.t("nat.mac.cal_label")).auLabel()
                if running {
                    // As in the sidebar: a spinner and "In progress" in place of the date.
                    // Reopens the calibration sheet, closed while the run went on.
                    StatusLink(model.t("nat.side.cal_running"), tone: .accent, size: 11, busy: true) {
                        model.showCalibration = true
                    }
                } else {
                    StatusLink(c.date.map(model.dateTime) ?? "", size: 11, help: model.t("nat.cald.open_help")) {
                        model.openCalibrationDetails()
                    }
                }
                Spacer()
                Text(model.t("nat.mac.speed_note")).auFont(11).foregroundStyle(AU.text3)
            }
            .padding(.bottom, 2)
            ForEach(rows) { row in
                HStack(spacing: 10) {
                    Text(fullName(row)).auFont(12).foregroundStyle(AU.text)
                        .lineLimit(1).frame(width: 170, alignment: .leading)
                    AUBar((row.fps1080p ?? 0) / top, height: 6)
                    Text(model.t("nat.mac.fps", ["fps": String(format: "%.1f", row.fps1080p ?? 0)]))
                        .auFont(AUFont.smallNumbers).foregroundStyle(AU.textCode)
                        .frame(width: 64, alignment: .trailing)
                }
                .frame(height: 17)
            }
        }
        .padding(.top, 6)
    }

    /// The model's full name in the app's language (the engine answers in its own).
    private func fullName(_ row: CalibrationState.ModelSpeed) -> String {
        let key = "mot.modello.\(row.key).label"
        return model.localizer.has(key) ? model.t(key) : row.label
    }

    private struct ToolRow: Identifiable {
        var id: String
        var name: String
        var detail: String
        var version: String
        var state: State
        var help: String?
        enum State { case verified, unverified, missing }
    }

    private var toolRows: [ToolRow] {
        guard let t = model.tools else { return [] }
        let byKey = Dictionary(uniqueKeysWithValues: t.tools.map { ($0.key, $0) })
        func state(_ items: [ToolsStatus.Tool]) -> ToolRow.State {
            if items.contains(where: { !$0.present }) { return .missing }
            return items.allSatisfy(\.verified) ? .verified : .unverified
        }
        func version(_ tool: ToolsStatus.Tool?) -> String {
            guard let tool else { return "" }
            guard let v = tool.version ?? (tool.present ? nil : tool.expectedVersion) else { return "" }
            return v.hasPrefix("v") ? v : "v" + v
        }
        var rows: [ToolRow] = []
        let ff = [byKey["ffmpeg"], byKey["ffprobe"]].compactMap { $0 }
        rows.append(ToolRow(id: "ffmpeg", name: "FFmpeg", detail: model.t("nat.tool.ffmpeg"),
                            version: byKey["ffmpeg"]?.present == true ? version(byKey["ffmpeg"]) : model.t("nat.tool.missing"),
                            state: state(ff), help: unverifiedHelp(ff)))
        for key in ["realesrgan", "realcugan"] {
            guard let tool = byKey[key] else { continue }
            rows.append(ToolRow(id: key, name: tool.name, detail: model.t("nat.tool.\(key)"),
                                version: tool.present ? version(tool) : model.t("nat.tool.missing"),
                                state: state([tool]), help: unverifiedHelp([tool])))
        }
        rows.append(ToolRow(id: "python", name: "Python", detail: model.t("nat.tool.python"),
                            version: "v" + t.python.short, state: .verified, help: nil))
        return rows
    }

    private func unverifiedHelp(_ tools: [ToolsStatus.Tool]) -> String? {
        guard let t = tools.first(where: { $0.present && !$0.verified }), let path = t.path else { return nil }
        return model.t("nat.tool.unverified", ["path": path])
    }

    private var tools: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(model.t("nat.mac.tools")).auLabel()
            VStack(alignment: .leading, spacing: (model.calibration?.isCalibrated ?? false) ? 4 : 6) {
                ForEach(toolRows) { row in
                    HStack(spacing: 6) {
                        icon(row.state).frame(width: 14)
                        Text(row.name).foregroundStyle(AU.text).frame(width: 110, alignment: .leading)
                        Text(row.detail).foregroundStyle(AU.text2).lineLimit(1)
                        Spacer(minLength: 6)
                        Text(row.version).auFont(AUFont.smallNumbers)
                            .foregroundStyle(row.state == .missing ? AU.redText : AU.text3)
                    }
                    .auFont(12)
                    .help(row.help ?? "")
                }
            }
        }
    }

    @ViewBuilder
    private func icon(_ state: ToolRow.State) -> some View {
        switch state {
        case .verified:
            Image(systemName: "checkmark").auFont(10, .semibold).foregroundStyle(AU.greenText)
        case .unverified:
            Image(systemName: "exclamationmark.triangle.fill").auFont(10).foregroundStyle(AU.yellow)
        case .missing:
            Image(systemName: "exclamationmark.octagon.fill").auFont(10).foregroundStyle(AU.redText)
        }
    }
}

// MARK: - How a batch goes

struct HowABatchGoesCard: View {
    @Environment(AppModel.self) private var model
    @State private var layout = Layout.plain

    /// By the card's width: the steps alone (a narrow column), each with its drawing
    /// at the right (board S1c), or side by side with the drawing above (one column).
    enum Layout { case plain, art, row }

    static func layout(_ width: CGFloat) -> Layout { width >= 820 ? .row : width >= 520 ? .art : .plain }

    var body: some View {
        Card {
            CardTitle(model.t("nat.how.title"), symbol: "list.bullet.rectangle")
            NumberedSteps([
                .init(title: model.t("nat.how.cal"), detail: model.t("nat.how.cal_text"),
                      done: model.calibration?.isCalibrated ?? false),
                .init(title: model.t("nat.how.add"), detail: model.t("nat.how.add_text"),
                      done: model.files.contains { $0.state == .ready }),
                // Compare is optional: done once a test has its results, never in the way when skipped.
                .init(title: model.t("nat.how.compare"), detail: model.t("nat.how.compare_text"),
                      done: model.compareHasResults),
                .init(title: model.t("nat.how.queue"), detail: model.t("nat.how.queue_text"),
                      done: model.files.contains { model.job($0.id)?.state == .done }),
            ], inRow: layout == .row, art: layout == .plain ? nil : { AnyView(StepOutline(index: $0)) })
            .frame(maxHeight: .infinity)
        }
        .onGeometryChange(for: Layout.self) { Self.layout($0.size.width) } action: { layout = $0 }
    }
}
