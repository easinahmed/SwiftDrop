package com.swiftdrop.android.spotify

import java.net.URI

/** A Spotify song, album or playlist. */
data class SpotifyLink(val kind: String, val id: String) {
    val url: String get() = "https://open.spotify.com/$kind/$id"
    val embedUrl: String get() = "https://open.spotify.com/embed/$kind/$id"
}

/** Why a Spotify link couldn't be turned into songs. [message] is shown to the user as is. */
class SpotifyException(val reason: Reason, message: String) : Exception(message) {
    enum class Reason { UNSUPPORTED, NOT_FOUND, PAGE_CHANGED, NETWORK }

    companion object {
        const val UNSUPPORTED_TITLE = "Unsupported Spotify link"

        fun unsupported(url: String? = null) = SpotifyException(
            Reason.UNSUPPORTED,
            if (url != null && SpotifyLinks.isPodcast(url)) SpotifyLinks.PODCAST_MESSAGE
            else "$UNSUPPORTED_TITLE. Only Spotify songs, albums and playlists can be downloaded.",
        )

        fun pageChanged(detail: String) = SpotifyException(
            Reason.PAGE_CHANGED,
            "Couldn't read this Spotify link: Spotify's page didn't have the song list SwiftDrop expects " +
                "($detail). Spotify may have changed its website.",
        )

        fun notFound(kind: String) = SpotifyException(
            Reason.NOT_FOUND,
            "This Spotify $kind is private or doesn't exist. Make sure it's public, then share it again.",
        )
    }
}

/**
 * Spotify links: open.spotify.com/{track|album|playlist}/{id} (with ?si=…, /intl-xx/ or /embed/),
 * and spotify.link short links, which redirect to one of those. Ported from the desktop
 * `swiftdrop/providers/spotify.py`. Pure Kotlin so it runs in JVM unit tests.
 */
object SpotifyLinks {

    private val SPOTIFY_HOSTS = setOf("open.spotify.com", "play.spotify.com")
    private val SHORT_LINK_HOSTS = setOf("spotify.link", "spotify.app.link")
    private val PATH = Regex(
        """^/(?:intl-[a-z]{2}(?:-[a-z]{2})?/)?(?:embed/)?(track|album|playlist)/([A-Za-z0-9]{22})/?$""",
        RegexOption.IGNORE_CASE,
    )
    private val PODCAST_PATH = Regex(
        """^/(?:intl-[a-z]{2}(?:-[a-z]{2})?/)?(?:embed/)?(episode|show|audiobook|chapter)/""",
        RegexOption.IGNORE_CASE,
    )
    private val LINK_IN_PAGE = Regex("""https://open\.spotify\.com/(track|album|playlist)/([A-Za-z0-9]{22})""")
    private const val MAX_REDIRECTS = 10

    /** Short enough for a two-line toast. */
    const val PODCAST_MESSAGE = "Spotify podcasts can't be saved (DRM). Songs, albums and playlists work."

    /** Lower-cased host without port or credentials ("www." is kept: it isn't a Spotify host). */
    fun host(url: String): String {
        val afterScheme = url.substringAfter("://", missingDelimiterValue = "")
        val authority = afterScheme.takeWhile { it != '/' && it != '?' && it != '#' }
        return authority.substringAfterLast('@').substringBefore(':').lowercase().trimEnd('.')
    }

    private fun path(url: String): String {
        val afterScheme = url.substringAfter("://", missingDelimiterValue = "")
        val rest = afterScheme.dropWhile { it != '/' && it != '?' && it != '#' }
        return rest.takeWhile { it != '?' && it != '#' }
    }

    /** A Spotify song, album or playlist link; null for anything else (podcasts, artists, …). */
    fun parse(url: String): SpotifyLink? {
        if (host(url) !in SPOTIFY_HOSTS) return null
        val match = PATH.matchEntire(path(url)) ?: return null
        return SpotifyLink(match.groupValues[1].lowercase(), match.groupValues[2])
    }

    /** spotify.link share links, which redirect to a song, album or playlist. */
    fun isShortLink(url: String): Boolean {
        val host = host(url)
        return SHORT_LINK_HOSTS.any { host == it || host.endsWith(".$it") }
    }

    /** Any Spotify link: these never go to yt-dlp, which can't read Spotify. */
    fun isSpotify(url: String): Boolean {
        val host = host(url)
        return host == "spotify.com" || host.endsWith(".spotify.com") || isShortLink(url)
    }

    fun isPodcast(url: String): Boolean = isSpotify(url) && PODCAST_PATH.containsMatchIn(path(url))

    /** Why SwiftDrop won't even try this Spotify link, or null when it can (or might, for short links). */
    fun refusal(url: String): String? = when {
        !isSpotify(url) || parse(url) != null || isShortLink(url) -> null
        isPodcast(url) -> PODCAST_MESSAGE
        else -> "${SpotifyException.UNSUPPORTED_TITLE}. Only Spotify songs, albums and playlists can be downloaded."
    }

    /** One HTTP answer, redirects not followed. */
    data class Answer(val code: Int, val location: String?, val body: String)

    /**
     * The song, album or playlist a link points to. Short links are followed one redirect at a
     * time with [fetch]. A plain (non-browser) User-Agent gets a redirect straight to the target;
     * a browser gets an in-between page that links to it, which is read only while still on a
     * short-link host: a dead link redirects to Spotify's home page, whose links are someone
     * else's playlists.
     */
    fun resolve(url: String, fetch: (String) -> Answer): SpotifyLink {
        var current = url
        repeat(MAX_REDIRECTS + 1) {
            parse(current)?.let { return it }
            if (!isShortLink(current)) throw SpotifyException.unsupported(current)
            val answer = fetch(current)
            val location = answer.location
            when {
                answer.code in 300..399 && !location.isNullOrBlank() ->
                    current = runCatching { URI(current).resolve(location.trim()).toString() }
                        .getOrElse { throw SpotifyException.unsupported() }
                answer.code >= 400 -> throw httpError(answer.code)
                else -> {
                    val found = LINK_IN_PAGE.find(answer.body) ?: throw SpotifyException.unsupported()
                    return SpotifyLink(found.groupValues[1], found.groupValues[2])
                }
            }
        }
        throw SpotifyException.unsupported()
    }

    fun httpError(code: Int): SpotifyException = when (code) {
        404, 410 -> SpotifyException(SpotifyException.Reason.NOT_FOUND, "This Spotify link doesn't exist any more.")
        429 -> SpotifyException(
            SpotifyException.Reason.NETWORK,
            "Spotify is limiting requests right now. Try again in a minute.",
        )
        else -> SpotifyException(SpotifyException.Reason.NETWORK, "Spotify answered with an error (HTTP $code). Try again later.")
    }
}
