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
            // The activity card slot: queue, Compare test or calibration
            // (later milestones). Empty while nothing runs.
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
            SidebarTab(symbol: "film.stack", title: model.t("nat.tab.queue"), subtitle: model.t("nat.tab.queue_sub"),
                       selected: model.tab == .queue) { model.tab = .queue }
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
            if c.running {
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
            Text(model.t("nat.side.version", ["version": model.hello?.version ?? "…"]))
                .font(AUFont.smallNumbers).foregroundStyle(AU.text3)
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
