import SwiftUI

// The window frame of the boards (screens.py `.win`, `.side`, `.main`): the
// page on `bg`, a floating sidebar panel inset 8 pt, its top row holding the
// window's own traffic lights and the Settings gear.

/// Measures of the window frame, by their names in screens.py.
public enum AUChrome {
    /// `.side`: width, inset from the window edge, inner padding, row gap.
    public static let sidebarWidth: CGFloat = 236
    public static let sidebarInset: CGFloat = 8
    public static let sidebarPadding = EdgeInsets(top: 12, leading: 10, bottom: 12, trailing: 10)
    public static let sidebarSpacing: CGFloat = 14
    /// The sidebar's top row: traffic lights on the left, gear on the right.
    public static let topRowHeight: CGFloat = 24
    public static let topRowPadding: CGFloat = 4
    /// `.main`: page padding.
    public static let page = EdgeInsets(top: 28, leading: 28, bottom: 28, trailing: 28)
    /// Below this window width the sidebar folds away (as the Streamlit app did).
    public static let collapseBelow: CGFloat = 1240
    /// The smallest window: the pages are laid out for it.
    public static let minWindow = CGSize(width: 720, height: 640)
    /// Width the traffic lights take in the top row (three 14 pt buttons, 6 pt apart).
    public static let lightsWidth: CGFloat = 54
}

/// Where the traffic lights go, in window coordinates (top-left origin).
public struct TrafficLightsAnchor: PreferenceKey {
    public static let defaultValue: CGRect? = nil
    public static func reduce(value: inout CGRect?, nextValue: () -> CGRect?) { value = nextValue() ?? value }
}

/// A gap for the window's traffic lights, which report its place so the
/// window can move its real buttons there.
public struct TrafficLightsSlot: View {
    public init() {}

    public var body: some View {
        Color.clear
            .frame(width: AUChrome.lightsWidth, height: AUChrome.topRowHeight)
            .background(GeometryReader { g in
                Color.clear.preference(key: TrafficLightsAnchor.self, value: g.frame(in: .global))
            })
    }
}

/// `.side`: the floating sidebar panel. `side` over `bg`, a hairline and a soft shadow.
public struct SidebarPanel<Content: View>: View {
    @ViewBuilder var content: () -> Content

    public init(@ViewBuilder content: @escaping () -> Content) { self.content = content }

    public var body: some View {
        VStack(alignment: .leading, spacing: AUChrome.sidebarSpacing) { content() }
            .frame(maxHeight: .infinity, alignment: .top)
            .auBox(RoundedRectangle(cornerRadius: AU.Radius.sidebar), fill: AU.side, line: AU.glassLine,
                   padding: AUChrome.sidebarPadding)
            .frame(width: AUChrome.sidebarWidth)
            .background { OuterShadow(cornerRadius: AU.Radius.sidebar, opacity: 0.35, blur: 24, y: 8) }
    }
}

/// A CSS `box-shadow`: drawn only outside the shape, so a see-through fill
/// on top doesn't let it darken the panel (SwiftUI's shadow sits under it).
public struct OuterShadow: View {
    var cornerRadius: CGFloat
    var opacity: Double
    /// CSS blur radius; SwiftUI's shadow radius is half of it.
    var blur: CGFloat
    var y: CGFloat

    public init(cornerRadius: CGFloat, opacity: Double, blur: CGFloat, y: CGFloat) {
        self.cornerRadius = cornerRadius
        self.opacity = opacity
        self.blur = blur
        self.y = y
    }

    public var body: some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius)
        shape.fill(.black)
            .shadow(color: .black.opacity(opacity), radius: blur / 2, y: y)
            .mask {
                Rectangle().padding(-(blur + abs(y)) * 2)
                    .overlay(shape.blendMode(.destinationOut))
                    .compositingGroup()
            }
    }
}

/// The 26 pt round tool button of the sidebar's top row (the Settings gear).
public struct ChromeIconButton: View {
    var symbol: String
    var help: String
    var action: () -> Void
    @State private var hover = false

    public init(_ symbol: String, help: String, action: @escaping () -> Void) {
        self.symbol = symbol
        self.help = help
        self.action = action
    }

    public var body: some View {
        Button(action: action) {
            Image(systemName: symbol)
                .auFont(13)
                .foregroundStyle(AU.text)
                .frame(width: 26, height: 26)
                .background(Circle().fill(hover ? AU.glassHover : AU.glass))
                .overlay(Circle().strokeBorder(AU.glassLine, lineWidth: 1))
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .help(help)
        .accessibilityLabel(help)
    }
}

extension EnvironmentValues {
    /// The pages' top padding (`.main` 28 pt). Under the top bar (board N1) it is
    /// smaller: the page title's line box puts its capitals 11 pt below its top,
    /// and from the bar's hairline the gap must look like the 28 pt at the sides.
    @Entry public var auPageTop: CGFloat = 28
}

/// A page's title and its intro: the intro's two lines (of similar length, the
/// second slightly longer) while each fits whole, otherwise one paragraph.
public struct PageHeader<Trailing: View>: View {
    var title: String
    var line1: String
    var line2: String
    @ViewBuilder var trailing: () -> Trailing

    public init(_ title: String, _ line1: String, _ line2: String, @ViewBuilder trailing: @escaping () -> Trailing) {
        self.title = title
        self.line1 = line1
        self.line2 = line2
        self.trailing = trailing
    }

    public var body: some View {
        HStack(alignment: .bottom, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text(title).auPageTitle()
                ViewThatFits(in: .horizontal) {
                    Text(line1 + "\n" + line2).auBody().fixedSize()
                    Text(line1 + " " + line2).auBody().fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            trailing()
        }
    }
}

extension PageHeader where Trailing == EmptyView {
    public init(_ title: String, _ line1: String, _ line2: String) {
        self.init(title, line1, line2) { EmptyView() }
    }
}
