import Foundation

/// `plans.get`: how each analysed file will be processed.
public struct PlansReply: Codable, Sendable, Equatable {
    public var plans: [String: FilePlan]
    public var calibratedWhen: Double?
}

public struct FilePlan: Codable, Sendable, Equatable {
    public struct ModelOption: Codable, Sendable, Equatable, Identifiable {
        public var key: String
        public var label: String
        public var verdict: String?
        public var estimate: Double?
        public var unreachable: String?
        public var id: String { key }
    }

    public var ready: Bool
    public var error: String?
    public var recommended: String?
    public var reason: String?
    public var sure: Bool?
    public var models: [ModelOption]?
    public var model: String?
    public var height: Int?
    public var heightIsDefault: Bool?
    public var verdict: String?
    public var estimate: Double?
    public var estimateBest: Double?
    public var estimateWorst: Double?
    public var calibrated: Bool?
    public var modelLabel: String?
    public var scale: Int?
    public var downscale: Double?
    public var outputWidth: Int?
    public var outputHeight: Int?
    public var frames: Int?
    public var chunks: Int?
    public var chunkSize: Int?
    /// More chunks than usual because the work disk is tight.
    public var chunksTight: Bool?
    public var codec: String?
    public var pixFmt: String?
    public var crf: Int?
    public var preset: String?
    public var restoration: [String]?
    public var dedup: Bool?
    public var dedupRatio: Double?
    public var dedupMeasured: Bool?
    public var outputName: String?
    public var outputFolder: String?
    /// The folder is the source's own (the default); false when a folder was chosen.
    public var outputNextToSource: Bool?
    public var peakDiskGb: Double?
    public var warnings: [String]?
    public var diskWarnings: [String]?

    public func option(_ key: String) -> ModelOption? { models?.first { $0.key == key } }
}

extension Fmt {
    /// "~ 38m", "~ 2h 09m"
    public static func estimate(_ seconds: Double) -> String { "~ " + span(max(60, seconds)) }
}
