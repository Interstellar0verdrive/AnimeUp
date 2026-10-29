import DesignSystem
import Models
import SwiftUI

/// Board T1: before Start, when video tools are missing. The window turns
/// into the main window when everything is verified.
struct ToolsSetupView: View {
    @Environment(AppModel.self) private var model

    private var failed: (key: String, error: String)? {
        if case .failed(let key, let error) = model.tools2.phase { return (key, error) }
        return nil
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .center, spacing: 16) {
                Image(nsImage: NSApp.applicationIconImage)
                    .resizable().frame(width: 64, height: 64)
                VStack(alignment: .leading, spacing: 4) {
                    Text(model.t("nat.start.welcome")).auFont(17, .bold).foregroundStyle(AU.text)
                    Text(model.t("nat.tools.intro1", ["mb": totalMB]) + "\n" + model.t("nat.tools.intro2"))
                        .auSmall().fixedSize(horizontal: false, vertical: true)
                }
            }
            if let failed {
                NoteView(.red, title: model.t("nat.tools.stopped_title"),
                         text: model.t(failed.error.lowercased().contains("checksum") ? "nat.tools.stopped_checksum" : "nat.tools.stopped_text",
                                       ["tool": name(failed.key)])
                            + "\n" + model.t("nat.tools.stopped_kept"))
                    .help(failed.error)
            } else {
                let totals = model.toolsTotals
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(model.t("nat.tools.downloading", ["i": totals.index, "n": totals.count]))
                        .auFont(13, .semibold).foregroundStyle(AU.text)
                    Text(model.t("nat.tools.progress", ["done": totals.done / 1_000_000,
                                                        "total": totals.total / 1_000_000]) + timeLeft(totals))
                        .auFont(12).foregroundStyle(AU.text2)
                }
            }
            rows
            HStack(spacing: 8) {
                if failed != nil {
                    UnderlineLink(model.t("nat.btn.show_log"), tone: .red) { model.showLog() }
                    Spacer()
                    Button(model.t("nat.btn.quit")) { NSApp.terminate(nil) }.auButton(.secondary, .regular)
                    Button(model.t("nat.btn.retry")) { model.retryTools() }.auButton(.primary, .regular)
                } else {
                    Text(model.t("nat.tools.inside")).auSmall()
                    Spacer()
                    Button(model.t("nat.btn.quit")) { NSApp.terminate(nil) }.auButton(.secondary, .regular)
                }
            }
        }
        .padding(.horizontal, 28)
        .padding(.top, 44)
        .padding(.bottom, 24)
        .frame(width: 600)
        .background(AU.bg)
    }

    /// " · about a minute left", from the bytes since the window opened.
    private func timeLeft(_ t: (done: Int64, total: Int64, index: Int, count: Int)) -> String {
        guard let start = model.tools2.startedAt, t.done > model.tools2.startBytes else { return "" }
        let rate = Double(t.done - model.tools2.startBytes) / max(1, Date().timeIntervalSince1970 - start)
        let left = Double(t.total - t.done) / max(1, rate)
        guard left.isFinite, left > 0 else { return "" }
        return " · " + (left < 90 ? model.t("nat.tools.minute_left") : model.t("nat.tools.minutes_left", ["n": Int((left / 60).rounded())]))
    }

    private var totalMB: Int {
        Int(model.tools2.rows.reduce(Int64(0)) { $0 + (ToolsSetupState.sizesMB[$1.key] ?? 0) })
    }

    private func name(_ key: String) -> String {
        ["ffmpeg": "FFmpeg", "realesrgan": "Real-ESRGAN", "realcugan": "Real-CUGAN", "python": "Python"][key] ?? key
    }

    private func version(_ key: String) -> String {
        ["ffmpeg": "v9.0.2", "realesrgan": "v0.2.5.0", "realcugan": "v20220728", "python": "v3.13"][key] ?? ""
    }

    private func detail(_ key: String) -> String {
        model.t(key == "python" ? "nat.tool.python" : key == "ffmpeg" ? "nat.tool.ffmpeg" : "nat.tools.its_models")
    }

    private var rows: some View {
        VStack(spacing: 0) {
            ForEach(Array(model.tools2.rows.enumerated()), id: \.element.id) { index, row in
                if index > 0 { Rectangle().fill(AU.line).frame(height: 1) }
                rowView(row)
            }
        }
        .background(RoundedRectangle(cornerRadius: AU.Radius.field).fill(AU.surface))
        .overlay(RoundedRectangle(cornerRadius: AU.Radius.field).strokeBorder(AU.line))
        .clipShape(RoundedRectangle(cornerRadius: AU.Radius.field))
    }

    private func rowView(_ row: ToolsSetupState.Row) -> some View {
        let running = row.state == .running
        let isFailed = row.state == .failed
        return HStack(spacing: 10) {
            icon(row.state)
            Text("\(name(row.key)) \(version(row.key)) · \(detail(row.key))")
                .auFont(12.5, running || isFailed ? .semibold : .regular)
                .foregroundStyle(isFailed ? AU.redText : running ? AU.text : row.state == .done ? AU.text : AU.text2)
                .lineLimit(1)
            Spacer(minLength: 8)
            if running, row.key != "python", row.total > 0 {
                AUBar(Double(row.bytes) / Double(row.total)).frame(width: 90)
            }
            if isFailed { StatusChip(model.t("nat.chip.stopped"), tone: .red) }
            Text("\(ToolsSetupState.sizesMB[row.key] ?? 0) MB")
                .auFont(AUFont.smallNumbers).foregroundStyle(AU.text3)
                .frame(width: 44, alignment: .trailing)
        }
        .padding(.horizontal, 14)
        .frame(height: 33)
        .background(running ? AU.soft : isFailed ? AU.redSoft : .clear)
    }

    @ViewBuilder
    private func icon(_ state: ToolProgress.State) -> some View {
        switch state {
        case .done:
            Image(systemName: "checkmark").auFont(9, .bold).foregroundStyle(AU.greenText)
                .frame(width: 18, height: 18).background(Circle().fill(AU.greenBg))
                .overlay(Circle().strokeBorder(AU.greenLine))
        case .running:
            Spinner(size: 16).frame(width: 18, height: 18)
        case .failed:
            Image(systemName: "xmark").auFont(8, .bold).foregroundStyle(AU.redText)
                .frame(width: 18, height: 18).overlay(Circle().strokeBorder(AU.redLine))
        case .waiting:
            Circle().strokeBorder(AU.glassLine).frame(width: 18, height: 18)
        }
    }
}
