import AppKit
import SwiftUI

// Colour tokens of the design system (boards DS1–DS4, generator ds/gen.py,
// dict `V`). Dark first: the dark value is the approved one; the light value
// is the generator's light set, used once light screens are approved.

extension Color {
    /// A colour that follows the appearance: `dark` in Dark Mode, `light` otherwise.
    public init(dark: String, light: String) {
        let darkColor = NSColor(css: dark)
        let lightColor = NSColor(css: light)
        self.init(nsColor: NSColor(name: nil) { appearance in
            let match = appearance.bestMatch(from: [.darkAqua, .aqua, .vibrantDark, .vibrantLight])
            let isDark = match == .darkAqua || match == .vibrantDark
            return isDark ? darkColor : lightColor
        })
    }
}

extension NSColor {
    /// `#RRGGBB` or `rgba(r,g,b,a)`.
    public convenience init(css: String) {
        let s = css.trimmingCharacters(in: .whitespaces)
        if s.hasPrefix("#"), s.count == 7, let v = UInt32(s.dropFirst(), radix: 16) {
            self.init(srgbRed: CGFloat((v >> 16) & 0xFF) / 255, green: CGFloat((v >> 8) & 0xFF) / 255,
                      blue: CGFloat(v & 0xFF) / 255, alpha: 1)
            return
        }
        if s.hasPrefix("rgba("), s.hasSuffix(")") {
            let parts = s.dropFirst(5).dropLast().split(separator: ",").map {
                Double($0.trimmingCharacters(in: .whitespaces)) ?? 0
            }
            if parts.count == 4 {
                self.init(srgbRed: parts[0] / 255, green: parts[1] / 255, blue: parts[2] / 255, alpha: parts[3])
                return
            }
        }
        self.init(srgbRed: 1, green: 0, blue: 1, alpha: 1)
    }
}

/// The tokens, by their names on the boards.
public enum AU {
    // Surfaces, back to front
    public static let desk = Color(dark: "#2A2D33", light: "#D9DDE3")
    public static let bg = Color(dark: "#101113", light: "#F6F7F9")
    public static let side = Color(dark: "rgba(30,33,38,.78)", light: "rgba(236,238,241,.82)")
    public static let surface = Color(dark: "#16181B", light: "#FFFFFF")
    public static let raised = Color(dark: "#1C1F23", light: "#EEF0F2")
    /// Sheets and alerts (boards SHEET, K1, K2, O4, C5). Light value to be drawn with the light screens.
    public static let sheet = Color(dark: "#22252A", light: "#FFFFFF")
    /// AnimeUp's own alerts (boards O1–O3, edge.py `alert()`). Light value to be drawn with the light screens.
    public static let alert = Color(dark: "#26292E", light: "#FFFFFF")
    public static let surfaceHover = Color(dark: "#1C1F23", light: "#F3F4F6")
    public static let inset = Color(dark: "rgba(0,0,0,.25)", light: "rgba(0,0,0,.04)")
    public static let control = Color(dark: "#1C1F23", light: "#FFFFFF")
    public static let glass = Color(dark: "rgba(255,255,255,.07)", light: "rgba(0,0,0,.04)")
    public static let glassHover = Color(dark: "rgba(255,255,255,.11)", light: "rgba(0,0,0,.07)")
    public static let glassPress = Color(dark: "rgba(255,255,255,.15)", light: "rgba(0,0,0,.11)")
    public static let glassLine = Color(dark: "rgba(255,255,255,.10)", light: "rgba(0,0,0,.12)")
    public static let line = Color(dark: "#26292E", light: "#E1E4E8")
    public static let boxLine = Color(dark: "rgba(255,255,255,.22)", light: "rgba(0,0,0,.25)")

    // Text
    public static let text = Color(dark: "#E8EAED", light: "#16181B")
    public static let text2 = Color(dark: "#9BA1A9", light: "#5C626A")
    public static let text3 = Color(dark: "#80868E", light: "#656B73")
    public static let textCode = Color(dark: "#C6CBD2", light: "#3A3F46")

    // Accent
    public static let primary = Color(dark: "#2AC9DE", light: "#0895D8")
    public static let primaryHover = Color(dark: "#4FD5E7", light: "#1FA2E2")
    public static let primaryPress = Color(dark: "#1FB0C4", light: "#0784C0")
    public static let onPrimary = Color(dark: "#06252A", light: "#FFFFFF")
    public static let primaryText = Color(dark: "#2AC9DE", light: "#0A6E9E")
    public static let focus = Color(dark: "rgba(42,201,222,.5)", light: "rgba(8,149,216,.45)")
    public static let sel = Color(dark: "rgba(42,201,222,.16)", light: "rgba(8,149,216,.14)")
    public static let soft = Color(dark: "rgba(42,201,222,.07)", light: "rgba(8,149,216,.07)")
    public static let softLine = Color(dark: "rgba(42,201,222,.28)", light: "rgba(8,149,216,.28)")
    public static let track = Color(dark: "#2A2E34", light: "#DADDE2")
    public static let trackSoft = Color(dark: "rgba(255,255,255,.14)", light: "rgba(0,0,0,.10)")

    // Status
    public static let green = Color(dark: "#3DD68C", light: "#12A150")
    public static let greenText = Color(dark: "#7FE3AC", light: "#146C3E")
    public static let greenBg = Color(dark: "rgba(18,161,80,.12)", light: "#E6F5EC")
    public static let greenLine = Color(dark: "rgba(61,214,140,.35)", light: "rgba(18,161,80,.35)")
    public static let greenTint = Color(dark: "rgba(61,214,140,.16)", light: "rgba(18,161,80,.14)")
    public static let yellow = Color(dark: "#F2B84B", light: "#F5B400")
    public static let yellowHover = Color(dark: "#F5C76E", light: "#FFC21F")
    public static let yellowText = Color(dark: "#F5CB78", light: "#7F5300")
    public static let yellowBg = Color(dark: "#2A2110", light: "#FFF0C4")
    public static let yellowLine = Color(dark: "rgba(242,184,75,.45)", light: "rgba(245,180,0,.45)")
    public static let yellowTint = Color(dark: "rgba(242,184,75,.16)", light: "rgba(245,180,0,.22)")
    public static let onYellow = Color(dark: "#2A1C00", light: "#2A1C00")
    /// White on red reaches 5.0 : 1 (was 4.45, under AA), hover 4.6, pressed 6.1 (board CT1, approved 31 Oct).
    public static let red = Color(dark: "#CD3725", light: "#CD3725")
    public static let redHover = Color(dark: "#D83A27", light: "#D83A27")
    public static let redPress = Color(dark: "#B63121", light: "#B63121")
    public static let redText = Color(dark: "#F59B9B", light: "#B42323")
    public static let redBg = Color(dark: "rgba(242,109,109,.10)", light: "#FDECEA")
    public static let redBgPress = Color(dark: "rgba(242,109,109,.17)", light: "#FADAD6")
    public static let redLine = Color(dark: "rgba(242,109,109,.55)", light: "rgba(217,64,46,.45)")
    public static let redSoft = Color(dark: "rgba(242,109,109,.07)", light: "rgba(217,64,46,.05)")
    public static let redTint = Color(dark: "rgba(242,109,109,.16)", light: "rgba(217,64,46,.12)")

    public static let chipBg = Color(dark: "#1C1F23", light: "#EEF0F2")
    public static let chipLine = Color(dark: "rgba(255,255,255,.10)", light: "rgba(0,0,0,.08)")
    public static let segOn = Color(dark: "#3A3E44", light: "#FFFFFF")

    /// Corners (DS1): nested shapes get a smaller radius than their container.
    public enum Radius {
        public static let icon: CGFloat = 6
        public static let field: CGFloat = 8
        public static let card: CGFloat = 10
        public static let sidebar: CGFloat = 16
        public static let window: CGFloat = 22
    }
}

/// The eight text styles of DS1: SF Pro and SF Mono, whole points.
public enum AUFont {
    /// Page title · 24 bold, −1 % tracking (use `.auPageTitle()` for the tracking).
    public static let pageTitle = AUTextStyle(24, .bold)
    /// Section title · 15 semibold (card titles).
    public static let sectionTitle = AUTextStyle(15, .semibold)
    /// File name · 12 medium.
    public static let fileName = AUTextStyle(12, .medium)
    /// Body · 13 regular, line height 1.5 (`.p`).
    public static let body = AUTextStyle(13, leading: 1.5)
    /// Callout · 12 regular.
    public static let callout = AUTextStyle(12)
    /// Small paragraph · 12 regular, line height 1.45 (`.sm`).
    public static let small = AUTextStyle(12, leading: 1.45)
    /// Label · 11 semibold, tertiary.
    public static let label = AUTextStyle(11, .semibold)
    /// Numbers · 12 mono.
    public static let numbers = AUTextStyle(12, mono: true)
    /// Small numbers · 11 mono.
    public static let smallNumbers = AUTextStyle(11, mono: true)
}

extension View {
    public func auPageTitle() -> some View {
        auFont(AUFont.pageTitle).tracking(-0.24).foregroundStyle(AU.text)
    }

    /// Body text with the boards' 1.5 line height.
    public func auBody(_ color: Color = AU.text2) -> some View {
        auFont(AUFont.body).foregroundStyle(color)
    }

    /// The small paragraph style of the cards (12, line height 1.45).
    public func auSmall(_ color: Color = AU.text2) -> some View {
        auFont(AUFont.small).foregroundStyle(color)
    }

    public func auLabel(_ color: Color = AU.text3) -> some View {
        auFont(AUFont.label).foregroundStyle(color)
    }
}
