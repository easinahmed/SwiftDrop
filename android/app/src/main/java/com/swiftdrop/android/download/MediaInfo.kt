package com.swiftdrop.android.download

import com.swiftdrop.android.core.LinkExtractor
import java.io.File
import org.json.JSONObject

/** What the UI needs from yt-dlp's `-J` output. */
data class MediaInfo(
    val title: String?,
    val site: String?,
    val thumbnail: String?,
    val isPlaylist: Boolean,
    /** Number of separate streams that are downloaded and merged (video + audio = 2). */
    val streamCount: Int,
    val infoFile: File,
) {
    companion object {
        fun parse(json: String, sourceUrl: String, infoFile: File): MediaInfo {
            val o = JSONObject(json)
            val type = o.str("_type") ?: "video"
            val thumbnail = o.str("thumbnail") ?: o.optJSONArray("thumbnails")?.let { list ->
                (list.length() - 1 downTo 0).asSequence()
                    .mapNotNull { list.optJSONObject(it)?.str("url") }
                    .firstOrNull()
            }
            val site = o.str("webpage_url_domain")?.removePrefix("www.")
                ?: LinkExtractor.hostOf(sourceUrl).ifEmpty { null }
                ?: o.str("extractor_key")
            return MediaInfo(
                title = o.str("title") ?: o.str("fulltitle"),
                site = site,
                thumbnail = thumbnail?.takeIf { it.startsWith("http") },
                isPlaylist = type == "playlist" || type == "multi_video",
                streamCount = o.optJSONArray("requested_formats")?.length()?.coerceAtLeast(1) ?: 1,
                infoFile = infoFile,
            )
        }

        private fun JSONObject.str(key: String): String? =
            if (has(key) && !isNull(key)) optString(key).takeIf { it.isNotBlank() } else null
    }
}
