# SwiftDrop for iPhone

An Apple Shortcut that works like the "YAS Download" shortcut: share a link
from any app, pick **SwiftDrop**, and the video or photos are saved to your
iPhone. It needs only an iPhone. No Mac, computer or app install.

SwiftDrop sends the link to free download services that return the real media
file, downloads it, and saves videos and photos to **Photos**. Other files
(audio, zip, pdf) are saved to **Files**.

Developed by Easin Codes.

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
- Or run SwiftDrop from the Shortcuts app or the Home Screen. It asks for the
  link and fills in whatever you copied.

A notification says "Saved N item(s) to your iPhone" when it's done. If
nothing could be downloaded, an alert says so.

## Supported sites

Checked live on 20 October 2026 from a home connection (the same kind of
network an iPhone uses). Services are tried in this order. The next one is
used if the earlier one answers with an error.

| Site | Services, in order | Status |
| --- | --- | --- |
| TikTok videos and photo slideshows | tikwm.com, then cobalt | Works (no watermark; every slideshow photo) |
| X / Twitter videos, GIFs, photos | FixTweet (api.fxtwitter.com), then vxtwitter, then cobalt | Works (every item of the post) |
| Instagram reels, videos, photos, carousels | InstaFix (eeinstagram.com), then cobalt | Works for public posts (every carousel item) |
| YouTube videos and Shorts | cobalt (rue-cobalt.xenon.zone) | Works (H.264 MP4, 720p by default) |
| Facebook videos and reels | cobalt | Works for public videos |
| Pinterest videos and images | cobalt | Works |
| Twitch clips | cobalt | Works |
| Vimeo | cobalt | Works |
| Bluesky videos and photos | fxbsky.app, then bskx.app, then cobalt | Works (only the first photo of a multi-photo post) |
| Direct file links (video, image, audio, pdf, zip...) | downloaded as they are | Works |
| Reddit | cobalt | Not working now (the free cobalt servers are blocked by Reddit) |
| SoundCloud | cobalt | Not working now |
| Threads | none | Not supported (no free service works without a key) |

Private posts, stories and age-restricted videos usually can't be downloaded.
Very long YouTube videos and live-stream recordings may fail.

## Privacy

The link you share is sent to free third-party services: tikwm.com,
fxtwitter.com, vxtwitter.com, eeinstagram.com, fxbsky.app, bskx.app and the
cobalt servers listed in the shortcut. They can see which link you
downloaded. SwiftDrop sends nothing else: no account, no contacts, no files.

These services are run by other people for free. Any of them can slow down,
change or stop working without notice, and then that site stops working in
SwiftDrop until the shortcut is updated.

## Changing the services

Open SwiftDrop in the Shortcuts app and tap the shortcut to edit it. The top
has:

- a **Dictionary** with each service address and `video_quality` (360, 480,
  720 or 1080);
- a **Text** with the cobalt servers, one per line, tried in order. Only cobalt
  servers that answer without a Turnstile check or API key work here. Find
  them on https://cobalt.directory (the "Turnstile" column shows a cross).
  Today only 2 of 18 listed servers qualify.

## Known limits

- Shortcuts has no time limit setting and no way to catch errors in "Get
  Contents of URL". The fallback order only helps when a service answers with
  an error. If a service doesn't answer at all, Shortcuts stops with its own
  error message, and the next service isn't tried.
- Some long Instagram image links from cobalt get cut short by Shortcuts
  ("Bad URL hash"). That is why InstaFix comes first for Instagram.
- Big videos are downloaded into memory first. From the share sheet iOS gives
  shortcuts much less memory, so a very large video (a long YouTube or Vimeo
  video can be 30-90 MB) may fail there. If that happens, copy the link and
  run SwiftDrop from the Shortcuts app instead, or lower `video_quality`.

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
file. The signature differs on each signing.
