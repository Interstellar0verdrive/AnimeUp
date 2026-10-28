import Foundation

/// `files.list` / events: one video in the Queue.
public struct QueueFile: Codable, Sendable, Equatable, Identifiable {
    public enum State: String, Codable, Sendable {
        case analysing, queued, ready, failed, missing
    }

    public var id: String
    public var path: String
    public var name: String
    public var added: Double
    public var size: Int64?
    public var state: State
    public var report: FileReport?
    public var analysisStarted: Double?
    public var deep: Bool?
    public var error: String?
    public var dedupUnmeasurable: Bool?

    public var url: URL { URL(fileURLWithPath: path) }
    public var warnings: [String] { report?.warnings ?? [] }
}

/// The analysis report, already shaped for rows and the Data groups.
public struct FileReport: Codable, Sendable, Equatable {
    public var container: String
    public var duration: Double
    public var videoCodec: String
    public var pixFmt: String
    public var bitDepth: Int
    public var colorSpace: String?
    public var colorPrimaries: String?
    public var colorTransfer: String?
    public var audioTracks: Int
    public var subtitleTracks: Int
    public var subtitleCodecs: [String]
    public var chapters: Int
    public var width: Int
    public var height: Int
    public var displayWidth: Int
    public var displayHeight: Int
    public var sar: String
    public var anamorphic: Bool
    public var fps: Double?
    public var fpsText: String?
    public var fpsFraction: String?
    public var timebase: String
    public var frames: Int
    public var fields: String?
    public var dedupMeasured: Double?
    public var dedupRatio: Double?
    public var warnings: [String]

    /// "4:2:0" from the pixel format.
    public var chroma: String {
        for mark in ["444", "422", "420", "411", "410"] where pixFmt.contains(mark) {
            return mark.map(String.init).joined(separator: ":")
        }
        return pixFmt
    }

    /// "CFR" / "VFR" / "CFR + gaps".
    public var timebaseLabel: String {
        switch timebase {
        case "cfr": "CFR"
        case "vfr": "VFR"
        case "cfr_con_buchi": "CFR + gaps"
        default: "?"
        }
    }

    public var codecLabel: String {
        switch videoCodec.lowercased() {
        case "h264": "H.264"
        case "hevc", "h265": "HEVC"
        case "av1": "AV1"
        case "mpeg4": "MPEG-4"
        case "mpeg2video": "MPEG-2"
        case "vp9": "VP9"
        default: videoCodec.uppercased()
        }
    }
}

public struct FilesActivity: Codable, Sendable, Equatable {
    public var running: Bool
    public var id: String?
    public var name: String?
    public var started: Double?
    public var index: Int?
    public var total: Int?

    public init(running: Bool = false) { self.running = running }
}

public struct FilesList: Codable, Sendable, Equatable {
    public var files: [QueueFile]
    public var activity: FilesActivity
}

/// `files.add`.
public struct AddResult: Codable, Sendable, Equatable {
    public var added: [String]
    public var already: Int
    public var unsupported: Int
    public var missing: [String]
    public var emptyFolders: [String]
}

/// `tools.progress` events.
public struct ToolProgress: Codable, Sendable, Equatable {
    public enum State: String, Codable, Sendable { case waiting, running, done, failed }
    public var key: String
    public var state: State
    public var bytes: Int64?
    public var total: Int64?
    public var error: String?
}

/// `updates.state` / `updates.check`.
public struct UpdatesState: Codable, Sendable, Equatable {
    public var current: String
    public var checked: Double?
    public var latest: String?
    public var available: String?
    public var url: String
    public var result: String?
}

/// Formatting shared by rows and panels.
public enum Fmt {
    /// 23:41 or 1:02:03.
    public static func clock(_ seconds: Double) -> String {
        let s = Int(seconds.rounded())
        return s >= 3600 ? String(format: "%d:%02d:%02d", s / 3600, (s % 3600) / 60, s % 60)
                         : String(format: "%02d:%02d", s / 60, s % 60)
    }

    /// 23:41.1
    public static func clockTenths(_ seconds: Double) -> String {
        let whole = Int(seconds)
        let tenths = Int((seconds - Double(whole)) * 10)
        return whole >= 3600 ? String(format: "%d:%02d:%02d.%d", whole / 3600, (whole % 3600) / 60, whole % 60, tenths)
                             : String(format: "%02d:%02d.%d", whole / 60, whole % 60, tenths)
    }

    /// 1h 57m, 23m
    public static func span(_ seconds: Double) -> String {
        let m = Int((seconds / 60).rounded())
        return m >= 60 ? "\(m / 60)h \(String(format: "%02d", m % 60))m" : "\(m)m"
    }

    /// 0:14 elapsed.
    public static func elapsed(_ seconds: Double) -> String {
        let s = max(0, Int(seconds))
        return s >= 3600 ? String(format: "%d:%02d:%02d", s / 3600, (s % 3600) / 60, s % 60)
                         : String(format: "%d:%02d", s / 60, s % 60)
    }

    /// 655 MB, 1.1 GB
    public static func bytes(_ n: Int64) -> String {
        let mb = Double(n) / 1_000_000
        if mb >= 1000 { return String(format: "%.1f GB", mb / 1000) }
        return "\(Int(mb.rounded())) MB"
    }

    /// 34,071
    public static func count(_ n: Int) -> String {
        let f = NumberFormatter()
        f.numberStyle = .decimal
        f.locale = Locale(identifier: "en_US")
        return f.string(from: NSNumber(value: n)) ?? "\(n)"
    }
}
