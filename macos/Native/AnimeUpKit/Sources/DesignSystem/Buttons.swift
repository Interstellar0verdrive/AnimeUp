import SwiftUI

/// DS2: six roles, three sizes. A button is chosen by what it does, never by
/// where it sits. All capsules; label weight 500 (primary and notice 600);
/// icon on the left with a 5 pt gap; the label sits 1 pt higher for optical
/// centring. Hover only lightens the same fill; disabled is 40 %.
public enum AUButtonRole: Sendable {
    /// The one way forward in a view (at most one per view).
    case primary
    /// Everything else.
    case secondary
    /// Ends or throws away work: outline only.
    case destructive
    /// Only inside a confirmation alert.
    case destructiveSolid
    /// Only inside a yellow note.
    case notice
    /// No fill or border until hover.
    case plain
}

public enum AUButtonSize: Sendable {
    /// 32 pt: alerts and dialogs.
    case large
    /// 28 pt: page headers, panels, Settings.
    case regular
    /// 24 pt: file rows and the sidebar.
    case small

    var height: CGFloat { switch self { case .large: 32; case .regular: 28; case .small: 24 } }
    var padding: CGFloat { switch self { case .large: 18; case .regular: 14; case .small: 10 } }
    var fontSize: CGFloat { switch self { case .large: 13; case .regular: 12.5; case .small: 12 } }
    var iconSize: CGFloat { switch self { case .large: 12; case .regular: 11; case .small: 10 } }
}

public struct AUButtonStyle: ButtonStyle {
    var role: AUButtonRole
    var size: AUButtonSize
    var fullWidth: Bool
    /// Icon-only: a circle as tall as the size.
    var iconOnly: Bool

    public init(_ role: AUButtonRole = .secondary, size: AUButtonSize = .regular,
                fullWidth: Bool = false, iconOnly: Bool = false) {
        self.role = role
        self.size = size
        self.fullWidth = fullWidth
        self.iconOnly = iconOnly
    }

    public func makeBody(configuration: Configuration) -> some View {
        AUButtonBody(configuration: configuration, role: role, size: size,
                     fullWidth: fullWidth, iconOnly: iconOnly)
    }
}

struct AUButtonBody: View {
    let configuration: ButtonStyleConfiguration
    let role: AUButtonRole
    let size: AUButtonSize
    let fullWidth: Bool
    let iconOnly: Bool
    @State private var hover = false
    @Environment(\.isEnabled) private var enabled

    var body: some View {
        configuration.label
            .labelStyle(AULabelStyle(iconSize: size.iconSize, iconOnly: iconOnly))
            .auControlFont(size.fontSize, weight)
            .foregroundStyle(foreground)
            .lineLimit(1)
            // A button label never truncates: the row around it gives way instead.
            .fixedSize()
            .frame(width: iconOnly ? size.height - 2 : nil, height: size.height - 2)
            .frame(maxWidth: fullWidth ? .infinity : nil)
            .auBox(Capsule(), fill: fill, line: border,
                   padding: EdgeInsets(vertical: 0, horizontal: iconOnly ? 0 : (role == .plain ? 6 : size.padding)))
            .contentShape(Capsule())
            .opacity(enabled ? 1 : 0.4)
            .onHover { hover = $0 }
            .animation(.easeOut(duration: 0.12), value: hover)
    }

    private var weight: Font.Weight {
        role == .primary || role == .notice ? .semibold : .medium
    }

    private var pressed: Bool { configuration.isPressed && enabled }
    private var hovering: Bool { hover && enabled }

    private var fill: Color {
        switch role {
        case .primary: pressed ? AU.primaryPress : hovering ? AU.primaryHover : AU.primary
        case .secondary: pressed ? AU.glassPress : hovering ? AU.glassHover : AU.glass
        case .destructive: pressed ? AU.redBgPress : hovering ? AU.redBg : .clear
        case .destructiveSolid: pressed ? AU.redPress : hovering ? AU.redHover : AU.red
        case .notice: pressed ? AU.yellow : hovering ? AU.yellowHover : AU.yellow
        case .plain: pressed ? AU.glassPress : hovering ? AU.glass : .clear
        }
    }

    private var border: Color {
        switch role {
        case .secondary: AU.glassLine
        case .destructive: AU.redText
        default: .clear
        }
    }

    private var foreground: Color {
        switch role {
        case .primary: AU.onPrimary
        case .secondary: AU.text
        case .destructive: AU.redText
        case .destructiveSolid: .white
        case .notice: AU.onYellow
        case .plain: AU.text2
        }
    }
}

/// Icon then title, 5 pt apart; the title nudged up 1 pt.
struct AULabelStyle: LabelStyle {
    var iconSize: CGFloat
    var iconOnly: Bool

    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 5) {
            configuration.icon.auFont(iconSize, .medium)
            if !iconOnly {
                configuration.title
            }
        }
    }
}

/// A tinted button that sits inside a note (DS3): background and line from
/// the note's status colour.
public struct AUTintedButtonStyle: ButtonStyle {
    var tone: AUTone
    var size: AUButtonSize

    public init(_ tone: AUTone, size: AUButtonSize = .small) {
        self.tone = tone
        self.size = size
    }

    public func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .labelStyle(AULabelStyle(iconSize: size.iconSize, iconOnly: false))
            .auControlFont(size.fontSize, .medium)
            .foregroundStyle(tone.text)
            .frame(height: size.height - 2)
            .auBox(Capsule(), fill: tone.tint, line: tone.line, padding: EdgeInsets(vertical: 0, horizontal: size.padding))
            .auHover(Capsule())
            .opacity(configuration.isPressed ? 0.8 : 1)
            .contentShape(Capsule())
    }
}

extension View {
    /// Shorthand: `.auButton(.primary, .regular)`.
    public func auButton(_ role: AUButtonRole, _ size: AUButtonSize = .regular,
                         fullWidth: Bool = false) -> some View {
        buttonStyle(AUButtonStyle(role, size: size, fullWidth: fullWidth))
    }
}
