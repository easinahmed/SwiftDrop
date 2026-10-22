# SwiftDrop for iPhone

An Apple Shortcut that works like the "YAS Download" shortcut: share a link
from any app, pick **SwiftDrop**, and the video or photos are saved to your
iPhone. It needs only an iPhone. No Mac, computer or app install.

SwiftDrop sends the link to free download services that return the real media
file, downloads it, and saves videos and photos to **Photos**. Other files
(audio, zip, pdf) are saved to **Files** (iCloud Drive > Shortcuts >
SwiftDrop). Run on its own, it shows a menu with **Settings** and **About**.

Version 1.1. Developed by Easin Codes. https://swiftdrop-mac.vercel.app

## Install on iPhone (iOS 17 or later)

1. Open the `SwiftDrop.shortcut` link in **Safari** on the iPhone. Use the
   link to `dist/SwiftDrop.shortcut` that you were given, or an iCloud link
   (see below).
2. Shortcuts opens and shows SwiftDrop. Tap **Add Shortcut**.
   - If Safari asks whether to download the file, tap **Download**, open it
     from the Downloads list, and Shortcuts opens.
   - If iOS refuses to open it, open **Settings > Shortcuts** (on iOS 18
     and later, **Settings > Apps > Shortcuts**), turn on any option that
     allows shortcuts from the internet or untrusted shortcuts (the wording
     depends on the iOS version, sometimes under **Advanced**), then open the
     link again.
3. The first time SwiftDrop uses each service, iOS asks "Allow SwiftDrop to
   connect to ...?". Tap **Always Allow**. It also asks once for access to
   Photos. Allow it so videos can be saved.

Easiest way to share with friends: once SwiftDrop is on your iPhone, open the
Shortcuts app, touch and hold SwiftDrop, choose **Share**, then **Copy iCloud
Link**, and send them that link.

## Use it

- In TikTok, Instagram, YouTube, X, Safari or any other app, tap **Share**
  (or **Copy link** then share), then pick **SwiftDrop**. If you don't see it,
  scroll to the end of the share sheet, tap **Edit Actions**, and add it.
- Or run SwiftDrop from the Shortcuts app or the Home Screen. A menu opens:
  - **Download link from clipboard**: downloads the link you copied. If the
    clipboard has no link, it asks for one.
  - **Settings**: see below.
  - **About**: version, developer, website and the privacy note.

A notification says "Saved N item(s) to your iPhone" when it's done (you can
turn it off). If nothing could be downloaded, an alert says so. For YouTube
the alert says "YouTube is blocking the free download servers right now.
Please try again later.", or that the video itself can't be downloaded
(private, age-restricted, live or removed) when a server says so.

## Settings

Run SwiftDrop from the Shortcuts app, choose **Settings**. The menu shows the
current choices; pick one to change it, **Done** to close.

| Setting | Choices (default first) |
| --- | --- |
| Save videos & photos to | **Photos**, or Files (the folder below) |
| Files folder name | **SwiftDrop**, inside iCloud Drive > Shortcuts. Audio, zip, pdf and other files always go here. A name that is taken gets "-2". |
| Video quality | **720p**, Max, 1080p, 480p, 360p. Sent to the cobalt servers (YouTube, Facebook, Vimeo...), and used to pick the size of X videos. |
| YouTube: download as | **Video**, or Audio only (m4a, saved to Files) |
| TikTok: HD when available | **On**, or Off (the normal-size video) |
| Show a notification when done | **On**, or Off |
| Reset settings | back to the defaults |

Settings are saved in iCloud Drive > Shortcuts > SwiftDrop > settings.json
and read at the start of every run. If the file is missing, the defaults are
used. Both the settings and the Files folder live in the Shortcuts folder of
iCloud Drive, so iCloud Drive should be turned on for Shortcuts.

## Supported sites

Checked live on 22 October 2026 from a home connection (the same kind of
network an iPhone uses), and run through a test copy of the shortcut on a Mac.
Services are tried in this order. The next one is used if the earlier one
answers with an error, an empty file or no media.

The "cobalt servers" are community servers of https://cobalt.tools. Of the 25
servers on https://cobalt.directory only two answer without a Turnstile check
or key; two more were found elsewhere. In order:

- YouTube: rue-cobalt.xenon.zone, co.otomir23.me, api.cobalt.liubquanti.click.
  cobaltapi.cjs.nz is left out for YouTube: YouTube blocks it
  ("error.api.youtube.login").
- Every other site: rue-cobalt.xenon.zone, co.otomir23.me, cobaltapi.cjs.nz,
  api.cobalt.liubquanti.click.

api.cobalt.liubquanti.click is a relay: it passes the link on to other cobalt
servers (cobalt.meowing.de, clxxped.lol) that need a key. It often works when
the others don't (on 22 October it was the only one that could fetch a
TWICE music video and Reddit), but it is slower and sends YouTube audio as
.opus instead of .m4a.

| Site | Services, in order | Status |
| --- | --- | --- |
| TikTok videos and photo slideshows | tikwm.com, then cobalt | Works (no watermark; HD when available; every slideshow photo) |
| X / Twitter videos, GIFs, photos | FixTweet (api.fxtwitter.com), then vxtwitter, then cobalt | Works (every item of the post; video size follows Video quality) |
| Instagram reels, videos, photos, carousels | InstaFix (eeinstagram.com), then cobalt | Works for public posts (every carousel item) |
| YouTube videos and Shorts | cobalt (YouTube servers above) | Works (H.264 MP4, 720p by default, or m4a audio) while one server isn't blocked by YouTube |
| Facebook videos and reels | cobalt | Works for public videos |
| Pinterest videos and images | cobalt | Works |
| Twitch clips | cobalt | Works |
| Vimeo | cobalt | Works |
| Reddit | cobalt | Works through api.cobalt.liubquanti.click only |
| SoundCloud | cobalt | Works through api.cobalt.liubquanti.click only (m4a) |
| Bluesky videos and photos | fxbsky.app, then bskx.app, then cobalt | Works (only the first photo of a multi-photo post) |
| Direct file links (video, image, audio, pdf, zip...) | downloaded as they are | Works |
| Threads | none | Not supported (no free service works without a key) |

Private posts, stories and age-restricted videos usually can't be downloaded.
Very long YouTube videos and live-stream recordings may fail.

## Privacy

The link you share is sent to free third-party services: tikwm.com,
fxtwitter.com, vxtwitter.com, eeinstagram.com, fxbsky.app, bskx.app and the
cobalt servers rue-cobalt.xenon.zone, co.otomir23.me, cobaltapi.cjs.nz and
api.cobalt.liubquanti.click (which passes it on to the servers it relays to).
They can see which link you downloaded. SwiftDrop sends nothing else: no
account, no contacts, no files. Settings stay in your iCloud Drive.

These services are run by other people for free. Any of them can slow down,
change or stop working without notice, and then that site stops working in
SwiftDrop until the shortcut is updated.

## Changing the services

Open SwiftDrop in the Shortcuts app and tap the shortcut to edit it. The top
has a **Dictionary** with each service address. `youtube_servers` and
`cobalt_servers` hold the cobalt servers, one per line, tried in order. Only
cobalt servers that answer without a Turnstile check or API key work here.
Find them on https://cobalt.directory (the "Turnstile" column shows a cross).
On 22 October 2026 only 2 of the 25 listed servers qualified. Put the most
reliable server first (see Known limits).

The video quality and the other choices are in **Settings** (see above), not
in the shortcut itself.

## Known limits

- Shortcuts has no time limit setting and no way to catch errors in "Get
  Contents of URL" (the action has no error output). The fallback order only
  helps when a service answers: with an error (for example
  "error.api.youtube.login" or a rate limit), an empty file, or no media. If
  a server doesn't answer at all (it is down, or its address no longer
  exists), Shortcuts stops with its own error message and the next server
  isn't tried. That is why the most reliable server is first. If that server
  goes away, move it down or delete it in the Dictionary.
- YouTube works only while at least one of the free servers isn't blocked by
  YouTube. A server of your own on Vercel is blocked too.
- If only api.cobalt.liubquanti.click can fetch a YouTube video, "Audio only"
  gives an .opus file instead of .m4a.
- Some long Instagram image links from cobalt get cut short by Shortcuts
  ("Bad URL hash"). That is why InstaFix comes first for Instagram.
- Big videos are downloaded into memory first. From the share sheet iOS gives
  shortcuts much less memory, so a very large video (a long YouTube or Vimeo
  video can be 30-90 MB) may fail there. If that happens, copy the link and
  run SwiftDrop from the Shortcuts app instead (Download link from clipboard),
  or lower Video quality in Settings.
- The shortcut has about 600 actions, so it takes a moment to open in the
  Shortcuts editor.

## Rebuild and sign (on a Mac)

The shortcut is generated by `build_shortcut.py`, which uses only the Python
standard library. Service addresses are at the top of that file.

```sh
python3 ios-shortcut/build_shortcut.py --sign
```

This writes the unsigned workflow to `ios-shortcut/build/` (not committed) and
signs it with:

```sh
shortcuts sign --mode anyone \
  --input ios-shortcut/build/SwiftDrop-unsigned.shortcut \
  --output ios-shortcut/dist/SwiftDrop.shortcut
```

`dist/SwiftDrop.shortcut` is the file to share. Signing works only on a Mac
signed in to an Apple Account. The same input always gives the same unsigned
file. The signature differs on each signing, and the signer drops
`WFWorkflowName` and writes its own `WFWorkflowClientVersion`; every action is
signed exactly as built.

### Test copy

```sh
python3 ios-shortcut/build_shortcut.py --debug --sign
```

builds `ios-shortcut/build/SwiftDrop Debug 1.1.shortcut`. Open it once to add
it to the Shortcuts library (the library name is the file name), then run it
with a text file holding a link, and optionally a JSON object of settings:

```sh
printf 'https://youtu.be/jNQXAC9IVRw\n{"quality":"480","youtube":"Audio"}\n' > link.txt
shortcuts run "SwiftDrop Debug 1.1" --input-path link.txt
```

It doesn't save to Photos or show alerts. It writes what it found, which
service answered and where each file would go to iCloud Drive > Shortcuts >
SwiftDrop Debug > report.txt (and saves Files downloads in that folder).
Opening the same file again doesn't replace the copy in the library; delete
test copies in the Shortcuts app.
