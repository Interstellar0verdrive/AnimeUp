import Foundation

// Codable mirrors of what `animeup serve` answers (src/animeup/serve.py).
// The engine writes snake_case keys; decode with `EngineCoding.decoder`.

public enum EngineCoding {
    public static var decoder: JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }

    public static var encoder: JSONEncoder {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        e.outputFormatting = [.sortedKeys]
        return e
    }
}

/// `hello`: who answered.
public struct EngineHello: Codable, Sendable, Equatable {
    public var engine: String
    public var version: String
    public var `protocol`: Int
    public var pid: Int
    public var python: String
    public var language: String
    public var stateFolder: String
    public var codeFolder: String
}

/// `settings.get` / `settings.set`: the keys of records/settings.json.
public struct EngineSettings: Codable, Sendable, Equatable {
    public var height: Int
    public var crf: Int
    public var preset: String
    public var dedup: Bool
    public var denoise: Bool
    public var force: Bool
    public var diskGb: Int
    public var pauseBetweenFiles: Int
    public var deepAnalysis: Bool
    public var language: String
    public var checkUpdates: Bool
    public var theme: String
    public var workFolder: String?
    public var notifications: Bool?
    public var dockProgress: Bool?
    public var keepWorkFiles: Bool?
    public var autoInstall: Bool?

    public init(height: Int = 1080, crf: Int = 18, preset: String = "slower", dedup: Bool = true,
                denoise: Bool = false, force: Bool = false, diskGb: Int = 51,
                pauseBetweenFiles: Int = 5, deepAnalysis: Bool = true, language: String = "en",
                checkUpdates: Bool = true, theme: String = "system", workFolder: String? = nil) {
        self.height = height; self.crf = crf; self.preset = preset; self.dedup = dedup
        self.denoise = denoise; self.force = force; self.diskGb = diskGb
        self.pauseBetweenFiles = pauseBetweenFiles; self.deepAnalysis = deepAnalysis
        self.language = language; self.checkUpdates = checkUpdates; self.theme = theme
        self.workFolder = workFolder
    }
}

/// `machine.info`.
public struct MachineInfo: Codable, Sendable, Equatable {
    public var chip: String
    public var chipShort: String
    public var cpuCores: Int?
    public var cpuPerformanceCores: Int?
    public var cpuEfficiencyCores: Int?
    public var gpuCores: Int?
    public var memoryGb: Int?
    public var macosVersion: String
    public var macosName: String
    public var arch: String
}

/// `calibration.state`.
/// `calibration.details`: every calibration of this Mac (newest first) and the
/// factory numbers, as the results sheet shows them (board K4).
public struct CalibrationDetails: Codable, Sendable, Equatable {
    public struct Model: Codable, Sendable, Equatable {
        public var key: String
        /// Frames per second on a 540p source, by scale ("2", "3", "4").
        public var fps: [String: Double?]
        /// Scales not measured: they use the speed of the same network's model.
        public var borrowed: [Int]
        /// Frames per second on a 1080p source, at 2x.
        public var bigFps: Double?
        /// The upscaling time of the reference episode.
        public var episodeSeconds: Double?
    }

    public struct Entry: Codable, Sendable, Equatable, Identifiable {
        public var id: String
        public var when: Double?
        public var version: String?
        public var models: [Model]
        public var extractionFps: Double?
        public var dedupFps: Double?
        public var encodingFps: Double?
        public var saveThreads: Int?

        public var date: Date? { when.map { Date(timeIntervalSince1970: $0) } }
        public var isFactory: Bool { when == nil }
        public func model(_ key: String) -> Model? { models.first { $0.key == key } }
    }

    public var calibrations: [Entry]
    public var factory: Entry
    public var episodeHeight: Int
    public var episodeMinutes: Int
}

public struct CalibrationState: Codable, Sendable, Equatable {
    public enum State: String, Codable, Sendable {
        case done
        case never
        case otherMac = "other_mac"
        case oldVersion = "old_version"
    }

    public struct ModelSpeed: Codable, Sendable, Equatable, Identifiable {
        public var key: String
        public var label: String
        public var short: String
        public var fps1080p: Double?
        public var factoryFps1080p: Double?
        public var id: String { key }

        enum CodingKeys: String, CodingKey {
            case key, label, short
            case fps1080p = "fps1080P"
            case factoryFps1080p = "factoryFps1080P"
        }
    }

    public var state: State
    public var when: Double?
    public var chip: String?
    public var otherChip: String?
    public var running: Bool
    public var lastRun: String?
    public var extractionFps: Double?
    public var encodingFps1080p: Double?
    public var models: [ModelSpeed]

    enum CodingKeys: String, CodingKey {
        case state, when, chip, otherChip, running, lastRun, extractionFps, models
        case encodingFps1080p = "encodingFps1080P"
    }

    public var date: Date? { when.map { Date(timeIntervalSince1970: $0) } }
    public var isCalibrated: Bool { state == .done }
}

/// `tools.status`.
public struct ToolsStatus: Codable, Sendable, Equatable {
    public struct Tool: Codable, Sendable, Equatable, Identifiable {
        public var key: String
        public var name: String
        public var present: Bool
        public var vendored: Bool
        public var verified: Bool
        public var version: String?
        public var expectedVersion: String
        public var path: String?
        public var id: String { key }
    }

    public struct Python: Codable, Sendable, Equatable {
        public var version: String
        public var short: String
    }

    public var tools: [Tool]
    public var python: Python
    public var allVerified: Bool
    public var binFolder: String
}

/// `folders.state`.
public struct FoldersState: Codable, Sendable, Equatable {
    public var workFolder: String
    /// nil: next to the originals.
    public var finishedFolder: String?
    public var workFolderDefault: String
    public var isDefault: Bool
    public var exists: Bool
    public var reachable: Bool
    public var volume: String
    public var freeGb: Double
    public var totalGb: Double
    public var spaceRuleGb: Int
    public var spaceMinGb: Int
    public var spaceSettingGb: Int

    /// Less free than the space slider's minimum: there is no limit worth
    /// choosing (the engine still puts the slider's top at minimum + 1, which
    /// read "51 GB of 48 GB free").
    public var tooFull: Bool { reachable && freeGb < Double(spaceMinGb) }

    /// Enough to work, but the prudent ceiling (85% of the free space, or all
    /// of it but 40 GB) fell under the minimum and was raised to minimum + 1:
    /// a slider from 50 to 51 has nothing to choose. The app says how close
    /// to full the disk is instead.
    public var tight: Bool { reachable && !tooFull && spaceRuleGb <= spaceMinGb + 1 }

    /// What stays free for the system when a job takes all it may.
    public var leftForSystemGb: Double { max(0, freeGb - Double(spaceRuleGb)) }
}

/// Formats sizes the way the boards do: "263 GB", "1 TB".
public enum SizeFormat {
    public static func gb(_ value: Double) -> String {
        if value >= 1000 {
            let tb = value / 1000
            let one = (tb * 10).rounded() / 10
            return one == one.rounded() ? "\(Int(one)) TB" : String(format: "%.1f TB", one)
        }
        return "\(Int(value.rounded())) GB"
    }
}
