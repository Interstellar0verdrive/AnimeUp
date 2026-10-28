import Foundation

/// `compare.clips` / `compare.scan.done`.
public struct CompareClips: Codable, Sendable, Equatable {
    public struct Clip: Codable, Sendable, Equatable, Identifiable {
        public var kind: String
        public var startFrame: Int
        public var frames: Int
        public var start: Double
        public var range: String
        public var motion: Double
        public var brightness: Double
        public var reason: String
        public var thumbnail: String?
        public var id: Int { startFrame }
    }
    public var id: String
    public var clips: [Clip]
    public var selected: [Int]?
    public var exhausted: Bool?
    public var duration: Double?
    public var new: Int?
}

/// `compare.models`.
public struct CompareModels: Codable, Sendable, Equatable {
    public struct Card: Codable, Sendable, Equatable, Identifiable {
        public var key: String
        public var label: String
        public var verdict: String?
        public var estimate: Double?
        public var unreachable: String?
        public var fps: Double?
        public var clipSeconds: Double?
        public var id: String { key }
    }
    public var id: String
    public var models: [Card]
    public var recommended: String
    public var reason: String
    public var sure: Bool
    public var height: Int
    public var sourceHeight: Int
    public var referenceSeconds: Double?
    public var clips: Int
    public var calibrated: Bool
}

/// `compare.status` / `compare.progress` (the 1.6 status.json plus quota and request).
public struct CompareStatus: Codable, Sendable, Equatable {
    public struct Result: Codable, Sendable, Equatable {
        public struct ModelTime: Codable, Sendable, Equatable {
            public var chiave: String
            public var nome: String
            public var secondi: Double
            public var intero: Double
            public var metriche: [Double?]?
        }
        public var cartella: String
        public var file: [String: String]
        public var tipo: String
        public var intervallo: String
        public var modelli: [ModelTime]
    }
    public struct Segment: Codable, Sendable, Equatable {
        public var tipo: String
        public var tc: String
        public var intervallo: String
        public var chiave: String
        public var peso: Double
    }
    public struct Request: Codable, Sendable, Equatable {
        public struct Clip: Codable, Sendable, Equatable {
            public var kind: String
            public var startFrame: Int
            public var frames: Int
        }
        public var file: String
        public var id: String?
        public var models: [String]
        public var reference: Bool
        public var clips: [Clip]
    }
    public var state: String?
    public var file: String?
    public var started: Double?
    public var ended: Double?
    public var total: Int?
    public var done: Int?
    public var fraction: Double?
    public var quota: Double?
    public var text: String?
    public var fase: String?
    public var failures: [String]?
    public var results: [Result]?
    public var segmenti: [Segment]?
    public var request: Request?
    public var log: String?

    public var running: Bool { state == "running" }
}
