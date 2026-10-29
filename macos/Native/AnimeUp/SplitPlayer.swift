import AVFoundation
import AppKit
import SwiftUI

/// Two synchronised players, one over the other: the left version shows on
/// the left of the split, the right one on the right. Hovering moves the split;
/// a click doesn't jump it.
@MainActor
final class SplitPlayerController: ObservableObject {
    let left = AVPlayer()
    let right = AVPlayer()
    @Published var playing = false
    @Published var time: Double = 0
    @Published var duration: Double = 0
    @Published var oneToOne = false
    /// Where the split is, 0…1 across the picture.
    @Published var split: CGFloat = 0.5
    private var observer: Any?

    init() {
        left.isMuted = true
        right.isMuted = true
        left.actionAtItemEnd = .pause
        right.actionAtItemEnd = .pause
        observer = left.addPeriodicTimeObserver(forInterval: CMTime(value: 1, timescale: 20), queue: .main) { [weak self] t in
            MainActor.assumeIsolated {
                guard let self else { return }
                self.time = t.seconds
                if let d = self.left.currentItem?.duration.seconds, d.isFinite { self.duration = d }
                // Keep the right player on the left one's clock.
                let drift = abs(self.right.currentTime().seconds - t.seconds)
                if drift > 0.08 { self.right.seek(to: t, toleranceBefore: .zero, toleranceAfter: .zero) }
                if self.playing && self.left.rate == 0 && self.duration > 0 && t.seconds >= self.duration - 0.05 {
                    self.playing = false
                }
            }
        }
    }

    func load(left l: URL?, right r: URL?) {
        let t = left.currentTime()
        let items = (l.map { AVPlayerItem(url: $0) }, r.map { AVPlayerItem(url: $0) })
        left.replaceCurrentItem(with: items.0)
        right.replaceCurrentItem(with: items.1)
        // Show the frame and the length before anything plays: wait for the clip,
        // then seek both players (a paused player draws nothing until it seeks).
        Task { @MainActor in
            if let d = try? await (items.0 ?? items.1)?.asset.load(.duration), d.seconds.isFinite { duration = d.seconds }
            for item in [items.0, items.1].compactMap({ $0 }) {
                for await status in item.publisher(for: \.status).values where status != .unknown { break }
            }
            // A seek to where the player already is decodes nothing: start a hair after 0.
            let at = t.seconds.isFinite && t.seconds > 0 ? t : CMTime(value: 1, timescale: 600)
            await left.seek(to: at, toleranceBefore: .zero, toleranceAfter: .zero)
            await right.seek(to: at, toleranceBefore: .zero, toleranceAfter: .zero)
            time = at.seconds
            if playing { left.play(); right.play() }
        }
    }

    func toggle() {
        if playing {
            left.pause(); right.pause(); playing = false
        } else {
            if duration > 0 && time >= duration - 0.05 { seek(0) }
            left.play(); right.play(); playing = true
        }
    }

    func seek(_ seconds: Double) {
        let t = CMTime(seconds: seconds, preferredTimescale: 600)
        left.seek(to: t, toleranceBefore: .zero, toleranceAfter: .zero)
        right.seek(to: t, toleranceBefore: .zero, toleranceAfter: .zero)
        time = seconds
    }
}

struct SplitPlayerView: NSViewRepresentable {
    @ObservedObject var controller: SplitPlayerController

    func makeNSView(context: Context) -> SplitView { SplitView(controller: controller) }

    func updateNSView(_ view: SplitView, context: Context) {
        view.oneToOne = controller.oneToOne
        view.needsLayout = true
    }

    final class SplitView: NSView {
        let leftLayer: AVPlayerLayer
        let rightLayer: AVPlayerLayer
        let mask = CALayer()
        let line = CALayer()
        let controller: SplitPlayerController
        var split: CGFloat = 0.5 { didSet { needsLayout = true } }
        var oneToOne = false

        init(controller: SplitPlayerController) {
            self.controller = controller
            leftLayer = AVPlayerLayer(player: controller.left)
            rightLayer = AVPlayerLayer(player: controller.right)
            super.init(frame: .zero)
            wantsLayer = true
            layer?.backgroundColor = NSColor.black.cgColor
            layer?.masksToBounds = true
            layer?.addSublayer(leftLayer)
            layer?.addSublayer(rightLayer)
            mask.backgroundColor = NSColor.black.cgColor
            rightLayer.mask = mask
            line.backgroundColor = NSColor.white.cgColor
            line.shadowColor = NSColor.black.cgColor
            line.shadowOpacity = 0.5
            line.shadowRadius = 4
            line.shadowOffset = .zero
            layer?.addSublayer(line)
        }

        required init?(coder: NSCoder) { fatalError() }

        override func updateTrackingAreas() {
            super.updateTrackingAreas()
            trackingAreas.forEach(removeTrackingArea)
            addTrackingArea(NSTrackingArea(rect: bounds, options: [.mouseMoved, .activeInKeyWindow, .inVisibleRect],
                                           owner: self, userInfo: nil))
        }

        override func mouseMoved(with event: NSEvent) {
            let p = convert(event.locationInWindow, from: nil)
            split = min(1, max(0, p.x / max(1, bounds.width)))
            controller.split = split
        }

        override func layout() {
            super.layout()
            CATransaction.begin()
            CATransaction.setDisableActions(true)
            for l in [leftLayer, rightLayer] {
                if oneToOne, let size = l.player?.currentItem?.presentationSize, size.width > 0 {
                    let scale = window?.backingScaleFactor ?? 2
                    let w = size.width / scale, h = size.height / scale
                    l.frame = CGRect(x: (bounds.width - w) / 2, y: (bounds.height - h) / 2, width: w, height: h)
                    l.videoGravity = .resize
                } else {
                    l.frame = bounds
                    l.videoGravity = .resizeAspect
                }
            }
            let x = bounds.width * split
            let inRight = convert(CGPoint(x: x, y: 0), to: nil)
            _ = inRight
            mask.frame = CGRect(x: x - rightLayer.frame.minX, y: -rightLayer.frame.minY,
                                width: bounds.width, height: bounds.height + 2 * abs(rightLayer.frame.minY))
            line.frame = CGRect(x: x - 1, y: 0, width: 2, height: bounds.height)
            CATransaction.commit()
        }
    }
}

/// The split's handle and the L / R corner tags, drawn over the picture as
/// on board C4: a 28 pt white knob on the line, tags 10 pt in from the corners.
struct SplitPlayerChrome: View {
    @ObservedObject var controller: SplitPlayerController

    var body: some View {
        GeometryReader { g in
            ZStack {
                Text(verbatim: "‹ ›").auFont(11, .bold).foregroundStyle(Color(red: 0.086, green: 0.094, blue: 0.106))
                    .frame(width: 28, height: 28)
                    .background(Circle().fill(.white).shadow(color: .black.opacity(0.4), radius: 4, y: 2))
                    .position(x: g.size.width * controller.split, y: g.size.height / 2)
                corner("L").position(x: 10 + 9, y: g.size.height - 10 - 7.5)
                corner("R").position(x: g.size.width - 10 - 9, y: g.size.height - 10 - 7.5)
            }
        }
        .allowsHitTesting(false)
    }

    private func corner(_ side: String) -> some View {
        Text(side).auFont(10.5, .semibold, mono: true).foregroundStyle(.white)
            .padding(.horizontal, 6).padding(.vertical, 1)
            .background(RoundedRectangle(cornerRadius: 4).fill(.black.opacity(0.6)))
            .overlay(RoundedRectangle(cornerRadius: 4).stroke(.white.opacity(0.25), lineWidth: 1))
            .fixedSize()
    }
}
