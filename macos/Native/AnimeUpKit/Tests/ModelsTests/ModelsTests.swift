import Foundation
import Testing
@testable import Models

@Suite struct DecodingTests {
    @Test func calibrationDecodesSnakeCaseAndDigits() throws {
        let json = """
        {"state":"old_version","when":1700000000.0,"chip":"Apple M4 Pro","other_chip":null,"running":false,
         "last_run":null,"extraction_fps":140.0,"encoding_fps_1080p":8.7,
         "models":[{"key":"animevideov3","label":"Real-ESRGAN animevideov3","short":"animevideov3",
                    "fps_1080p":5.74,"factory_fps_1080p":3.76}]}
        """
        let c = try EngineCoding.decoder.decode(CalibrationState.self, from: Data(json.utf8))
        #expect(c.state == .oldVersion)
        #expect(c.encodingFps1080p == 8.7)
        #expect(c.models.first?.fps1080p == 5.74)
        #expect(c.models.first?.factoryFps1080p == 3.76)
        #expect(c.date == Date(timeIntervalSince1970: 1_700_000_000))
    }

    @Test func settingsDecode() throws {
        let json = """
        {"height":1080,"crf":18,"preset":"slower","dedup":true,"denoise":false,"force":false,"disk_gb":51,
         "pause_between_files":5,"deep_analysis":true,"language":"it","check_updates":true,"theme":"system","work_folder":null}
        """
        let s = try EngineCoding.decoder.decode(EngineSettings.self, from: Data(json.utf8))
        #expect(s.diskGb == 51 && s.language == "it" && s.workFolder == nil)
    }

    @Test func sizes() {
        #expect(SizeFormat.gb(263.4) == "263 GB")
        #expect(SizeFormat.gb(1000.2) == "1 TB")
        #expect(SizeFormat.gb(1995) == "2 TB")
    }
}

@Suite struct LocalizerTests {
    func catalogs() throws -> URL {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        for (lang, text) in [("en", "Hello {name}"), ("it", "Ciao {name}")] {
            let dir = root.appendingPathComponent(lang)
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            let plural = lang == "en" ? "{n} file" : "{n} file"
            let json = ["x.hello": text, "x.files.uno": "one \(plural)", "x.files.altri": plural + "s",
                        "x.only": lang == "en" ? "English only" : "Solo"]
            try JSONSerialization.data(withJSONObject: json).write(to: dir.appendingPathComponent("a.json"))
        }
        return root
    }

    @Test func liveSwitchAndPlaceholders() throws {
        let l = Localizer(folder: try catalogs(), language: "en")
        #expect(l.t("x.hello", ["name": "Ada"]) == "Hello Ada")
        l.setLanguage("it")
        #expect(l.t("x.hello", ["name": "Ada"]) == "Ciao Ada")
        #expect(l.tn("x.files", 1) == "one 1 file")
        #expect(l.t("missing.key") == "missing.key")
        l.setLanguage("fr")
        #expect(l.language == "en")
    }

    @Test func formatBraces() {
        #expect(Localizer.format("{{literal}} {a} {b:.1f}", ["a": 1, "b": "2.0"]) == "{literal} 1 2.0")
        #expect(Localizer.format("{unknown}", [:]) == "{unknown}")
    }

    /// The real catalogs: native.json exists in both languages with the same keys.
    @Test func realCatalogsHaveTheSameKeys() throws {
        let repo = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        let locales = repo.appendingPathComponent("src/animeup/locales")
        let l = Localizer(folder: locales)
        #expect(l.keys("en") == l.keys("it"))
        #expect(l.has("nat.start.title"))
    }
}
