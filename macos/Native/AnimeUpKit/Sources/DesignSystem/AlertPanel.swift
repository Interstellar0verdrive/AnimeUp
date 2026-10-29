import AppKit
import SwiftUI

// Boards O1–O3 (edge.py `alert()`, one board per colour): AnimeUp's own
// alert, chosen over the native one on 2026-10-28. A 280 pt card, symbol at 40 pt in the
// status colour, centred title and text, buttons stacked at full width.
// `runModal()` is synchronous like NSAlert's, so it works inside
// applicationShouldTerminate too.

/// AnimeUp's own alert icons (drawn for boards O1–O3, 2026-10-28): 40 pt outline,
/// in the app's asset catalog as template images under "AlertIcons/".
public enum AlertIcon: String, Sendable {
    case stopFile = "stop-file", stopAll = "stop-all", discard, diskMissing = "disk-missing",
         folderReadonly = "folder-readonly", error
    case quit, calibrateLater = "calibrate-later", folderMove = "folder-move", folderEmpty = "folder-empty",
         folderInside = "folder-inside", folderBusy = "folder-busy"
    case update, windowClose = "window-close", info

    var image: Image { Image("AlertIcons/\(rawValue)", bundle: .main) }
}

/// What a button of the alert does.
public struct AUAlertButton {
    public var title: String
    public var role: AUButtonRole
    /// Esc presses it; the last button is the cancel button unless one says so.
    public var cancel: Bool

    public init(_ title: String, role: AUButtonRole = .secondary, cancel: Bool = false) {
        self.title = title
        self.role = role
        self.cancel = cancel
    }
}

@MainActor
public final class AUAlert {
    public var icon: AlertIcon
    public var tone: AUTone
    public var title: String
    public var texts: [String]
    public private(set) var buttons: [AUAlertButton] = []
    /// An optional "Don't show again" box under the buttons, and whether it was ticked.
    public var checkbox: String?
    public fileprivate(set) var checked = false

    public init(icon: AlertIcon, tone: AUTone, title: String, text: String) {
        self.icon = icon
        self.tone = tone
        self.title = title
        // One paragraph per line of the text, as on the boards.
        self.texts = text.split(separator: "\n", omittingEmptySubsequences: true).map(String.init)
    }

    /// The first button added is the default one (Return).
    public func button(_ title: String, role: AUButtonRole = .secondary, cancel: Bool = false) {
        buttons.append(AUAlertButton(title, role: role, cancel: cancel))
    }

    /// Shows the alert over the main window and returns the index of the button pressed.
    @discardableResult
    public func runModal() -> Int {
        let cancelIndex = buttons.lastIndex(where: \.cancel) ?? (buttons.count > 1 ? buttons.count - 1 : 0)
        let panel = AlertWindow(cancelIndex: cancelIndex)
        let card = AlertCard(alert: self) { index in NSApp.stopModal(withCode: .init(rawValue: 1000 + index)) }
        let host = NSHostingView(rootView: card.padding(AlertWindow.margin))
        host.frame.size = host.fittingSize
        panel.contentView = host
        panel.setContentSize(host.fittingSize)
        panel.place(over: NSApp.mainWindow ?? NSApp.keyWindow ?? NSApp.windows.first { $0.isVisible })
        panel.makeKeyAndOrderFront(nil)
        let response = NSApp.runModal(for: panel)
        panel.orderOut(nil)
        return max(0, response.rawValue - 1000)
    }
}

/// A borderless, see-through panel: the card draws its own shape and shadow.
final class AlertWindow: NSPanel {
    /// Room around the card for its 60 pt shadow.
    static let margin: CGFloat = 48
    let cancelIndex: Int

    init(cancelIndex: Int) {
        self.cancelIndex = cancelIndex
        super.init(contentRect: .zero, styleMask: [.borderless], backing: .buffered, defer: false)
        isOpaque = false
        backgroundColor = .clear
        hasShadow = false
        level = .modalPanel
        // Not movable by its background: a SwiftUI host lets AppKit start a window
        // drag on mouse-down, and the buttons never got the click (Stop and Cancel
        // did nothing, 29 Oct).
        isMovableByWindowBackground = false
    }

    override var canBecomeKey: Bool { true }

    override func cancelOperation(_ sender: Any?) {
        NSApp.stopModal(withCode: .init(rawValue: 1000 + cancelIndex))
    }

    /// Centred on the window, its top a third of the way down, as macOS places alerts.
    func place(over window: NSWindow?) {
        guard let window else { center(); return }
        let w = window.frame, s = frame.size
        setFrameOrigin(NSPoint(x: (w.midX - s.width / 2).rounded(), y: (w.maxY - w.height / 3 - s.height / 2).rounded()))
    }
}

struct AlertCard: View {
    let alert: AUAlert
    let press: (Int) -> Void
    @State private var checked = false
    /// 280 pt card, 1 pt line, 16 pt padding each side.
    static let textWidth: CGFloat = 280 - 2 - 32

    var body: some View {
        VStack(spacing: 8) {
            alert.icon.image
                .renderingMode(.template)
                .resizable().scaledToFit()
                .frame(width: 40, height: 40)
                .foregroundStyle(alert.tone.text)
                .padding(.bottom, 4)
            // Lines of similar length (text-wrap: balance on board O1), never a short last line.
            BalancedText(alert.title, style: AUTextStyle(14, .bold), maxWidth: Self.textWidth)
                .foregroundStyle(AU.text)
            ForEach(Array(alert.texts.enumerated()), id: \.offset) { _, text in
                BalancedText(text, style: AUTextStyle(12, leading: 1.45), maxWidth: Self.textWidth)
                    .foregroundStyle(AU.textCode)
            }
            VStack(spacing: 8) {
                ForEach(Array(alert.buttons.enumerated()), id: \.offset) { index, b in
                    let button = Button(b.title) { press(index) }
                        .buttonStyle(AUButtonStyle(b.role, size: .large, fullWidth: true))
                    if index == 0 { button.keyboardShortcut(.defaultAction) } else { button }
                }
            }
            .padding(.top, 6)
            if let title = alert.checkbox {
                AlertCheckbox(title: title, isOn: Binding(get: { checked }, set: { checked = $0; alert.checked = $0 }))
                    .padding(.top, 4)
            }
        }
        .frame(width: Self.textWidth)
        .auBox(RoundedRectangle(cornerRadius: 24), fill: AU.alert, line: AU.glassLine,
               padding: EdgeInsets(top: 20, leading: 16, bottom: 16, trailing: 16))
        .background { OuterShadow(cornerRadius: 24, opacity: 0.6, blur: 60, y: 24) }
    }
}

/// The suppression box under an alert's buttons (board O3, "AnimeUp keeps working").
struct AlertCheckbox: View {
    var title: String
    @Binding var isOn: Bool

    var body: some View {
        Button { isOn.toggle() } label: {
            HStack(spacing: 8) {
                ZStack {
                    if isOn {
                        RoundedRectangle(cornerRadius: 4).fill(AU.primary)
                        Image(systemName: "checkmark").auFont(9, .bold).foregroundStyle(AU.onPrimary)
                    } else {
                        RoundedRectangle(cornerRadius: 4).fill(AU.control)
                        RoundedRectangle(cornerRadius: 4).strokeBorder(AU.boxLine)
                    }
                }
                .frame(width: 15, height: 15)
                Text(title).auFont(12).foregroundStyle(AU.text2)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}
