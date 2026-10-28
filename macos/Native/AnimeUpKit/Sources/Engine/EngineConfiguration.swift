import Foundation

/// Where the engine lives and what it runs with.
///
/// - `codeFolder`: the program (launcher `animeup`, `src/`, `samples/`). In the
///   app bundle it's `Contents/Resources/AnimeUp`; in Debug the scheme sets
///   `ANIMEUP_CODE` to the worktree, so Python changes need no rebuild.
/// - `stateFolder`: what AnimeUp downloads and records (Python, bin/,
///   records/). 2.0 starts a NEW one, with no migration from 1.6:
///   `~/Library/Application Support/AnimeUp 2`, or `AnimeUp-dev` in Debug.
public struct EngineConfiguration: Sendable, Equatable {
    public var codeFolder: URL
    public var stateFolder: URL
    public var extraEnvironment: [String: String]
    public var logFile: URL

    public init(codeFolder: URL, stateFolder: URL, extraEnvironment: [String: String] = [:], logFile: URL? = nil) {
        self.codeFolder = codeFolder
        self.stateFolder = stateFolder
        self.extraEnvironment = extraEnvironment
        self.logFile = logFile ?? stateFolder.appendingPathComponent("records/engine.log")
    }

    public var launcher: URL { codeFolder.appendingPathComponent("animeup") }
    public var localesFolder: URL { codeFolder.appendingPathComponent("src/animeup/locales") }

    /// The default for this build. `ANIMEUP_CODE` and `ANIMEUP_STATO` in the
    /// app's own environment win (the Debug scheme sets them).
    public static func standard(debug: Bool, bundle: Bundle = .main,
                                environment: [String: String] = ProcessInfo.processInfo.environment) -> EngineConfiguration {
        let code: URL
        if let env = environment["ANIMEUP_CODE"], !env.isEmpty {
            code = URL(fileURLWithPath: (env as NSString).expandingTildeInPath)
        } else {
            code = (bundle.resourceURL ?? bundle.bundleURL).appendingPathComponent("AnimeUp")
        }
        let state: URL
        if let env = environment["ANIMEUP_STATO"], !env.isEmpty {
            state = URL(fileURLWithPath: (env as NSString).expandingTildeInPath)
        } else {
            let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            state = support.appendingPathComponent(debug ? "AnimeUp-dev" : "AnimeUp 2")
        }
        var extra: [String: String] = [:]
        // Passed through when set (the Debug scheme keeps work files in a
        // test folder, away from real jobs).
        for key in ["ANIMEUP_WORK", "ANIMEUP_LANG"] {
            if let v = environment[key], !v.isEmpty { extra[key] = v }
        }
        return EngineConfiguration(codeFolder: code, stateFolder: state, extraEnvironment: extra)
    }

    /// The environment the sidecar starts with.
    func environment(base: [String: String] = ProcessInfo.processInfo.environment) -> [String: String] {
        var env = base
        // Never inherit these from a terminal that launched the app: they
        // would point the engine at somebody else's folders.
        for key in ["ANIMEUP_INPUT", "ANIMEUP_OUTPUT", "ANIMEUP_ROOT", "PYTHONPATH", "VIRTUAL_ENV",
                    "UV_PROJECT_ENVIRONMENT", "ANIMEUP_CODE"] {
            env.removeValue(forKey: key)
        }
        env["ANIMEUP_STATO"] = stateFolder.path
        // The data root: the state folder, so nothing is ever written next
        // to the program (the bundle is read-only).
        env["ANIMEUP_ROOT"] = stateFolder.path
        env["ANIMEUP_APP"] = "2"
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        let path = env["PATH"] ?? ""
        let essentials = "/usr/bin:/bin:/usr/sbin:/sbin"
        env["PATH"] = path.isEmpty ? essentials : "\(path):\(essentials)"
        for (k, v) in extraEnvironment { env[k] = v }
        return env
    }
}
