# FFmpeg in SwiftDrop

SwiftDrop bundles unmodified FFmpeg command-line programs (`ffmpeg`, `ffprobe`) and runs them as
separate processes to merge and convert media. They are not linked into SwiftDrop.

* Licence of the bundled build: **GPL v2 or later** (determined from its build configuration).
* Obtained from: local copy of /usr/local/bin
* FFmpeg source code: https://ffmpeg.org/download.html (the release matching the version below).
* Licence texts: https://www.gnu.org/licenses/ — see also https://ffmpeg.org/legal.html

To ship an LGPL-only build instead, provision one with `scripts/fetch_binaries.py --from <dir>`
(any statically linked build without `--enable-gpl` / `--enable-nonfree`).

## ffmpeg

* Version: `ffmpeg version 7.1.1-https://www.martin-riedl.de Copyright (c) 2000-2025 the FFmpeg developers`
* SHA-256: `a0c8a9eb2234780c5ac102ecb4b12f2375fe45bf7f6e8263ae3ab54e8f87acfd`

## ffprobe

* Version: `ffprobe version 7.1.1-https://www.martin-riedl.de Copyright (c) 2007-2025 the FFmpeg developers`
* SHA-256: `ae4978e9d6dc7900d138a52625a723bbc4c10faf51afa37b47702b0724e5042c`

## Build configuration

```
configuration:
    --prefix=/Volumes/ffmpeg_arm64/out
    --pkg-config-flags=--static
    --extra-version='https://www.martin-riedl.de'
    --enable-gray
    --enable-libxml2
    --enable-gpl
    --enable-libfreetype
    --enable-fontconfig
    --enable-libharfbuzz
    --enable-libsnappy
    --enable-libsrt
    --enable-libvmaf
    --enable-libass
    --enable-libklvanc
    --enable-libzimg
    --enable-libzvbi
    --enable-libaom
    --enable-libdav1d
    --enable-libopenh264
    --enable-libopenjpeg
    --enable-librav1e
    --enable-libsvtav1
    --enable-libvpx
    --enable-libvvenc
    --enable-libwebp
    --enable-libx264
    --enable-libx265
    --enable-libmp3lame
    --enable-libopus
    --enable-libvorbis
    --enable-libtheora
```
