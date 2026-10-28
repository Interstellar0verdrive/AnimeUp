import Foundation
import Testing
@testable import Engine
@testable import Models

/// The repository root, from this file's path.
let repo = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
    .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    .deletingLastPathComponent().deletingLastPathComponent()

/// A code folder whose `animeup` runs `script` with the repo's Python.
func fakeCode(_ script: String) throws -> URL {
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent("animeup-code-\(UUID().uuidString)")
    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    let launcher = dir.appendingPathComponent("animeup")
    try script.write(to: launcher, atomically: true, encoding: .utf8)
    try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: launcher.path)
    return dir
}

func tempState() -> URL {
    FileManager.default.temporaryDirectory.appendingPathComponent("animeup-state-\(UUID().uuidString)")
}

let python = repo.appendingPathComponent(".venv/bin/python").path

@Suite(.serialized) struct EngineClientTests {
    /// The real engine, run straight from the worktree's source.
    @Test(.enabled(if: FileManager.default.isExecutableFile(atPath: python)))
    func realEngineAnswers() async throws {
        let code = try fakeCode("""
        #!/bin/bash
        export PYTHONPATH="\(repo.path)/src"
        exec "\(python)" -m animeup.cli "$@"
        """)
        let state = tempState()
        let client = EngineClient(configuration: EngineConfiguration(
            codeFolder: code, stateFolder: state, extraEnvironment: ["ANIMEUP_WORK": state.appendingPathComponent("Jobs").path]))
        try await client.start()
        let hello = try await client.hello()
        #expect(hello.engine == "animeup" && hello.protocol == 1)
        #expect(hello.stateFolder.hasSuffix(state.lastPathComponent))
        async let machine = client.machineInfo()
        async let calibration = client.calibrationState()
        async let tools = client.toolsStatus()
        async let folders = client.foldersState()
        let (m, c, t, f) = try await (machine, calibration, tools, folders)
        #expect(!m.chip.isEmpty)
        #expect(c.state == .never)
        #expect(t.tools.map(\.key) == ["ffmpeg", "ffprobe", "realesrgan", "realcugan"])
        #expect(f.workFolder.hasSuffix("Jobs") && f.isDefault)
        let s = try await client.setSettings(["language": "it"])
        #expect(s.language == "it")
        let again = try await client.settings()
        #expect(again.language == "it")
        do {
            _ = try await client.raw("no.such.method")
            Issue.record("an unknown method answered")
        } catch let EngineError.remote(code, _) {
            #expect(code == "unknown_method")
        }
        await client.stop()
    }

    /// A crash fails the pending call and the client starts a new engine.
    @Test func restartsAfterACrash() async throws {
        let code = try fakeCode("""
        #!/bin/bash
        exec /usr/bin/env python3 -u -c '
        import json, sys, os
        print(json.dumps({"event": "ready", "data": {"pid": os.getpid()}}), flush=True)
        for line in sys.stdin:
            r = json.loads(line)
            if r["method"] == "crash":
                os._exit(3)
            print("not json, must be ignored", flush=True)
            print(json.dumps({"id": r["id"], "result": {"pid": os.getpid()}}), flush=True)
        '
        """)
        let client = EngineClient(configuration: EngineConfiguration(codeFolder: code, stateFolder: tempState()))
        try await client.start()
        struct P: Decodable, Sendable { var pid: Int }
        let first = try await client.call("hello", as: P.self)
        do {
            _ = try await client.raw("crash")
            Issue.record("the crash call answered")
        } catch {
            #expect(error as? EngineError == .terminated)
        }
        // Back within the first restart delay (1 s).
        var second: P?
        for _ in 0..<40 {
            try await Task.sleep(for: .milliseconds(100))
            if let p = try? await client.call("hello", as: P.self) { second = p; break }
        }
        #expect(second != nil && second?.pid != first.pid)
        #expect(await client.restarts == 1)
        await client.stop()
    }

    @Test func missingLauncherIsAnError() async {
        let client = EngineClient(configuration: EngineConfiguration(
            codeFolder: URL(fileURLWithPath: "/nonexistent"), stateFolder: tempState()))
        await #expect(throws: EngineError.self) { try await client.start() }
    }

    @Test func environmentIsolation() {
        let cfg = EngineConfiguration(codeFolder: URL(fileURLWithPath: "/code"),
                                      stateFolder: URL(fileURLWithPath: "/state"),
                                      extraEnvironment: ["ANIMEUP_WORK": "/w"])
        let env = cfg.environment(base: ["ANIMEUP_OUTPUT": "/real/OUTPUT", "PATH": "/opt/x"])
        #expect(env["ANIMEUP_OUTPUT"] == nil)
        #expect(env["ANIMEUP_STATO"] == "/state" && env["ANIMEUP_ROOT"] == "/state")
        #expect(env["ANIMEUP_WORK"] == "/w")
        #expect(env["PATH"]!.hasPrefix("/opt/x:") && env["PATH"]!.contains("/usr/bin"))
    }

    @Test func standardFolders() {
        let dev = EngineConfiguration.standard(debug: true, environment: [:])
        #expect(dev.stateFolder.lastPathComponent == "AnimeUp-dev")
        let release = EngineConfiguration.standard(debug: false, environment: [:])
        #expect(release.stateFolder.lastPathComponent == "AnimeUp 2")
        let env = EngineConfiguration.standard(debug: true, environment: ["ANIMEUP_CODE": "/c", "ANIMEUP_STATO": "/s"])
        #expect(env.codeFolder.path == "/c" && env.stateFolder.path == "/s")
    }
}

@Suite struct LogRotationTests {
    @Test func rotatesAboveTheLimit() throws {
        let dir = tempState()
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let log = dir.appendingPathComponent("engine.log")
        try Data(repeating: 65, count: 2000).write(to: log)
        Sidecar.rotate(log, limit: 5000)
        #expect(FileManager.default.fileExists(atPath: log.path))
        Sidecar.rotate(log, limit: 1000)
        #expect(!FileManager.default.fileExists(atPath: log.path))
        #expect(FileManager.default.fileExists(atPath: dir.appendingPathComponent("engine.1.log").path))
    }
}

@Suite struct SignalMaskTests {
    /// Jobs started by the engine must be stoppable: nothing blocked in the mask.
    @Test func sidecarStartsWithNoBlockedSignals() async throws {
        let code = try fakeCode("""
        #!/bin/bash
        exec /usr/bin/env python3 -u -c '
        import json, sys, signal
        for line in sys.stdin:
            r = json.loads(line)
            blocked = sorted(int(s) for s in signal.pthread_sigmask(signal.SIG_BLOCK, []))
            print(json.dumps({"id": r["id"], "result": {"blocked": blocked}}), flush=True)
        '
        """)
        // Block SIGTERM and SIGUSR1 on this thread, as a GUI thread might.
        var set = sigset_t()
        sigemptyset(&set)
        sigaddset(&set, SIGTERM)
        sigaddset(&set, SIGUSR1)
        var old = sigset_t()
        pthread_sigmask(SIG_BLOCK, &set, &old)
        defer { pthread_sigmask(SIG_SETMASK, &old, nil) }
        let client = EngineClient(configuration: EngineConfiguration(codeFolder: code, stateFolder: tempState()))
        try await client.start()
        struct R: Decodable, Sendable { var blocked: [Int] }
        let r = try await client.call("hello", as: R.self)
        #expect(r.blocked.isEmpty, "blocked signals in the engine: \(r.blocked)")
        await client.stop()
    }
}
