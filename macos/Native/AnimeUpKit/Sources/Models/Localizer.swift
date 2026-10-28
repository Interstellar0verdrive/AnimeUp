import Foundation
import Observation

/// The app's texts, from the same catalogs the engine uses:
/// `src/animeup/locales/<language>/*.json` (one file per area, the same keys
/// in every language). The native app's own texts live in `native.json`.
///
/// Works like `animeup.i18n.t`: a key that is missing in the active language
/// falls back to English, then to the key itself. Placeholders are Python
/// format fields (`{name}`); plurals are `<key>.uno` / `<key>.altri`.
///
/// Observable: views that call `t` redraw when `language` changes, so the
/// switch between English and Italian is live.
@Observable
public final class Localizer: @unchecked Sendable {
    public static let languages: [(code: String, name: String)] = [("en", "English"), ("it", "Italiano")]
    public static let fallback = "en"

    public private(set) var language: String
    private var catalogs: [String: [String: String]] = [:]
    @ObservationIgnored public let folder: URL?

    /// `folder` is the `locales` directory; nil gives a localiser that shows keys.
    public init(folder: URL?, language: String = Localizer.fallback) {
        self.folder = folder
        self.language = Self.languages.contains { $0.code == language } ? language : Self.fallback
        for (code, _) in Self.languages {
            catalogs[code] = folder.map { Self.load($0.appendingPathComponent(code)) } ?? [:]
        }
    }

    public func setLanguage(_ code: String) {
        let valid = Self.languages.contains { $0.code == code } ? code : Self.fallback
        if valid != language { language = valid }
    }

    /// The language to start in on first launch: macOS's, if it's one of ours.
    public static func systemLanguage() -> String {
        for preferred in Locale.preferredLanguages {
            let code = String(preferred.prefix(2))
            if languages.contains(where: { $0.code == code }) { return code }
        }
        return fallback
    }

    public func t(_ key: String, _ values: [String: Any] = [:]) -> String {
        let text = catalogs[language]?[key] ?? catalogs[Self.fallback]?[key] ?? key
        return Self.format(text, values)
    }

    public func tn(_ key: String, _ n: Int, _ values: [String: Any] = [:]) -> String {
        var all = values
        all["n"] = n
        return t("\(key).\(n == 1 ? "uno" : "altri")", all)
    }

    public func has(_ key: String) -> Bool { catalogs[Self.fallback]?[key] != nil }

    public func keys(_ code: String) -> Set<String> { Set(catalogs[code]?.keys ?? [:].keys) }

    /// `{name}` filled from `values`; `{{` and `}}` are literal braces.
    public static func format(_ text: String, _ values: [String: Any]) -> String {
        guard text.contains("{") || text.contains("}") else { return text }
        var out = ""
        var i = text.startIndex
        while i < text.endIndex {
            let c = text[i]
            let next = text.index(after: i)
            if c == "{", next < text.endIndex, text[next] == "{" {
                out.append("{"); i = text.index(after: next); continue
            }
            if c == "}", next < text.endIndex, text[next] == "}" {
                out.append("}"); i = text.index(after: next); continue
            }
            if c == "{", let close = text[next...].firstIndex(of: "}") {
                let field = String(text[next..<close])
                let name = field.split(separator: ":", maxSplits: 1).first.map(String.init) ?? field
                if let v = values[name] { out.append("\(v)") } else { out.append("{\(field)}") }
                i = text.index(after: close)
                continue
            }
            out.append(c)
            i = next
        }
        return out
    }

    static func load(_ folder: URL) -> [String: String] {
        var merged: [String: String] = [:]
        let files = (try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)) ?? []
        for file in files.filter({ $0.pathExtension == "json" }).sorted(by: { $0.lastPathComponent < $1.lastPathComponent }) {
            guard let data = try? Data(contentsOf: file),
                  let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
            for (k, v) in dict { if let s = v as? String { merged[k] = s } }
        }
        return merged
    }
}
