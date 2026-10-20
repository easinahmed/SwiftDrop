package com.swiftdrop.android.core

/** Download quality offered in Settings. Stored by [name]. */
enum class Quality(val label: String, val maxShortSide: Int?) {
    BEST("Best available", null),
    P1080("1080p", 1080),
    P720("720p", 720),
    P480("480p", 480),
    AUDIO("Audio only (m4a)", null);

    val isAudio: Boolean get() = this == AUDIO

    companion object {
        val DEFAULT = P1080

        fun fromKey(key: String?): Quality = entries.firstOrNull { it.name == key } ?: DEFAULT
    }
}

/** The yt-dlp selection for one quality: `-f` expression, optional `-S` sort, and post-processing flags. */
data class FormatPlan(
    val format: String,
    val sort: String?,
    val postProcessing: List<String>,
) {
    fun toArgs(): List<String> = buildList {
        add("-f"); add(format)
        if (sort != null) { add("-S"); add(sort) }
        addAll(postProcessing)
    }
}

/**
 * Builds yt-dlp format arguments.
 *
 * Video: separate best video + best audio merged to MP4, falling back to the best single
 * file (`/b`), which is also what a direct file link resolves to. `-S res:N` caps the
 * resolution by the *shorter* side, so vertical Shorts at 1080x1920 still count as 1080p;
 * `vcodec:h264,acodec:aac,ext:mp4:m4a` makes H.264 + AAC in MP4/M4A win ties, which
 * plays everywhere and merges into MP4 without re-encoding.
 */
object FormatSelector {

    private const val CODEC_PREFERENCE = "vcodec:h264,acodec:aac,ext:mp4:m4a"
    private val MERGE_TO_MP4 = listOf("--merge-output-format", "mp4")

    fun plan(quality: Quality): FormatPlan = when (quality) {
        Quality.BEST -> FormatPlan("bv*+ba/b", "res,$CODEC_PREFERENCE", MERGE_TO_MP4)
        Quality.P1080, Quality.P720, Quality.P480 ->
            FormatPlan("bv*+ba/b", "res:${quality.maxShortSide},$CODEC_PREFERENCE", MERGE_TO_MP4)
        Quality.AUDIO -> FormatPlan(
            "ba[ext=m4a]/ba[acodec^=mp4a]/ba/b",
            "acodec:aac,ext:m4a",
            listOf("-x", "--audio-format", "m4a"),
        )
    }

    fun args(quality: Quality): List<String> = plan(quality).toArgs()
}
