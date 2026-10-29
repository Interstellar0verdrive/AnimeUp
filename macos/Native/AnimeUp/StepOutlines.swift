import DesignSystem
import SwiftUI

// Board S1c (ds/start_how.py): "How a batch goes" with a bare outline drawing
// for each step, at its right and on its line, in the style of E0 and F0.
// 160 × 44 units, drawn at 150 pt.

/// The drawing for step `index` (0 calibrate, 1 add videos, 2 compare, 3 queue).
struct StepOutline: View {
    var index: Int
    static let width: CGFloat = 150

    var body: some View {
        Canvas { ctx, size in
            let u = size.width / 160
            func r(_ x: Double, _ y: Double, _ w: Double, _ h: Double) -> CGRect { CGRect(x: x * u, y: y * u, width: w * u, height: h * u) }
            let line = StrokeStyle(lineWidth: 1.25, lineCap: .round, lineJoin: .round)
            let accent = StrokeStyle(lineWidth: 1.5, lineCap: .round, lineJoin: .round)
            func stroke(_ p: Path, on: Bool = false) {
                if on { ctx.fill(p, with: .color(AU.sel)) }
                ctx.stroke(p, with: .color(on ? AU.primary : AU.text3), style: on ? accent : line)
            }
            func text(_ x: Double, _ y: Double, _ w: Double) {
                ctx.fill(Path(roundedRect: r(x, y, w, 3), cornerRadius: 1.5 * u), with: .color(AU.text3.opacity(0.55)))
            }
            switch index {
            case 0:
                // Three speed rows, the first measured.
                for (i, (w, on)) in [(100.0, true), (64, false), (56, false)].enumerated() {
                    let y = 4 + Double(i) * 14
                    text(1, y + 1, 34)
                    ctx.stroke(Path(roundedRect: r(44, y, 110, 5), cornerRadius: 2.5 * u), with: .color(AU.text3), style: line)
                    ctx.fill(Path(roundedRect: r(44, y, w, 5), cornerRadius: 2.5 * u),
                             with: .color(on ? AU.primary : AU.text3.opacity(0.5)))
                }
            case 1:
                // Two files arriving, the first analysed.
                for (i, on) in [true, false].enumerated() {
                    let y = 2 + Double(i) * 21
                    stroke(Path(roundedRect: r(1, y, 158, 17), cornerRadius: 3 * u), on: on)
                    stroke(Path(ellipseIn: r(6.5, y + 5, 7, 7)), on: on)
                    text(20, y + 5, 56)
                    text(20, y + 10, 34)
                    stroke(Path(roundedRect: r(122, y + 4.5, 30, 8), cornerRadius: 4 * u), on: on)
                }
            case 2:
                // The split picture, its line in the accent, and three versions.
                stroke(Path(roundedRect: r(1, 1, 78, 42), cornerRadius: 4 * u))
                var hills = Path()
                hills.addLines([(6, 36), (22, 22), (32, 30), (48, 16), (62, 28), (74, 22)].map { CGPoint(x: $0.0 * u, y: $0.1 * u) })
                ctx.stroke(hills, with: .color(AU.text3), style: line)
                var split = Path()
                split.move(to: CGPoint(x: 44 * u, y: 1 * u)); split.addLine(to: CGPoint(x: 44 * u, y: 43 * u))
                ctx.stroke(split, with: .color(AU.primary), style: accent)
                stroke(Path(ellipseIn: r(40, 18, 8, 8)), on: true)
                for i in 0..<3 { stroke(Path(roundedRect: r(92, 4 + Double(i) * 14, 66, 10), cornerRadius: 3 * u), on: i == 0) }
            default:
                // A file being processed, chunk by chunk.
                stroke(Path(roundedRect: r(1, 4, 158, 22), cornerRadius: 4 * u))
                stroke(Path(ellipseIn: r(7, 11, 8, 8)), on: true)
                text(21, 11, 60)
                text(21, 17, 36)
                ctx.fill(Path(roundedRect: r(1, 33, 158, 4), cornerRadius: 2 * u), with: .color(AU.trackSoft))
                ctx.fill(Path(roundedRect: r(1, 33, 96, 4), cornerRadius: 2 * u), with: .color(AU.primary))
                for x in [40.0, 80, 120] { ctx.fill(Path(r(x, 32, 2.5, 6)), with: .color(AU.surface)) }
            }
        }
        .frame(width: Self.width, height: Self.width * 44 / 160)
    }
}
