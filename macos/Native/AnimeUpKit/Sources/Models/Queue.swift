import Foundation

/// `queue.progress` / `queue.status`.
public struct QueueProgress: Codable, Sendable, Equatable {
    public struct Queue: Codable, Sendable, Equatable {
        public var running: Bool
        public var paused: Bool
        public var total: Int?
        public var position: Int?
        public var ids: [String]?
        public var started: Double?
        public var leftMin: Double?
        public var leftMax: Double?
        public var finish: Double?
        public var restingUntil: Double?

        public init() { running = false; paused = false }
        public var resting: Bool { restingUntil != nil }
    }

    public struct Job: Codable, Sendable, Equatable {
        public enum State: String, Codable, Sendable { case running, paused, done, interrupted, queued }
        public var id: String
        public var state: State
        public var stage: String?
        public var fraction: Double?
        public var chunk: Int?
        public var chunks: Int?
        public var chunkDone: Int?
        public var chunkTotal: Int?
        public var framesDone: Int?
        public var framesTotal: Int?
        public var fps: Double?
        public var left: Double?
        public var elapsed: Double?
        public var pausedSince: Double?
        public var log: String?
        public var seconds: Double?
        public var warnings: [String]?
        public var defective: Bool?
        public var output: String?
        public var recipe: Recipe?
    }

    /// The values a job started with, where they differ from the settings now.
    public struct Recipe: Codable, Sendable, Equatable {
        public var values: [String: JSONValue]
        public var model: String?
        public var id: String?
        public var name: String?
    }

    public var queue: Queue
    public var files: [String: Job]
    public var now: Double?

    public init() { queue = Queue(); files = [:] }
}

/// `calibration.status` / `calibration.progress`.
public struct CalibrationRun: Codable, Sendable, Equatable {
    public struct Row: Codable, Sendable, Equatable, Identifiable {
        public var key: String
        public var before: Double?
        public var now: Double?
        public var id: String { key }
    }
    public var state: String?
    public var started: Double?
    public var index: Int?
    public var total: Int?
    public var fraction: Double?
    public var left: Double?
    public var label: String?
    public var error: String?
    public var seen: Bool?
    public var ended: Double?
    public var steps: [String]
    public var stepStarted: [Double?]?
    public var running: Bool
    public var log: String
    public var table: [Row]
}

/// `queue.finished` / `queue.last`: the launch record (records/launches.jsonl).
public struct LaunchRecord: Codable, Sendable, Equatable {
    public var launch: [String: JSONValue]?
}

/// A small JSON value for records we only read a few fields from.
public enum JSONValue: Codable, Sendable, Equatable {
    case string(String), number(Double), bool(Bool), array([JSONValue]), object([String: JSONValue]), null

    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let n = try? c.decode(Double.self) { self = .number(n) }
        else if let s = try? c.decode(String.self) { self = .string(s) }
        else if let a = try? c.decode([JSONValue].self) { self = .array(a) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let s): try c.encode(s)
        case .number(let n): try c.encode(n)
        case .bool(let b): try c.encode(b)
        case .array(let a): try c.encode(a)
        case .object(let o): try c.encode(o)
        case .null: try c.encodeNil()
        }
    }

    public var string: String? { if case .string(let s) = self { return s }; return nil }
    public var number: Double? { if case .number(let n) = self { return n }; return nil }
    public var array: [JSONValue] { if case .array(let a) = self { return a }; return [] }
}
