import Foundation
import Models

/// A push message from the engine (no request id): `ready`,
/// `settings.changed`... plus the client's own `engine.started`,
/// `engine.exited` and `engine.gave_up`.
public struct EngineEvent: Sendable {
    public var name: String
    /// The raw JSON of `data` (an object, possibly empty).
    public var data: Data

    public func decode<T: Decodable>(_ type: T.Type) throws -> T {
        try EngineCoding.decoder.decode(T.self, from: data)
    }
}

/// Talks to `animeup serve`: one long-lived Python sidecar per app run.
///
/// - `start()` spawns it (posix_spawn, own process group).
/// - `call(_:params:)` sends a request and awaits its reply, by id.
/// - `events` streams the engine's push messages.
/// - When the engine dies unexpectedly, pending calls fail with
///   `.terminated` and it's restarted with a growing delay (1, 2, 4... 30 s);
///   after 5 crashes in 2 minutes the client gives up (`engine.gave_up`).
public actor EngineClient {
    public nonisolated let configuration: EngineConfiguration
    public nonisolated let events: AsyncStream<EngineEvent>
    private let eventSink: AsyncStream<EngineEvent>.Continuation

    private var sidecar: Sidecar?
    private var nextID = 1
    private var pending: [Int: CheckedContinuation<Data, Error>] = [:]
    private var stopping = false
    private var crashes: [Date] = []
    private var gaveUp = false
    public private(set) var restarts = 0

    public init(configuration: EngineConfiguration) {
        self.configuration = configuration
        (events, eventSink) = AsyncStream<EngineEvent>.makeStream(bufferingPolicy: .bufferingNewest(256))
    }

    public var isRunning: Bool { sidecar?.isRunning ?? false }
    public var pid: Int32? { sidecar?.pid }

    public func start() throws {
        guard sidecar == nil else { return }
        stopping = false
        gaveUp = false
        try spawn()
    }

    private func spawn() throws {
        let process = try Sidecar(
            configuration: configuration,
            onLine: { [weak self] line in
                guard let self else { return }
                Task { await self.received(line) }
            },
            onExit: { [weak self] status in
                guard let self else { return }
                Task { await self.exited(status: status) }
            })
        sidecar = process
        emit("engine.started", ["pid": Int(process.pid)])
    }

    /// Stops the engine for good (no restart). Pending calls fail.
    public func stop() {
        stopping = true
        sidecar?.stop()
        failPending(EngineError.terminated)
    }

    /// For the app quitting: no grace period.
    public func terminateNow() {
        stopping = true
        sidecar?.terminateNow()
        failPending(EngineError.terminated)
    }

    // MARK: requests

    /// Sends `method` with `params` and decodes the `result`.
    public func call<R: Decodable & Sendable>(_ method: String, params: [String: any Sendable] = [:],
                                              as type: R.Type = R.self) async throws -> R {
        let data = try await raw(method, params: params)
        do {
            return try EngineCoding.decoder.decode(R.self, from: data)
        } catch {
            throw EngineError.badReply("\(method): \(error)")
        }
    }

    /// The raw JSON of `result`.
    public func raw(_ method: String, params: [String: any Sendable] = [:]) async throws -> Data {
        if gaveUp { throw EngineError.gaveUp }
        guard let sidecar, sidecar.isRunning else { throw EngineError.notRunning }
        let id = nextID
        nextID += 1
        let request: [String: Any] = ["id": id, "method": method, "params": params]
        let line = try JSONSerialization.data(withJSONObject: request)
        return try await withCheckedThrowingContinuation { continuation in
            pending[id] = continuation
            do {
                try sidecar.send(line)
            } catch {
                pending.removeValue(forKey: id)
                continuation.resume(throwing: error)
            }
        }
    }

    // MARK: typed helpers

    public func hello() async throws -> EngineHello { try await call("hello") }
    public func settings() async throws -> EngineSettings { try await call("settings.get") }
    public func setSettings(_ values: [String: any Sendable]) async throws -> EngineSettings {
        try await call("settings.set", params: ["values": values])
    }
    public func machineInfo() async throws -> MachineInfo { try await call("machine.info") }
    public func calibrationState() async throws -> CalibrationState { try await call("calibration.state") }
    public func calibrationDetails() async throws -> CalibrationDetails { try await call("calibration.details") }
    public func toolsStatus() async throws -> ToolsStatus { try await call("tools.status") }
    public func foldersState() async throws -> FoldersState { try await call("folders.state") }
    public func defaults() async throws -> EngineSettings { try await call("settings.defaults") }
    public func filesList() async throws -> FilesList { try await call("files.list") }
    public func addFiles(_ paths: [String], subfolders: Bool, restore: Bool = false) async throws -> AddResult {
        try await call("files.add", params: ["paths": paths, "subfolders": subfolders, "restore": restore])
    }
    public func removeFiles(_ ids: [String]) async throws {
        _ = try await raw("files.remove", params: ["ids": ids])
    }
    public func reanalyse(_ ids: [String]?) async throws {
        if let ids { _ = try await raw("files.reanalyse", params: ["ids": ids]) }
        else { _ = try await raw("files.reanalyse", params: ["all": true]) }
    }
    public func deepAnalysis(_ ids: [String]) async throws { _ = try await raw("files.deep", params: ["ids": ids]) }
    public func orderFiles(_ ids: [String]) async throws { _ = try await raw("files.order", params: ["ids": ids]) }
    public func installTools(_ keys: [String]?) async throws {
        if let keys { _ = try await raw("tools.install", params: ["keys": keys]) }
        else { _ = try await raw("tools.install") }
    }
    public func plans(_ ids: [String]? = nil) async throws -> PlansReply {
        if let ids { return try await call("plans.get", params: ["ids": ids]) }
        return try await call("plans.get")
    }
    /// Model and/or height per file; pass `NSNull()` to go back to the default.
    public func setFiles(_ ids: [String], model: (any Sendable)? = nil, height: (any Sendable)? = nil) async throws {
        var params: [String: any Sendable] = ["ids": ids]
        if let model { params["model"] = model }
        if let height { params["height"] = height }
        _ = try await raw("files.set", params: params)
    }
    public func queueStatus() async throws -> QueueProgress { try await call("queue.status") }
    /// `overwrite`: files redone with the name of the video already made (Redo, confirmed).
    public func queueStart(_ ids: [String], overwrite: [String] = []) async throws {
        _ = try await raw("queue.start", params: ["ids": ids, "overwrite": overwrite])
    }
    public func queueCommand(_ method: String, id: String? = nil) async throws {
        if let id { _ = try await raw(method, params: ["id": id]) } else { _ = try await raw(method) }
    }
    public func lastLaunch() async throws -> LaunchRecord { try await call("queue.last") }
    public func calibrationRun() async throws -> CalibrationRun { try await call("calibration.status") }
    public func compareClips(_ id: String) async throws -> CompareClips { try await call("compare.clips", params: ["id": id]) }
    public func compareScan(_ id: String, more: Bool) async throws { _ = try await raw("compare.scan", params: ["id": id, "more": more]) }
    public func compareModels(_ id: String, clips: [Int]) async throws -> CompareModels {
        try await call("compare.models", params: ["id": id, "clips": clips])
    }
    public func compareStart(_ id: String, clips: [Int], models: [String], reference: Bool) async throws {
        _ = try await raw("compare.start", params: ["id": id, "clips": clips, "models": models, "reference": reference])
    }
    public func compareStatus() async throws -> CompareStatus { try await call("compare.status") }
    public func playable(_ path: String) async throws -> String {
        struct R: Decodable, Sendable { var path: String }
        return try await call("compare.playable", params: ["path": path], as: R.self).path
    }
    public func pausedWithOtherValues() async throws -> QueueProgress.Recipe? {
        struct R: Decodable, Sendable { var paused: QueueProgress.Recipe? }
        return try await call("settings.paused", as: R.self).paused
    }
    public func updatesState() async throws -> UpdatesState { try await call("updates.state") }
    public func checkUpdates() async throws -> UpdatesState { try await call("updates.check") }

    // MARK: incoming

    private func received(_ line: Data) {
        guard let object = try? JSONSerialization.jsonObject(with: line) as? [String: Any] else {
            // Not protocol: the engine's fd discipline makes this rare, but
            // never fatal.
            return
        }
        if let name = object["event"] as? String {
            let data = (object["data"]).flatMap { try? JSONSerialization.data(withJSONObject: $0) } ?? Data("{}".utf8)
            eventSink.yield(EngineEvent(name: name, data: data))
            return
        }
        guard let id = object["id"] as? Int, let continuation = pending.removeValue(forKey: id) else { return }
        if let error = object["error"] as? [String: Any] {
            continuation.resume(throwing: EngineError.remote(code: error["code"] as? String ?? "error",
                                                             message: error["message"] as? String ?? ""))
        } else if let result = object["result"] {
            if let data = try? JSONSerialization.data(withJSONObject: result, options: [.fragmentsAllowed]) {
                continuation.resume(returning: data)
            } else {
                continuation.resume(throwing: EngineError.badReply("result"))
            }
        } else {
            continuation.resume(throwing: EngineError.badReply("no result"))
        }
    }

    private func exited(status: Int32) {
        sidecar = nil
        failPending(EngineError.terminated)
        emit("engine.exited", ["status": Int(status)])
        guard !stopping else { return }
        let now = Date()
        crashes = crashes.filter { now.timeIntervalSince($0) < 120 } + [now]
        if crashes.count > 5 {
            gaveUp = true
            emit("engine.gave_up", [:])
            return
        }
        let delay = min(30.0, pow(2.0, Double(crashes.count - 1)))
        Task {
            try? await Task.sleep(for: .seconds(delay))
            await self.restartAfterCrash()
        }
    }

    private func restartAfterCrash() {
        guard !stopping, sidecar == nil, !gaveUp else { return }
        restarts += 1
        do { try spawn() } catch { exited(status: -1) }
    }

    private func failPending(_ error: Error) {
        let waiting = pending
        pending.removeAll()
        for (_, c) in waiting { c.resume(throwing: error) }
    }

    private func emit(_ name: String, _ data: [String: Any]) {
        let json = (try? JSONSerialization.data(withJSONObject: data)) ?? Data("{}".utf8)
        eventSink.yield(EngineEvent(name: name, data: json))
    }
}
