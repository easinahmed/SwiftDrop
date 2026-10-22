package com.swiftdrop.android.core

/**
 * Download quality offered in Settings and in the share sheet. Stored by [name] (in settings and
 * in each history row), so names never change; new entries are only ever added.
 */
enum class Quality(val label: String, val maxShortSide: Int?) {
    BEST("Best available", null),
    P2160("2160p (4K)", 2160),
    P1440("1440p", 1440),
    P1080("1080p", 1080),
    P720("720p", 720),
    P480("480p", 480),
    P360("360p", 360),
    AUDIO("Audio only", null);

    val isAudio: Boolean get() = this == AUDIO

    /** "1080p", "Best", "Audio" for the compact quality chips. */
    val shortLabel: String
        get() = when (this) {
            BEST -> "Best"
            P2160 -> "4K"
            AUDIO -> "Audio"
            else -> label
        }

    companion object {
        val DEFAULT = P1080

        val VIDEO: List<Quality> get() = entries.filter { !it.isAudio }

        fun fromKey(key: String?): Quality = entries.firstOrNull { it.name == key } ?: DEFAULT
    }
}

/** Container for video downloads. */
enum class VideoFormat(val label: String, val extension: String) {
    MP4("MP4", "mp4"),
    MKV("MKV", "mkv"),
    WEBM("WebM", "webm");

    companion object {
        val DEFAULT = MP4
        fun fromKey(key: String?): VideoFormat = entries.firstOrNull { it.name == key } ?: DEFAULT
    }
}

/** Format for audio-only downloads (yt-dlp extracts it with the bundled FFmpeg). */
enum class AudioFormat(val label: String, val extension: String) {
    M4A("M4A", "m4a"),
    MP3("MP3", "mp3"),
    OPUS("Opus", "opus");

    companion object {
        val DEFAULT = M4A
        fun fromKey(key: String?): AudioFormat = entries.firstOrNull { it.name == key } ?: DEFAULT
    }
}

object Mp3Bitrates {
    val OPTIONS = listOf(128, 192, 320)
    const val DEFAULT = 192

    fun coerce(kbps: Int?): Int = kbps?.takeIf { it in OPTIONS } ?: DEFAULT
}

/** Everything besides the quality that shapes yt-dlp's format choice. Defaults = SwiftDrop 1.1. */
data class FormatOptions(
    val videoFormat: VideoFormat = VideoFormat.DEFAULT,
    val preferH264: Boolean = true,
    val audioFormat: AudioFormat = AudioFormat.DEFAULT,
    val mp3Bitrate: Int = Mp3Bitrates.DEFAULT,
)

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
 * Video: separate best video + best audio merged into the chosen container, falling back to the
 * best single file (`/b`), which is also what a direct file link resolves to. `-S res:N` caps the
 * resolution by the *shorter* side, so vertical Shorts at 1080x1920 still count as 1080p.
 * With "Prefer H.264" on, `vcodec:h264,acodec:aac` makes H.264 + AAC win ties, which plays
 * everywhere and merges into MP4 without re-encoding. WebM can't hold H.264, so it prefers VP9 +
 * Opus instead, and falls back to MKV when a site only has streams WebM can't carry.
 *
 * Audio: extracted (and converted when needed) by yt-dlp's FFmpeg post-processor.
 */
object FormatSelector {

    private const val H264_PREFERENCE = "vcodec:h264,acodec:aac"

    fun plan(quality: Quality, options: FormatOptions = FormatOptions()): FormatPlan =
        if (quality.isAudio) audioPlan(options) else videoPlan(quality, options)

    fun args(quality: Quality, options: FormatOptions = FormatOptions()): List<String> =
        plan(quality, options).toArgs()

    private fun videoPlan(quality: Quality, options: FormatOptions): FormatPlan {
        val resolution = quality.maxShortSide?.let { "res:$it" } ?: "res"
        val preferences = when (options.videoFormat) {
            VideoFormat.MP4 -> if (options.preferH264) "$H264_PREFERENCE,ext:mp4:m4a" else null
            VideoFormat.MKV -> if (options.preferH264) H264_PREFERENCE else null
            VideoFormat.WEBM -> "vcodec:vp9,acodec:opus,ext:webm:webm"
        }
        val container = when (options.videoFormat) {
            VideoFormat.MP4 -> listOf("--merge-output-format", "mp4")
            VideoFormat.MKV -> listOf("--merge-output-format", "mkv", "--remux-video", "mkv")
            VideoFormat.WEBM -> listOf("--merge-output-format", "webm/mkv")
        }
        return FormatPlan("bv*+ba/b", listOfNotNull(resolution, preferences).joinToString(","), container)
    }

    private fun audioPlan(options: FormatOptions): FormatPlan = when (options.audioFormat) {
        AudioFormat.M4A -> FormatPlan(
            "ba[ext=m4a]/ba[acodec^=mp4a]/ba/b",
            "acodec:aac,ext:m4a",
            listOf("-x", "--audio-format", "m4a"),
        )
        AudioFormat.MP3 -> FormatPlan(
            "ba/b",
            null,
            listOf("-x", "--audio-format", "mp3", "--audio-quality", "${Mp3Bitrates.coerce(options.mp3Bitrate)}K"),
        )
        AudioFormat.OPUS -> FormatPlan(
            "ba[acodec=opus]/ba/b",
            "acodec:opus",
            listOf("-x", "--audio-format", "opus"),
        )
    }
}
