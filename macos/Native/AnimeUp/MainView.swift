import DesignSystem
import Models
import SwiftUI

struct MainView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow
    @State private var lightsAnchor: CGRect?

    var body: some View {
        Group {
            if model.showsToolsWindow {
                ToolsSetupView()
                    .onAppear { WindowSizer.toTools() }
            } else {
                split
            }
        }
        .onAppear { model.reopenMainWindow = { openWindow(id: "main") } }
        .sheet(isPresented: Binding(get: { model.showCalibration }, set: { if !$0 { model.closeCalibration() } })) {
            CalibrationSheet().environment(model).preferredColorScheme(.dark)
        }
        .sheet(isPresented: Binding(get: { model.showCalibrationDetails }, set: { model.showCalibrationDetails = $0 })) {
            CalibrationDetailsSheet().environment(model).preferredColorScheme(.dark)
        }
        .sheet(isPresented: Binding(get: { model.showFinished && !model.showCalibration && !model.showCalibrationDetails },
                                    set: { if !$0 { model.markFinishedSeen() } })) {
            FinishedSheet().environment(model).preferredColorScheme(.dark)
        }
        .onChange(of: model.alert?.id) {
            guard let alert = model.alert else { return }
            log.info("alert: \(alert)")
            // After this update: the alert runs its own modal loop.
            DispatchQueue.main.async {
                model.alert = nil
                AlertBuilder.present(alert, model: model)
            }
        }
    }

    /// The boards' frame: the sidebar panel and the page on `bg`. Below
    /// `AUChrome.collapseBelow` the sidebar folds away and the top bar (board N1)
    /// takes its place; in a wide window it can also be hidden from View.
    private var split: some View {
        GeometryReader { g in
            let narrow = g.size.width < AUChrome.collapseBelow
            let inline = !narrow && (model.sidebarChoice ?? true)
            HStack(spacing: 0) {
                if inline {
                    sidebar.transition(.move(edge: .leading).combined(with: .opacity))
                }
                VStack(spacing: 0) {
                    if !inline { TopBar(canShowSidebar: !narrow) }
                    page.environment(\.auPageTop, inline ? 28 : 17).overlay(alignment: .top) {
                        // What scrolls under the top bar fades into it. At rest the page's
                        // own top padding is under the fade, so nothing shows.
                        if !inline {
                            LinearGradient(colors: [AU.bg, AU.bg.opacity(0)], startPoint: .top, endPoint: .bottom)
                                .frame(height: 18)
                                .allowsHitTesting(false)
                        }
                    }
                }
            }
            .onChange(of: narrow, initial: true) { _, now in model.sidebarNarrow = now }
            .onChange(of: inline, initial: true) { _, now in model.sidebarShown = now }
        }
        .background(AU.bg)
        .ignoresSafeArea()
        .background(WindowChrome(anchor: lightsAnchor, onClose: { model.windowClosed() }))
        .onPreferenceChange(TrafficLightsAnchor.self) { lightsAnchor = $0 }
        .animation(.easeOut(duration: 0.2), value: model.sidebarChoice)
        .frame(minWidth: AUChrome.minWindow.width, minHeight: AUChrome.minWindow.height)
    }

    private var sidebar: some View {
        SidebarView().padding([.leading, .top, .bottom], AUChrome.sidebarInset)
    }

    private var page: some View {
        ZStack {
            switch model.tab {
            case .start: StartView()
            case .compare: CompareView()
            case .queue: QueueView()
            }
        }
        // The page never sets the window's height: a wrapped text measured at
        // a narrow width would otherwise make the frame taller than the window.
        .frame(minWidth: 0, maxWidth: .infinity, minHeight: 0, maxHeight: .infinity)
        // Pages reach up under the title bar; with the sidebar folded, the top bar
        // sits there instead, and a scrolled page must not slide under it.
        .clipped()
    }
}

struct PlaceholderView: View {
    var title: String
    var symbol: String
    var text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).auPageTitle()
            Text(text).auBody()
            Spacer()
        }
        .padding(.horizontal, 28)
        .padding(.top, 28)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .overlay {
            Image(systemName: symbol).auFont(64, .ultraLight).foregroundStyle(AU.line)
        }
    }
}

/// The engine is starting, or didn't: shown in place of the Start cards.
struct EngineStatusView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(spacing: 14) {
            switch model.status {
            case .starting:
                Spinner(size: 22)
                Text(model.t("nat.engine.starting")).auBody(AU.text)
                Text(model.t("nat.engine.first")).auSmall()
            case .failed(let error):
                NoteView(.red, title: model.t("nat.engine.failed"), text: error) {
                    Button(model.t("nat.btn.retry")) { model.retry() }
                        .buttonStyle(AUTintedButtonStyle(.red))
                    Button(model.t("nat.btn.show_log")) { model.showLog() }
                        .buttonStyle(AUTintedButtonStyle(.red))
                }
                .frame(maxWidth: 560)
            case .gaveUp:
                NoteView(.red, title: model.t("nat.engine.failed"), text: model.t("nat.engine.gave_up")) {
                    Button(model.t("nat.btn.show_log")) { model.showLog() }
                        .buttonStyle(AUTintedButtonStyle(.red))
                }
                .frame(maxWidth: 560)
            case .ready:
                EmptyView()
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
