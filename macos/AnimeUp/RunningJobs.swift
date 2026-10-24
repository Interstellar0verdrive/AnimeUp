// RunningJobs.swift - the upscaling jobs running right now, and stopping them.
//
// Jobs are processes of their own (the CLI in its own session), so the app
// finds them the way the interface does: through the markers the CLI leaves
// next to the finished videos, in OUTPUT/JOBS.
//
//   OUTPUT/JOBS/<job>/running.lock   PID of the CLI working on that file
//   OUTPUT/JOBS/.queue               {"pid": …} of the CLI running a queue
//   OUTPUT/JOBS/.pause               {"pid": …} while it rests between files
//
// Stopping is what the interface's "Stop all" does: SIGTERM to the process
// group, so the queue's shell doesn't start the next file. The file in
// progress stays resumable.

import Foundation

enum RunningJobs {
    /// PIDs of AnimeUp CLIs alive now, without duplicates.
    static func pids(output: URL) -> [pid_t] {
        let fm = FileManager.default
        let jobs = output.appendingPathComponent("JOBS", isDirectory: true)
        var found: [pid_t] = []
        for marker in [".queue", ".pause"] {
            let url = jobs.appendingPathComponent(marker)
            if let raw = try? Data(contentsOf: url),
               let json = try? JSONSerialization.jsonObject(with: raw) as? [String: Any],
               let pid = (json["pid"] as? NSNumber)?.int32Value {
                found.append(pid)
            }
        }
        for job in (try? fm.contentsOfDirectory(at: jobs, includingPropertiesForKeys: nil)) ?? [] {
            let lock = job.appendingPathComponent("running.lock")
            if let text = try? String(contentsOf: lock, encoding: .utf8),
               let pid = pid_t(text.trimmingCharacters(in: .whitespacesAndNewlines)) {
                found.append(pid)
            }
        }
        var seen = Set<pid_t>()
        return found.filter { $0 > 1 && seen.insert($0).inserted && isOurs($0) }
    }

    /// SIGTERM to each job's process group (or the process alone).
    static func stop(_ pids: [pid_t]) {
        for pid in pids where isOurs(pid) {
            let group = getpgid(pid)
            if group > 1 && group != getpgrp() {
                killpg(group, SIGTERM)
            } else {
                kill(pid, SIGTERM)
            }
        }
    }

    /// Alive, and really an AnimeUp CLI: after a crash a PID can be reused
    /// by an unrelated process.
    private static func isOurs(_ pid: pid_t) -> Bool {
        guard kill(pid, 0) == 0 else { return false }
        let ps = Process()
        ps.executableURL = URL(fileURLWithPath: "/bin/ps")
        ps.arguments = ["-o", "command=", "-p", String(pid)]
        let pipe = Pipe()
        ps.standardOutput = pipe
        ps.standardError = FileHandle.nullDevice
        do { try ps.run() } catch { return false }
        ps.waitUntilExit()
        let command = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        return command.contains("animeup") || command.contains("python")
    }
}
