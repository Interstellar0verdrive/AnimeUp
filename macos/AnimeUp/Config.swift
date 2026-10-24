// Config.swift - where AnimeUp lives on disk, which port it uses, which
// language it speaks.
//
// The .app bundle is treated as read-only (it gets replaced whole on every
// update), so everything AnimeUp downloads or generates goes elsewhere:
//
//   state  ~/Library/Application Support/AnimeUp   Python, venv, caches, bin/, logs/
//   data   ~/Movies/AnimeUp (or <state>/cartella_dati)   INPUT/OUTPUT/JOBS/registri
//
// The bash launcher learns both through ANIMEUP_STATO and ANIMEUP_ROOT.

import Foundation

/// The app's own port. Folder mode (`./animeup ui`) uses 8899, so both can
/// run side by side without stepping on each other.
let serverPort = 8898

/// Base URL of the local server. 127.0.0.1 and not "localhost": the server
/// only listens on IPv4 loopback, and "localhost" may resolve to ::1 first.
let serverURL = URL(string: "http://127.0.0.1:\(serverPort)/")!
let healthURL = URL(string: "http://127.0.0.1:\(serverPort)/_stcore/health")!

/// Hosts that are "us": navigation to anything else goes to the default browser.
let localHosts: Set<String> = ["127.0.0.1", "localhost", "::1", "[::1]"]

struct AppPaths {
    /// `Contents/Resources/AnimeUp`: the program (launcher, src/, ui/, ...).
    let program: URL
    /// `Contents/Resources/AnimeUp/animeup`: the bash launcher.
    let launcher: URL
    /// Per-user state folder (Python, venv, caches, downloaded tools, logs).
    let state: URL
    /// Per-user data folder (INPUT, OUTPUT, JOBS, registri).
    let data: URL
    /// `<state>/logs/app.log`: launcher and server output, appended.
    let logFile: URL
    /// The folder the user chose, when it isn't reachable now (an external
    /// drive that isn't connected): `data` is then the default folder, and
    /// the interface says so.
    let unavailableData: String?

    enum Failure: Error {
        case missingProgram(String)
        case cannotCreate(String, Error)
    }

    /// Works out every path and creates the state, log and data folders.
    static func resolve() throws -> AppPaths {
        let fm = FileManager.default
        guard let resources = Bundle.main.resourceURL else {
            throw Failure.missingProgram(Bundle.main.bundlePath)
        }
        let program = resources.appendingPathComponent("AnimeUp", isDirectory: true)
        let launcher = program.appendingPathComponent("animeup")
        guard fm.fileExists(atPath: launcher.path) else {
            throw Failure.missingProgram(launcher.path)
        }

        let support = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? fm.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support")
        let state = support.appendingPathComponent("AnimeUp", isDirectory: true)
        let logs = state.appendingPathComponent("logs", isDirectory: true)
        let (data, unavailable) = dataFolder(state: state)

        for dir in [state, logs, data] {
            do {
                try fm.createDirectory(at: dir, withIntermediateDirectories: true)
            } catch {
                throw Failure.cannotCreate(dir.path, error)
            }
        }
        return AppPaths(program: program, launcher: launcher, state: state, data: data,
                        logFile: logs.appendingPathComponent("app.log"),
                        unavailableData: unavailable)
    }

    /// The text of `<state>/cartella_dati`, the folder the user chose in the
    /// interface; nil when they never chose one.
    static func chosenDataFolder(state: URL) -> String? {
        let pointer = state.appendingPathComponent("cartella_dati")
        guard let text = try? String(contentsOf: pointer, encoding: .utf8) else { return nil }
        let line = text.split(whereSeparator: \.isNewline).first.map(String.init) ?? ""
        let path = (line.trimmingCharacters(in: .whitespaces) as NSString).expandingTildeInPath
        return path.hasPrefix("/") ? path : nil
    }

    /// The data folder: the one chosen in the interface if it's reachable,
    /// otherwise ~/Movies/AnimeUp. The second value is the chosen folder when
    /// it had to be skipped.
    private static func dataFolder(state: URL) -> (URL, String?) {
        let fm = FileManager.default
        let movies = fm.urls(for: .moviesDirectory, in: .userDomainMask).first
            ?? fm.homeDirectoryForCurrentUser.appendingPathComponent("Movies")
        let fallback = movies.appendingPathComponent("AnimeUp", isDirectory: true)
        guard let chosen = chosenDataFolder(state: state) else { return (fallback, nil) }
        let url = URL(fileURLWithPath: chosen, isDirectory: true)
        return isReachable(url) ? (url, nil) : (fallback, chosen)
    }

    /// A folder is usable if it exists, or if it can be created because its
    /// disk is there. Under /Volumes a missing disk would otherwise turn into
    /// a plain folder inside /Volumes, or an error that stops the app.
    private static func isReachable(_ url: URL) -> Bool {
        let fm = FileManager.default
        var isDir: ObjCBool = false
        if fm.fileExists(atPath: url.path, isDirectory: &isDir) { return isDir.boolValue }
        let parts = url.standardizedFileURL.pathComponents      // ["/", "Volumes", "Disk", ...]
        if parts.count >= 3 && parts[1] == "Volumes" {
            return fm.fileExists(atPath: "/Volumes/" + parts[2])
        }
        return fm.fileExists(atPath: url.deletingLastPathComponent().path)
    }
}

// MARK: - Language

/// English or Italian, with the same rule as the bash launcher: Italian only
/// if `<data>/registri/impostazioni.json` says `"lingua": "it"`.
nonisolated(unsafe) var italian = false

func detectLanguage(data: URL) {
    let file = data.appendingPathComponent("registri/impostazioni.json")
    guard let raw = try? Data(contentsOf: file),
          let json = try? JSONSerialization.jsonObject(with: raw) as? [String: Any] else {
        italian = false
        return
    }
    italian = (json["lingua"] as? String) == "it"
}

/// One string in both languages: `tr("English", "Italiano")`.
func tr(_ en: String, _ it: String) -> String {
    italian ? it : en
}

/// The version shown in About, from Info.plist (written by tools/build_app.sh
/// from pyproject.toml).
var appVersion: String {
    Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "?"
}
