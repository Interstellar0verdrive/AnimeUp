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
                Image(systemName: symbol).font(.system(size: 9, weight: .semibold))
            }
            Text(text)
        }
        .font(AUFont.smallNumbers)
        .foregroundStyle(tone.text)
        .padding(.horizontal, 8)
        .padding(.vertical, 1)
        .background(Capsule().fill(tone == .accent ? AU.sel : tone.background))
        .overlay(Capsule().strokeBorder(tone.line, lineWidth: 1))
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
    var centred: Bool
    @ViewBuilder var actions: () -> Actions

    public init(_ tone: AUTone, title: String? = nil, text: String, centred: Bool = false,
                @ViewBuilder actions: @escaping () -> Actions) {
        self.tone = tone
        self.title = title
        self.text = text
        self.centred = centred
        self.actions = actions
    }

    public var body: some View {
        HStack(alignment: centred ? .center : .top, spacing: 8) {
            Image(systemName: tone.noteSymbol)
                .symbolRenderingMode(.monochrome)
                .font(.system(size: 14))
                .frame(width: 18, height: 17)
                .frame(maxHeight: centred ? .infinity : nil, alignment: .top)
                .padding(.top, 1)
            VStack(alignment: .leading, spacing: 2) {
                if let title {
                    Text(title).fontWeight(.semibold)
                }
                Text(text).lineSpacing(3)
            }
            .font(.system(size: 12.5))
            .frame(maxWidth: .infinity, alignment: .leading)
            .fixedSize(horizontal: false, vertical: true)
            actions()
        }
        .foregroundStyle(tone.text)
        .padding(.vertical, 12)
        .padding(.horizontal, 14)
        .background(RoundedRectangle(cornerRadius: AU.Radius.field).fill(tone.background))
        .overlay(RoundedRectangle(cornerRadius: AU.Radius.field).strokeBorder(tone.line, lineWidth: 1))
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
            .padding(.vertical, 18)
            .padding(.horizontal, 20)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(RoundedRectangle(cornerRadius: AU.Radius.card).fill(AU.surface))
            .overlay(RoundedRectangle(cornerRadius: AU.Radius.card).strokeBorder(AU.line, lineWidth: 1))
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
            Image(systemName: symbol).font(.system(size: 15)).foregroundStyle(AU.text2)
                .frame(width: 20)
            Text(title).font(AUFont.sectionTitle).foregroundStyle(AU.text)
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
                    Image(systemName: item.symbol).font(.system(size: 16)).foregroundStyle(AU.text2)
                        .frame(width: 18)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(item.value).font(.system(size: 13, weight: .semibold)).foregroundStyle(AU.text)
                        Text(item.label).font(.system(size: 11)).foregroundStyle(AU.text3)
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
        .background(RoundedRectangle(cornerRadius: AU.Radius.field).fill(AU.raised))
        .overlay(RoundedRectangle(cornerRadius: AU.Radius.field).strokeBorder(AU.chipLine, lineWidth: 1))
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

    public init(_ steps: [Step], firstNumber: Int = 0) {
        self.steps = steps
        self.firstNumber = firstNumber
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                if index > 0 { Spacer(minLength: 8) }
                HStack(alignment: .center, spacing: 12) {
                    circle(step, number: firstNumber + index)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(step.title).font(.system(size: 13, weight: .semibold)).foregroundStyle(AU.text)
                        Text(step.detail).auSmall()
                            .fixedSize(horizontal: false, vertical: true)
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
                Image(systemName: "checkmark").font(.system(size: 12, weight: .semibold)).foregroundStyle(AU.greenText)
            } else {
                Circle().strokeBorder(AU.glassLine, lineWidth: 1)
                Text("\(number)").font(.system(size: 13, weight: .semibold, design: .monospaced))
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
    @State private var targeted = false
    @State private var fanned = false

    public init(title: String, buttonTitle: String, shortcut: String = "⌘O", primary: Bool,
                onOpen: @escaping () -> Void, onDrop: @escaping ([URL]) -> Void) {
        self.title = title
        self.buttonTitle = buttonTitle
        self.shortcut = shortcut
        self.primary = primary
        self.onOpen = onOpen
        self.onDrop = onDrop
    }

    public var body: some View {
        VStack(spacing: 12) {
            thumbs
            Text(title).font(.system(size: 13, weight: .medium)).foregroundStyle(AU.text)
            HStack(spacing: 8) {
                Button(buttonTitle, action: onOpen)
                    .auButton(primary ? .primary : .secondary, .regular)
                Text(shortcut).font(AUFont.smallNumbers).foregroundStyle(AU.text3)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background {
            RoundedRectangle(cornerRadius: AU.Radius.field)
                .fill(AU.inset)
                .overlay(
                    EllipticalGradient(colors: [targeted ? AU.sel : AU.soft, .clear],
                                       center: UnitPoint(x: 0.5, y: 0.4),
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
                    Image(systemName: "play.fill").font(.system(size: 9))
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
            self.leading = AnyView(Image(systemName: symbol).font(.system(size: 11)))
        } else {
            self.leading = paused
                ? AnyView(Image(systemName: "pause.fill").font(.system(size: 9)))
                : AnyView(Spinner(size: 11))
        }
        self.buttons = buttons
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                leading
                Text(kind).font(.system(size: 11, weight: .semibold))
            }
            .foregroundStyle(AU.primaryText)
            line.font(.system(size: 12)).foregroundStyle(AU.text).lineSpacing(2)
            if let fraction { AUBar(fraction) }
            if let footnote {
                Text(footnote).font(.system(size: 11)).foregroundStyle(AU.text2)
            }
            HStack(spacing: 6) { buttons() }
                .padding(.top, 4)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: AU.Radius.card).fill(AU.soft))
        .overlay(RoundedRectangle(cornerRadius: AU.Radius.card).strokeBorder(AU.softLine, lineWidth: 1))
    }
}

/// The ring spinner of the boards: accent arc on a soft ring.
public struct Spinner: View {
    var size: CGFloat
    @State private var turning = false

    public init(size: CGFloat = 14) { self.size = size }

    public var body: some View {
        ZStack {
            Circle().stroke(AU.softLine, lineWidth: size > 12 ? 2 : 1.6)
            Circle().trim(from: 0, to: 0.25)
                .stroke(AU.primary, style: StrokeStyle(lineWidth: size > 12 ? 2 : 1.6, lineCap: .round))
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
                if let symbol { Image(systemName: symbol).font(.system(size: 10, weight: .medium)) }
                Text(title)
                    .underline(true, color: tone.text.opacity(hover ? 1 : 0.55))
            }
            .font(.system(size: 12.5, weight: .medium))
            .foregroundStyle(tone.text)
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .pointerStyle(.link)
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
                    .font(.system(size: 14))
                    .foregroundStyle(selected ? AU.onPrimary : AU.text2)
                    .frame(width: 26, height: 26)
                    .background(RoundedRectangle(cornerRadius: 7).fill(selected ? AU.primary : .clear))
                VStack(alignment: .leading, spacing: 0) {
                    Text(title).font(.system(size: 13, weight: .semibold)).foregroundStyle(AU.text)
                    Text(subtitle).font(.system(size: 11)).foregroundStyle(AU.text2)
                }
                .lineLimit(1)
                Spacer(minLength: 0)
                switch trailing {
                case .none: EmptyView()
                case .done: Image(systemName: "checkmark").font(.system(size: 11, weight: .semibold)).foregroundStyle(AU.greenText)
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

// MARK: - Path field

/// A path in an inset, mono, truncating in the middle.
public struct PathField: View {
    var path: String
    var symbol: String

    public init(_ path: String, symbol: String = "externaldrive") {
        self.path = path
        self.symbol = symbol
    }

    public var body: some View {
        HStack(spacing: 8) {
            Image(systemName: symbol).font(.system(size: 11)).foregroundStyle(AU.text3)
            Text(path).font(AUFont.numbers).foregroundStyle(AU.textCode)
                .lineLimit(1).truncationMode(.middle)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 10)
        .frame(height: 28)
        .frame(maxWidth: .infinity)
        .background(RoundedRectangle(cornerRadius: AU.Radius.field).fill(AU.inset))
        .overlay(RoundedRectangle(cornerRadius: AU.Radius.field).strokeBorder(AU.line, lineWidth: 1))
        .help(path)
    }
}

/// A coloured dot, 7 pt, for one-line states ("Not done yet").
public struct StatusDot: View {
    var tone: AUTone
    public init(_ tone: AUTone) { self.tone = tone }
    public var body: some View { Circle().fill(tone.solid).frame(width: 7, height: 7) }
}
