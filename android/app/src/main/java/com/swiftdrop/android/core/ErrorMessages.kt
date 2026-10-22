package com.swiftdrop.android.core

/** Turns yt-dlp's (and cobalt's) errors into one plain sentence that says what to do. */
object ErrorMessages {

    const val BOT_CHECK = "YouTube is blocking downloads from this network. Try Wi-Fi, or sign in to YouTube in Settings."
    const val AGE_RESTRICTED = "This video is age-restricted. Sign in to YouTube in Settings to download it."
    const val PRIVATE = "This video is private."
    const val MEMBERS_ONLY = "This video is for channel members only."
    const val GEO_BLOCKED = "This video isn't available in your country."
    const val UNAVAILABLE = "This video is unavailable. It may have been removed."
    const val NOT_STARTED = "This live stream or premiere hasn't started yet."
    const val UNSUPPORTED = "This link isn't supported."
    const val NOT_FOUND = "The file wasn't found (HTTP 404)."
    const val FORBIDDEN = "The site refused the download (HTTP 403). Try again, or update the engine in Settings."
    const val NETWORK = "Couldn't reach the site. Check your connection and retry."
    const val GENERIC = "Download failed."

    private val ERROR_PREFIX = Regex("""^ERROR:\s*(\[[^\]]+]\s*)?([\w-]{6,}:\s*)?""")

    internal fun isAgeRestricted(lower: String) =
        "confirm your age" in lower || "age-restricted" in lower || "age restricted" in lower ||
            "inappropriate for some users" in lower || "content.video.age" in lower

    internal fun isPrivate(lower: String) =
        "private video" in lower || "this video is private" in lower || "content.video.private" in lower

    internal fun isMembersOnly(lower: String) =
        "members-only" in lower || "members only" in lower || "join this channel" in lower ||
            "channel's members" in lower || "channel’s members" in lower

    internal fun isGeoBlocked(lower: String) =
        "not available in your country" in lower || "not made this video available in your country" in lower ||
            "geo restrict" in lower || "geo-restrict" in lower || "blocked it in your country" in lower ||
            "content.video.region" in lower

    /** A one-line, human-readable reason from yt-dlp's stderr. */
    fun readable(stderr: String?): String {
        val all = stderr.orEmpty()
        val lower = all.lowercase()
        when {
            isAgeRestricted(lower) -> return AGE_RESTRICTED
            isPrivate(lower) -> return PRIVATE
            isMembersOnly(lower) -> return MEMBERS_ONLY
            isGeoBlocked(lower) -> return GEO_BLOCKED
        }
        val lines = all.lines().map { it.trim() }.filter { it.isNotEmpty() }
        val error = lines.lastOrNull { it.startsWith("ERROR:") }
            ?: lines.lastOrNull { !it.startsWith("WARNING:") }
            ?: return GENERIC
        val message = error.replace(ERROR_PREFIX, "").trim()
        val m = message.lowercase()
        val friendly = when {
            "unsupported url" in m -> UNSUPPORTED
            "this live event will begin" in m || "premieres in" in m || "live event will begin" in m -> NOT_STARTED
            EngineOutput.isForbidden(message) -> FORBIDDEN
            BotCheck.isBotCheck(all) -> BOT_CHECK
            "http error 404" in m -> NOT_FOUND
            "unable to download webpage" in m || "failed to resolve" in m || "network is unreachable" in m ||
                "temporary failure in name resolution" in m || "timed out" in m -> NETWORK
            "video unavailable" in m || "no longer available" in m || "has been removed" in m -> UNAVAILABLE
            else -> message
        }
        return friendly.take(300).ifEmpty { GENERIC }
    }

    /** cobalt's error code ("error.api.content.video.age"), or null when it is about the server, not the video. */
    fun fromCobaltCode(code: String?): String? {
        val c = code?.lowercase() ?: return null
        return when {
            "content.video.age" in c -> AGE_RESTRICTED
            "content.video.private" in c -> PRIVATE
            "content.video.region" in c -> GEO_BLOCKED
            "content.video.live" in c -> NOT_STARTED
            "content.video.unavailable" in c -> UNAVAILABLE
            else -> null
        }
    }
}
