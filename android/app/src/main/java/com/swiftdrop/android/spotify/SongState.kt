package com.swiftdrop.android.spotify

import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject

/**
 * One Spotify song as stored with its download row: the song, and once found, its YouTube
 * match, so a retried or restarted download uses the same recording without searching again.
 */
data class SongState(val track: SpotifyTrack, val match: Candidate? = null) {

    fun toJson(): String = JSONObject().apply {
        put("track", JSONObject().apply {
            put("id", track.id)
            put("title", track.title)
            put("artists", JSONArray(track.artists))
            putOpt("duration", track.duration)
            putOpt("image", track.image)
        })
        match?.let { m ->
            put("match", JSONObject().apply {
                put("videoId", m.videoId)
                put("title", m.title)
                putOpt("duration", m.duration)
                put("artists", JSONArray(m.artists))
                put("channel", m.channel)
                put("music", m.music)
                putOpt("album", m.album)
            })
        }
    }.toString()

    companion object {
        fun fromJson(json: String?): SongState? {
            if (json.isNullOrBlank()) return null
            return try {
                val o = JSONObject(json)
                val t = o.getJSONObject("track")
                val track = SpotifyTrack(
                    id = t.getString("id"),
                    title = t.getString("title"),
                    artists = t.optJSONArray("artists").strings(),
                    duration = t.number("duration"),
                    image = t.string("image"),
                )
                val match = o.optJSONObject("match")?.let { m ->
                    Candidate(
                        videoId = m.getString("videoId"),
                        title = m.optString("title"),
                        duration = m.number("duration"),
                        artists = m.optJSONArray("artists").strings(),
                        channel = m.optString("channel"),
                        music = m.optBoolean("music"),
                        album = m.string("album"),
                    )
                }
                SongState(track, match)
            } catch (e: JSONException) {
                null
            }
        }
    }
}

/** Reads yt-dlp's `-J` output for song searches and lookups. */
object YtDlpResults {

    /** Search results (`--flat-playlist -J`): entries with an id. */
    fun searchResults(json: String, music: Boolean): List<Candidate> {
        val entries = JSONObject(json).optJSONArray("entries") ?: return emptyList()
        return (0 until entries.length()).mapNotNull { i ->
            val e = entries.optJSONObject(i) ?: return@mapNotNull null
            val id = e.string("id") ?: return@mapNotNull null
            Candidate(
                videoId = id,
                title = e.string("title") ?: "",
                duration = e.number("duration"),
                channel = if (music) "" else e.string("channel") ?: e.string("uploader") ?: "",
                music = music,
            )
        }
    }

    /** A YouTube Music song looked up in detail (`-J` on music.youtube.com/watch?v=…). */
    fun details(json: String, videoId: String): Candidate {
        val info = JSONObject(json)
        val artists = info.optJSONArray("artists")?.strings()?.takeIf { it.isNotEmpty() }
            ?: info.optJSONArray("creators").strings()
        return Candidate(
            videoId = videoId,
            title = info.string("track") ?: info.string("title") ?: "",
            duration = info.number("duration"),
            artists = artists,
            channel = info.string("channel") ?: "",
            music = true,
            album = info.string("album"),
        )
    }

    /**
     * The info JSON with the Spotify song's title, artists and album, so yt-dlp's
     * `--embed-metadata` tags the file with them instead of the YouTube video's.
     */
    fun withSongTags(infoJson: String, track: SpotifyTrack, album: String?): String {
        val info = JSONObject(infoJson)
        info.put("track", track.title)
        info.put("artist", track.artists.joinToString(", "))
        info.put("artists", JSONArray(track.artists))
        if (album != null) info.put("album", album)
        return info.toString()
    }
}

internal fun JSONObject.string(key: String): String? = (opt(key) as? String)?.takeIf { it.isNotEmpty() }

internal fun JSONObject.number(key: String): Double? = (opt(key) as? Number)?.toDouble()

internal fun JSONArray?.strings(): List<String> =
    if (this == null) emptyList() else (0 until length()).mapNotNull { (opt(it) as? String)?.takeIf(String::isNotEmpty) }
