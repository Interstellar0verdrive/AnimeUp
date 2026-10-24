// ServerProcess.swift - runs `animeup ui` as a child process and watches it.
//
// Why posix_spawn and not Foundation's Process: we want the child to lead its
// own process group, so that quitting can signal the whole group (bash, and
// `uv sync` while the environment is still being prepared). Process can't do
// that. The launcher `exec`s Python, which `exec`s Streamlit, so once the
// server is up the child PID *is* the Streamlit server.
//
// Upscaling jobs are started by the UI with `start_new_session=True`: they
// live in their own session and process group, so signalling our group
// never reaches them and they keep running after the app quits.

import Foundation

final class ServerProcess {
    private let paths: AppPaths

    /// PID of the child (= its process group ID). 0 before start().
    private(set) var pid: pid_t = 0

    /// Called on the main queue for every non-empty output line.
    var onLine: ((String) -> Void)?
    /// Called on the main queue when the child exits, with a description of
    /// how it ended ("exit code 1", "signal 9").
    var onExit: ((String) -> Void)?

    // Output handling happens on this serial queue: log file, partial line,
    // recent lines.
    private let io = DispatchQueue(label: "animeup.server.io")
    private var log: FileHandle?
    private var partial = Data()
    private var recent: [String] = []
    private let recentLimit = 20

    private var reader: FileHandle?
    private let exitedSignal = DispatchSemaphore(value: 0)
    private let exitLock = NSLock()
    private var exitedFlag = false

    var hasExited: Bool {
        exitLock.lock(); defer { exitLock.unlock() }
        return exitedFlag
    }

    init(paths: AppPaths) {
        self.paths = paths
    }

    // MARK: Start

    func start() throws {
        openLog()

        // stdin from /dev/null; stdout and stderr into one pipe we read.
        var fds: [Int32] = [0, 0]
        guard pipe(&fds) == 0 else { throw posixError("pipe") }
        let (readFD, writeFD) = (fds[0], fds[1])

        var actions: posix_spawn_file_actions_t?
        posix_spawn_file_actions_init(&actions)
        defer { posix_spawn_file_actions_destroy(&actions) }
        posix_spawn_file_actions_addopen(&actions, 0, "/dev/null", O_RDONLY, 0)
        posix_spawn_file_actions_adddup2(&actions, writeFD, 1)
        posix_spawn_file_actions_adddup2(&actions, writeFD, 2)
        posix_spawn_file_actions_addchdir_np(&actions, paths.program.path)

        var attr: posix_spawnattr_t?
        posix_spawnattr_init(&attr)
        defer { posix_spawnattr_destroy(&attr) }
        // SETPGROUP + pgroup 0: the child becomes leader of a new group.
        // CLOEXEC_DEFAULT: no file descriptor of ours leaks into the server
        // (and from there into the detached jobs), except 0/1/2 above.
        // SETSIGDEF/SETSIGMASK: the child starts with default signal handling.
        let flags = POSIX_SPAWN_SETPGROUP | POSIX_SPAWN_CLOEXEC_DEFAULT
            | POSIX_SPAWN_SETSIGDEF | POSIX_SPAWN_SETSIGMASK
        posix_spawnattr_setflags(&attr, Int16(flags))
        posix_spawnattr_setpgroup(&attr, 0)
        var allSignals = ~sigset_t(0)
        var noSignals = sigset_t(0)
        posix_spawnattr_setsigdefault(&attr, &allSignals)
        posix_spawnattr_setsigmask(&attr, &noSignals)

        let argv = ["/bin/bash", paths.launcher.path,
                    "ui", "--porta", String(serverPort), "--senza-browser"]
        let envp = environment().map { "\($0.key)=\($0.value)" }

        let cArgv = argv.map { strdup($0) } + [nil]
        let cEnvp = envp.map { strdup($0) } + [nil]
        defer {
            cArgv.forEach { free($0) }
            cEnvp.forEach { free($0) }
        }

        var child: pid_t = 0
        let rc = posix_spawn(&child, "/bin/bash", &actions, &attr, cArgv, cEnvp)
        close(writeFD)
        guard rc == 0 else {
            close(readFD)
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(rc),
                          userInfo: [NSLocalizedDescriptionKey: "posix_spawn: \(String(cString: strerror(rc)))"])
        }
        pid = child
        writeLog("[app] started launcher, pid \(child)\n")

        // Read output as it comes.
        let handle = FileHandle(fileDescriptor: readFD, closeOnDealloc: true)
        reader = handle
        handle.readabilityHandler = { [weak self] h in
            let chunk = h.availableData
            guard let self else { return }
            if chunk.isEmpty {
                h.readabilityHandler = nil
                self.io.async { self.flushPartial() }
            } else {
                self.io.async { self.consume(chunk) }
            }
        }

        // Reap the child on a dedicated thread; waitpid blocks.
        let watched = child
        Thread.detachNewThread { [weak self] in
            var status: Int32 = 0
            while waitpid(watched, &status, 0) == -1 && errno == EINTR {}
            let how: String
            if status & 0x7f == 0 {
                how = "exit code \((status >> 8) & 0xff)"
            } else {
                how = "signal \(status & 0x7f)"
            }
            guard let self else { return }
            self.exitLock.lock(); self.exitedFlag = true; self.exitLock.unlock()
            self.exitedSignal.signal()
            // Give the reader a moment to drain the last lines first.
            self.io.asyncAfter(deadline: .now() + 0.2) {
                self.flushPartial()
                self.writeLog("[app] launcher/server exited (\(how))\n")
                DispatchQueue.main.async { self.onExit?(how) }
            }
        }
    }

    /// A small, predictable environment: nothing from the user's shell
    /// profile, Homebrew or conda can leak into the program.
    private func environment() -> [String: String] {
        let inherited = ProcessInfo.processInfo.environment
        var env: [String: String] = [
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": inherited["HOME"] ?? NSHomeDirectory(),
            "LANG": inherited["LANG"].flatMap { $0.contains("UTF-8") ? $0 : nil } ?? "en_US.UTF-8",
            "ANIMEUP_STATO": paths.state.path,
            "ANIMEUP_ROOT": paths.data.path,
            "ANIMEUP_APP": "1",
            "PYTHONUNBUFFERED": "1",
        ]
        for key in ["USER", "LOGNAME", "TMPDIR", "SHELL"] {
            if let v = inherited[key] { env[key] = v }
        }
        return env
    }

    // MARK: Output

    private func consume(_ chunk: Data) {
        log?.write(chunk)
        partial.append(chunk)
        // Lines end with \n; progress-style output may use \r.
        while let i = partial.firstIndex(where: { $0 == 0x0A || $0 == 0x0D }) {
            let line = partial[partial.startIndex..<i]
            partial.removeSubrange(partial.startIndex...i)
            emit(line)
        }
    }

    private func flushPartial() {
        if !partial.isEmpty {
            emit(partial)
            partial.removeAll()
        }
    }

    private func emit(_ bytes: Data) {
        let text = Self.clean(String(decoding: bytes, as: UTF8.self))
        guard !text.isEmpty else { return }
        recent.append(text)
        if recent.count > recentLimit { recent.removeFirst(recent.count - recentLimit) }
        DispatchQueue.main.async { [weak self] in self?.onLine?(text) }
    }

    /// Strips ANSI escape sequences (rich colours) and surrounding blanks.
    static func clean(_ s: String) -> String {
        s.replacingOccurrences(of: "\u{1B}\\[[0-9;?]*[ -/]*[@-~]", with: "",
                               options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// The last ~20 output lines, oldest first.
    func recentLines() -> [String] {
        io.sync { recent }
    }

    // MARK: Log file

    private func openLog() {
        let fm = FileManager.default
        let path = paths.logFile.path
        // Keep the log from growing forever: one rotation at 5 MB.
        if let size = (try? fm.attributesOfItem(atPath: path))?[.size] as? Int, size > 5_000_000 {
            let old = path + ".1"
            try? fm.removeItem(atPath: old)
            try? fm.moveItem(atPath: path, toPath: old)
        }
        if !fm.fileExists(atPath: path) {
            fm.createFile(atPath: path, contents: nil)
        }
        log = FileHandle(forWritingAtPath: path)
        log?.seekToEndOfFile()
        let stamp = ISO8601DateFormatter().string(from: Date())
        writeLog("\n===== AnimeUp app \(appVersion) - \(stamp) =====\n")
    }

    /// Writes a line of our own into the log (call on any queue).
    func writeLog(_ s: String) {
        let data = Data(s.utf8)
        io.async { [weak self] in self?.log?.write(data) }
    }

    // MARK: Stop

    /// SIGTERM to the child's whole process group, wait up to `timeout`
    /// seconds, then SIGKILL whatever is left of the group. Blocking.
    func terminate(timeout: TimeInterval = 4) {
        guard pid > 0, !hasExited else { return }
        writeLog("[app] stopping server (SIGTERM to process group \(pid))\n")
        if kill(-pid, SIGTERM) != 0 { kill(pid, SIGTERM) }
        if exitedSignal.wait(timeout: .now() + timeout) == .timedOut {
            writeLog("[app] server did not stop in time: SIGKILL\n")
            if kill(-pid, SIGKILL) != 0 { kill(pid, SIGKILL) }
            _ = exitedSignal.wait(timeout: .now() + 1)
        } else {
            // The leader is gone; anything else still in the group (a helper
            // started without its own session) gets the same SIGTERM.
            kill(-pid, SIGTERM)
        }
        io.sync { log?.synchronizeFile() }
    }

    private func posixError(_ what: String) -> NSError {
        NSError(domain: NSPOSIXErrorDomain, code: Int(errno),
                userInfo: [NSLocalizedDescriptionKey: "\(what): \(String(cString: strerror(errno)))"])
    }
}

// MARK: - Health check

/// Asks the server's health endpoint; calls back on the main queue with true
/// when it answers "ok".
func checkHealth(_ done: @escaping (Bool) -> Void) {
    var request = URLRequest(url: healthURL)
    request.timeoutInterval = 1.0
    request.cachePolicy = .reloadIgnoringLocalCacheData
    healthSession.dataTask(with: request) { data, response, _ in
        let ok = (response as? HTTPURLResponse)?.statusCode == 200
            && data.map { String(decoding: $0, as: UTF8.self)
                .trimmingCharacters(in: .whitespacesAndNewlines) == "ok" } == true
        DispatchQueue.main.async { done(ok) }
    }.resume()
}

private let healthSession: URLSession = {
    let config = URLSessionConfiguration.ephemeral
    config.timeoutIntervalForRequest = 1.0
    config.timeoutIntervalForResource = 2.0
    config.connectionProxyDictionary = [:]   // never through a system proxy
    return URLSession(configuration: config)
}()

/// PID listening on our port (a server left over from a crash, reused at
/// launch), found with lsof. nil if none.
func listenerPID() -> pid_t? {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
    p.arguments = ["-nP", "-t", "-iTCP:\(serverPort)", "-sTCP:LISTEN"]
    let out = Pipe()
    p.standardOutput = out
    p.standardError = FileHandle.nullDevice
    do { try p.run() } catch { return nil }
    p.waitUntilExit()
    let text = String(decoding: out.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
    return text.split(whereSeparator: \.isNewline).first.flatMap { pid_t($0) }
}
