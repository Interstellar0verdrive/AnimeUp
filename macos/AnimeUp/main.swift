// main.swift - AnimeUp.app: a native window around AnimeUp's local server.
//
// On launch: work out the state/data folders, start `animeup ui` on port
// 8898 (or reuse a server already answering there), show "Preparing
// AnimeUp…" until /_stcore/health answers, then show the interface in a
// WKWebView. On quit: stop the server (not the upscaling jobs).

import AppKit

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
