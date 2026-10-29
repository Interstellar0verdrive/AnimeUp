import DesignSystem
import Models
import SwiftUI

/// Board N1: with the sidebar folded (a narrow window, or hidden from View), a
/// 52 pt row takes its place. Traffic lights on the left, the three pages as a
/// segmented control in the middle, on the right only what needs doing (a
/// calibration chip) and the Settings gear. Nothing covers the page.
struct TopBar: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openSettings) private var openSettings
    /// The window is wide enough for the sidebar: offer the button that brings it back.
    var canShowSidebar: Bool

    var body: some View {
        HStack(spacing: 8) {
            HStack(spacing: 16) {
                TrafficLightsSlot()
                if canShowSidebar {
                    ChromeIconButton("sidebar.left", help: model.t("nat.menu.show_sidebar")) { model.toggleSidebar() }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            TopBarSegments {
                TopBarSegment(symbol: "house", title: model.t("nat.tab.start"), selected: model.tab == .start) {
                    model.tab = .start
                }
                TopBarSegment(symbol: "rectangle.split.2x1", title: model.t("nat.tab.compare"),
                              selected: model.tab == .compare, busy: model.cmp.status?.running == true) {
                    model.tab = .compare
                }
                TopBarSegment(symbol: "film.stack", title: model.t("nat.tab.queue"), selected: model.tab == .queue,
                              busy: model.activity.running || (model.progress.queue.running && !model.progress.queue.paused),
                              count: model.files.isEmpty ? nil : model.files.count) {
                    model.tab = .queue
                }
            }
            .fixedSize()
            HStack(spacing: 8) {
                calibration
                ChromeIconButton("gearshape", help: model.t("nat.side.settings")) { openSettings() }
            }
            .frame(maxWidth: .infinity, alignment: .trailing)
        }
        // The lights' left edge and the gear's right edge on the page's 28 pt margins.
        .padding(.leading, 25)
        .padding(.trailing, 28)
        .frame(height: 52)
        // Where the bar ends and the page that scrolls under it begins.
        .overlay(alignment: .bottom) { Rectangle().fill(AU.line).frame(height: 1) }
    }

    /// Of the sidebar's "This Mac" only what needs doing: calibrating (it opens the sheet).
    @ViewBuilder
    private var calibration: some View {
        if let c = model.calibration {
            if c.running || model.calRun?.running == true {
                chip(model.t("nat.top.calibrating"), tone: .accent, busy: true) { model.showCalibration = true }
            } else if c.state == .never {
                chip(model.t("nat.top.not_calibrated"), tone: .yellow) { model.calibrate() }
            } else if c.state == .oldVersion || c.state == .otherMac {
                chip(model.t("nat.top.recalibrate"), tone: .yellow) { model.calibrate() }
            }
        }
    }

    private func chip(_ title: String, tone: AUTone, busy: Bool = false, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 6) {
                if busy { Spinner(size: 10) } else { StatusDot(tone) }
                Text(title).auFont(11.5).lineLimit(1)
            }
            .foregroundStyle(tone.text)
            .padding(.horizontal, 9)
            .frame(height: 24)
            .background(Capsule().fill(tone.background))
            .overlay(Capsule().strokeBorder(tone.line))
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .fixedSize()
    }
}
