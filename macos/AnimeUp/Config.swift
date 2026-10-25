// Config.swift - where AnimeUp lives on disk, which port it uses, which
// language it speaks.
//
// The .app bundle is treated as read-only (it gets replaced whole on every
// update), so everything AnimeUp downloads or generates goes elsewhere:
//
//   state   ~/Library/Application Support/AnimeUp   Python, venv, bin/, logs/,
//                                                   records/ (history, settings,
//                                                   calibration), cache/
//   input   ~/Movies/AnimeUp/INPUT  (or <state>/input-folder)   videos to process
//   output  ~/Movies/AnimeUp/OUTPUT (or <state>/output-folder)  finished videos,
//                                                   logs/ and JOBS/ inside
//
// The bash launcher learns them through ANIMEUP_STATO, ANIMEUP_INPUT and
// ANIMEUP_OUTPUT. ANIMEUP_ROOT is the folder the defaults live in: before
// 1.6 it held everything, and the program moves what it finds there into
// the new places on first launch.

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
    /// The base folder: the defaults INPUT and OUTPUT live here, and so did
    /// everything else before 1.6.
    let data: URL
    /// Videos to process.
    let input: URL
    /// Finished videos (with logs/ and JOBS/ inside).
    let output: URL
    /// `<state>/logs/app.log`: launcher and server output, appended.
    let logFile: URL
    /// A folder the user chose that isn't reachable now (an external drive
    /// that isn't connected): the default is used instead, and the interface
    /// says so.
    let unavailableInput: String?
    let unavailableOutput: String?

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
        let (data, unavailableData) = dataFolder(state: state)
        // A base folder chosen before 1.6 that is gone now: both folders
        // inside it are missing too, unless chosen on their own since.
        let (input, unavailableInput) = folder(state: state, file: "input-folder",
            fallback: data.appendingPathComponent("INPUT", isDirectory: true),
            missing: unavailableData.map { $0 + "/INPUT" })
        let (output, unavailableOutput) = folder(state: state, file: "output-folder",
            fallback: data.appendingPathComponent("OUTPUT", isDirectory: true),
            missing: unavailableData.map { $0 + "/OUTPUT" })

        for dir in [state, logs, input, output] {
            do {
                try fm.createDirectory(at: dir, withIntermediateDirectories: true)
            } catch {
                throw Failure.cannotCreate(dir.path, error)
            }
        }
        return AppPaths(program: program, launcher: launcher, state: state, data: data,
                        input: input, output: output,
                        logFile: logs.appendingPathComponent("app.log"),
                        unavailableInput: unavailableInput,
                        unavailableOutput: unavailableOutput)
    }

    /// What the interface has chosen, all in one value: when it changes, the
    /// server restarts on the new folders.
    static func choices(state: URL) -> [String?] {
        ["cartella_dati", "input-folder", "output-folder"].map { chosen(state: state, file: $0) }
    }

    /// The folder written in `<state>/<file>` by the interface's folder
    /// picker; nil when the user never chose one. `cartella_dati` is the
    /// single data folder of 1.5, still honoured as the base folder.
    static func chosen(state: URL, file: String) -> String? {
        let pointer = state.appendingPathComponent(file)
        guard let text = try? String(contentsOf: pointer, encoding: .utf8) else { return nil }
        let line = text.split(whereSeparator: \.isNewline).first.map(String.init) ?? ""
        // Only the line end goes: a folder name may really end with a space,
        // and trimming it pointed the app at a new, empty sibling folder.
        let path = (line.trimmingCharacters(in: .newlines) as NSString).expandingTildeInPath
        return path.hasPrefix("/") ? path : nil
    }

    /// The base folder: the one chosen in 1.5 if it's reachable, otherwise
    /// ~/Movies/AnimeUp. The second value is the chosen folder when it had
    /// to be skipped.
    private static func dataFolder(state: URL) -> (URL, String?) {
        let fm = FileManager.default
        let movies = fm.urls(for: .moviesDirectory, in: .userDomainMask).first
            ?? fm.homeDirectoryForCurrentUser.appendingPathComponent("Movies")
        let fallback = movies.appendingPathComponent("AnimeUp", isDirectory: true)
        return folder(state: state, file: "cartella_dati", fallback: fallback, missing: nil)
    }

    /// The folder chosen in `<state>/<file>` if it's reachable, otherwise
    /// `fallback`; the second value names the choice that was skipped.
    private static func folder(state: URL, file: String, fallback: URL,
                               missing: String?) -> (URL, String?) {
        guard let path = chosen(state: state, file: file) else { return (fallback, missing) }
        let url = URL(fileURLWithPath: path, isDirectory: true)
        // Reachable but impossible to create (a read-only disk, permissions):
        // stopping the launch there left no way to pick another folder,
        // because the folder picker lives in the interface.
        guard isReachable(url),
              (try? FileManager.default.createDirectory(
                  at: url, withIntermediateDirectories: true)) != nil
        else { return (fallback, path) }
        return (url, nil)
    }

    /// A folder skipped at launch (its disk wasn't there) can be used now.
    static func cameBack(_ path: String?) -> Bool {
        guard let path else { return false }
        return isReachable(URL(fileURLWithPath: path, isDirectory: true))
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
/// if `<state>/records/settings.json` says `"language": "it"` (before 1.6:
/// `"lingua"` in `<data>/registri/impostazioni.json`).
nonisolated(unsafe) var italian = false

func detectLanguage(state: URL, data: URL) {
    for (file, key) in [(state.appendingPathComponent("records/settings.json"), "language"),
                        (data.appendingPathComponent("registri/impostazioni.json"), "lingua")] {
        guard let raw = try? Data(contentsOf: file),
              let json = try? JSONSerialization.jsonObject(with: raw) as? [String: Any] else {
            continue
        }
        italian = (json[key] as? String) == "it"
        return
    }
    italian = false
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

// MARK: - Theme

/// The window's appearance follows the interface's System / Dark / Light
/// choice (`"theme"` in `<state>/records/settings.json`), so the title bar
/// and the page never disagree. System leaves it to macOS.
func savedTheme(state: URL) -> String {
    let file = state.appendingPathComponent("records/settings.json")
    guard let raw = try? Data(contentsOf: file),
          let json = try? JSONSerialization.jsonObject(with: raw) as? [String: Any],
          let theme = json["theme"] as? String else { return "system" }
    return theme
}

