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
                StartContent(minGrid: geo.size.height - StartContent.headerHeight)
                ScrollView { StartContent(minGrid: 0) }
            }
        }
        .ignoresSafeArea(edges: .top)
    }

}

/// The title, the intro and the four cards.
struct StartContent: View {
    @Environment(AppModel.self) private var model
    var minGrid: CGFloat

    private var calibrated: Bool { model.calibration?.isCalibrated ?? false }

    var body: some View { content(minGrid: minGrid) }

    /// Title, intro and paddings above and below the cards.
    static let headerHeight: CGFloat = 28 + 29 + 6 + 40 + 18 + 24

    private func content(minGrid: CGFloat) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 6) {
                Text(model.t(calibrated || model.status != .ready ? "nat.start.title" : "nat.start.welcome"))
                    .auPageTitle()
                // Two lines of similar length, the second slightly longer.
                Text(model.t("nat.start.intro1") + "\n" + model.t("nat.start.intro2")).auBody()
                    .fixedSize(horizontal: false, vertical: true)
            }
            if model.status == .ready {
                GridLayout(gap: 14, leftShare: 1.15 / 2.15, minHeight: minGrid) {
                    if model.files.isEmpty { AddVideosCard() } else { YourVideosCard() }
                    WhereFilesGoCard()
                    ThisMacCard()
                    HowABatchGoesCard()
                }
            } else {
                EngineStatusView().frame(minHeight: minGrid)
            }
        }
        .padding(.top, 28)
        .padding(.horizontal, 28)
        .padding(.bottom, 24)
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }

}

/// Two columns (1.15 : 1) and two rows of equal height, 14 pt apart.
struct GridLayout: Layout {
    var gap: CGFloat
    var leftShare: CGFloat
    /// Fill at least this height (the window), with two equal rows if they fit.
    var minHeight: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? 900
        let (left, right) = widths(width)
        let rows = rowHeights(subviews, left: left, right: right)
        let natural = rows.0 + rows.1 + gap
        let height = max(natural, minHeight)
        return CGSize(width: width, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
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
                    Label(model.localizer.tn("nat.add.received", n), systemImage: "checkmark")
                        .labelStyle(SmallIconLabel())
                        .auSmall(AU.greenText)
                } else {
                    Label(model.t("nat.add.not_handled"), systemImage: "info.circle")
                        .labelStyle(SmallIconLabel())
                        .auSmall(AU.text3)
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
            Text(title).font(.system(size: size, weight: size < 13 ? .medium : .regular)).foregroundStyle(AU.text).lineLimit(1)
            Spacer()
            Image(systemName: "chevron.down").font(.system(size: 9, weight: .semibold)).foregroundStyle(AU.text2)
        }
        .padding(.leading, 12)
        .padding(.trailing, 10)
        .frame(width: width, height: height)
        .background(RoundedRectangle(cornerRadius: AU.Radius.field).fill(AU.control))
        .overlay(RoundedRectangle(cornerRadius: AU.Radius.field).strokeBorder(AU.glassLine, lineWidth: 1))
        .contentShape(Rectangle())
    }
}

struct SmallIconLabel: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 6) {
            configuration.icon.font(.system(size: 11))
            configuration.title
        }
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
                    ForEach(Array(files.enumerated()), id: \.element.id) { i, f in
                        if i > 0 { Rectangle().fill(AU.line).frame(height: 1) }
                        Button { model.tab = .queue; model.expanded = f.id; model.panelTab = .analysis } label: {
                            HStack(spacing: 8) {
                                icon(f).frame(width: 16)
                                Text(f.name).font(.system(size: 12, weight: .medium)).foregroundStyle(AU.text)
                                    .lineLimit(1).truncationMode(.middle)
                                Spacer(minLength: 4)
                                if !f.warnings.isEmpty {
                                    StatusChip(model.localizer.tn("nat.queue.n_warnings", f.warnings.count), tone: .yellow,
                                               symbol: "exclamationmark.triangle.fill")
                                }
                                Text(f.report.map { Fmt.clock($0.duration) } ?? "—").font(AUFont.smallNumbers)
                                    .foregroundStyle(AU.textCode).frame(width: 50, alignment: .trailing)
                            }
                            .padding(.horizontal, 8).padding(.vertical, 5)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
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
            HStack(spacing: 10) {
                Text(model.t("nat.start.drop_more")).auSmall()
                Button { model.openVideos() } label: { Label(model.t("nat.queue.add"), systemImage: "plus") }
                    .auButton(.secondary, .small)
            }
            .frame(maxWidth: .infinity, minHeight: 58, maxHeight: .infinity)
            .overlay(RoundedRectangle(cornerRadius: AU.Radius.field)
                .strokeBorder(AU.boxLine, style: StrokeStyle(lineWidth: 1.5, dash: [5, 4])))
            .onDrop(of: [.fileURL], isTargeted: nil) { providers in
                Task { @MainActor in model.add(await loadURLs(providers)) }
                return true
            }
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
        switch f.state {
        case .ready: Image(systemName: "checkmark").font(.system(size: 10, weight: .semibold)).foregroundStyle(AU.greenText)
        case .analysing: Spinner(size: 10)
        case .queued: Circle().strokeBorder(AU.glassLine).frame(width: 10, height: 10)
        case .failed, .missing: Image(systemName: "exclamationmark.octagon.fill").font(.system(size: 10)).foregroundStyle(AU.redText)
        }
    }
}

// MARK: - Where files go

struct WhereFilesGoCard: View {
    @Environment(AppModel.self) private var model
    @State private var space: Double = 0
    @State private var editing = false

    var body: some View {
        Card(spacing: 22) {
            CardTitle(model.t("nat.where.title"), symbol: "folder").padding(.bottom, -6)
            VStack(alignment: .leading, spacing: 6) {
                Text(model.t("nat.where.finished")).auLabel()
                Menu {
                    Button(model.t("nat.where.next_to")) {}
                } label: {
                    PopupLabel(model.t("nat.where.next_to"))
                }
                .menuStyle(.button)
                .buttonStyle(.plain)
                .menuIndicator(.hidden)
                .frame(width: 280)
                Text(model.t("nat.where.or_pick")).auSmall()
            }
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
            if let f = model.folders {
                VStack(alignment: .leading, spacing: 6) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(model.t("nat.where.space")).auLabel()
                        Spacer()
                        Text("\(Text("\(Int(space)) GB").foregroundStyle(AU.text)) \(model.t("nat.where.of_free", ["free": SizeFormat.gb(f.freeGb)]))")
                            .foregroundStyle(AU.text3)
                            .font(AUFont.smallNumbers)
                    }
                    Slider(value: $space,
                           in: Double(f.spaceMinGb)...Double(max(f.spaceMinGb + 1, f.spaceRuleGb)),
                           step: 1) { editing = $0; if !$0 { model.setSpace(Int(space)) } }
                        .controlSize(.small)
                        .tint(AU.primary)
                    Text(model.t("nat.where.space_note")).auSmall()
                }
                .onAppear { space = Double(model.settings?.diskGb ?? f.spaceSettingGb) }
                .onChange(of: model.settings?.diskGb) { _, new in if !editing, let new { space = Double(new) } }
            }
            Spacer(minLength: 0)
            Label(model.t("nat.where.settings"), systemImage: "gearshape")
                .labelStyle(SmallIconLabel())
                .auSmall(AU.text3)
        }
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
            Spacer(minLength: 0)
            tools
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
            if c.running {
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

    private func speeds(_ c: CalibrationState) -> some View {
        // The three of board S2 (denoise leggero runs on the same network as
        // no-denoise, at the same speed).
        let rows = c.models.filter { $0.fps1080p != nil && $0.key != "cugan-denoise" }
        let top = max(1, (rows.compactMap(\.fps1080p).max() ?? 1) * 1.06)
        return VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Text(model.t("nat.mac.cal_label")).auLabel()
                StatusChip(model.t("nat.mac.cal_chip", ["when": c.date.map(model.relative) ?? ""]),
                           tone: .green, symbol: "checkmark")
                Spacer()
                Text(model.t("nat.mac.speed_note")).font(.system(size: 11)).foregroundStyle(AU.text3)
            }
            .padding(.bottom, 2)
            ForEach(rows) { row in
                HStack(spacing: 10) {
                    Text(shortName(row)).font(.system(size: 12)).foregroundStyle(AU.text)
                        .lineLimit(1).frame(width: 140, alignment: .leading)
                    AUBar((row.fps1080p ?? 0) / top, height: 6)
                    Text(model.t("nat.mac.fps", ["fps": String(format: "%.1f", row.fps1080p ?? 0)]))
                        .font(AUFont.smallNumbers).foregroundStyle(AU.textCode)
                        .frame(width: 64, alignment: .trailing)
                }
                .frame(height: 17)
            }
        }
        .padding(.top, 6)
    }

    /// The model's short name in the app's language (the engine answers in
    /// its own): the catalog label without "Real-ESRGAN " / "Real-".
    private func shortName(_ row: CalibrationState.ModelSpeed) -> String {
        let key = "mot.modello.\(row.key).label"
        guard model.localizer.has(key) else { return row.short }
        let label = model.t(key)
        return label.hasPrefix("Real-ESRGAN ") ? String(label.dropFirst(12))
            : label.hasPrefix("Real-") ? String(label.dropFirst(5)) : label
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
                        Text(row.version).font(AUFont.smallNumbers)
                            .foregroundStyle(row.state == .missing ? AU.redText : AU.text3)
                    }
                    .font(.system(size: 12))
                    .help(row.help ?? "")
                }
            }
        }
    }

    @ViewBuilder
    private func icon(_ state: ToolRow.State) -> some View {
        switch state {
        case .verified:
            Image(systemName: "checkmark").font(.system(size: 10, weight: .semibold)).foregroundStyle(AU.greenText)
        case .unverified:
            Image(systemName: "exclamationmark.triangle.fill").font(.system(size: 10)).foregroundStyle(AU.yellow)
        case .missing:
            Image(systemName: "exclamationmark.octagon.fill").font(.system(size: 10)).foregroundStyle(AU.redText)
        }
    }
}

// MARK: - How a batch goes

struct HowABatchGoesCard: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Card {
            CardTitle(model.t("nat.how.title"), symbol: "list.bullet.rectangle")
            NumberedSteps([
                .init(title: model.t("nat.how.cal"), detail: model.t("nat.how.cal_text"),
                      done: model.calibration?.isCalibrated ?? false),
                .init(title: model.t("nat.how.add"), detail: model.t("nat.how.add_text"),
                      done: model.files.contains { $0.state == .ready }),
                .init(title: model.t("nat.how.compare"), detail: model.t("nat.how.compare_text")),
                .init(title: model.t("nat.how.queue"), detail: model.t("nat.how.queue_text")),
            ])
            .frame(maxHeight: .infinity)
        }
    }
}
