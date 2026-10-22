package com.swiftdrop.android.cobalt

import com.swiftdrop.android.core.AudioFormat
import com.swiftdrop.android.core.FormatOptions
import com.swiftdrop.android.core.Quality
import com.swiftdrop.android.core.VideoFormat
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject

/**
 * Community cobalt servers (https://github.com/imputnet/cobalt) tried, in order, when YouTube
 * refuses yt-dlp on this phone's network. Only servers that answer without a Turnstile/JWT key
 * work here. Keep this list short and current; it is the one place to edit.
 */
object CobaltInstances {
    val DEFAULT: List<String> = listOf(
        "https://rue-cobalt.xenon.zone/",
        "https://api.cobalt.liubquanti.click/",
        "https://cobaltapi.cjs.nz/",
    )
}

/** The JSON body for cobalt's `POST /` (API v10+). */
data class CobaltRequest(
    val url: String,
    val audioOnly: Boolean,
    /** "1080", "720", … (cobalt's videoQuality); capped at 1080. */
    val videoQuality: String,
    /** "h264" or "vp9". */
    val videoCodec: String,
    /** "mp4", "mkv" or "webm". */
    val videoContainer: String,
    /** "best", "mp3" or "opus". */
    val audioFormat: String,
    /** "128", "256" or "320"; only sent for MP3. */
    val audioBitrate: String?,
) {
    fun toJson(): String = JSONObject().apply {
        put("url", url)
        if (audioOnly) {
            put("downloadMode", "audio")
            put("audioFormat", audioFormat)
            audioBitrate?.let { put("audioBitrate", it) }
        } else {
            put("videoQuality", videoQuality)
            put("youtubeVideoContainer", videoContainer)
        }
        // "best" audio follows the codec: H.264 streams come with AAC (an .m4a), VP9 with Opus.
        put("youtubeVideoCodec", videoCodec)
        put("filenameStyle", "basic")
    }.toString()

    companion object {
        const val MAX_HEIGHT = 1080
        private val HEIGHTS = listOf(1080, 720, 480, 360, 240, 144)

        /** The user's quality and formats, translated to what cobalt accepts. */
        fun build(url: String, quality: Quality, options: FormatOptions): CobaltRequest {
            val height = (quality.maxShortSide ?: MAX_HEIGHT).coerceAtMost(MAX_HEIGHT)
            val videoQuality = HEIGHTS.firstOrNull { it <= height } ?: HEIGHTS.last()
            val webm = options.videoFormat == VideoFormat.WEBM
            val codec = when {
                quality.isAudio -> if (options.audioFormat == AudioFormat.OPUS) "vp9" else "h264"
                webm -> "vp9"
                options.preferH264 || options.videoFormat == VideoFormat.MP4 -> "h264"
                else -> "vp9"
            }
            return CobaltRequest(
                url = url,
                audioOnly = quality.isAudio,
                videoQuality = videoQuality.toString(),
                videoCodec = codec,
                videoContainer = options.videoFormat.extension,
                // cobalt has no "m4a" (it answers invalid_body); "best" with H.264 gives YouTube's AAC .m4a.
                audioFormat = when (options.audioFormat) {
                    AudioFormat.M4A -> "best"
                    AudioFormat.MP3 -> "mp3"
                    AudioFormat.OPUS -> "opus"
                },
                // cobalt accepts 320/256/128/96/64/8 kbps, not 192: round up so quality never drops.
                audioBitrate = if (options.audioFormat == AudioFormat.MP3) {
                    when {
                        options.mp3Bitrate <= 128 -> "128"
                        options.mp3Bitrate <= 256 -> "256"
                        else -> "320"
                    }
                } else {
                    null
                },
            )
        }
    }
}

/** One answer from cobalt's `POST /`. */
sealed interface CobaltResponse {
    /** A file to fetch: "tunnel" (streamed through the server) or "redirect" (straight from the source). */
    data class Download(val url: String, val filename: String?, val tunnel: Boolean) : CobaltResponse

    /** Several items (photo posts and the like); YouTube never answers this, other sites can. */
    data class Picker(val items: List<PickerItem>, val audioUrl: String?, val audioFilename: String?) : CobaltResponse

    data class Error(val code: String) : CobaltResponse

    /** A status this app doesn't handle (e.g. "local-processing"). */
    data class Unsupported(val status: String) : CobaltResponse

    data class PickerItem(val type: String, val url: String)

    companion object {
        const val MALFORMED = "error.swiftdrop.malformed"

        fun parse(body: String?): CobaltResponse {
            val json = try {
                JSONObject(body ?: return Error(MALFORMED))
            } catch (_: JSONException) {
                return Error(MALFORMED)
            }
            return when (val status = json.optString("status")) {
                "tunnel", "redirect", "stream" -> {
                    val url = json.str("url") ?: return Error(MALFORMED)
                    Download(url, json.str("filename"), tunnel = status != "redirect")
                }
                "picker" -> {
                    val list = json.optJSONArray("picker") ?: JSONArray()
                    val items = (0 until list.length()).mapNotNull { i ->
                        val item = list.optJSONObject(i) ?: return@mapNotNull null
                        val url = item.str("url") ?: return@mapNotNull null
                        PickerItem(item.str("type") ?: "video", url)
                    }
                    if (items.isEmpty() && json.str("audio") == null) Error(MALFORMED)
                    else Picker(items, json.str("audio"), json.str("audioFilename"))
                }
                "error" -> Error(json.optJSONObject("error")?.str("code") ?: json.str("text") ?: "error.api.generic")
                else -> Unsupported(status.ifEmpty { "unknown" })
            }
        }

        private fun JSONObject.str(key: String): String? =
            if (has(key) && !isNull(key)) optString(key).takeIf { it.isNotBlank() } else null
    }
}

/** What to download from a cobalt answer, or null when there is nothing usable. */
fun CobaltResponse.mediaUrl(audioOnly: Boolean): Pair<String, String?>? = when (this) {
    is CobaltResponse.Download -> url to filename
    is CobaltResponse.Picker -> when {
        audioOnly && audioUrl != null -> audioUrl to audioFilename
        else -> (items.firstOrNull { it.type == "video" } ?: items.firstOrNull())?.let { it.url to null }
            ?: audioUrl?.let { it to audioFilename }
    }
    else -> null
}

object CobaltErrors {
    /** The server itself is blocked by YouTube (needs a login) — try the next one. */
    fun isLoginBlocked(code: String): Boolean = "youtube.login" in code

    /** The server wants a Turnstile/JWT key this app can't provide. */
    fun needsKey(code: String): Boolean = code.startsWith("error.api.auth.")
}

/** "Big Buck Bunny (720p, h264).mp4" → "Big Buck Bunny": cobalt's file name without its quality note. */
object CobaltNames {
    private val QUALITY_NOTE = Regex("""\s*\((?:\d{3,4}p|audio)[^)]*\)\s*$""", RegexOption.IGNORE_CASE)

    fun title(filename: String?): String? {
        val base = filename?.substringBeforeLast('.', filename)?.trim() ?: return null
        return base.replace(QUALITY_NOTE, "").trim().ifEmpty { null }
    }

    fun extension(filename: String?): String? =
        filename?.substringAfterLast('.', "")?.lowercase()?.takeIf { it.length in 2..5 && it.all(Char::isLetterOrDigit) }
}
