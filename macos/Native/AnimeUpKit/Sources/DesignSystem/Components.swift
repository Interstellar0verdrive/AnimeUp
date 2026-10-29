import SwiftUI
import UniformTypeIdentifiers

/// The status colours, always used as text + tint + line together.
public enum AUTone: Sendable {
    case neutral, accent, green, yellow, red

    public var text: Color {
        switch self {
        case .neutral: AU.text2
        case .accent: AU.primaryText
        case .green: AU.greenText
        case .yellow: AU.yellowText
        case .red: AU.redText
        }
    }

    /// The note / chip background.
    public var background: Color {
        switch self {
        case .neutral: AU.chipBg
        case .accent: AU.soft
        case .green: AU.greenBg
        case .yellow: AU.yellowBg
        case .red: AU.redBg
        }
    }

    public var line: Color {
        switch self {
        case .neutral: AU.chipLine
        case .accent: AU.softLine
        case .green: AU.greenLine
        case .yellow: AU.yellowLine
        case .red: AU.redLine
        }
    }

    /// Tinted buttons inside a note.
    public var tint: Color {
        switch self {
        case .neutral: AU.glass
        case .accent: AU.sel
        case .green: AU.greenTint
        case .yellow: AU.yellowTint
        case .red: AU.redTint
        }
    }

    /// The solid dot / bar colour.
    public var solid: Color {
        switch self {
        case .neutral: AU.text3
        case .accent: AU.primary
        case .green: AU.green
        case .yellow: AU.yellow
        case .red: AU.red
        }
    }

    /// Notes always use the filled shapes.
    public var noteSymbol: String {
        switch self {
        case .neutral, .accent: "info.circle.fill"
        case .green: "checkmark.circle.fill"
        case .yellow: "exclamationmark.triangle.fill"
        case .red: "exclamationmark.octagon.fill"
        }
    }
}

// MARK: - Status chip (DS3)

/// Mono, lowercase, capsule. Colour plus a word: never colour alone.
public struct StatusChip: View {
    var text: String
    var tone: AUTone
    var symbol: String?

    public init(_ text: String, tone: AUTone = .neutral, symbol: String? = nil) {
        self.text = text
        self.tone = tone
        self.symbol = symbol
    }

    public var body: some View {
        HStack(spacing: 4) {
            if let symbol {
                Image(systemName: symbol).font(.system(size: 10))
            }
            Text(text)
        }
        // The font's own line box, centred in the chip's height: the fixed line box of
        // `auFont` puts its extra space above the text, which sat low (29 Oct).
        .font(AUFont.smallNumbers.font)
        .frame(height: AUFont.smallNumbers.lineHeight)
        .foregroundStyle(tone.text)
        .auBox(Capsule(), fill: tone == .accent ? AU.sel : tone.background, line: tone.line,
               padding: EdgeInsets(vertical: 1, horizontal: 8))
        .fixedSize()
    }
}

// MARK: - Note (DS3)

/// One shape for every message: tint, 1 pt line, 8 pt corners, 12/14 padding.
/// Icon, title, text and buttons all take the status colour.
public struct NoteView<Actions: View>: View {
    var tone: AUTone
    var title: String?
    var text: String
    /// Lines under the text, each with a bullet: the items the title counts (F6b's warnings).
    var bullets: [String]
    /// A line in semibold under the text: the question a note asks (F6e).
    var strong: String?
    /// A last line, a touch lighter (F6: the steps' times).
    var footnote: String?
    var centred: Bool
    @ViewBuilder var actions: () -> Actions

    public init(_ tone: AUTone, title: String? = nil, text: String, strong: String? = nil, bullets: [String] = [], footnote: String? = nil,
                centred: Bool = false, @ViewBuilder actions: @escaping () -> Actions) {
        self.tone = tone
        self.title = title
        self.text = text
        self.bullets = bullets
        self.strong = strong
        self.footnote = footnote
        self.centred = centred
        self.actions = actions
    }

    public var body: some View {
        // The buttons sit in the middle of the note's height; the symbol on the first
        // line of text, centred on its capitals.
        HStack(alignment: .center, spacing: 8) {
        HStack(alignment: centred ? .center : .firstTextBaseline, spacing: 8) {
            Image(systemName: tone.noteSymbol)
                .symbolRenderingMode(.monochrome)
                .auFont(14)
                .frame(width: 18, height: 17)
                .alignmentGuide(.firstTextBaseline) { $0[VerticalAlignment.center] + 4.5 }
            VStack(alignment: .leading, spacing: 2) {
                if let title {
                    Text(title).fontWeight(.semibold)
                }
                Text(text).lineSpacing(3)
                if let strong { Text(strong).fontWeight(.semibold) }
                if !bullets.isEmpty {
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(bullets, id: \.self) { b in
                            HStack(alignment: .firstTextBaseline, spacing: 7) { Text(verbatim: "•"); Text(b) }
                        }
                    }
                    // A little apart: the items the title counts (board F6b).
                    .padding(.top, 4)
                }
                // The note's own font, only fainter (board F6); after a list, a little apart again (F6b).
                if let footnote {
                    Text(verbatim: footnote).opacity(0.7)
                        .padding(.top, bullets.isEmpty ? 0 : 4)
                }
            }
            .auFont(12.5)
            .frame(maxWidth: .infinity, alignment: .leading)
            .fixedSize(horizontal: false, vertical: true)
        }
            actions()
        }
        .foregroundStyle(tone.text)
        .auBox(RoundedRectangle(cornerRadius: AU.Radius.field), fill: tone.background, line: tone.line,
               padding: EdgeInsets(vertical: 12, horizontal: 14))
        // As tall as its text: in a card with room to spare it would otherwise take
        // its share of it (the symbol's column reaches the note's full height).
        .fixedSize(horizontal: false, vertical: true)
    }
}

extension NoteView where Actions == EmptyView {
    public init(_ tone: AUTone, title: String? = nil, text: String) {
        self.init(tone, title: title, text: text, actions: { EmptyView() })
    }
}

// MARK: - Card

/// Rows, cards, panels: 10 pt corners, surface, 1 pt line, 18/20 padding.
public struct Card<Content: View>: View {
    var spacing: CGFloat
    @ViewBuilder var content: () -> Content

    public init(spacing: CGFloat = 14, @ViewBuilder content: @escaping () -> Content) {
        self.spacing = spacing
        self.content = content
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: spacing) { content() }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .auBox(RoundedRectangle(cornerRadius: AU.Radius.card), fill: AU.surface, line: AU.line,
                   padding: EdgeInsets(vertical: 18, horizontal: 20))
    }
}

/// A card title: 16 pt symbol in secondary, 15 semibold title.
public struct CardTitle<Trailing: View>: View {
    var symbol: String
    var title: String
    @ViewBuilder var trailing: () -> Trailing

    public init(_ title: String, symbol: String, @ViewBuilder trailing: @escaping () -> Trailing) {
        self.title = title
        self.symbol = symbol
        self.trailing = trailing
    }

    public var body: some View {
        HStack(spacing: 8) {
            Image(systemName: symbol).auFont(15).foregroundStyle(AU.text2)
                .frame(width: 20)
            Text(title).auFont(AUFont.sectionTitle).foregroundStyle(AU.text)
            Spacer(minLength: 0)
            trailing()
        }
    }
}

extension CardTitle where Trailing == EmptyView {
    public init(_ title: String, symbol: String) {
        self.init(title, symbol: symbol, trailing: { EmptyView() })
    }
}

// MARK: - Value strip (DS4)

/// A row of facts in one box, split by hairlines: icon, value, label.
public struct ValueStrip: View {
    public struct Item: Identifiable, Sendable {
        public var symbol: String
        public var value: String
        public var label: String
        public var id: String { symbol + value }

        public init(symbol: String, value: String, label: String) {
            self.symbol = symbol
            self.value = value
            self.label = label
        }
    }

    var items: [Item]

    public init(_ items: [Item]) { self.items = items }

    public var body: some View {
        HStack(spacing: 0) {
            ForEach(Array(items.enumerated()), id: \.offset) { index, item in
                if index > 0 { Rectangle().fill(AU.line).frame(width: 1) }
                HStack(spacing: 8) {
                    Image(systemName: item.symbol).auFont(16).foregroundStyle(AU.text2)
                        .frame(width: 18)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(item.value).auFont(13, .semibold).foregroundStyle(AU.text)
                        Text(item.label).auFont(11).foregroundStyle(AU.text3)
                    }
                    .lineLimit(1)
                    .fixedSize()
                }
                .padding(.vertical, 9)
                .padding(.horizontal, 10)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .fixedSize(horizontal: false, vertical: true)
        .auBox(RoundedRectangle(cornerRadius: AU.Radius.field), fill: AU.raised, line: AU.chipLine)
    }
}

// MARK: - Numbered steps (DS4)

/// How something works, in order. A line joins the 32 pt circles; a done
/// step turns green with a check.
public struct NumberedSteps: View {
    public struct Step: Identifiable, Sendable {
        public var title: String
        public var detail: String
        public var done: Bool
        public var id: String { title }

        public init(title: String, detail: String, done: Bool = false) {
            self.title = title
            self.detail = detail
            self.done = done
        }
    }

    var steps: [Step]
    var firstNumber: Int
    /// A drawing for each step, on its line at the right (board S1c); nil for none.
    var art: ((Int) -> AnyView)?
    /// The steps side by side, each drawing above its step: for a card much wider than tall.
    var inRow: Bool

    public init(_ steps: [Step], firstNumber: Int = 0, inRow: Bool = false, art: ((Int) -> AnyView)? = nil) {
        self.steps = steps
        self.firstNumber = firstNumber
        self.inRow = inRow
        self.art = art
    }

    public var body: some View {
        if inRow { row } else { column }
    }

    /// Side by side: drawing, then number and title, then the text in one paragraph.
    private var row: some View {
        HStack(alignment: .top, spacing: 24) {
            ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                VStack(alignment: .leading, spacing: 12) {
                    if let art { art(index) }
                    HStack(spacing: 10) {
                        circle(step, number: firstNumber + index)
                        Text(step.title).auFont(13, .semibold).foregroundStyle(AU.text)
                    }
                    // The texts' line breaks are for the column; here they wrap where they must.
                    BalancedParagraph(step.detail.replacingOccurrences(of: "\n", with: " "), style: AUFont.small)
                        .foregroundStyle(AU.text2)
                }
                .frame(maxWidth: .infinity, alignment: .topLeading)
            }
        }
    }

    private var column: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                if index > 0 { Spacer(minLength: 8) }
                HStack(alignment: .center, spacing: 12) {
                    circle(step, number: firstNumber + index)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(step.title).auFont(13, .semibold).foregroundStyle(AU.text)
                        // The text's own line breaks only while each line fits whole;
                        // otherwise one paragraph, wrapping where it must.
                        ViewThatFits(in: .horizontal) {
                            Text(step.detail).auSmall().fixedSize()
                            BalancedParagraph(step.detail.replacingOccurrences(of: "\n", with: " "), style: AUFont.small)
                                .foregroundStyle(AU.text2)
                        }
                    }
                    if let art {
                        Spacer(minLength: 16)
                        art(index)
                    }
                }
            }
        }
        .frame(maxHeight: 300)
        .background(alignment: .leading) {
            RoundedRectangle(cornerRadius: 1).fill(AU.line)
                .frame(width: 2)
                .padding(.vertical, 30)
                .padding(.leading, 15)
        }
    }

    @ViewBuilder
    private func circle(_ step: Step, number: Int) -> some View {
        ZStack {
            Circle().fill(AU.surface)
            if step.done {
                Circle().fill(AU.greenBg)
                Circle().strokeBorder(AU.greenLine, lineWidth: 1)
                Image(systemName: "checkmark").auFont(12, .semibold).foregroundStyle(AU.greenText)
            } else {
                Circle().strokeBorder(AU.glassLine, lineWidth: 1)
                Text("\(number)").auFont(13, .semibold, mono: true)
                    .foregroundStyle(AU.text2)
            }
        }
        .frame(width: 32, height: 32)
    }
}

// MARK: - Drop zone (DS4)

/// Where files can be dropped; the button opens the same thing from the
/// keyboard. Dashed 1.5 pt border, inset fill with a soft accent glow, and
/// three fanned video cards that open when the view appears.
public struct DropZone: View {
    var title: String
    var buttonTitle: String
    var shortcut: String
    var primary: Bool
    var onOpen: () -> Void
    var onDrop: ([URL]) -> Void
    /// Horizontal (boards E0, F0): the cards, then title and `text`, the button on the right.
    var axis: Axis
    var text: String?
    @State private var targeted = false
    @State private var fanned = false

    public init(title: String, buttonTitle: String, shortcut: String = "⌘O", primary: Bool,
                axis: Axis = .vertical, text: String? = nil,
                onOpen: @escaping () -> Void, onDrop: @escaping ([URL]) -> Void) {
        self.axis = axis
        self.text = text
        self.title = title
        self.buttonTitle = buttonTitle
        self.shortcut = shortcut
        self.primary = primary
        self.onOpen = onOpen
        self.onDrop = onDrop
    }

    public var body: some View {
        Group {
            if axis == .vertical {
                VStack(spacing: 12) {
                    thumbs
                    VStack(spacing: 3) {
                        Text(title).auFont(13, .medium).foregroundStyle(AU.text)
                        if let text {
                            Text(text).auSmall().multilineTextAlignment(.center)
                                .frame(maxWidth: 420).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    openButton
                }
                .padding(16)
            } else {
                HStack(spacing: 14) {
                    thumbs
                    // The text takes the width the row has, the button stays on the right:
                    // with a spacer the text kept only its ideal width and wrapped narrow.
                    VStack(alignment: .leading, spacing: 3) {
                        Text(title).auFont(13, .medium).foregroundStyle(AU.text)
                        if let text { Text(text).auSmall().fixedSize(horizontal: false, vertical: true) }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.trailing, 2)
                    openButton
                }
                .padding(.vertical, 16).padding(.leading, 18).padding(.trailing, 26)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background {
            RoundedRectangle(cornerRadius: AU.Radius.field)
                .fill(AU.inset)
                .overlay(
                    EllipticalGradient(colors: [targeted ? AU.sel : AU.soft, .clear],
                                       center: axis == .vertical ? UnitPoint(x: 0.5, y: 0.4) : UnitPoint(x: 0.12, y: 0.5),
                                       startRadiusFraction: 0, endRadiusFraction: 0.7)
                        .clipShape(RoundedRectangle(cornerRadius: AU.Radius.field)))
        }
        .overlay(
            RoundedRectangle(cornerRadius: AU.Radius.field)
                .strokeBorder(targeted ? AU.primary : AU.boxLine,
                              style: StrokeStyle(lineWidth: 1.5, dash: [5, 4])))
        .onDrop(of: [.fileURL], isTargeted: $targeted) { providers in
            Task { @MainActor in
                var urls: [URL] = []
                for provider in providers {
                    if let url = try? await provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier) as? URL {
                        urls.append(url)
                    } else if let data = try? await provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier) as? Data,
                              let url = URL(dataRepresentation: data, relativeTo: nil) {
                        urls.append(url)
                    }
                }
                onDrop(urls)
            }
            return true
        }
        .onAppear {
            withAnimation(.timingCurve(0.2, 0.8, 0.2, 1, duration: 0.7).delay(0.25)) { fanned = true }
        }
    }

    private var openButton: some View {
        HStack(spacing: 8) {
            Button(buttonTitle, action: onOpen)
                .auButton(primary ? .primary : .secondary, .regular)
            Text(shortcut).auFont(AUFont.smallNumbers).foregroundStyle(AU.text3)
        }
    }

    private var thumbs: some View {
        ZStack {
            thumb(width: 76, height: 52, front: false)
                .rotationEffect(.degrees(fanned ? -9 : 0))
                .offset(x: fanned ? -48 : -10, y: 9)
            thumb(width: 76, height: 52, front: false)
                .rotationEffect(.degrees(fanned ? 9 : 0))
                .offset(x: fanned ? 48 : 10, y: 9)
            thumb(width: 96, height: 66, front: true)
        }
        .frame(width: 200, height: 96)
    }

    private func thumb(width: CGFloat, height: CGFloat, front: Bool) -> some View {
        RoundedRectangle(cornerRadius: 8)
            .fill(LinearGradient(colors: [AU.raised, AU.surface], startPoint: .topLeading, endPoint: .bottomTrailing))
            .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(front ? AU.softLine : AU.glassLine, lineWidth: 1))
            .overlay {
                if front {
                    Image(systemName: "play.fill").auFont(9)
                        .foregroundStyle(AU.onPrimary)
                        .offset(x: 1)
                        .frame(width: 22, height: 22)
                        .background(Circle().fill(AU.primary))
                }
            }
            .overlay(alignment: .bottom) {
                Capsule().fill(AU.trackSoft).frame(height: 3)
                    .overlay(alignment: .leading) {
                        GeometryReader { g in
                            Capsule().fill(AU.primary).frame(width: front ? g.size.width * 0.6 : 0)
                        }
                    }
                    .padding(.horizontal, 8)
                    .padding(.bottom, 7)
            }
            .frame(width: width, height: height)
            .shadow(color: .black.opacity(0.25), radius: 8, y: 6)
    }
}

// MARK: - Progress bar

/// 4 pt (sidebar, rows) or 6 pt (Compare, calibration speeds) bar.
public struct AUBar: View {
    var fraction: Double
    var height: CGFloat
    var fill: Color
    var track: Color

    public init(_ fraction: Double, height: CGFloat = 4, fill: Color = AU.primary, track: Color = AU.trackSoft) {
        self.fraction = fraction
        self.height = height
        self.fill = fill
        self.track = track
    }

    public var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule().fill(track)
                Capsule().fill(fill).frame(width: max(0, min(1, fraction)) * g.size.width)
            }
        }
        .frame(height: height)
        .clipShape(Capsule())
    }
}

// MARK: - Activity card (DS4)

/// One card at the bottom of the sidebar for whatever keeps AnimeUp busy:
/// queue, analysis, calibration. Soft accent tint.
public struct ActivityCard<Buttons: View>: View {
    var kind: String
    var line: Text
    var fraction: Double?
    var footnote: String?
    var leading: AnyView
    @ViewBuilder var buttons: () -> Buttons

    public init(kind: String, symbol: String? = nil, line: Text, fraction: Double?, footnote: String? = nil,
                paused: Bool = false, @ViewBuilder buttons: @escaping () -> Buttons) {
        self.kind = kind
        self.line = line
        self.fraction = fraction
        self.footnote = footnote
        if let symbol {
            self.leading = AnyView(Image(systemName: symbol).auFont(11))
        } else {
            self.leading = paused
                ? AnyView(Image(systemName: "pause.fill").auFont(9))
                : AnyView(Spinner(size: 11))
        }
        self.buttons = buttons
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                leading
                Text(kind).auFont(11, .semibold)
            }
            .foregroundStyle(AU.primaryText)
            line.auFont(12).foregroundStyle(AU.text).lineSpacing(2)
            if let fraction { AUBar(fraction) }
            if let footnote {
                Text(footnote).auFont(11).foregroundStyle(AU.text2)
            }
            HStack(spacing: 6) { buttons() }
                .padding(.top, 4)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .auBox(RoundedRectangle(cornerRadius: AU.Radius.card), fill: AU.soft, line: AU.softLine,
               padding: EdgeInsets(vertical: 12, horizontal: 12))
    }
}

/// The ring spinner of the boards: accent arc on a soft ring.
public struct Spinner: View {
    var size: CGFloat
    var tint: Color
    @State private var turning = false

    /// `tint` for a spinner on a coloured fill (the selected top-bar segment).
    public init(size: CGFloat = 14, tint: Color = AU.primary) {
        self.size = size
        self.tint = tint
    }

    public var body: some View {
        ZStack {
            Circle().stroke(tint == AU.primary ? AU.softLine : tint.opacity(0.3), lineWidth: size > 12 ? 2 : 1.6)
            Circle().trim(from: 0, to: 0.25)
                .stroke(tint, style: StrokeStyle(lineWidth: size > 12 ? 2 : 1.6, lineCap: .round))
                .rotationEffect(.degrees(turning ? 360 : 0))
        }
        .frame(width: size, height: size)
        .onAppear {
            withAnimation(.linear(duration: 1).repeatForever(autoreverses: false)) { turning = true }
        }
    }
}

// MARK: - Underlined link (DS4)

/// Secondary actions inside text, notes, cards: underlined, in the colour of
/// what surrounds them. Never the main action.
public struct UnderlineLink: View {
    var title: String
    var tone: AUTone
    var symbol: String?
    var action: () -> Void
    @State private var hover = false

    public init(_ title: String, tone: AUTone = .accent, symbol: String? = nil, action: @escaping () -> Void) {
        self.title = title
        self.tone = tone
        self.symbol = symbol
        self.action = action
    }

    public var body: some View {
        Button(action: action) {
            HStack(alignment: .firstTextBaseline, spacing: 5) {
                if let symbol { Image(systemName: symbol).auFont(10, .medium) }
                Text(title)
                    .underline(true, color: tone.text.opacity(hover ? 1 : 0.55))
            }
            .auFont(12.5, .medium)
            .foregroundStyle(tone.text)
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .auPointingHand()
    }
}

// MARK: - Sidebar tab (DS3)

/// Icon tile 26 pt, title 13 semibold, one status line. The current tab gets
/// the selection tint and an accent tile; work going on shows a spinner.
public struct SidebarTab: View {
    public enum Trailing: Sendable { case none, done, busy }

    var symbol: String
    var title: String
    var subtitle: String
    var selected: Bool
    var trailing: Trailing
    var action: () -> Void
    @State private var hover = false

    public init(symbol: String, title: String, subtitle: String, selected: Bool,
                trailing: Trailing = .none, action: @escaping () -> Void) {
        self.symbol = symbol
        self.title = title
        self.subtitle = subtitle
        self.selected = selected
        self.trailing = trailing
        self.action = action
    }

    public var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: symbol)
                    .auFont(14)
                    .foregroundStyle(selected ? AU.onPrimary : AU.text2)
                    .frame(width: 26, height: 26)
                    .background(RoundedRectangle(cornerRadius: 7).fill(selected ? AU.primary : .clear))
                VStack(alignment: .leading, spacing: 0) {
                    Text(title).auFont(13, .semibold).foregroundStyle(AU.text)
                    Text(subtitle).auFont(11).foregroundStyle(AU.text2)
                }
                .lineLimit(1)
                Spacer(minLength: 0)
                switch trailing {
                case .none: EmptyView()
                case .done: Image(systemName: "checkmark").auFont(11, .semibold).foregroundStyle(AU.greenText)
                case .busy: Spinner(size: 14)
                }
            }
            .padding(.vertical, 7)
            .padding(.horizontal, 10)
            .background(RoundedRectangle(cornerRadius: 9).fill(selected ? AU.sel : hover ? AU.glass : .clear))
            .contentShape(RoundedRectangle(cornerRadius: 9))
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

// MARK: - Top bar segment (board N1)

/// One page in the top bar's segmented control: 12 pt symbol and 12.5 pt title,
/// 24 pt tall; the current one filled with the accent. Work going on shows a
/// spinner, a count (the Queue's files) a small number.
public struct TopBarSegment: View {
    var symbol: String
    var title: String
    var selected: Bool
    var busy: Bool
    var count: Int?
    var action: () -> Void
    @State private var hover = false

    public init(symbol: String, title: String, selected: Bool, busy: Bool = false, count: Int? = nil,
                action: @escaping () -> Void) {
        self.symbol = symbol
        self.title = title
        self.selected = selected
        self.busy = busy
        self.count = count
        self.action = action
    }

    public var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Image(systemName: symbol).auFont(12)
                Text(title).auFont(12.5, selected ? .semibold : .regular).lineLimit(1)
                // The number stays while the Queue works: the spinner joins it, never replaces it.
                if let count {
                    // DS3 "Top bar": a neutral capsule, glass on the bar, a darker veil on the current segment.
                    Text("\(count)").auFont(10, .semibold, mono: true)
                        .foregroundStyle(selected ? AU.onPrimary : AU.text2)
                        .padding(.horizontal, 5)
                        .frame(minWidth: 16, minHeight: 16)
                        .background(Capsule().fill(selected ? Color.black.opacity(0.18) : AU.glass))
                        .overlay(Capsule().strokeBorder(selected ? .clear : AU.glassLine))
                }
                if busy { Spinner(size: 10, tint: selected ? AU.onPrimary : AU.primary) }
            }
            .foregroundStyle(selected ? AU.onPrimary : AU.text2)
            .padding(.leading, 12)
            .padding(.trailing, count != nil || busy ? 8 : 12)
            .frame(height: 24)
            .background(RoundedRectangle(cornerRadius: 7).fill(selected ? AU.primary : hover ? AU.glassHover : .clear))
            .contentShape(RoundedRectangle(cornerRadius: 7))
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

/// A small choice between two or three views of the same thing (board C6: the
/// player's fit or 1:1): 22 pt segments, 6 pt corners in an 8 pt glass track.
public struct AUMiniSegments: View {
    public struct Option {
        var label: AnyView
        var help: String
        var selected: Bool
        var action: () -> Void
        public init(_ label: some View, help: String, selected: Bool, action: @escaping () -> Void) {
            self.label = AnyView(label)
            self.help = help
            self.selected = selected
            self.action = action
        }
    }

    var options: [Option]
    /// Every segment this wide, when given: an icon and "1:1" side by side look alike.
    var segmentWidth: CGFloat?
    public init(_ options: [Option], segmentWidth: CGFloat? = nil) {
        self.options = options
        self.segmentWidth = segmentWidth
    }

    public var body: some View {
        HStack(spacing: 2) {
            ForEach(Array(options.enumerated()), id: \.offset) { _, o in
                Button(action: o.action) {
                    // The semibold width held in place: choosing doesn't nudge the segments.
                    ZStack {
                        o.label.auFont(12, .semibold).hidden()
                        o.label.auFont(12, o.selected ? .semibold : .regular)
                    }
                        .foregroundStyle(o.selected ? AU.onPrimary : AU.text2)
                        .padding(.horizontal, segmentWidth == nil ? 9 : 0)
                        .frame(width: segmentWidth, height: 22)
                        .background(RoundedRectangle(cornerRadius: 6).fill(o.selected ? AU.primary : .clear))
                        .contentShape(RoundedRectangle(cornerRadius: 6))
                        .auHover(RoundedRectangle(cornerRadius: 6), enabled: !o.selected)
                }
                .buttonStyle(.plain)
                .help(o.help)
                .accessibilityLabel(o.help)
                .accessibilityAddTraits(o.selected ? .isSelected : [])
            }
        }
        .padding(2)
        .background(RoundedRectangle(cornerRadius: 8).fill(AU.glass))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(AU.glassLine))
    }
}

/// The track of the top bar's segments: 2 pt inset in glass, glass line.
public struct TopBarSegments<Content: View>: View {
    @ViewBuilder var content: () -> Content
    public init(@ViewBuilder content: @escaping () -> Content) { self.content = content }

    public var body: some View {
        HStack(spacing: 2) { content() }
            .padding(2)
            .background(RoundedRectangle(cornerRadius: 9).fill(AU.glass))
            .overlay(RoundedRectangle(cornerRadius: 9).strokeBorder(AU.glassLine))
    }
}

// MARK: - Path field

/// A path in an inset, mono, truncating in the middle.
public struct PathField: View {
    var path: String
    var symbol: String

    var height: CGFloat

    /// 28 pt in cards, 26 pt next to a small button (settings rows).
    public init(_ path: String, symbol: String = "externaldrive", height: CGFloat = 28) {
        self.path = path
        self.symbol = symbol
        self.height = height
    }

    public var body: some View {
        HStack(spacing: 8) {
            Image(systemName: symbol).auFont(11).foregroundStyle(AU.text3)
            Text(path).auFont(AUFont.numbers).foregroundStyle(AU.textCode)
                .lineLimit(1).truncationMode(.middle)
            Spacer(minLength: 0)
        }
        .frame(height: height - 2)
        .frame(maxWidth: .infinity)
        .auBox(RoundedRectangle(cornerRadius: AU.Radius.field), fill: AU.inset, line: AU.line,
               padding: EdgeInsets(vertical: 0, horizontal: 10))
        .help(path)
    }
}

/// A coloured dot, 7 pt, for one-line states ("Not done yet").
/// Board K3: a status line that opens its details. The dot, the text and a
/// chevron in the tone's text colour; the hover veil and the pointing hand.
public struct StatusLink: View {
    var title: String
    var tone: AUTone
    var help: String?
    /// 12 in a list of statuses (sidebar, Settings); 11 next to a label, at its size (Start).
    var size: CGFloat
    /// Work in progress: a spinner in place of the dot (a calibration running).
    var busy: Bool
    var action: () -> Void
    @State private var hover = false

    public init(_ title: String, tone: AUTone = .green, size: CGFloat = 12, busy: Bool = false, help: String? = nil,
                action: @escaping () -> Void) {
        self.title = title
        self.tone = tone
        self.size = size
        self.busy = busy
        self.help = help
        self.action = action
    }

    public var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                if busy { Spinner(size: size - 1) } else { StatusDot(tone) }
                Text(title).auFont(size).lineLimit(1)
                Image(systemName: "chevron.right").auFont(8, .semibold)
            }
            .foregroundStyle(tone.text)
            .padding(.horizontal, 4).padding(.vertical, 2)
            // Under the pointer, the tone's tint: the plain veil is too faint on a coloured line.
            .background(RoundedRectangle(cornerRadius: 6).fill(tone.background).opacity(hover ? 1 : 0))
            .contentShape(RoundedRectangle(cornerRadius: 6))
            .onHover { hover = $0 }
            .animation(.easeOut(duration: 0.12), value: hover)
        }
        .buttonStyle(.plain)
        .padding(.horizontal, -4)
        .auPointingHand()
        .help(help ?? "")
    }
}

public struct StatusDot: View {
    var tone: AUTone
    public init(_ tone: AUTone) { self.tone = tone }
    public var body: some View { Circle().fill(tone.solid).frame(width: 7, height: 7) }
}
