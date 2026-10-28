import DesignSystem
import Models
import SwiftUI

/// The glass sidebar of the boards: traffic lights and the Settings gear on
/// the top row, three tabs, This Mac, the activity card slot and the footer.
struct SidebarView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openSettings) private var openSettings

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            nav
            Rectangle().fill(AU.glassLine).frame(height: 1).padding(.horizontal, 6).padding(.vertical, 2)
            thisMac
            Spacer(minLength: 12)
            // The activity card slot: one card for whatever keeps AnimeUp
            // busy (analysis now; queue, Compare test, calibration later).
            if let run = model.calRun, run.running {
                ActivityCard(kind: model.t("nat.cal.card"),
                             line: Text(model.t("nat.cal.step", ["i": min((run.index ?? 0) + 1, max(1, run.total ?? 1)), "n": max(1, run.total ?? 1)])
                                        + (run.left.map { " · " + model.t("nat.run.left", ["t": Fmt.elapsed($0)]) } ?? "")),
                             fraction: run.fraction ?? 0) {
                    Button { model.stopCalibration() } label: { Label(model.t("nat.run.stop"), systemImage: "stop.fill") }
                        .auButton(.secondary, .small, fullWidth: true)
                }
                .onTapGesture { model.showCalibration = true }
            } else if model.progress.queue.running {
                QueueCard()
            } else if let v = model.updates?.available {
                UpdateCard(version: v)
            } else if model.activity.running, let name = model.activity.name {
                ActivityCard(kind: model.t("nat.side.analysis"),
                             line: Text("\(model.t("nat.side.file_of", ["i": model.activity.index ?? 1, "n": model.activity.total ?? 1])) · \(name)"),
                             fraction: Double((model.activity.index ?? 1) - 1) / Double(max(1, model.activity.total ?? 1)),
                             footnote: model.t("nat.side.usable_meanwhile")) { EmptyView() }
                    .onTapGesture { model.tab = .queue; model.expanded = model.activity.id }
            }
            footer
        }
        .padding(.horizontal, 10)
        .padding(.bottom, 12)
        .toolbar {
            ToolbarItem(placement: .automatic) {
                Button { openSettings() } label: {
                    Image(systemName: "gearshape").font(.system(size: 13))
                }
                .help(model.t("nat.side.settings"))
            }
        }
    }

    private var nav: some View {
        VStack(spacing: 2) {
            SidebarTab(symbol: "house", title: model.t("nat.tab.start"), subtitle: model.t("nat.tab.start_sub"),
                       selected: model.tab == .start) { model.tab = .start }
            SidebarTab(symbol: "rectangle.split.2x1", title: model.t("nat.tab.compare"),
                       subtitle: model.t("nat.tab.compare_sub"), selected: model.tab == .compare) { model.tab = .compare }
            SidebarTab(symbol: "film.stack", title: model.t("nat.tab.queue"), subtitle: model.queueSubtitle,
                       selected: model.tab == .queue,
                       trailing: model.activity.running || (model.progress.queue.running && !model.progress.queue.paused) ? .busy : .none) { model.tab = .queue }
        }
    }

    private var thisMac: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text(model.t("nat.side.this_mac")).auLabel().padding(.bottom, -10)
            VStack(alignment: .leading, spacing: 6) {
                rowTitle("gauge.medium", model.t("nat.side.calibration"))
                calibration
            }
            VStack(alignment: .leading, spacing: 6) {
                rowTitle("externaldrive", model.t("nat.side.space"))
                space
            }
        }
        .padding(.horizontal, 6)
        .padding(.top, 4)
    }

    private func rowTitle(_ symbol: String, _ title: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: symbol).font(.system(size: 13)).foregroundStyle(AU.text2).frame(width: 16)
            Text(title).font(.system(size: 12, weight: .medium)).foregroundStyle(AU.text)
        }
    }

    @ViewBuilder
    private var calibration: some View {
        if let c = model.calibration {
            if c.running || model.calRun?.running == true {
                HStack(spacing: 6) {
                    Spinner(size: 11)
                    Text(model.t("nat.side.cal_running")).font(.system(size: 12)).foregroundStyle(AU.primaryText)
                }
            } else {
                switch c.state {
                case .never:
                    HStack(spacing: 6) {
                        StatusDot(.yellow)
                        Text(model.t("nat.side.cal_never")).font(.system(size: 12)).foregroundStyle(AU.yellowText)
                        Spacer(minLength: 4)
                        Button(model.t("nat.btn.calibrate")) { model.calibrate() }.auButton(.secondary, .small)
                    }
                case .done:
                    HStack(spacing: 6) {
                        StatusDot(.green)
                        Text(model.t("nat.side.cal_done", ["when": c.date.map(model.relative) ?? ""]))
                            .font(.system(size: 12)).foregroundStyle(AU.greenText)
                    }
                    Button(model.t("nat.btn.calibrate_again")) { model.calibrate() }.auButton(.secondary, .small)
                case .oldVersion, .otherMac:
                    HStack(spacing: 6) {
                        StatusDot(.yellow)
                        Text(model.t(c.state == .oldVersion ? "nat.side.cal_old" : "nat.side.cal_other"))
                            .font(.system(size: 12)).foregroundStyle(AU.yellowText)
                    }
                    Button(model.t("nat.btn.calibrate_again")) { model.calibrate() }.auButton(.primary, .small)
                }
            }
        } else {
            Text("—").font(.system(size: 12)).foregroundStyle(AU.text3)
        }
    }

    @ViewBuilder
    private var space: some View {
        if let f = model.folders {
            if f.reachable {
                Text("\(Text(SizeFormat.gb(f.freeGb)).fontWeight(.semibold).foregroundStyle(AU.text)) \(model.t("nat.side.free_of", ["total": SizeFormat.gb(f.totalGb)]))")
                    .foregroundStyle(AU.text2)
                    .font(.system(size: 12))
                AUBar(f.totalGb > 0 ? 1 - f.freeGb / f.totalGb : 0, fill: AU.text3, track: AU.track)
                    .padding(.top, 4)
                    .help(f.workFolder)
            } else {
                Text(model.t("nat.side.not_connected")).font(.system(size: 12)).foregroundStyle(AU.yellowText)
            }
        } else {
            Text("—").font(.system(size: 12)).foregroundStyle(AU.text3)
        }
    }

    private var footer: some View {
        HStack(spacing: 8) {
            Text(model.t("nat.side.version", ["version": AppModel.appVersion]))
                .font(AUFont.smallNumbers).foregroundStyle(AU.text3)
                .help(model.t("nat.side.engine_version", ["version": model.hello?.version ?? "…"]))
            Button { model.checkForUpdates() } label: {
                Image(systemName: "arrow.clockwise").font(.system(size: 10, weight: .medium))
            }
            .buttonStyle(.plain)
            .foregroundStyle(AU.text3)
            .help(model.t("nat.side.check_updates"))
            Spacer(minLength: 0)
            Link(destination: URL(string: "https://github.com/Interstellar0verdrive/AnimeUp")!) {
                HStack(spacing: 4) {
                    Image("GitHubMark").resizable().renderingMode(.template).frame(width: 13, height: 13)
                    Text(model.t("nat.side.github")).font(.system(size: 11))
                }
                .foregroundStyle(AU.text3)
            }
            .pointerStyle(.link)
        }
        .padding(.horizontal, 6)
        .padding(.top, 2)
    }
}


/// The sidebar card while the queue runs, rests or is paused (DS4 activity cards).
struct QueueCard: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let q = model.progress.queue
        let live = model.progress.files.values.first { $0.state == .running || $0.state == .paused }
        let total = Double(max(1, q.total ?? 1))
        let fraction = (Double(max(0, (q.position ?? 1) - 1)) + (live?.fraction ?? 0)) / total
        if let until = q.restingUntil {
            ActivityCard(kind: model.t("nat.run.card_rest"), symbol: "cup.and.saucer",
                         line: Text(model.t("nat.run.rest_line", ["i": min((q.position ?? 1) + 1, q.total ?? 1), "n": q.total ?? 1,
                                                                 "t": Fmt.elapsed(until - Date().timeIntervalSince1970)])),
                         fraction: fraction) {
                Button { model.command("queue.startNow") } label: { Label(model.t("nat.run.start_now"), systemImage: "play.fill") }
                    .auButton(.secondary, .small, fullWidth: true)
                Button { model.confirmStopAll() } label: { Label(model.t("nat.run.stop_all"), systemImage: "stop.fill") }
                    .auButton(.secondary, .small, fullWidth: true)
            }
        } else if q.paused {
            ActivityCard(kind: model.t("nat.run.card_paused"),
                         line: Text(model.t("nat.run.card_paused_line", ["i": q.position ?? 1, "n": q.total ?? 1,
                                                                        "pct": Int(((live?.fraction ?? 0) * 100).rounded())])),
                         fraction: fraction, paused: true) {
                Button { model.command("queue.resume") } label: { Label(model.t("nat.run.resume"), systemImage: "play.fill") }
                    .auButton(.secondary, .small, fullWidth: true)
                Button { model.confirmStopAll() } label: { Label(model.t("nat.run.stop_all"), systemImage: "stop.fill") }
                    .auButton(.secondary, .small, fullWidth: true)
            }
        } else {
            ActivityCard(kind: model.t("nat.tab.queue"),
                         line: Text(model.t("nat.run.processing_line", ["i": q.position ?? 1, "n": q.total ?? 1])
                                    + (q.finish.map { " · " + model.t("nat.run.ends_around", ["time": model.clockTime($0)]) } ?? "")),
                         fraction: fraction) {
                Button { model.command("queue.pause") } label: { Label(model.t("nat.run.pause"), systemImage: "pause.fill") }
                    .auButton(.secondary, .small, fullWidth: true)
                Button { model.confirmStopAll() } label: { Label(model.t("nat.run.stop_all"), systemImage: "stop.fill") }
                    .auButton(.secondary, .small, fullWidth: true)
            }
        }
    }
}


/// DS4 "Update · notice": the yellow card when a newer version is out.
struct UpdateCard: View {
    @Environment(AppModel.self) private var model
    var version: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(model.t("nat.side.update", ["version": version]), systemImage: "arrow.down.circle")
                .labelStyle(SmallIconLabel()).font(.system(size: 12, weight: .semibold))
            HStack(alignment: .firstTextBaseline) {
                UnderlineLink(model.t("nat.side.whats_new"), tone: .yellow) { open() }
                Spacer()
                Button(model.t("nat.side.install")) { open() }.auButton(.notice, .small)
            }
        }
        .foregroundStyle(AU.yellowText)
        .padding(.horizontal, 12).padding(.vertical, 10)
        .background(RoundedRectangle(cornerRadius: AU.Radius.card).fill(AU.yellowBg))
        .overlay(RoundedRectangle(cornerRadius: AU.Radius.card).strokeBorder(AU.yellowLine))
    }

    private func open() {
        NSWorkspace.shared.open(URL(string: model.updates?.url ?? "https://github.com/Interstellar0verdrive/AnimeUp/releases/latest")!)
    }
}
