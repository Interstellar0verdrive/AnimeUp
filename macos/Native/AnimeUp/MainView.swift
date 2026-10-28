import DesignSystem
import Models
import SwiftUI

struct MainView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow
    @State private var columns = NavigationSplitViewVisibility.all

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
        .alert(item: Binding(get: { model.alert }, set: { model.alert = $0 })) { alert in
            AlertBuilder.build(alert, model: model)
        }
    }

    private var split: some View {
        NavigationSplitView(columnVisibility: $columns) {
            SidebarView()
                .navigationSplitViewColumnWidth(min: 236, ideal: 236, max: 280)
                .toolbar(removing: .sidebarToggle)
        } detail: {
            ZStack {
                AU.bg.ignoresSafeArea()
                switch model.tab {
                case .start: StartView()
                case .compare: PlaceholderView(title: model.t("nat.tab.compare"), symbol: "rectangle.split.2x1",
                                               text: model.t("nat.compare.later"))
                case .queue: QueueView()
                }
            }
            .toolbar(.hidden, for: .windowToolbar)
        }
        .navigationSplitViewStyle(.balanced)
        .frame(minWidth: 1100, minHeight: 720)
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
            Image(systemName: symbol).font(.system(size: 64, weight: .ultraLight)).foregroundStyle(AU.line)
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
