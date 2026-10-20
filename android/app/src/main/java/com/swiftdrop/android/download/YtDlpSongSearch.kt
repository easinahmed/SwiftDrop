package com.swiftdrop.android.download

import com.swiftdrop.android.spotify.Candidate
import com.swiftdrop.android.spotify.SongMatch
import com.swiftdrop.android.spotify.SongSearch
import com.swiftdrop.android.spotify.YtDlpResults
import com.yausername.youtubedl_android.YoutubeDLRequest
import java.io.File
import java.net.URLEncoder

/**
 * YouTube Music and YouTube search through yt-dlp, as the desktop app does it: no sign-in, no
 * cookies. [run] executes one request and returns yt-dlp's stdout (the `-J` JSON).
 */
class YtDlpSongSearch(
    private val cacheDir: File,
    private val run: suspend (YoutubeDLRequest) -> String,
) : SongSearch {

    override suspend fun music(query: String): List<Candidate> {
        val url = "https://music.youtube.com/search?q=${encode(query)}#songs"
        return YtDlpResults.searchResults(run(request(url, flat = true)), music = true)
    }

    override suspend fun details(videoId: String): Candidate {
        val url = "https://music.youtube.com/watch?v=${encode(videoId)}"
        return YtDlpResults.details(run(request(url, flat = false)), videoId)
    }

    override suspend fun videos(query: String): List<Candidate> =
        YtDlpResults.searchResults(run(request("ytsearch${SongMatch.SEARCH_RESULTS}:$query", flat = true)), music = false)

    private fun request(url: String, flat: Boolean) = YoutubeDLRequest(url).apply {
        addOption("-J")
        addOption("--no-warnings")
        addOption("--socket-timeout", "20")
        addOption("--extractor-retries", "2")
        addOption("--cache-dir", cacheDir.absolutePath)
        if (flat) {
            addOption("--flat-playlist")
            addOption("--playlist-end", SongMatch.SEARCH_RESULTS.toString())
        } else {
            // Only the song's details are needed, not a format that can be downloaded right now.
            addOption("--no-playlist")
            addOption("--ignore-no-formats-error")
        }
    }

    private fun encode(text: String): String = URLEncoder.encode(text, "UTF-8").replace("+", "%20")
}
