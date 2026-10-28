import AVFoundation
import DesignSystem
import Models
import SwiftUI

/// Boards C1–C5 (+ E1–E8): pick clips, pick models, run the test, compare.
struct CompareView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            header
            if model.compareFiles.isEmpty {
                NoteView(.accent, title: model.t("nat.cmp.no_files_title"), text: model.t("nat.cmp.no_files"))
                Spacer()
            } else if model.files.first(where: { $0.id == model.cmp.fileId })?.state != .ready && model.cmp.status?.running != true {
                NoteView(.accent, title: model.t("nat.cmp.waiting_title"), text: model.t("nat.cmp.waiting"))
                Spacer()
            } else {
                StepIndicator(step: model.cmp.step)
                switch model.cmp.step {
                case .clips: CompareClipsStep()
                case .models: CompareModelsStep()
                case .results: CompareResultsStep()
                }
            }
        }
        .padding(.top, 28)
        .padding(.horizontal, 28)
        .padding(.bottom, 24)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .ignoresSafeArea(edges: .top)
        .onAppear { model.openCompare() }
    }

    private var header: some View {
        HStack(alignment: .bottom) {
            VStack(alignment: .leading, spacing: 6) {
                Text(model.t("nat.tab.compare")).auPageTitle()
                Text(model.t("nat.cmp.intro1") + "\n" + model.t("nat.cmp.intro2")).auBody()
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
            VStack(alignment: .leading, spacing: 4) {
                Text(model.t("nat.cmp.file")).auLabel()
                Menu {
                    ForEach(model.compareFiles) { f in
                        Button(f.state == .ready ? f.name : "\(f.name) — \(model.t("nat.cmp.analysing"))") {
                            model.selectCompareFile(f.id)
                        }
                        .disabled(f.state != .ready)
                    }
                } label: {
                    PopupLabel(model.files.first { $0.id == model.cmp.fileId }?.name ?? model.t("nat.cmp.pick_file"), width: 320)
                }
                .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize()
                .disabled(model.cmp.status?.running == true)
            }
        }
    }
}

/// DS4 step indicator: Clips › Models › Results.
struct StepIndicator: View {
    @Environment(AppModel.self) private var model
    var step: CompareState.Step

    var body: some View {
        HStack(spacing: 8) {
            ForEach([CompareState.Step.clips, .models, .results], id: \.rawValue) { s in
                if s != .clips { Image(systemName: "chevron.right").font(.system(size: 9)).foregroundStyle(AU.text3) }
                HStack(spacing: 6) {
                    ZStack {
                        if s.rawValue < step.rawValue {
                            Circle().fill(AU.greenBg).overlay(Circle().strokeBorder(AU.greenLine))
                            Image(systemName: "checkmark").font(.system(size: 8, weight: .bold)).foregroundStyle(AU.greenText)
                        } else if s == step {
                            if model.cmp.status?.running == true && s == .results { Spinner(size: 16) }
                            else {
                                Circle().fill(AU.primary)
                                Text("\(s.rawValue + 1)").font(.system(size: 10, weight: .bold, design: .monospaced)).foregroundStyle(AU.onPrimary)
                            }
                        } else {
                            Circle().strokeBorder(AU.glassLine)
                            Text("\(s.rawValue + 1)").font(.system(size: 10, design: .monospaced)).foregroundStyle(AU.text3)
                        }
                    }
                    .frame(width: 18, height: 18)
                    Text(model.t("nat.cmp.step.\(s.rawValue)")).font(.system(size: 12, weight: s == step ? .semibold : .regular))
                        .foregroundStyle(s == step ? AU.text : s.rawValue < step.rawValue ? AU.greenText : AU.text3)
                    if s == .clips && step.rawValue > 0 {
                        Text(model.localizer.tn("nat.cmp.n_picked", model.cmp.selected.count)).font(AUFont.smallNumbers).foregroundStyle(AU.text3)
                    }
                }
                .padding(.horizontal, 10).padding(.vertical, 4)
                .background(Capsule().fill(s == step ? AU.sel : s.rawValue < step.rawValue ? AU.greenBg : .clear))
                .overlay(Capsule().strokeBorder(s == step ? AU.softLine : s.rawValue < step.rawValue ? AU.greenLine : AU.glassLine))
                .onTapGesture {
                    if s.rawValue < step.rawValue && model.cmp.status?.running != true { model.cmp.step = s }
                }
            }
        }
    }
}

// MARK: - Step 1: clips

struct CompareClipsStep: View {
    @Environment(AppModel.self) private var model
    private let columns = Array(repeating: GridItem(.flexible(), spacing: 12), count: 4)

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let err = model.cmp.scanError {
                NoteView(.red, title: model.t("nat.cmp.scan_failed"), text: err) {
                    Button(model.t("nat.btn.retry")) { model.scanClips(more: false) }.buttonStyle(AUTintedButtonStyle(.red))
                }
            }
            if model.cmp.clips.isEmpty {
                if model.cmp.scanning {
                    HStack(spacing: 8) {
                        Spinner(size: 14)
                        Text(model.cmp.scanText.isEmpty ? model.t("nat.cmp.scanning") : model.cmp.scanText).auSmall(AU.text)
                    }
                    .padding(.vertical, 40).frame(maxWidth: .infinity)
                } else if model.cmp.scanError == nil {
                    NoteView(.yellow, title: model.t("nat.cmp.no_clips_title"), text: model.t("nat.cmp.no_clips"))
                }
                Spacer()
            } else {
                ScrollView {
                    LazyVGrid(columns: columns, spacing: 12) {
                        ForEach(model.cmp.clips) { c in ClipCard(clip: c) }
                    }
                    HStack(spacing: 10) {
                        if model.cmp.scanning {
                            Spinner(size: 12)
                            Text(model.cmp.scanText.isEmpty ? model.t("nat.cmp.scanning") : model.cmp.scanText).auSmall()
                        } else if model.cmp.exhausted {
                            Text(model.t("nat.cmp.no_more")).auSmall()
                        } else {
                            Button { model.scanClips(more: true) } label: { Label(model.t("nat.cmp.find_more"), systemImage: "plus.magnifyingglass") }
                                .auButton(.secondary, .regular)
                        }
                    }
                    .padding(.top, 12)
                }
                ActionBar {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(model.localizer.tn("nat.cmp.clips_selected", model.cmp.selected.count)).font(.system(size: 13, weight: .semibold))
                        Text(selectedLine).auSmall()
                    }
                } trailing: {
                    Button { model.goToModels() } label: {
                        HStack(spacing: 5) { Text(model.t("nat.cmp.next_models")); Image(systemName: "arrow.right") }
                    }
                    .auButton(.primary, .regular)
                    .disabled(model.cmp.selected.isEmpty)
                }
            }
        }
    }

    private var selectedLine: String {
        model.cmp.clips.filter { model.cmp.selected.contains($0.startFrame) }
            .map { "\(model.t("conf.tipo.\($0.kind)")) \($0.range)" }.joined(separator: " · ")
    }
}

struct ClipCard: View {
    @Environment(AppModel.self) private var model
    var clip: CompareClips.Clip
    private var on: Bool { model.cmp.selected.contains(clip.startFrame) }

    var body: some View {
        Button {
            if on { model.cmp.selected.remove(clip.startFrame) } else { model.cmp.selected.insert(clip.startFrame) }
        } label: {
            VStack(alignment: .leading, spacing: 8) {
                ZStack {
                    RoundedRectangle(cornerRadius: 6).fill(AU.inset)
                    if let path = clip.thumbnail, let img = NSImage(contentsOfFile: path) {
                        Image(nsImage: img).resizable().aspectRatio(contentMode: .fill)
                    }
                }
                .aspectRatio(16 / 9, contentMode: .fit)
                .clipShape(RoundedRectangle(cornerRadius: 6))
                HStack(spacing: 6) {
                    TriCheckbox(state: on ? .on : .off) {
                        if on { model.cmp.selected.remove(clip.startFrame) } else { model.cmp.selected.insert(clip.startFrame) }
                    }
                    Text(model.t("conf.tipo.\(clip.kind)")).font(.system(size: 12, weight: .semibold)).foregroundStyle(AU.text)
                    Spacer()
                    Text(clip.range).font(AUFont.smallNumbers).foregroundStyle(AU.text3)
                }
                Text(clip.reason).font(.system(size: 11)).foregroundStyle(AU.text2).lineLimit(2)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(10)
            .background(RoundedRectangle(cornerRadius: AU.Radius.card).fill(on ? AU.soft : AU.surface))
            .overlay(RoundedRectangle(cornerRadius: AU.Radius.card).strokeBorder(on ? AU.softLine : AU.line))
        }
        .buttonStyle(.plain)
    }
}

/// DS4 action bar: summary on the left, actions on the right.
struct ActionBar<Leading: View, Trailing: View>: View {
    @ViewBuilder var leading: () -> Leading
    @ViewBuilder var trailing: () -> Trailing

    var body: some View {
        HStack(spacing: 10) {
            leading()
            Spacer()
            trailing()
        }
        .padding(.horizontal, 16).padding(.vertical, 12)
        .background(RoundedRectangle(cornerRadius: AU.Radius.card).fill(AU.surface))
        .overlay(RoundedRectangle(cornerRadius: AU.Radius.card).strokeBorder(AU.line))
    }
}

// MARK: - Step 2: models

struct CompareModelsStep: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if let m = model.cmp.models {
                NoteView(.accent, title: model.t("nat.cmp.guide_title", ["h": m.sourceHeight]), text: m.reason) {
                    UnderlineLink(model.t("nat.cmp.model_guide"), symbol: "arrow.up.right") {
                        NSWorkspace.shared.open(URL(string: "https://interstellar0verdrive.github.io/AnimeUp/guide/")!)
                    }
                }
                HStack(alignment: .top, spacing: 12) {
                    ForEach(m.models) { card in ModelCard(card: card, recommended: card.key == m.recommended) }
                }
                Toggle(isOn: Binding(get: { model.cmp.includeOriginal }, set: { model.cmp.includeOriginal = $0 })) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(model.t("nat.cmp.include_original")).font(.system(size: 13, weight: .medium))
                        Text(model.t("nat.cmp.include_original_desc")).auSmall()
                    }
                }
                .toggleStyle(.switch).tint(AU.primary)
                if model.progress.queue.running {
                    NoteView(.yellow, title: model.t("nat.cmp.gpu_busy_title"), text: model.t("nat.cmp.gpu_busy_text")) {
                        Button(model.t("nat.cmp.pause_queue")) { model.command("queue.pause") }
                            .buttonStyle(AUTintedButtonStyle(.yellow))
                    }
                }
                Spacer()
                ActionBar {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(model.localizer.tn("nat.cmp.versions", model.cmp.chosenModels.count + (model.cmp.includeOriginal ? 1 : 0)))
                            .font(.system(size: 13, weight: .semibold))
                        Text(model.t("nat.cmp.test_estimate", ["time": Fmt.estimate(estimate(m))])).auSmall()
                    }
                } trailing: {
                    Button(model.t("nat.cmp.back")) { model.cmp.step = .clips }.auButton(.plain, .regular)
                    Button { model.startTest() } label: { Label(model.t("nat.cmp.start_test"), systemImage: "play.fill") }
                        .auButton(.primary, .regular)
                        .disabled(model.cmp.chosenModels.isEmpty || model.progress.queue.running || model.calRun?.running == true)
                }
            } else {
                HStack { Spinner(size: 14); Text(model.t("nat.cmp.loading_models")).auSmall() }
                Spacer()
            }
        }
    }

    private func estimate(_ m: CompareModels) -> Double {
        m.models.filter { model.cmp.chosenModels.contains($0.key) }.compactMap(\.clipSeconds).reduce(0, +)
            + (model.cmp.includeOriginal ? (m.referenceSeconds ?? 0) : 0)
    }
}

struct ModelCard: View {
    @Environment(AppModel.self) private var model
    var card: CompareModels.Card
    var recommended: Bool
    private var on: Bool { model.cmp.chosenModels.contains(card.key) }
    private var disabled: Bool { card.unreachable != nil }

    var body: some View {
        Button {
            if on { model.cmp.chosenModels.remove(card.key) } else { model.cmp.chosenModels.insert(card.key) }
        } label: {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 1) {
                        Text(card.label.hasPrefix("Real-ESRGAN") ? "Real-ESRGAN" : "Real-CUGAN").font(.system(size: 11)).foregroundStyle(AU.text3)
                        Text(model.shortModel(card.key).replacingOccurrences(of: "CUGAN ", with: ""))
                            .font(.system(size: 14, weight: .semibold)).foregroundStyle(AU.text)
                    }
                    Spacer()
                    TriCheckbox(state: on ? .on : .off) {
                        if on { model.cmp.chosenModels.remove(card.key) } else { model.cmp.chosenModels.insert(card.key) }
                    }
                }
                if let why = card.unreachable {
                    StatusChip(why, tone: .red)
                } else {
                    switch card.verdict {
                    case "ok": StatusChip(model.t("nat.chip.recommended"), tone: .green, symbol: "checkmark")
                    case "verifica": StatusChip(model.t("nat.chip.worth_checking"), tone: .yellow)
                    case "no": StatusChip(model.t("nat.chip.not_recommended"), tone: .red)
                    default: EmptyView()
                    }
                }
                Text(model.t("mot.modello.\(card.key).descrizione")).font(.system(size: 11)).foregroundStyle(AU.text2)
                    .lineLimit(4).fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
                Rectangle().fill(AU.line).frame(height: 1)
                HStack {
                    VStack(alignment: .leading, spacing: 1) {
                        Text(model.t("nat.cmp.this_test")).font(.system(size: 10)).foregroundStyle(AU.text3)
                        Text(card.clipSeconds.map { Fmt.estimate($0) } ?? "—").font(AUFont.smallNumbers).foregroundStyle(AU.textCode)
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 1) {
                        Text(model.t("nat.cmp.full_episode")).font(.system(size: 10)).foregroundStyle(AU.text3)
                        Text(card.estimate.map { Fmt.estimate($0) } ?? "—").font(AUFont.smallNumbers).foregroundStyle(AU.textCode)
                    }
                }
            }
            .padding(12)
            .frame(maxWidth: .infinity, minHeight: 210, alignment: .topLeading)
            .background(RoundedRectangle(cornerRadius: AU.Radius.card).fill(on ? AU.soft : AU.surface))
            .overlay(RoundedRectangle(cornerRadius: AU.Radius.card).strokeBorder(on ? AU.softLine : AU.line))
            .opacity(disabled ? 0.45 : 1)
        }
        .buttonStyle(.plain)
        .disabled(disabled)
    }
}

// MARK: - Step 3: running and results

struct CompareResultsStep: View {
    @Environment(AppModel.self) private var model
    @StateObject private var player = SplitPlayerController()

    var body: some View {
        let st = model.cmp.status
        VStack(alignment: .leading, spacing: 12) {
            if let st, st.running {
                running(st)
            } else if let st, let res = st.results, !res.isEmpty {
                if st.state == "stopped" || st.state == "interrupted" || !(st.failures ?? []).isEmpty {
                    NoteView(st.state == "failed" ? .red : .yellow, title: model.t("nat.cmp.stopped_title"),
                             text: (st.failures ?? []).joined(separator: "\n").isEmpty ? model.t("nat.cmp.stopped_text")
                                   : (st.failures ?? []).joined(separator: "\n")) {
                        UnderlineLink(model.t("nat.btn.show_log"), tone: .red) { model.openLog(st.log) }
                        Button(model.t("nat.cmp.render_rest")) { model.renderRest() }.buttonStyle(AUTintedButtonStyle(.yellow))
                    }
                }
                resultsView(st, res)
            } else if let st, st.state == "failed" || st.state == "stopped" || st.state == "interrupted" {
                NoteView(.red, title: model.t("nat.cmp.stopped_title"), text: (st.failures ?? []).joined(separator: "\n")) {
                    UnderlineLink(model.t("nat.btn.show_log"), tone: .red) { model.openLog(st.log) }
                    Button(model.t("nat.btn.retry")) { model.renderRest() }.buttonStyle(AUTintedButtonStyle(.red))
                }
                Spacer()
            } else {
                Text(model.t("nat.cmp.no_results")).auSmall()
                Spacer()
            }
        }
    }

    // C3
    private func running(_ st: CompareStatus) -> some View {
        let segs = st.segmenti ?? []
        let groups = Dictionary(grouping: segs.enumerated(), by: { $0.element.intervallo })
        let order = segs.map(\.intervallo).reduce(into: [String]()) { if !$0.contains($1) { $0.append($1) } }
        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(model.t("nat.cmp.running", ["pct": Int(((st.quota ?? 0) * 100).rounded())])).font(.system(size: 13, weight: .semibold))
                Text(st.text ?? "").auSmall()
                Spacer()
                Button { model.stopTest() } label: { Label(model.t("nat.run.stop"), systemImage: "stop.fill") }.auButton(.secondary, .regular)
            }
            ForEach(order, id: \.self) { clip in
                VStack(alignment: .leading, spacing: 8) {
                    Text("\(model.t("conf.tipo.\(groups[clip]?.first?.element.tipo ?? "motion")")) \(clip)")
                        .font(.system(size: 13, weight: .semibold))
                    ForEach(groups[clip] ?? [], id: \.offset) { item in
                        let i = item.offset
                        let done = i < (st.done ?? 0)
                        let current = i == (st.done ?? 0)
                        HStack(spacing: 10) {
                            Text(item.element.chiave == "original" ? model.t("nat.cmp.original") : model.shortModel(item.element.chiave))
                                .font(.system(size: 12)).frame(width: 170, alignment: .leading)
                            AUBar(done ? 1 : current ? (st.fraction ?? 0) : 0, height: 6, fill: done ? AU.green : AU.primary)
                            Group {
                                if done { Image(systemName: "checkmark").foregroundStyle(AU.greenText) }
                                else if current { Spinner(size: 11) }
                                else { Text("—").foregroundStyle(AU.text3) }
                            }
                            .font(.system(size: 10, weight: .semibold)).frame(width: 20)
                        }
                    }
                }
                .padding(14)
                .background(RoundedRectangle(cornerRadius: AU.Radius.card).fill(AU.surface))
                .overlay(RoundedRectangle(cornerRadius: AU.Radius.card).strokeBorder(AU.line))
            }
            Spacer()
        }
    }

    // C4
    private func resultsView(_ st: CompareStatus, _ results: [CompareStatus.Result]) -> some View {
        let tab = min(model.cmp.clipTab, results.count - 1)
        let r = results[tab]
        let keys = ["original", "animevideov3", "cugan-denoise", "cugan", "cugan-conservative"].filter { r.file[$0] != nil }
        return VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 4) {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 2) {
                        ForEach(Array(results.enumerated()), id: \.offset) { i, res in
                            Button { model.cmp.clipTab = i } label: {
                                HStack(spacing: 6) {
                                    Text(model.t("conf.tipo.\(res.tipo)")).font(.system(size: 12, weight: .semibold))
                                    Text(res.intervallo).font(AUFont.smallNumbers).foregroundStyle(AU.text3)
                                }
                                .padding(.horizontal, 14).padding(.vertical, 7)
                                .background(UnevenRoundedRectangle(topLeadingRadius: 8, topTrailingRadius: 8)
                                    .fill(i == tab ? AU.surface : .clear))
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
                Spacer()
                UnderlineLink(model.t("nat.cmp.show_clips"), tone: .neutral) {
                    NSWorkspace.shared.open(URL(fileURLWithPath: r.cartella))
                }
            }
            VStack(spacing: 10) {
                HStack(spacing: 10) {
                    versionPicker(keys, side: "L", selection: Binding(get: { model.cmp.left }, set: { model.cmp.left = $0 }))
                    Spacer()
                    Button { let l = model.cmp.left; model.cmp.left = model.cmp.right; model.cmp.right = l } label: {
                        Label(model.t("nat.cmp.swap"), systemImage: "arrow.left.arrow.right")
                    }
                    .auButton(.plain, .small)
                    Spacer()
                    versionPicker(keys, side: "R", selection: Binding(get: { model.cmp.right }, set: { model.cmp.right = $0 }))
                }
                SplitPlayerView(controller: player)
                    .aspectRatio(16 / 9, contentMode: .fit)
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                HStack(spacing: 10) {
                    Button { player.toggle() } label: { Image(systemName: player.playing ? "pause.fill" : "play.fill") }
                        .auButton(.secondary, .small)
                    Slider(value: Binding(get: { player.time }, set: { player.seek($0) }), in: 0...max(0.1, player.duration))
                        .controlSize(.small).tint(AU.primary)
                    Text(Fmt.elapsed(player.time)).font(AUFont.smallNumbers).foregroundStyle(AU.text3)
                    Toggle("1:1", isOn: $player.oneToOne).toggleStyle(.button).controlSize(.small)
                }
            }
            .padding(12)
            .background(RoundedRectangle(cornerRadius: AU.Radius.card).fill(AU.surface))
            .overlay(RoundedRectangle(cornerRadius: AU.Radius.card).strokeBorder(AU.line))
            .task(id: "\(tab)|\(model.cmp.left)|\(model.cmp.right)") { await load(r) }
            HStack(alignment: .top, spacing: 12) {
                ForEach(r.modelli, id: \.chiave) { m in ResultCard(result: m, inUse: model.plan(model.cmp.fileId ?? "")?.model == m.chiave) }
            }
            HStack {
                Button(model.t("nat.cmp.change_test")) { model.cmp.step = .clips }.auButton(.secondary, .regular)
                Spacer()
                Button { model.tab = .queue; model.expanded = model.cmp.fileId } label: {
                    HStack(spacing: 5) { Text(model.t("nat.cmp.next_queue")); Image(systemName: "arrow.right") }
                }
                .auButton(.primary, .regular)
            }
        }
        .sheet(isPresented: Binding(get: { model.cmp.showUseMany }, set: { model.cmp.showUseMany = $0 })) {
            UseManySheet().environment(model).preferredColorScheme(.dark)
        }
    }

    private func versionPicker(_ keys: [String], side: String, selection: Binding<String>) -> some View {
        HStack(spacing: 6) {
            if side == "L" { Text("L").font(.system(size: 10, weight: .bold)).foregroundStyle(AU.onPrimary).frame(width: 16, height: 16).background(RoundedRectangle(cornerRadius: 3).fill(AU.primary)) }
            Menu {
                ForEach(keys, id: \.self) { k in Button(k == "original" ? model.t("nat.cmp.original") : model.shortModel(k)) { selection.wrappedValue = k } }
            } label: {
                PopupLabel(selection.wrappedValue == "original" ? model.t("nat.cmp.original") : model.shortModel(selection.wrappedValue), width: 200)
            }
            .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize()
            if side == "R" { Text("R").font(.system(size: 10, weight: .bold)).foregroundStyle(AU.onPrimary).frame(width: 16, height: 16).background(RoundedRectangle(cornerRadius: 3).fill(AU.primary)) }
        }
    }

    private func load(_ r: CompareStatus.Result) async {
        var urls: [URL?] = [nil, nil]
        for (i, key) in [model.cmp.left, model.cmp.right].enumerated() {
            guard let path = r.file[key] else { continue }
            if let mp4 = try? await model.engine.playable(path) { urls[i] = URL(fileURLWithPath: mp4) }
        }
        player.load(left: urls[0], right: urls[1])
    }
}

struct ResultCard: View {
    @Environment(AppModel.self) private var model
    var result: CompareStatus.Result.ModelTime
    var inUse: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(model.shortModel(result.chiave)).font(.system(size: 13, weight: .semibold))
                Spacer()
                if model.cmp.left == result.chiave { tag("L") }
                if model.cmp.right == result.chiave { tag("R") }
            }
            HStack {
                Text("\(Text(model.t("nat.cmp.this_clip")).foregroundStyle(AU.text3)) \(Text(Fmt.elapsed(result.secondi)).fontWeight(.semibold))").font(.system(size: 11))
                Spacer()
                Text("\(Text(model.t("nat.cmp.full_episode")).foregroundStyle(AU.text3)) \(Text(Fmt.estimate(result.intero)).fontWeight(.semibold))").font(.system(size: 11))
            }
            if let m = result.metriche, m.count == 2 {
                metric(model.t("nat.cmp.detail"), m[0], AU.primary)
                metric(model.t("nat.cmp.noise"), m[1], AU.yellow)
            }
            if inUse {
                Label(model.t("nat.cmp.in_use"), systemImage: "checkmark").labelStyle(SmallIconLabel())
                    .font(.system(size: 12, weight: .medium)).foregroundStyle(AU.greenText)
                    .frame(maxWidth: .infinity).frame(height: 24)
            } else {
                Button(model.t("nat.cmp.use_this")) { if let id = model.cmp.fileId { model.useModel(result.chiave, for: [id]) } }
                    .auButton(.secondary, .small, fullWidth: true)
            }
            Button(model.t("nat.cmp.use_many")) { model.cmp.showUseMany = true; model.cmp.right = result.chiave }
                .auButton(.secondary, .small, fullWidth: true)
        }
        .padding(12)
        .frame(maxWidth: .infinity)
        .background(RoundedRectangle(cornerRadius: AU.Radius.card).fill(inUse ? AU.soft : AU.surface))
        .overlay(RoundedRectangle(cornerRadius: AU.Radius.card).strokeBorder(inUse ? AU.softLine : AU.line))
    }

    private func tag(_ s: String) -> some View {
        Text(s).font(.system(size: 10, weight: .bold)).foregroundStyle(AU.onPrimary)
            .frame(width: 16, height: 16).background(RoundedRectangle(cornerRadius: 3).fill(AU.primary))
    }

    private func metric(_ name: String, _ value: Double?, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack {
                Text(name).font(.system(size: 11)).foregroundStyle(AU.text2)
                Spacer()
                Text(value.map { "\(Int(($0 * 100).rounded()))%" } ?? "—").font(AUFont.smallNumbers).foregroundStyle(AU.textCode)
            }
            AUBar(min(1, (value ?? 0) / 2), height: 4, fill: color)
        }
    }
}

/// C5: use the model for several files.
struct UseManySheet: View {
    @Environment(AppModel.self) private var model
    @State private var picked: Set<String> = []

    var body: some View {
        let key = model.cmp.right
        VStack(alignment: .leading, spacing: 14) {
            Text(model.t("nat.cmp.use_many_title", ["model": model.shortModel(key)])).font(.system(size: 17, weight: .bold))
            Text(model.t("nat.cmp.use_many_text")).auSmall()
            VStack(spacing: 0) {
                ForEach(model.files.filter { $0.state == .ready }) { f in
                    let reach = model.plans[f.id]?.option(key)?.unreachable
                    HStack(spacing: 8) {
                        TriCheckbox(state: picked.contains(f.id) ? .on : .off) {
                            if picked.contains(f.id) { picked.remove(f.id) } else { picked.insert(f.id) }
                        }
                        .disabled(reach != nil)
                        Text(f.name).font(.system(size: 12, weight: .medium)).lineLimit(1)
                        Spacer()
                        if let reach { Text(reach).font(.system(size: 11)).foregroundStyle(AU.redText) }
                        else if model.plans[f.id]?.model == key { Text(model.t("nat.cmp.already_uses")).font(.system(size: 11)).foregroundStyle(AU.text3) }
                        else { Text("\(model.shortModel(model.plans[f.id]?.model ?? "")) → \(model.shortModel(key))").font(AUFont.smallNumbers).foregroundStyle(AU.text3) }
                    }
                    .padding(.horizontal, 12).padding(.vertical, 8)
                    .background(picked.contains(f.id) ? AU.soft : .clear)
                }
            }
            .background(RoundedRectangle(cornerRadius: AU.Radius.field).fill(AU.inset))
            HStack {
                Spacer()
                Button(model.t("nat.btn.cancel")) { model.cmp.showUseMany = false }.auButton(.secondary, .large)
                Button(model.localizer.tn("nat.cmp.use_for_n", picked.count)) {
                    model.useModel(key, for: Array(picked))
                    model.cmp.showUseMany = false
                }
                .auButton(.primary, .large).disabled(picked.isEmpty)
            }
        }
        .padding(24)
        .frame(width: 520)
        .background(AU.bg)
    }
}
