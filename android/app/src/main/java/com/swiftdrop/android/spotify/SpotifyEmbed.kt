package com.swiftdrop.android.spotify

import com.swiftdrop.android.core.FileNames
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject

/** What a Spotify link holds: one song, or an album/playlist of songs. */
sealed interface SpotifyContent

data class SpotifyTrack(
    val id: String,
    val title: String,
    val artists: List<String>,
    /** Seconds. */
    val duration: Double?,
    val image: String? = null,
) : SpotifyContent {
    /** "Artist, Artist - Title": the list title and the file name. */
    val display: String get() = if (artists.isNotEmpty()) "${artists.joinToString(", ")} - $title" else title

    /** "Artist, Artist - Title.m4a", safe for every Android storage backend. */
    fun fileName(extension: String): String = FileNames.displayName(display, extension)
}

data class SpotifyCollection(
    /** "album" | "playlist" */
    val kind: String,
    val id: String,
    val name: String,
    val image: String?,
    val tracks: List<SpotifyTrack>,
) : SpotifyContent {
    /** Without signing in, Spotify's embed page lists only the first 100 songs of a playlist. */
    val partial: Boolean get() = kind == "playlist" && tracks.size >= SpotifyEmbed.EMBED_TRACK_LIMIT
}

/**
 * Reads Spotify's public embed page (https://open.spotify.com/embed/{type}/{id}): its
 * `__NEXT_DATA__` JSON has the song, or the album/playlist and its songs. No sign-in, no cookies.
 * The JSON paths mirror the desktop `parse_embed`; anything unexpected fails clearly.
 */
object SpotifyEmbed {

    const val EMBED_TRACK_LIMIT = 100

    private val NEXT_DATA = Regex(
        """<script id="__NEXT_DATA__" type="application/json">(.*?)</script>""",
        RegexOption.DOT_MATCHES_ALL,
    )

    /** Spotify joins artists with comma + no-break space; "Tyler, The Creator" is one artist. */
    private const val ARTIST_SEPARATOR = ", "

    fun parse(html: String, link: SpotifyLink): SpotifyContent {
        val found = NEXT_DATA.find(html) ?: throw SpotifyException.pageChanged("no __NEXT_DATA__")
        val data = try {
            JSONObject(found.groupValues[1])
        } catch (e: JSONException) {
            throw SpotifyException.pageChanged("unreadable __NEXT_DATA__")
        }
        val props = data.optJSONObject("props")?.opt("pageProps") as? JSONObject
            ?: throw SpotifyException.pageChanged("no pageProps")

        // A missing or private playlist still answers HTTP 200; this is the only signal.
        val status = props.opt("status")
        if (status is Number && status.toDouble() == 404.0) throw SpotifyException.notFound(link.kind)

        val entity = props.optJSONObject("state")?.optJSONObject("data")?.opt("entity") as? JSONObject
            ?: throw SpotifyException.pageChanged("no entity")
        val image = largestImage(entity)

        if (link.kind == "track") {
            val artists = entity.optJSONArray("artists").objects()
                .mapNotNull { text(it.opt("name")) }
            val title = text(entity.opt("title")) ?: text(entity.opt("name"))
                ?: throw SpotifyException.pageChanged("a song without a title")
            return SpotifyTrack(link.id, title, artists, seconds(entity.opt("duration")), image)
        }

        val items = entity.opt("trackList") as? JSONArray ?: throw SpotifyException.pageChanged("no trackList")
        val tracks = items.objects().mapNotNull { item ->
            val uri = text(item.opt("uri")) ?: ""
            val colon = uri.lastIndexOf(':')
            val kind = if (colon >= 0) uri.substring(0, colon) else ""
            val trackId = uri.substring(colon + 1)
            val title = text(item.opt("title"))
            // Podcast episodes in a playlist and local files are left out.
            if (kind != "spotify:track" || trackId.isEmpty() || title == null) return@mapNotNull null
            val artists = (text(item.opt("subtitle")) ?: "")
                .split(ARTIST_SEPARATOR)
                .map { it.trim() }
                .filter { it.isNotEmpty() }
            SpotifyTrack(trackId, title, artists, seconds(item.opt("duration")))
        }
        val name = text(entity.opt("name"))?.trim()?.ifEmpty { null }
            ?: text(entity.opt("title"))?.trim()?.ifEmpty { null }
            ?: "Spotify ${link.kind}"
        return SpotifyCollection(link.kind, link.id, name, image, tracks)
    }

    private fun largestImage(entity: JSONObject): String? {
        val sized = entity.optJSONObject("visualIdentity")?.optJSONArray("image").objects()
            .filter { text(it.opt("url")) != null }
        if (sized.isNotEmpty()) {
            // The first of the widest, like Python's max().
            var best = sized.first()
            for (image in sized) if (width(image) > width(best)) best = image
            return text(best.opt("url"))
        }
        return entity.optJSONObject("coverArt")?.optJSONArray("sources").objects()
            .firstNotNullOfOrNull { text(it.opt("url")) }
    }

    private fun width(image: JSONObject): Double = (image.opt("maxWidth") as? Number)?.toDouble() ?: 0.0

    private fun seconds(ms: Any?): Double? =
        (ms as? Number)?.toDouble()?.takeIf { it > 0 }?.let { it / 1000 }

    /** A non-empty string value; JSON null, numbers and objects don't count. */
    private fun text(value: Any?): String? = (value as? String)?.takeIf { it.isNotEmpty() }

    private fun JSONArray?.objects(): List<JSONObject> =
        if (this == null) emptyList() else (0 until length()).mapNotNull { optJSONObject(it) }
}
