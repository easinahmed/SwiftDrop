# SwiftDrop

_Developed by Easin Codes_

A fast, reliable media downloader for macOS. Paste one link or hundreds. SwiftDrop works out what each
link is, shows you a preview, and downloads everything locally: with live progress, pause/resume,
retries, playlists and a clean native-feeling interface.

- **Bulk first.** Paste or import 100+ links at once. Duplicates, invalid links and links you already
  downloaded are flagged before anything starts. Downloads run with a configurable concurrency limit
  (1–10), so 1,000 queued links never mean 1,000 processes.
- **Real downloads, honest numbers.** Files are streamed to disk. Speed and time remaining are measured
  from real byte counts and only shown when they're known. Interrupted transfers resume where the
  server allows it.
- **Video/audio sites, playlists and direct files.** Direct HTTP(S) files (video, audio, images, PDFs,
  archives…), HLS/DASH streams, podcast RSS feeds, and the public video/audio sites supported by
  [yt-dlp](https://github.com/yt-dlp/yt-dlp). Quality and format selection is available, with FFmpeg
  merging and conversion bundled.
- **Spotify songs, albums and playlists.** Saved as audio from the matching YouTube Music recording, named
  and tagged with Spotify's title, artist and album.
- **Respectful by design.** No DRM circumvention, no private-profile or paywall bypass. Passwords are
  never requested or stored.

---

## Install

1. Download `SwiftDrop-<version>-arm64.dmg` from the [Releases](../../releases) page, open it and drag
   **SwiftDrop** to **Applications**.
2. The development build is **not signed with an Apple Developer ID** (see [Signing](#signing--notarization)).
   On first launch, right-click SwiftDrop in Applications → **Open** → **Open**. Alternatively, run:
   ```sh
   xattr -dr com.apple.quarantine /Applications/SwiftDrop.app
   ```

**Requirements:** macOS 12 or later on Apple Silicon (M1 or newer). See [Architectures](#architectures) for
Intel Macs.

Optional: YouTube now expects a JavaScript runtime for some formats. SwiftDrop automatically uses
[Deno](https://deno.com) (`brew install deno`) or Node.js 22+ if it finds one in Homebrew's standard
locations, `~/.deno`, `~/.volta` or your `PATH`. Without one, YouTube still works, with yt-dlp's
reduced fallback.

## Windows

1. Download `SwiftDrop-Setup-<version>.exe` from the [Releases](../../releases) page and run it. It
   installs for your user account only, so no administrator rights are needed.
2. The installer isn't code-signed, so SmartScreen may warn you: click **More info** → **Run anyway**.

**Requirements:** Windows 10 or 11, 64-bit (x64). The window uses Microsoft Edge WebView2, which is built
into current Windows versions.

Videos are saved in their original codec, with no conversion for QuickTime. They play in Media Player. If
a video won't play, install Microsoft's free **AV1 Video Extension** or the **HEVC Video Extensions** from
the Microsoft Store. Node.js 22+ in `C:\Program Files\nodejs` is used for YouTube's JavaScript checks, if
you have it installed. "Open at login" and system notifications aren't available on Windows yet.

The installer is built by GitHub Actions (`.github/workflows/windows.yml`) on every push to the `windows`
branch and on `v*` tags. The workflow builds the UI, bundles the app and a pinned gyan.dev FFmpeg build
with PyInstaller (`packaging/windows/SwiftDrop-windows.spec`), and runs the bundled app's `--self-test`.
It then builds the installer with Inno Setup (`packaging/windows/SwiftDrop.iss`). The installer is kept
as a workflow artifact. For tags, or when you run the workflow manually with `release_tag`, it's also
attached to that GitHub release.

## Android

SwiftDrop for Android is a share-to-download app, in the style of Snaptube. In YouTube, Chrome or any other
app, tap **Share → SwiftDrop**, or long-press a link and choose **Open with → Download with SwiftDrop**.
The download starts at once in the background, with a progress notification (percent, speed, **Cancel**).
When it finishes, tap the notification to play the file. If it fails, the notification shows the reason
and a **Retry** button. You can also paste a link into the app, where the list of downloads lets you
cancel, retry, open, share or remove each one. Removing an entry leaves the file in place.

It uses the same yt-dlp engine as the desktop app, via
[youtubedl-android](https://github.com/JunkFood02/youtubedl-android), with Python and FFmpeg bundled. It
handles the sites yt-dlp supports, plus direct file links.

**Install**

1. Copy `SwiftDrop-Android-1.0.0.apk` to the phone and open it.
2. Android asks you to allow **Install unknown apps** for the app you opened it from (Files, Chrome…).
   Allow it, go back and tap **Install**.
3. Open SwiftDrop once. Allow notifications so you can see progress and finished downloads.

**Requirements:** Android 8.0 (API 26) or later, on an ARM phone (arm64-v8a or armeabi-v7a).

**Where files go:** `Download/SwiftDrop` in the phone's shared storage. Galleries, music players and the
Files app all see it. Android 10 and later save there through MediaStore, which needs no storage
permission. On Android 8–9, SwiftDrop asks for storage access, which saving needs.

**Settings:**

- **Default quality:** Best, 1080p (the default), 720p, 480p, or Audio only (m4a). Videos prefer MP4
  (H.264 + AAC), merged into `.mp4`.
- **Wi-Fi only:** downloads wait for an unmetered network.
- **Update download engine:** updates yt-dlp from its stable channel. SwiftDrop also checks for an
  update once a week in the background. If YouTube downloads start failing, update the engine first.

**Build**

You need JDK 17 and the Android SDK (platform 36, build-tools 36.0.0). Point `android/local.properties`
at the SDK with `sdk.dir=…`, or set `ANDROID_HOME`.

```sh
cd android
JAVA_HOME=/path/to/jdk-17 ./gradlew testDebugUnitTest assembleRelease
# → app/build/outputs/apk/release/app-release.apk
```

The stack is Kotlin, Jetpack Compose (Material 3), WorkManager and Room. It builds with AGP 9.1 on the
Gradle 9.3.1 wrapper.

**Release signing:** the build reads `~/.swiftdrop/android/keystore.properties` (`storeFile`,
`storePassword`, `keyAlias`, `keyPassword`). To use another file, set `SWIFTDROP_KEYSTORE_PROPERTIES`. If
the file is missing, the build prints a warning and produces an unsigned `app-release-unsigned.apk`.
The release key is `~/.swiftdrop/android/swiftdrop-release.jks` (alias `swiftdrop`).

> **Back up the keystore and its properties file somewhere safe and private, such as a password
> manager.** Android only installs an update over an existing app if it's signed with the same key. If
> the key is lost, users must uninstall SwiftDrop (and lose their download history) to install a new
> build. Never commit either file. `android/.gitignore` excludes them.

## Using SwiftDrop

| Screen | What it does |
| --- | --- |
| **New Download** | Paste, type, drop a `.txt` file or links, or *Import .txt*. Each link is validated and classified instantly; titles, sizes and playlist contents are then fetched in the background (4 links at a time). Pick quality, format and destination, then **Download**. |
| **Downloads** | Every job with live progress, speed, ETA and size. Pause/resume/cancel/retry per item, for a selection, or for the whole queue (*Pause all*, *Resume all*, *Retry failed*, *Clear completed*). Export results (CSV) or failed links (TXT). |
| **Playlists** | Playlists, albums, channels and feeds grouped into collections with overall progress. Pick individual items before downloading; unavailable items are skipped and items already downloaded aren't fetched again. |
| **History** | Searchable, filterable list of past downloads with *Open*, *Show in Finder* and *Copy link*. Clearing history never deletes files. |
| **Pop-up** | Copy a download or video link anywhere, then press **⌃⌥D** (**Ctrl+Alt+D** on Windows): SwiftDrop opens a small window to name it, pick a folder and **Start**, **Start later** or **Cancel**; several links at once go to New Download with **Add all**. With no download link on the clipboard you get a short "No link copied" message instead. The shortcut works with SwiftDrop's window hidden and can be changed or turned off in Settings. The **Send to SwiftDrop** bookmark (Settings) sends the page you're on. Copying alone does nothing unless you turn on **Pop up automatically when I copy a download link** (off by default). While the shortcut or the automatic pop-up is on, closing the window keeps SwiftDrop running (in the Dock on Mac; open it again to show it on Windows). |
| **Settings** | Destination, simultaneous downloads, bandwidth limit, default quality/format, theme, notifications, the keyboard shortcut, the opt-in automatic pop-up, an opt-in in-app banner for other copied links, resume-on-launch, open-at-login, browser sign-in, partial-file cleanup, diagnostics. |

Keyboard: `⌘1`–`⌘4` switch sections, `⌘,` opens Settings, and `⌘↩` adds links or starts the download. From any app, `⌃⌥D` (`Ctrl+Alt+D` on Windows) opens the link you just copied.

Where files go:
- Finished downloads go to `~/Downloads` by default, or the folder you pick, optionally sorted into
  `Videos/Audio/Images/Other` and per-playlist folders. Name clashes become `name (1).ext`; nothing is
  overwritten.
- In-progress and paused data lives in `~/Library/Application Support/SwiftDrop/partial/<job>/`, separate
  from finished files. *Settings → Storage* shows its size and cleans it up.
- The database (settings, queue, history) is `~/Library/Application Support/SwiftDrop/swiftdrop.sqlite3`.
- Logs are in `~/Library/Logs/SwiftDrop/`. Tokens, signatures, cookies and credentials are redacted
  before anything is written.

## Supported and unsupported sources

**Supported**
- Direct HTTP(S) files of any type, with `Range` resume, redirects, `Content-Disposition` names and
  integrity checks (size and SHA-256).
- HLS (`.m3u8`) and DASH (`.mpd`) streams that aren't DRM-protected.
- Public pages on sites supported by yt-dlp: YouTube, Vimeo, SoundCloud, Bandcamp, Internet Archive,
  Dailymotion, Twitch VODs, TED, Mixcloud and many more. Also generic pages that embed HTML5
  `<video>`/`<audio>`.
- Playlists, albums, channels and podcast RSS/Atom feeds, expanded into selectable items.
- Spotify songs, albums and public playlists. Spotify's own audio is DRM-protected and is never touched:
  SwiftDrop reads the song list from Spotify's public page (no sign-in), finds each song on YouTube Music
  (then YouTube) with the same title and artist and a length within a few seconds, and saves that
  recording as audio in your chosen format. A song without a close match is reported as "No matching
  song found" instead of being guessed. Sound quality is YouTube's, not Spotify's. Without signing in,
  Spotify lists only the first 100 songs of a playlist (albums and single songs are complete).
- Instagram, Facebook, X, TikTok and similar: **public** posts where the site allows it. For media
  your own account can access, turn on *Settings → Privacy → Use browser sign-in*. Cookies are read
  from that browser only when a download starts, and are never stored or logged. Safari requires
  granting SwiftDrop Full Disk Access.

**Not supported (by design)**
- DRM-protected services: Apple Music, Apple TV, Netflix, Disney+, Prime Video, Max, Hulu, Paramount+,
  Peacock, TIDAL, Deezer, Amazon Music, Audible, and Spotify podcasts and audiobooks. These links are
  refused up front, with a compliant alternative (the service's own offline mode, DRM-free stores, or a
  podcast's public RSS feed).
- Private profiles, paywalls and other access controls. SwiftDrop never tries to get around them.
- Live streams that are still in progress.

Sites change frequently. When a site changes its pages, its downloads fail with a "Site changed" message
until the bundled yt-dlp is updated (see [Updating yt-dlp](#updating-yt-dlp)).

---

## Architecture

SwiftDrop is a **Python** application. The user interface is a React + TypeScript + Tailwind single-page
app, compiled to static files and rendered in the system **WKWebView** through
[pywebview](https://pywebview.flowrl.com). There's no Electron and no bundled Chromium, so the app is
about 164 MB with FFmpeg and Python included.

```
React UI (WKWebView, file://)        swiftdrop/ui/web  ← built from frontend/
   │  window.pywebview.api.<fn>()       ▲  window.__SD_PUSH__(changes)  (≤5×/s, coalesced)
   ▼                                    │
ui/bridge.py ── allow-listed, validated functions ── publisher thread
   │
service.py (AppService façade)
   ├── preview.py      paste → parse/dedupe/classify (instant) → 4 inspector threads (metadata)
   ├── queue.py        FIFO scheduler, ≤N worker threads, pause/resume/cancel/retry, persistence
   │     └── providers/registry.py → direct.py (engine/http.py) | ytdlp.py (yt-dlp + FFmpeg)
   ├── history.py, settings.py, storage.py (SQLite, WAL)
   ├── platform/macos.py  Finder, clipboard, notifications, login item (PyObjC)
   └── hotkey.py       the copy-then-press shortcut → platform/hotkey_macos.py (Carbon) | hotkey_windows.py
```

| Module | Responsibility |
| --- | --- |
| `urls.py` | Extracts links from any text, validates them (http/https only, no embedded credentials), normalises them (tracking parameters removed, signed query strings preserved byte-for-byte), and generates duplicate keys (`youtu.be/X` ≡ `youtube.com/watch?v=X`). |
| `providers/registry.py`, `restricted.py`, `sites.py` | Offline classification: DRM services, file extensions, well-known sites. Unknown links are resolved on first contact: a file goes to the direct engine, a web page or feed goes to yt-dlp. |
| `engine/http.py` | Streaming downloader: 256 KB chunks, `Range` + `If-Range` resume, retries with exponential backoff and jitter (honours `Retry-After`), disk-space checks, SHA-256, shared token-bucket bandwidth limit. |
| `providers/ytdlp.py` | yt-dlp in-process, one instance per job, with quality/format mapping, FFmpeg merge/convert, merged two-stream progress, and cancellation from the progress hooks. |
| `queue.py` | Bounded concurrency, cooperative cancellation (`cancel.py`), error isolation per job, and conflict-safe finalisation (`fileops.py`, `O_EXCL` placeholders). |
| `errors.py`, `redact.py` | Maps every failure to a title, message, hint and redacted technical detail. |
| `selftest.py` | `SwiftDrop --self-test`: end-to-end check of the bundle against a local HTTP server. |

**Restart safety.** State changes are written to SQLite immediately, and progress every 5 s. On launch,
anything that was downloading becomes *Interrupted* (or is re-queued if *Resume on launch* is on) and
continues from its partial data. A completed download is never assumed: if its file has disappeared, it's
marked as missing and can be retried.

**Security model.** These are the pywebview equivalents of the requested Electron settings:

| Electron requirement | SwiftDrop |
| --- | --- |
| `contextIsolation`, no Node in renderer | The page has no Python or system access. It can only call the 30 functions registered with `window.expose()`, an exact-name allow-list. No object is passed as `js_api`, so pywebview's attribute walking can't reach internals. |
| Restricted, validated preload API | Every argument is type- and size-checked in `ui/bridge.py`. Ids must match `[0-9a-f]{16}`. Errors return a message, never a traceback. |
| No arbitrary paths/commands from renderer | Open and reveal take a job or history id, and the path comes from SwiftDrop's records. Destinations must be the saved default, `~/Downloads`, or a folder picked in the native dialog. No shell is ever invoked, and helper tools get fixed argument lists. |
| CSP / no remote code | `index.html` CSP: scripts only from the bundle (`'unsafe-eval'` is required by pywebview's own bridge). All data is rendered as text (ESLint forbids `dangerouslySetInnerHTML`). The UI loads from `file://`, so no local HTTP server is started. |
| Secrets | No passwords are requested or stored. Browser cookies are read per download only. Logs are redacted. The clipboard is read when you press the shortcut. It is only watched if you turn on the automatic pop-up or the in-app banner (both off by default): only download and video links trigger the pop-up, contents are never stored, and copies made inside SwiftDrop or marked concealed by password managers are skipped. The shortcut is a Carbon hot key on macOS, so it needs no Accessibility permission. Links from the clipboard or `swiftdrop://` are always shown for confirmation, never started on their own. |

---

## Development

Prerequisites: macOS, the Python 3.12+ framework build from python.org (needed for GUI apps and
PyInstaller), Node.js 22+, and FFmpeg (only for building the bundle and for the FFmpeg tests).

```sh
make setup        # .venv + Python and npm dependencies
make run          # build the UI, then run the app from source
make dev          # UI only, in a browser, with a clearly labelled preview bridge (no downloads)
make check        # ruff + eslint + mypy + tsc + pytest + vitest
make selftest     # end-to-end self-test from source
make test-network # also run opt-in tests that read public sites (metadata only)
```

The compiled UI in `swiftdrop/ui/web/` is part of the repository, so the Python app runs without Node.
Rebuild it with `make ui` after changing `frontend/`.

**Tests.** There are 421 Python tests (419 local, plus 2 opt-in network tests) and 17 frontend tests. Everything runs against local fixtures: a
local HTTP server that can inject 503s, `Retry-After`, dropped connections, slow streams and missing
`Range` support, plus HLS streams, RSS feeds and HTML5 pages generated with FFmpeg. No test depends on a
live website unless you opt in with `SWIFTDROP_NETWORK_TESTS=1`.

**QA hook.** Setting `SWIFTDROP_QA_DIR=/some/dir` before launching enables an automation hook. It
evaluates `*.js` files dropped into that folder in the page, and writes WKWebView snapshots for `*.snap`
files. It's read only from the process environment and is off otherwise. Combine it with
`SWIFTDROP_HOME=/tmp/x` to keep test data away from your real library.

**Renaming the app.** Change `APP_NAME`, `BUNDLE_ID` and `APP_VERSION` in `swiftdrop/appinfo.py`. The
window, data folders, bundle and DMG all follow. Use a bundle identifier from a domain you control.

## Packaging

```sh
make dmg          # = packaging/build_macos.sh
```

The script:
1. Builds the UI.
2. Provisions FFmpeg into `vendor/bin/<arch>/` (`scripts/fetch_binaries.py`). It refuses binaries for the
   wrong architecture, binaries linked to non-system libraries (such as Homebrew dylibs), and
   `--enable-nonfree` builds.
3. Renders the icon and DMG artwork.
4. Bundles with PyInstaller (`packaging/SwiftDrop.spec`).
5. Signs the app and verifies the signature strictly.
6. Runs the self-test **from inside the bundle**.
7. Builds `dist/SwiftDrop-<version>-<arch>.dmg` with drag-to-Applications.

### Signing & notarization

Without credentials, the bundle is **ad-hoc signed**. It runs on the Mac that built it, and on other Macs
after the right-click → Open step, but Gatekeeper reports it as unidentified. For distribution:

```sh
export SWIFTDROP_CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
xcrun notarytool store-credentials swiftdrop-notary --apple-id you@example.com --team-id TEAMID
export SWIFTDROP_NOTARY_PROFILE=swiftdrop-notary
make dmg
```

With an identity set, every binary is signed with the hardened runtime and `packaging/entitlements.plist`,
which Python's runtime needs. With a notary profile set, the DMG is also notarized and stapled.

### Architectures

The DMG is **arm64 (Apple Silicon)**. A universal build isn't produced: several bundled Python
extensions (brotli, websockets) are published as arm64-only and x86_64-only wheels, and the bundled
FFmpeg is arm64-only. For Intel Macs, run the same build on an Intel Mac (or an x86_64 Python under
Rosetta) with `SWIFTDROP_ARCH=x86_64` and an x86_64 static FFmpeg passed to
`scripts/fetch_binaries.py --from`.

### FFmpeg licence

The bundled FFmpeg is an unmodified, statically linked build from martin-riedl.de, configured with
`--enable-gpl`, so it's GPL. It runs as a separate process. `vendor/licenses/FFMPEG-NOTICE.md`
(also inside the app under `Contents/Resources/licenses/`) records its version, checksum, build
configuration and where to get the source. If you distribute SwiftDrop commercially, review the GPL
obligations, or provision an LGPL build. Any static build works with `scripts/fetch_binaries.py --from DIR`.

### Updating yt-dlp

Site support comes from the pinned `yt-dlp` in `requirements.txt`. To pick up site fixes, bump the
version, run `make check` and `make dmg`, and ship a new release.

## Troubleshooting

- **"Sign-in required" / "Verification required":** the site needs an account or rate-limited you.
  Use *Use browser sign-in* for content your account can access, or lower *Simultaneous downloads*.
- **"FFmpeg unavailable":** run `SwiftDrop --self-test` from Terminal
  (`/Applications/SwiftDrop.app/Contents/MacOS/SwiftDrop --self-test`) and check the FFmpeg line.
- **"Can't save to folder":** pick another destination, or grant access in *System Settings → Privacy &
  Security → Files and Folders*.
- **Diagnostics:** *Settings → About & diagnostics → Copy diagnostics / Logs*.

## Known limitations

- An unsigned build needs the right-click → Open step. Notifications in an ad-hoc signed build depend on
  macOS granting permission. In development, from source, they go to the log instead.
- Cancelling during a site's metadata lookup takes effect once that request returns (the socket timeout is
  20 s). Cancelling during an FFmpeg merge takes effect when the merge finishes.
- "Pause" for site downloads stops the transfer and keeps yt-dlp's partial files; resuming continues them.
  Some servers don't support resuming direct files. SwiftDrop then says so and restarts that file from
  the beginning.
- Spotify playlists are read from Spotify's public embed page, which lists at most 100 songs and can
  change without notice. If Spotify changes it, Spotify links fail with "Couldn't read this Spotify link"
  until SwiftDrop is updated.
- The project has no licence file yet. Choose one before publishing, and keep it compatible with the
  bundled components (FFmpeg GPL, yt-dlp Unlicense, pywebview BSD, PyObjC MIT).
