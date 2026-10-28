#if DEBUG
import AppKit
import DesignSystem
import Models
import SwiftUI

/// Debug only: `ANIMEUP_QA=<scenario>` drives the app through its own model
/// methods (the same ones the buttons call) and writes renders and a log
/// line at each checkpoint, to `ANIMEUP_SNAPSHOT`-prefixed PNGs. Alerts are
/// skipped: the script calls what their buttons would call.
@MainActor
enum DebugQA {
    static func scheduleIfAsked(model: AppModel) {
        let env = ProcessInfo.processInfo.environment
        guard let scenario = env["ANIMEUP_QA"], let base = env["ANIMEUP_SNAPSHOT"] else { return }
        Task { @MainActor in
            for _ in 0..<120 where model.status != .ready { try? await Task.sleep(for: .milliseconds(500)) }
            try? await Task.sleep(for: .seconds(3))
            note("QA \(scenario) start, tab \(model.tab)")
            switch scenario {
            case "queue": await queue(model, base, names: ["Part 1", "Part 2"], height: 720, model: "animevideov3", stopSecond: false)
            case "stop": await queue(model, base, names: (env["ANIMEUP_QA_FILES"] ?? "Part 3,Part 4").components(separatedBy: ","), height: 1080, model: "animevideov3", stopSecond: true)
            case "follow": await follow(model, base)
            case "files": await files(model, base)
            case "compare": await compare(model, base)
            case "italian": await italian(model, base)
            case "attach":
                // Attach to a running two-file queue, in the queue's own order.
                let order = model.progress.queue.ids ?? []
                if order.count == 2 { await afterStart(model, base, chosen: order, stopSecond: true) }
                else { note("no two-file queue running") }
            default: note("QA: unknown scenario")
            }
            note("QA \(scenario) end")
        }
    }

    static func note(_ s: String) { log.info("QA: " + s) }

    static func wait(_ seconds: Double, _ what: String, _ cond: () -> Bool) async -> Bool {
        let end = Date().addingTimeInterval(seconds)
        while Date() < end {
            if cond() { return true }
            try? await Task.sleep(for: .seconds(1))
        }
        note("timeout waiting for \(what)")
        return false
    }

    static func describe(_ model: AppModel) -> String {
        let q = model.progress.queue
        var s = "running \(q.running) paused \(q.paused) pos \(q.position ?? -1)/\(q.total ?? -1) resting \(q.restingUntil.map { Int($0 - Date().timeIntervalSince1970) } ?? -1)s finish \(q.finish.map { model.clockTime($0) } ?? "-")"
        for id in q.ids ?? [] {
            let j = model.job(id)
            s += " | \(model.file(id)?.name.prefix(14) ?? "?") \(j?.state.rawValue ?? "-") \(Int((j?.fraction ?? 0) * 100))% \(j?.stage ?? "")"
        }
        return s
    }

    static func ids(_ model: AppModel, _ names: [String]) -> [String] {
        names.compactMap { n in model.files.first { $0.name.contains(n) }?.id }
    }

    static func queue(_ model: AppModel, _ base: String, names: [String], height: Int, model key: String?, stopSecond: Bool) async {
        _ = try? await model.engine.setSettings(["pause_between_files": 1])
        await model.loadAll()
        let chosen = ids(model, names)
        guard chosen.count == names.count else { note("files not found: \(names)"); return }
        for id in chosen { model.chooseHeight(height, for: id) }
        if let key { model.chooseModel(key, for: chosen) }
        model.unticked = Set(model.files.map(\.id)).subtracting(chosen)
        try? await Task.sleep(for: .seconds(4))
        await model.refreshPlans()
        note("plans: " + chosen.map { "\(model.plan($0)?.model ?? "-") \(model.plan($0)?.estimate.map { Fmt.span($0) } ?? "-")" }.joined(separator: ", "))
        model.markFinishedSeen(); model.finished = nil
        model.tab = .queue
        model.startQueue()
        _ = await wait(30, "queue order") { (model.progress.queue.ids ?? []).count == chosen.count }
        await afterStart(model, base, chosen: model.progress.queue.ids ?? chosen, stopSecond: stopSecond)
    }

    static func afterStart(_ model: AppModel, _ base: String, chosen: [String], stopSecond: Bool) async {
        _ = await wait(120, "first running") { model.job(chosen[0])?.state == .running }
        try? await Task.sleep(for: .seconds(8))
        note(describe(model))
        DebugSnapshot.renderQueue(model, "\(base)-1-first-running.png")
        _ = await wait(1800, "rest") { model.progress.queue.restingUntil != nil || !model.progress.queue.running }
        note(describe(model))
        DebugSnapshot.renderQueue(model, "\(base)-2-resting.png")
        DebugSnapshot.renderSidebar(model, "\(base)-2-resting-sidebar.png")
        if model.progress.queue.restingUntil != nil {
            try? await Task.sleep(for: .seconds(5))
            note("Start Now")
            model.command("queue.startNow")
            let ok = await wait(40, "second running") { model.job(chosen[1])?.state == .running }
            note("after Start Now: \(ok) \(describe(model))")
        }
        _ = await wait(120, "second at 15%") { (model.job(chosen[1])?.fraction ?? 0) > 0.15 || !model.progress.queue.running }
        note(describe(model))
        DebugSnapshot.renderQueue(model, "\(base)-3-second-running.png")
        DebugSnapshot.renderSidebar(model, "\(base)-3-second-sidebar.png")
        if stopSecond {
            note("Stop All")
            model.command("queue.stopAll")
            _ = await wait(60, "stopped") { !model.progress.queue.running }
            try? await Task.sleep(for: .seconds(3))
            note(describe(model) + " second state \(model.job(chosen[1])?.state.rawValue ?? "-") recipe \(String(describing: model.job(chosen[1])?.recipe))")
            DebugSnapshot.renderQueue(model, "\(base)-4-interrupted.png")
            if model.showFinished { DebugSnapshot.render(FinishedSheet().environment(model), width: 640, "\(base)-4-finished.png") }
            note("Resume")
            model.markFinishedSeen()
            model.command("job.resume", id: chosen[1])
            _ = await wait(60, "resumed") { model.job(chosen[1])?.state == .running }
            note(describe(model))
            try? await Task.sleep(for: .seconds(6))
            DebugSnapshot.renderQueue(model, "\(base)-5-resumed.png")
            _ = await wait(2400, "resumed done") { model.job(chosen[1])?.state == .done }
            try? await Task.sleep(for: .seconds(4))
            note("resumed job: \(describe(model)) stages \(String(describing: model.job(chosen[1])?.stages))")
            model.markFinishedSeen()
            model.expanded = chosen[1]
            DebugSnapshot.renderQueue(model, "\(base)-6-completed-panel.png")
            model.expanded = nil
            if let other = ids(model, [env("ANIMEUP_QA_DISCARD") ?? "Part 1"]).first {
                await discard(model, base, other)
            }
            exit(0)
        } else {
            await follow(model, base)
        }
    }

    static func env(_ k: String) -> String? { ProcessInfo.processInfo.environment[k] }

    /// Start one file, Stop All early, then Discard it (what the alert's button calls).
    static func discard(_ model: AppModel, _ base: String, _ id: String) async {
        model.unticked = Set(model.files.map(\.id)).subtracting([id])
        model.startQueue()
        _ = await wait(90, "discard file running") { (model.job(id)?.fraction ?? 0) > 0.05 }
        model.command("queue.stopAll")
        _ = await wait(60, "stopped") { !model.progress.queue.running && model.job(id)?.state == .interrupted }
        try? await Task.sleep(for: .seconds(3))
        let folders = (try? FileManager.default.contentsOfDirectory(atPath: "/Volumes/USB_1TB/AnimeUp-native-test/Jobs/JOBS")) ?? []
        note("before discard: \(model.job(id)?.state.rawValue ?? "-") folders \(folders)")
        DebugSnapshot.renderQueue(model, "\(base)-8-interrupted-other.png")
        model.markFinishedSeen()
        model.command("job.discard", id: id)
        try? await Task.sleep(for: .seconds(5))
        await model.refreshFiles()
        let after = (try? FileManager.default.contentsOfDirectory(atPath: "/Volumes/USB_1TB/AnimeUp-native-test/Jobs/JOBS")) ?? []
        note("after discard: job \(model.job(id)?.state.rawValue ?? "none") file \(model.file(id)?.state.rawValue ?? "-") folders \(after)")
        DebugSnapshot.renderQueue(model, "\(base)-9-discarded.png")
    }

    static func line(_ model: AppModel) -> String {
        model.files.map { f in "\(f.name.prefix(22)) \(f.state.rawValue)\(model.job(f.id).map { "/" + $0.state.rawValue } ?? "")\(model.isTicked(f) ? "+" : "")" }
            .joined(separator: " | ")
    }

    /// Re-analyse All, remove + Undo, add a folder with subfolders.
    static func files(_ model: AppModel, _ base: String) async {
        model.tab = .queue
        note("before: \(model.files.count) files: \(line(model))")
        model.reanalyse(nil)
        _ = await wait(20, "analysing") { model.files.contains { $0.state == .analysing || $0.state == .queued } }
        note("re-analysing: \(line(model))")
        DebugSnapshot.renderQueue(model, "\(base)-1-reanalysing.png")
        _ = await wait(400, "analysed") { !model.files.contains { $0.state == .analysing || $0.state == .queued } }
        note("re-analysed: \(line(model))")
        guard let victim = model.files.first(where: { $0.name.contains("Part 3") }) else { return }
        let before = (model.plan(victim.id)?.model, model.job(victim.id)?.state)
        model.remove([victim.id])
        try? await Task.sleep(for: .seconds(3))
        note("removed: \(model.files.count) files")
        model.undoRemove()
        _ = await wait(60, "undo") { model.files.contains { $0.name == victim.name && $0.state == .ready } }
        try? await Task.sleep(for: .seconds(3))
        await model.refreshPlans()
        let back = model.files.first { $0.name == victim.name }
        note("undo: back \(back != nil) same id \(back?.id == victim.id) model \(String(describing: before.0)) -> \(String(describing: back.flatMap { model.plan($0.id)?.model })) job \(String(describing: before.1)) -> \(String(describing: back.flatMap { model.job($0.id)?.state }))")
        model.lastReceived = nil
        model.add([URL(fileURLWithPath: "/Volumes/USB_1TB/AnimeUp-native-test/videos")], subfolders: true)
        try? await Task.sleep(for: .seconds(6))
        note("added folder: lastReceived \(String(describing: model.lastReceived)) alert \(String(describing: model.alert)) \(model.files.count) files")
        DebugSnapshot.renderQueue(model, "\(base)-2-after-add.png")
        DebugSnapshot.renderComposite(model, "\(base)-2-start-after-add.png")
        await italian(model, base)
    }

    /// Live switch to Italian with Queue and Compare: render the main screens.
    static func italian(_ model: AppModel, _ base: String) async {
        func completed(_ lang: String) {
            if let f = model.files.first(where: { $0.name.contains("Part 4") }), let j = model.job(f.id), j.state == .done {
                DebugSnapshot.render(JobCompleted(file: f, job: j).environment(model).padding(20).background(AU.bg), width: 900, "\(base)-completed-\(lang).png")
            }
        }
        completed("en")
        model.tab = .queue
        model.setLanguage("it")
        try? await Task.sleep(for: .seconds(4))
        await model.loadAll()
        try? await Task.sleep(for: .seconds(2))
        DebugSnapshot.renderQueue(model, "\(base)-it-queue.png")
        if let f = model.files.first(where: { $0.name.contains("Part 2") }) {
            model.expanded = f.id
            DebugSnapshot.renderQueue(model, "\(base)-it-queue-open.png")
            model.expanded = nil
        }
        DebugSnapshot.renderComposite(model, "\(base)-it-start.png")
        model.openCompare()
        try? await Task.sleep(for: .seconds(3))
        DebugSnapshot.renderPage(CompareView(), model, "\(base)-it-compare.png")
        for tab in SettingsTab.allCases {
            DebugSnapshot.render(SettingsPage(tab: tab).environment(model), width: 640, "\(base)-it-settings-\(tab.rawValue).png")
        }
        DebugSnapshot.render(FinishedSheet().environment(model), width: 640, "\(base)-it-finished.png")
        completed("it")
        DebugSnapshot.render(CalibrationSheet().environment(model), width: 540, "\(base)-it-calibration.png")
        model.setLanguage("en")
        try? await Task.sleep(for: .seconds(2))
        exit(0)
    }

    static func cmpLine(_ model: AppModel) -> String {
        let st = model.cmp.status
        let keys = (st?.results ?? []).map { "\($0.tipo):\($0.file.keys.sorted().joined(separator: ","))" }
        return "step \(model.cmp.step) state \(st?.state ?? "-") \(Int((st?.fraction ?? 0) * 100))% results \(keys) partial \(st?.parziali?.mapValues { $0.count } ?? [:])"
    }

    /// Start a test, stop it halfway, Render the Rest, then use a model.
    static func compare(_ model: AppModel, _ base: String) async {
        guard let f = model.files.first(where: { $0.name.contains("Part 1") }) else { return }
        model.tab = .compare
        model.selectCompareFile(f.id)
        _ = await wait(300, "clips") { model.cmp.clips.count >= 2 && !model.cmp.scanning }
        note("clips \(model.cmp.clips.count) selected \(model.cmp.selected.count)")
        model.goToModels()
        _ = await wait(60, "models") { model.cmp.models != nil }
        model.cmp.chosenModels = ["animevideov3", "cugan"]
        model.cmp.includeOriginal = true
        model.startTest()
        _ = await wait(60, "test running") { model.cmp.status?.running == true }
        _ = await wait(600, "half") { (model.cmp.status?.fraction ?? 0) >= 0.45 || model.cmp.status?.running != true }
        note("before stop: " + cmpLine(model))
        model.stopTest()
        _ = await wait(60, "stopped") { model.cmp.status?.running != true }
        try? await Task.sleep(for: .seconds(3))
        note("stopped: " + cmpLine(model))
        DebugSnapshot.renderPage(CompareView(), model, "\(base)-1-stopped.png")
        model.renderRest()
        _ = await wait(60, "rest running") { model.cmp.status?.running == true }
        _ = await wait(900, "rest done") { model.cmp.status?.running != true }
        try? await Task.sleep(for: .seconds(3))
        note("rest done: " + cmpLine(model))
        DebugSnapshot.renderPage(CompareView(), model, "\(base)-2-results.png")
        let before = model.plan(f.id)?.model
        model.useModel("cugan", for: [f.id])
        try? await Task.sleep(for: .seconds(4))
        await model.refreshPlans()
        note("Use for This File: \(before ?? "-") -> \(model.plan(f.id)?.model ?? "-")")
        model.cmp.useKey = "animevideov3"
        let rows = model.files.filter { $0.state == .ready }
        let picked = rows.filter { r in
            let p = model.plans[r.id]
            return p?.model != "animevideov3" && p?.option("animevideov3")?.verdict != "no" && p?.option("animevideov3")?.unreachable == nil
        }.map(\.id)
        DebugSnapshot.render(UseManySheet().environment(model), width: 620, "\(base)-3-usemany.png")
        let was = rows.map { "\($0.name.prefix(16))=\(model.plan($0.id)?.model ?? "-")" }
        model.useModel("animevideov3", for: picked)
        try? await Task.sleep(for: .seconds(4))
        await model.refreshPlans()
        note("Use for Multiple Files: picked \(picked.compactMap { model.file($0)?.name.prefix(16) }) before \(was) after \(rows.map { "\($0.name.prefix(16))=\(model.plan($0.id)?.model ?? "-")" })")
        model.tab = .queue
        DebugSnapshot.renderQueue(model, "\(base)-4-queue.png")
        exit(0)
    }

    /// Relaunched while a job runs: which tab, then follow it to the end.
    static func follow(_ model: AppModel, _ base: String) async {
        note("relaunched: tab \(model.tab) \(describe(model))")
        DebugSnapshot.renderQueue(model, "\(base)-6-relaunched.png")
        _ = await wait(2400, "queue end") { !model.progress.queue.running && model.finished != nil && model.showFinished }
        try? await Task.sleep(for: .seconds(3))
        note("finished: tab \(model.tab) showFinished \(model.showFinished) \(describe(model))")
        if let f = model.finished { note("launch: \(f)") }
        DebugSnapshot.renderQueue(model, "\(base)-7-done.png")
        DebugSnapshot.render(FinishedSheet().environment(model), width: 640, "\(base)-7-finished.png")
        exit(0)
    }
}
#endif
