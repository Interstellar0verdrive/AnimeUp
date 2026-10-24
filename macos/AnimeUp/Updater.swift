// Updater.swift - installs a newer AnimeUp from the GitHub release.
//
// The interface only asks (it writes `<state>/update-request`); the
// app does the rest by itself and trusts nothing in that request: it asks
// GitHub for the latest release, downloads the app zip, checks it against the
// SHA256 GitHub publishes for that file, checks the app inside (identifier,
// version, signature), swaps it in place of this one and relaunches.
//
// Why this matters with an unsigned app: macOS asks for "Open Anyway" again
// for every new version downloaded with a browser, because the browser marks
// the file as quarantined. A file downloaded by the app itself carries no
// such mark, so an update installed this way opens without asking.

import AppKit
import CryptoKit

let releasesAPI = URL(string: "https://api.github.com/repos/Interstellar0verdrive/AnimeUp/releases/latest")!
let releasesPage = URL(string: "https://github.com/Interstellar0verdrive/AnimeUp/releases/latest")!

enum UpdateError: LocalizedError {
    case network(String)
    case noAsset
    case notNewer(String)
    case checksum(expected: String, found: String)
    case badPackage(String)
    case cannotReplace(String)

    var errorDescription: String? {
        switch self {
        case .network(let s):
            return tr("Couldn't reach GitHub: \(s)", "Impossibile raggiungere GitHub: \(s)")
        case .noAsset:
            return tr("The latest release has no app download.",
                      "L'ultima release non contiene l'app da scaricare.")
        case .notNewer(let v):
            return tr("AnimeUp is already up to date (latest release: \(v)).",
                      "AnimeUp è già aggiornato (ultima release: \(v)).")
        case .checksum(let expected, let found):
            return tr("The download doesn't match the checksum published on GitHub, so it was discarded.\n\nexpected \(expected)\nfound    \(found)",
                      "Il file scaricato non corrisponde al checksum pubblicato su GitHub ed è stato scartato.\n\natteso  \(expected)\ntrovato \(found)")
        case .badPackage(let s):
            return tr("The downloaded package isn't a valid AnimeUp app: \(s)",
                      "Il pacchetto scaricato non è un'app AnimeUp valida: \(s)")
        case .cannotReplace(let s):
            return s
        }
    }
}

struct Release {
    let version: String
    let zipURL: URL
    let sha256: String
    let size: Int
}

enum Updater {
    /// The file the interface writes when the user clicks "Install update".
    static func requestFile(state: URL) -> URL {
        state.appendingPathComponent("update-request")
    }

    /// Numeric comparison of "1.5.10" and "v1.5.2" style versions.
    static func isNewer(_ candidate: String, than current: String) -> Bool {
        func parts(_ v: String) -> [Int] {
            v.trimmingCharacters(in: CharacterSet(charactersIn: "v"))
                .split(separator: ".").map { Int($0) ?? 0 }
        }
        let a = parts(candidate), b = parts(current)
        for i in 0..<max(a.count, b.count) {
            let x = i < a.count ? a[i] : 0, y = i < b.count ? b[i] : 0
            if x != y { return x > y }
        }
        return false
    }

    /// Where this copy of the app can be replaced, or why it can't.
    static func replaceableLocation() -> Result<URL, UpdateError> {
        let app = Bundle.main.bundleURL
        if app.path.contains("/AppTranslocation/") {
            return .failure(.cannotReplace(tr(
                "AnimeUp is running from a temporary copy that macOS makes for apps that haven't been moved yet. Move AnimeUp.app into the Applications folder, open it from there, and try again.",
                "AnimeUp è in esecuzione da una copia temporanea che macOS crea per le app non ancora spostate. Sposta AnimeUp.app nella cartella Applicazioni, aprila da lì e riprova.")))
        }
        let folder = app.deletingLastPathComponent()
        guard FileManager.default.isWritableFile(atPath: folder.path) else {
            return .failure(.cannotReplace(tr(
                "This account can't write to \(folder.path), so AnimeUp can't replace itself. Download the new version from the release page instead.",
                "Questo utente non può scrivere in \(folder.path), quindi AnimeUp non può sostituirsi da solo. Scarica la nuova versione dalla pagina della release.")))
        }
        return .success(app)
    }

    /// The latest release and its app zip, as GitHub describes them.
    static func latestRelease() async throws -> Release {
        var request = URLRequest(url: releasesAPI, timeoutInterval: 20)
        request.setValue("AnimeUp/\(appVersion)", forHTTPHeaderField: "User-Agent")
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        let data: Data
        do {
            let (d, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, http.statusCode != 200 {
                throw UpdateError.network("HTTP \(http.statusCode)")
            }
            data = d
        } catch let e as UpdateError {
            throw e
        } catch {
            throw UpdateError.network(error.localizedDescription)
        }
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let tag = json["tag_name"] as? String,
              let assets = json["assets"] as? [[String: Any]] else {
            throw UpdateError.network(tr("unexpected answer", "risposta inattesa"))
        }
        guard let asset = assets.first(where: { ($0["name"] as? String)?.hasSuffix("-macos-app.zip") == true }),
              let link = (asset["browser_download_url"] as? String).flatMap(URL.init(string:)),
              let digest = asset["digest"] as? String, digest.hasPrefix("sha256:") else {
            throw UpdateError.noAsset
        }
        // Only from this project's own releases on GitHub.
        guard link.host == "github.com",
              link.path.hasPrefix("/Interstellar0verdrive/AnimeUp/releases/download/") else {
            throw UpdateError.noAsset
        }
        return Release(version: String(tag.drop(while: { $0 == "v" })), zipURL: link,
                       sha256: String(digest.dropFirst("sha256:".count)).lowercased(),
                       size: asset["size"] as? Int ?? 0)
    }

    /// Downloads, verifies and unpacks the release; returns the new AnimeUp.app.
    static func download(_ release: Release, into work: URL) async throws -> URL {
        let (tmp, response): (URL, URLResponse)
        do {
            (tmp, response) = try await URLSession.shared.download(from: release.zipURL)
        } catch {
            throw UpdateError.network(error.localizedDescription)
        }
        if let http = response as? HTTPURLResponse, http.statusCode != 200 {
            throw UpdateError.network("HTTP \(http.statusCode)")
        }
        let zip = work.appendingPathComponent("AnimeUp.zip")
        try? FileManager.default.removeItem(at: zip)
        try FileManager.default.moveItem(at: tmp, to: zip)

        let found = SHA256.hash(data: try Data(contentsOf: zip))
            .map { String(format: "%02x", $0) }.joined()
        guard found == release.sha256 else {
            throw UpdateError.checksum(expected: release.sha256, found: found)
        }

        let unpacked = work.appendingPathComponent("unpacked", isDirectory: true)
        try? FileManager.default.removeItem(at: unpacked)
        guard run("/usr/bin/ditto", ["-x", "-k", zip.path, unpacked.path]) == 0 else {
            throw UpdateError.badPackage(tr("it can't be unzipped", "non si scompatta"))
        }
        let app = unpacked.appendingPathComponent("AnimeUp.app", isDirectory: true)
        guard let info = NSDictionary(contentsOf: app.appendingPathComponent("Contents/Info.plist")),
              info["CFBundleIdentifier"] as? String == Bundle.main.bundleIdentifier else {
            throw UpdateError.badPackage(tr("wrong or missing app identifier",
                                            "identificativo dell'app mancante o diverso"))
        }
        guard info["CFBundleShortVersionString"] as? String == release.version else {
            throw UpdateError.badPackage(tr("its version doesn't match the release",
                                            "la versione non corrisponde alla release"))
        }
        guard run("/usr/bin/codesign", ["--verify", "--deep", "--strict", app.path]) == 0 else {
            throw UpdateError.badPackage(tr("its signature is broken", "la firma non è integra"))
        }
        return app
    }

    /// Puts `newApp` where this app is, keeping the old one aside until the
    /// new one is in place, and returns the old copy's temporary location.
    static func swap(current: URL, with newApp: URL) throws -> URL {
        let fm = FileManager.default
        let aside = current.deletingLastPathComponent()
            .appendingPathComponent(".AnimeUp-old-\(Int(Date().timeIntervalSince1970)).app")
        do {
            try fm.moveItem(at: current, to: aside)
        } catch {
            throw UpdateError.cannotReplace(tr("Couldn't move the current app aside: \(error.localizedDescription)",
                                               "Impossibile mettere da parte l'app attuale: \(error.localizedDescription)"))
        }
        do {
            try fm.moveItem(at: newApp, to: current)
        } catch {
            try? fm.moveItem(at: aside, to: current)          // put things back
            throw UpdateError.cannotReplace(tr("Couldn't install the new app: \(error.localizedDescription)",
                                               "Impossibile installare la nuova app: \(error.localizedDescription)"))
        }
        return aside
    }

    /// After this process quits: removes the old copy and opens the new app.
    static func relaunch(newApp: URL, oldCopy: URL) {
        let script = """
        while kill -0 \(getpid()) 2>/dev/null; do sleep 0.2; done
        rm -rf '\(oldCopy.path.replacingOccurrences(of: "'", with: "'\\''"))'
        open '\(newApp.path.replacingOccurrences(of: "'", with: "'\\''"))'
        """
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/sh")
        p.arguments = ["-c", script]
        try? p.run()
    }

    @discardableResult
    private static func run(_ tool: String, _ args: [String]) -> Int32 {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: tool)
        p.arguments = args
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do { try p.run() } catch { return -1 }
        p.waitUntilExit()
        return p.terminationStatus
    }
}
