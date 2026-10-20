package com.swiftdrop.android.spotify

import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.Charset

/** Reads a Spotify link's songs from the public embed page. Blocking: call it off the main thread. */
object SpotifyClient {

    /**
     * Short links get a plain User-Agent: a browser gets Branch's in-between page (or a redirect
     * loop) instead of a redirect to the song, album or playlist.
     */
    private const val PLAIN_USER_AGENT = "SwiftDrop-Android/1.1"

    /** The embed page is read the way the desktop app reads it, as Safari. */
    private const val BROWSER_USER_AGENT =
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) " +
            "Version/18.0 Safari/605.1.15"

    private const val TIMEOUT_MS = 20_000
    private const val MAX_PAGE_BYTES = 8 * 1024 * 1024

    /** The song, or the album/playlist and its songs, behind [url]. */
    fun load(url: String): Pair<SpotifyLink, SpotifyContent> {
        val link = SpotifyLinks.resolve(url) { get(it, PLAIN_USER_AGENT, followRedirects = false) }
        val page = get(link.embedUrl, BROWSER_USER_AGENT, followRedirects = true)
        if (page.code >= 400) throw SpotifyLinks.httpError(page.code)
        return link to SpotifyEmbed.parse(page.body, link)
    }

    private fun get(url: String, userAgent: String, followRedirects: Boolean): SpotifyLinks.Answer {
        val connection = try {
            URL(url).openConnection() as HttpURLConnection
        } catch (e: IOException) {
            throw offline()
        }
        try {
            connection.instanceFollowRedirects = followRedirects
            connection.connectTimeout = TIMEOUT_MS
            connection.readTimeout = TIMEOUT_MS
            connection.setRequestProperty("User-Agent", userAgent)
            connection.setRequestProperty("Accept-Language", "en")
            val code = connection.responseCode
            val location = connection.getHeaderField("Location")
            val stream = if (code >= 400) connection.errorStream else connection.inputStream
            val body = if (code in 300..399 || stream == null) "" else stream.use { read(it, charset(connection)) }
            return SpotifyLinks.Answer(code, location, body)
        } catch (e: IOException) {
            throw offline()
        } finally {
            connection.disconnect()
        }
    }

    private fun read(input: InputStream, charset: Charset): String {
        val out = ByteArrayOutputStream()
        val buffer = ByteArray(64 * 1024)
        while (out.size() < MAX_PAGE_BYTES) {
            val n = input.read(buffer)
            if (n < 0) break
            out.write(buffer, 0, n)
        }
        return String(out.toByteArray(), charset)
    }

    private fun charset(connection: HttpURLConnection): Charset {
        val name = connection.contentType?.substringAfter("charset=", "")?.substringBefore(';')?.trim()
        return name?.takeIf { it.isNotEmpty() }?.let { runCatching { Charset.forName(it) }.getOrNull() } ?: Charsets.UTF_8
    }

    private fun offline() = SpotifyException(
        SpotifyException.Reason.NETWORK,
        "Couldn't reach Spotify. Check your connection and retry.",
    )
}
