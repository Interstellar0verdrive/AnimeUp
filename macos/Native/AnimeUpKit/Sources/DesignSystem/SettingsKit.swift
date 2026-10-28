import SwiftUI

/// DS4 "Snapping slider": a few fixed values; dots mark them, the knob snaps
/// to the nearest, and the value under it lights up.
public struct SnapSlider<Value: Hashable>: View {
    var values: [Value]
    var label: (Value) -> String
    @Binding var selection: Value
    var width: CGFloat
    @Environment(\.isEnabled) private var enabled
    @State private var dragging: Int?

    public init(values: [Value], selection: Binding<Value>, width: CGFloat = 236,
                label: @escaping (Value) -> String) {
        self.values = values
        self._selection = selection
        self.width = width
        self.label = label
    }

    private var index: Int { dragging ?? values.firstIndex(of: selection) ?? 0 }

    public var body: some View {
        let steps = max(1, values.count - 1)
        let usable = width - 16
        VStack(alignment: .leading, spacing: 4) {
            ZStack(alignment: .leading) {
                Capsule().fill(AU.trackSoft).frame(height: 4).padding(.horizontal, 8)
                Capsule().fill(AU.primary)
                    .frame(width: usable * CGFloat(index) / CGFloat(steps), height: 4)
                    .padding(.leading, 8)
                ForEach(values.indices, id: \.self) { i in
                    Circle().fill(i <= index ? AU.primary : AU.trackSoft)
                        .frame(width: 5, height: 5)
                        .offset(x: 8 + usable * CGFloat(i) / CGFloat(steps) - 2.5)
                }
                Circle().fill(.white)
                    .frame(width: 16, height: 16)
                    .shadow(color: .black.opacity(0.45), radius: 1.5, y: 1)
                    .offset(x: usable * CGFloat(index) / CGFloat(steps))
            }
            .frame(width: width, height: 16)
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0)
                .onChanged { g in
                    guard enabled else { return }
                    let f = min(max((g.location.x - 8) / usable, 0), 1)
                    dragging = Int((f * CGFloat(steps)).rounded())
                }
                .onEnded { _ in
                    if let d = dragging, values.indices.contains(d) { selection = values[d] }
                    dragging = nil
                })
            ZStack(alignment: .leading) {
                ForEach(values.indices, id: \.self) { i in
                    Text(label(values[i]))
                        .font(.system(size: 10, weight: i == index ? .bold : .regular, design: .monospaced))
                        .foregroundStyle(i == index ? AU.text : AU.text3)
                        .fixedSize()
                        .frame(width: 60, alignment: i == 0 ? .leading : i == values.count - 1 ? .trailing : .center)
                        .offset(x: i == 0 ? 0 : i == values.count - 1 ? width - 60
                                : 8 + usable * CGFloat(i) / CGFloat(steps) - 30)
                }
            }
            .frame(width: width, height: 12, alignment: .leading)
        }
        .frame(width: width)
        .opacity(enabled ? 1 : 0.4)
        .animation(.easeOut(duration: 0.12), value: index)
    }
}

/// A group of settings rows: surface, 10 pt corners, hairlines between rows.
public struct SettingsGroup<Content: View>: View {
    var title: String?
    @ViewBuilder var content: () -> Content

    public init(_ title: String? = nil, @ViewBuilder content: @escaping () -> Content) {
        self.title = title
        self.content = content
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let title { Text(title).auLabel().padding(.leading, 4) }
            Group(subviews: content()) { subviews in
                VStack(spacing: 0) {
                    ForEach(Array(subviews.enumerated()), id: \.offset) { index, sub in
                        if index > 0 { Rectangle().fill(AU.line).frame(height: 1) }
                        sub
                    }
                }
            }
                .background(RoundedRectangle(cornerRadius: AU.Radius.card).fill(AU.surface))
                .overlay(RoundedRectangle(cornerRadius: AU.Radius.card).strokeBorder(AU.line))
        }
    }
}

/// One settings row: title, description ending in the accent "Default: …",
/// and the control on the right.
public struct SettingsRow<Control: View>: View {
    var title: String
    var description: String?
    var defaultText: String?
    @ViewBuilder var control: () -> Control

    public init(_ title: String, description: String? = nil, defaultText: String? = nil,
                @ViewBuilder control: @escaping () -> Control) {
        self.title = title
        self.description = description
        self.defaultText = defaultText
        self.control = control
    }

    public var body: some View {
        HStack(alignment: .center, spacing: 16) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.system(size: 13, weight: .medium)).foregroundStyle(AU.text)
                if description != nil || defaultText != nil {
                    Text(describe)
                        .font(.system(size: 12)).lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            control()
        }
        .padding(.vertical, 11)
        .padding(.horizontal, 14)
    }

    private var describe: AttributedString {
        var out = AttributedString(description ?? "")
        out.foregroundColor = AU.text2
        if let defaultText {
            var d = AttributedString((description == nil ? "" : " ") + defaultText)
            d.foregroundColor = AU.primaryText
            out += d
        }
        return out
    }
}

/// A capsule segmented control drawn like DS3 (System · Light · Dark).
public struct CapsuleSegments<Value: Hashable>: View {
    var options: [(Value, String)]
    @Binding var selection: Value

    public init(_ options: [(Value, String)], selection: Binding<Value>) {
        self.options = options
        self._selection = selection
    }

    public var body: some View {
        HStack(spacing: 0) {
            ForEach(options.indices, id: \.self) { i in
                let on = options[i].0 == selection
                Button { selection = options[i].0 } label: {
                    Text(options[i].1).font(.system(size: 12, weight: on ? .medium : .regular))
                        .foregroundStyle(on ? AU.text : AU.text2)
                        .padding(.horizontal, 14).padding(.vertical, 3)
                        .background(Capsule().fill(on ? AU.segOn : .clear)
                            .shadow(color: .black.opacity(on ? 0.4 : 0), radius: 1, y: 1))
                        .contentShape(Capsule())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(2)
        .background(Capsule().fill(AU.glass))
        .overlay(Capsule().strokeBorder(AU.glassLine))
    }
}
