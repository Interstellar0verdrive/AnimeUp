import Darwin
import Foundation

/// One run of `animeup serve`: spawned with posix_spawn in its own process
/// group, stdin/stdout as pipes, stderr appended to a log file.
///
/// The process group matters: the launcher is a bash script that execs
/// Python, and Python may start helpers (ffmpeg -version, sysctl...).
/// Stopping signals the whole group, so nothing is left behind. GPU jobs are
/// NOT children of this group: the engine starts them detached, as 1.6 does.
final class Sidecar: @unchecked Sendable {
    let pid: pid_t
    private let input: FileHandle
    private let output: FileHandle
    private let exitSource: DispatchSourceProcess
    private let lock = NSLock()
    private var buffer = Data()
    private var exited = false

    /// - onLine: every complete line from stdout (the protocol channel).
    /// - onExit: the exit status, once.
    init(configuration: EngineConfiguration,
         onLine: @escaping @Sendable (Data) -> Void,
         onExit: @escaping @Sendable (Int32) -> Void) throws {
        let fm = FileManager.default
        try fm.createDirectory(at: configuration.logFile.deletingLastPathComponent(), withIntermediateDirectories: true)
        Self.rotate(configuration.logFile)
        if !fm.fileExists(atPath: configuration.logFile.path) {
            fm.createFile(atPath: configuration.logFile.path, contents: nil)
        }
        guard fm.isExecutableFile(atPath: configuration.launcher.path) else {
            throw EngineError.launcherMissing(configuration.launcher.path)
        }

        var stdinPipe: [Int32] = [0, 0]
        var stdoutPipe: [Int32] = [0, 0]
        guard pipe(&stdinPipe) == 0, pipe(&stdoutPipe) == 0 else { throw EngineError.spawnFailed(errno) }
        let logFD = open(configuration.logFile.path, O_WRONLY | O_APPEND | O_CREAT, 0o644)
        guard logFD >= 0 else { throw EngineError.spawnFailed(errno) }

        var actions: posix_spawn_file_actions_t? = nil
        posix_spawn_file_actions_init(&actions)
        defer { posix_spawn_file_actions_destroy(&actions) }
        posix_spawn_file_actions_adddup2(&actions, stdinPipe[0], 0)
        posix_spawn_file_actions_adddup2(&actions, stdoutPipe[1], 1)
        posix_spawn_file_actions_adddup2(&actions, logFD, 2)
        posix_spawn_file_actions_addchdir(&actions, configuration.stateFolder.path)

        var attributes: posix_spawnattr_t? = nil
        posix_spawnattr_init(&attributes)
        defer { posix_spawnattr_destroy(&attributes) }
        posix_spawnattr_setpgroup(&attributes, 0)
        // CLOEXEC_DEFAULT: only the three descriptors above reach the child,
        // nothing else the app has open.
        // SETSIGMASK with an empty mask: the thread that spawns may block
        // signals (Swift concurrency threads do), and a blocked SIGTERM or
        // SIGUSR1 would be inherited by every job the engine starts: Stop
        // and Stop All would do nothing.
        posix_spawnattr_setflags(&attributes, Int16(POSIX_SPAWN_SETPGROUP | POSIX_SPAWN_CLOEXEC_DEFAULT
                                                    | POSIX_SPAWN_SETSIGDEF | POSIX_SPAWN_SETSIGMASK))
        var noMask = sigset_t()
        sigemptyset(&noMask)
        posix_spawnattr_setsigmask(&attributes, &noMask)
        var defaults = sigset_t()
        sigemptyset(&defaults)
        sigaddset(&defaults, SIGPIPE)
        sigaddset(&defaults, SIGINT)
        sigaddset(&defaults, SIGTERM)
        posix_spawnattr_setsigdefault(&attributes, &defaults)

        try fm.createDirectory(at: configuration.stateFolder, withIntermediateDirectories: true)
        let argv: [String] = [configuration.launcher.path, "serve"]
        let env = configuration.environment().map { "\($0.key)=\($0.value)" }
        var cArgv = argv.map { strdup($0) } + [nil]
        var cEnv = env.map { strdup($0) } + [nil]
        defer {
            cArgv.forEach { free($0) }
            cEnv.forEach { free($0) }
        }
        var child: pid_t = 0
        let status = posix_spawn(&child, configuration.launcher.path, &actions, &attributes, &cArgv, &cEnv)
        close(stdinPipe[0]); close(stdoutPipe[1]); close(logFD)
        guard status == 0 else {
            close(stdinPipe[1]); close(stdoutPipe[0])
            throw EngineError.spawnFailed(status)
        }
        pid = child
        // A dead engine must give EPIPE, not kill the app with SIGPIPE.
        _ = fcntl(stdinPipe[1], F_SETNOSIGPIPE, 1)
        input = FileHandle(fileDescriptor: stdinPipe[1], closeOnDealloc: true)
        output = FileHandle(fileDescriptor: stdoutPipe[0], closeOnDealloc: true)

        exitSource = DispatchSource.makeProcessSource(identifier: child, eventMask: .exit, queue: .global())
        exitSource.setEventHandler { [weak self] in
            var raw: Int32 = 0
            waitpid(child, &raw, 0)
            self?.markExited()
            self?.exitSource.cancel()
            onExit(raw)
        }
        exitSource.resume()

        output.readabilityHandler = { [weak self] handle in
            let chunk = handle.availableData
            guard let self else { return }
            if chunk.isEmpty {
                handle.readabilityHandler = nil
                return
            }
            for line in self.append(chunk) { onLine(line) }
        }
    }

    /// Keeps two files of ~5 MB: `engine.log` and `engine.1.log`.
    static func rotate(_ log: URL, limit: Int = 5_000_000) {
        let fm = FileManager.default
        guard let size = (try? fm.attributesOfItem(atPath: log.path))?[.size] as? Int, size > limit else { return }
        let old = log.deletingPathExtension().appendingPathExtension("1.log")
        try? fm.removeItem(at: old)
        try? fm.moveItem(at: log, to: old)
    }

    private func markExited() {
        lock.lock(); exited = true; lock.unlock()
    }

    var isRunning: Bool {
        lock.lock(); defer { lock.unlock() }
        return !exited
    }

    private func append(_ chunk: Data) -> [Data] {
        lock.lock(); defer { lock.unlock() }
        buffer.append(chunk)
        var lines: [Data] = []
        while let nl = buffer.firstIndex(of: 0x0A) {
            let line = buffer[buffer.startIndex..<nl]
            if !line.isEmpty { lines.append(Data(line)) }
            buffer.removeSubrange(buffer.startIndex...nl)
        }
        return lines
    }

    func send(_ line: Data) throws {
        var data = line
        data.append(0x0A)
        do {
            try input.write(contentsOf: data)
        } catch {
            throw EngineError.notRunning
        }
    }

    /// Closes stdin (the engine exits on EOF), then signals the group.
    func stop(grace: TimeInterval = 2) {
        try? input.close()
        let pid = self.pid
        DispatchQueue.global().asyncAfter(deadline: .now() + grace) { [weak self] in
            guard let self, self.isRunning else { return }
            kill(-pid, SIGTERM)
            DispatchQueue.global().asyncAfter(deadline: .now() + grace) { [weak self] in
                guard let self, self.isRunning else { return }
                kill(-pid, SIGKILL)
            }
        }
    }

    /// Immediately: for the app quitting.
    func terminateNow() {
        try? input.close()
        kill(-pid, SIGTERM)
    }
}

public enum EngineError: Error, Equatable, CustomStringConvertible {
    case launcherMissing(String)
    case spawnFailed(Int32)
    case notRunning
    case terminated
    case gaveUp
    case badReply(String)
    case remote(code: String, message: String)

    public var description: String {
        switch self {
        case .launcherMissing(let p): return "engine launcher not found: \(p)"
        case .spawnFailed(let e): return "could not start the engine: \(String(cString: strerror(e)))"
        case .notRunning: return "the engine is not running"
        case .terminated: return "the engine stopped before answering"
        case .gaveUp: return "the engine keeps crashing; restart AnimeUp"
        case .badReply(let s): return "unreadable reply from the engine: \(s)"
        case .remote(let code, let message): return "\(code): \(message)"
        }
    }
}
