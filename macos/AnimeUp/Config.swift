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
        let data = dataFolder(state: state)

        for dir in [state, logs, data] {
            do {
                try fm.createDirectory(at: dir, withIntermediateDirectories: true)
            } catch {
                throw Failure.cannotCreate(dir.path, error)
            }
        }
        return AppPaths(program: program, launcher: launcher, state: state, data: data,
                        logFile: logs.appendingPathComponent("app.log"))
    }

    /// `<state>/cartella_dati` holds one absolute path (written by the UI when
    /// the user moves the data elsewhere); without it, ~/Movies/AnimeUp.
    private static func dataFolder(state: URL) -> URL {
        let fm = FileManager.default
        let pointer = state.appendingPathComponent("cartella_dati")
        if let text = try? String(contentsOf: pointer, encoding: .utf8) {
            let line = text.split(whereSeparator: \.isNewline).first.map(String.init) ?? ""
            let path = (line.trimmingCharacters(in: .whitespaces) as NSString).expandingTildeInPath
            if path.hasPrefix("/") {
                return URL(fileURLWithPath: path, isDirectory: true)
            }
        }
        let movies = fm.urls(for: .moviesDirectory, in: .userDomainMask).first
            ?? fm.homeDirectoryForCurrentUser.appendingPathComponent("Movies")
        return movies.appendingPathComponent("AnimeUp", isDirectory: true)
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
