import DesignSystem
import Models
import SwiftUI

/// Boards K1/K2: the calibration sheet on the main window.
struct CalibrationSheet: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let run = model.calRun
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 12) {
                Image(systemName: "gauge.medium").font(.system(size: 26)).foregroundStyle(AU.primaryText)
                VStack(alignment: .leading, spacing: 2) {
                    Text(model.t(title(run))).font(.system(size: 17, weight: .bold)).foregroundStyle(AU.text)
                    Text(model.t("nat.cal.intro")).auSmall().fixedSize(horizontal: false, vertical: true)
                }
            }
            if let run, run.running {
                running(run)
            } else if let run, run.state == "done", run.seen != true {
                results(run)
            } else if let run, run.state == "failed" || (run.state == "interrupted" && !(run.error ?? "").isEmpty) {
                NoteView(.red, title: model.t("nat.cal.failed"), text: run.error ?? "")
            } else {
                NoteView(.accent, text: model.t("nat.cal.before"))
            }
            HStack(spacing: 8) {
                if let run, run.state == "failed" || run.running {
                    UnderlineLink(model.t("nat.btn.show_log"), tone: .neutral) { model.openLog(run.log) }
                }
                Spacer()
                if let run, run.running {
                    Button(model.t("nat.cal.close")) { model.closeCalibration() }.auButton(.secondary, .regular)
                    Button(model.t("nat.run.stop")) { model.stopCalibration() }.auButton(.destructive, .regular)
                } else if let run, run.state == "done", run.seen != true {
                    Button(model.t("nat.btn.ok")) { model.closeCalibration() }.auButton(.primary, .regular)
                        .keyboardShortcut(.defaultAction)
                } else {
                    Button(model.t("nat.btn.cancel")) { model.closeCalibration() }.auButton(.secondary, .regular)
                        .keyboardShortcut(.cancelAction)
                    Button(model.t(run?.state == "failed" ? "nat.btn.retry" : "nat.cal.start")) { model.startCalibration() }
                        .auButton(.primary, .regular)
                        .keyboardShortcut(.defaultAction)
                }
            }
        }
        .padding(24)
        .frame(width: 520)
        .background(AU.bg)
    }

    private func title(_ run: CalibrationRun?) -> String {
        guard let run else { return "nat.cal.title" }
        if run.running { return "nat.cal.title_running" }
        if run.state == "done" && run.seen != true { return "nat.cal.title_done" }
        return "nat.cal.title"
    }

    private func running(_ run: CalibrationRun) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(model.t("nat.cal.step", ["i": min((run.index ?? 0) + 1, max(1, run.total ?? 1)), "n": max(1, run.total ?? 1)]))
                    .font(.system(size: 13, weight: .semibold))
                if let left = run.left { Text("· " + model.t("nat.run.left", ["t": Fmt.elapsed(left)])).auSmall() }
                Spacer()
                Text("\(Int(((run.fraction ?? 0) * 100).rounded()))%").font(AUFont.numbers).foregroundStyle(AU.primaryText)
            }
            AUBar(run.fraction ?? 0, height: 6)
            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(run.steps.enumerated()), id: \.offset) { i, step in
                    HStack(spacing: 8) {
                        if i < (run.index ?? 0) {
                            Image(systemName: "checkmark").font(.system(size: 10, weight: .semibold)).foregroundStyle(AU.greenText)
                                .frame(width: 16)
                        } else if i == (run.index ?? 0) {
                            Spinner(size: 12).frame(width: 16)
                        } else {
                            Circle().strokeBorder(AU.glassLine).frame(width: 12, height: 12).frame(width: 16)
                        }
                        Text(step).font(.system(size: 12)).foregroundStyle(i <= (run.index ?? 0) ? AU.text : AU.text3)
                        Spacer()
                    }
                    .padding(.vertical, 5).padding(.horizontal, 10)
                    .background(i == (run.index ?? 0) ? AU.soft : .clear)
                }
            }
            .frame(maxHeight: 220)
            .clipped()
            .background(RoundedRectangle(cornerRadius: AU.Radius.field).fill(AU.inset))
            Text(model.t("nat.cal.close_note")).auSmall()
        }
    }

    private func results(_ run: CalibrationRun) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(model.t("nat.col.model")).frame(width: 170, alignment: .leading)
                Text(model.t("nat.cal.before_col")).frame(width: 80, alignment: .trailing)
                Text(model.t("nat.cal.now_col")).frame(width: 80, alignment: .trailing)
                Text(model.t("nat.cal.change_col")).frame(width: 80, alignment: .trailing)
            }
            .auLabel()
            ForEach(run.table.filter { $0.now != nil }) { r in
                HStack {
                    Text(model.shortModel(r.key)).font(.system(size: 12)).frame(width: 170, alignment: .leading)
                    Text(r.before.map { String(format: "%.1f fps", $0) } ?? "—").frame(width: 80, alignment: .trailing)
                    Text(r.now.map { String(format: "%.1f fps", $0) } ?? "—").frame(width: 80, alignment: .trailing)
                    Text(change(r)).frame(width: 80, alignment: .trailing)
                }
                .font(AUFont.smallNumbers).foregroundStyle(AU.textCode)
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: AU.Radius.field).fill(AU.inset))
    }

    private func change(_ r: CalibrationRun.Row) -> String {
        guard let b = r.before, let n = r.now, b > 0 else { return "—" }
        return String(format: "%+.0f%%", (n / b - 1) * 100)
    }
}
