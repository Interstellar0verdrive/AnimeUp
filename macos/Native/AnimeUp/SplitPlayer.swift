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
        left.replaceCurrentItem(with: l.map { AVPlayerItem(url: $0) })
        right.replaceCurrentItem(with: r.map { AVPlayerItem(url: $0) })
        left.seek(to: t, toleranceBefore: .zero, toleranceAfter: .zero)
        right.seek(to: t, toleranceBefore: .zero, toleranceAfter: .zero)
        if playing { left.play(); right.play() }
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
        var split: CGFloat = 0.5 { didSet { needsLayout = true } }
        var oneToOne = false

        init(controller: SplitPlayerController) {
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
            line.backgroundColor = NSColor.white.withAlphaComponent(0.85).cgColor
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
            line.frame = CGRect(x: x - 0.5, y: 0, width: 1, height: bounds.height)
            CATransaction.commit()
        }
    }
}
