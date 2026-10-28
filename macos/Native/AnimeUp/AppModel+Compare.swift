import AppKit
import Engine
import Models

/// The Compare wizard's state (boards C1–C5).
struct CompareState: Equatable {
    enum Step: Int { case clips, models, results }
    var fileId: String?
    var step: Step = .clips
    var clips: [CompareClips.Clip] = []
    var selected: Set<Int> = []
    var exhausted = false
    var scanning = false
    var scanText = ""
    var scanError: String?
    var models: CompareModels?
    var chosenModels: Set<String> = []
    var includeOriginal = true
    var status: CompareStatus?
    var clipTab = 0
    var left = "original"
    var right = ""
    var showUseMany = false
    var useKey = ""
}

extension AppModel {
    var compareFiles: [QueueFile] { files.filter { $0.state == .ready || $0.state == .analysing || $0.state == .queued } }

    func selectCompareFile(_ id: String) {
        guard cmp.fileId != id else { return }
        cmp = CompareState(fileId: id, status: cmp.status)
        Task { await loadClips(scanIfEmpty: true) }
    }

    /// On opening the tab: the running or last test's file, else the first analysed file.
    func openCompare() {
        if let st = cmp.status, let id = st.request?.id, files.contains(where: { $0.id == id }), cmp.fileId == nil {
            cmp.fileId = id
            cmp.step = .results
            Task { await loadClips(scanIfEmpty: false) }
            return
        }
        if cmp.fileId == nil, let f = files.first(where: { $0.state == .ready }) { selectCompareFile(f.id) }
    }

    func loadClips(scanIfEmpty: Bool) async {
        guard let id = cmp.fileId else { return }
        do {
            let c = try await engine.compareClips(id)
            applyClips(c)
            if c.clips.isEmpty && scanIfEmpty { scanClips(more: false) }
        } catch {
            cmp.scanError = nil
        }
    }

    func applyClips(_ c: CompareClips) {
        cmp.clips = c.clips
        cmp.exhausted = c.exhausted ?? false
        if cmp.selected.isEmpty {
            if let saved = c.selected, !saved.isEmpty {
                cmp.selected = Set(saved).intersection(c.clips.map(\.startFrame))
            } else {
                // Two picked at first: one in motion, one dark if there is one.
                var pick: [Int] = []
                if let m = c.clips.first(where: { $0.kind == "motion" }) { pick.append(m.startFrame) }
                if let d = c.clips.first(where: { $0.kind == "dark" || $0.kind == "static" }) { pick.append(d.startFrame) }
                cmp.selected = Set(pick.isEmpty ? c.clips.prefix(2).map(\.startFrame) : pick)
            }
        }
    }

    func scanClips(more: Bool) {
        guard let id = cmp.fileId else { return }
        cmp.scanning = true
        cmp.scanText = ""
        cmp.scanError = nil
        Task {
            do { try await engine.compareScan(id, more: more) } catch {
                cmp.scanning = false
                cmp.scanError = String(describing: error)
            }
        }
    }

    func goToModels() {
        guard let id = cmp.fileId else { return }
        cmp.step = .models
        Task {
            do {
                let m = try await engine.compareModels(id, clips: Array(cmp.selected))
                cmp.models = m
                if cmp.chosenModels.isEmpty {
                    var pick: Set<String> = [m.recommended]
                    if let alt = m.models.first(where: { $0.verdict == "verifica" && $0.unreachable == nil }) { pick.insert(alt.key) }
                    cmp.chosenModels = pick.filter { key in m.models.first { $0.key == key }?.unreachable == nil }
                }
            } catch { log.error("compare.models: \(error)") }
        }
    }

    func startTest() {
        guard let id = cmp.fileId else { return }
        let order = ["animevideov3", "cugan-denoise", "cugan", "cugan-conservative"]
        let models = order.filter { cmp.chosenModels.contains($0) }
        Task {
            do {
                try await engine.compareStart(id, clips: cmp.clips.map(\.startFrame).filter { cmp.selected.contains($0) },
                                              models: models, reference: cmp.includeOriginal)
                cmp.step = .results
                if let st = try? await engine.compareStatus() { applyCompareStatus(st) }
            } catch EngineError.remote(let code, _) where code == "gpu_busy" {
                alert = AppAlert(kind: .info(title: t("nat.cmp.gpu_busy_title"), text: t("nat.cmp.gpu_busy_text")))
            } catch {
                alert = AppAlert(kind: .info(title: t("nat.run.error_title"), text: String(describing: error)))
            }
        }
    }

    /// Render the Rest: the same request again; finished versions come from the cache.
    func renderRest() {
        guard let r = cmp.status?.request, let id = r.id ?? cmp.fileId else { return }
        Task {
            do {
                try await engine.compareStart(id, clips: r.clips.map(\.startFrame), models: r.models, reference: r.reference)
            } catch { alert = AppAlert(kind: .info(title: t("nat.run.error_title"), text: String(describing: error))) }
        }
    }

    func stopTest() { Task { _ = try? await engine.raw("compare.stop") } }

    func applyCompareStatus(_ st: CompareStatus) {
        let wasRunning = cmp.status?.running ?? false
        cmp.status = st
        if st.running, let id = st.request?.id, cmp.fileId == id { cmp.step = .results }
        if wasRunning && !st.running {
            let keys = Set(st.results?.flatMap { $0.file.keys } ?? [])
            if cmp.right.isEmpty || !keys.contains(cmp.right) {
                cmp.right = st.request?.models.first(where: { keys.contains($0) }) ?? keys.first ?? ""
            }
            if !keys.contains(cmp.left) { cmp.left = keys.contains("original") ? "original" : (keys.first ?? "") }
            notify(t("nat.cmp.note_done_title"), t("nat.cmp.note_done", ["name": file(st.request?.id ?? "")?.name ?? ""]))
        }
    }

    func useModel(_ key: String, for ids: [String]) {
        chooseModel(key, for: ids)
    }
}
