package com.swiftdrop.android.core

/**
 * Recognises YouTube refusing yt-dlp itself (a bot check, usually because the network's address
 * is flagged, as with many mobile carriers), as opposed to the video being private, age-restricted,
 * members-only, blocked in the country or removed. Only a bot check is worth retrying elsewhere.
 */
object BotCheck {

    private val BOT_SIGNS = listOf(
        "not a bot", // "Sign in to confirm you’re not a bot" (curly or straight apostrophe)
        "confirm you're not a robot",
        "confirm you’re not a robot",
        "unusual traffic",
        "only images are available for download", // every stream withheld
        "http error 429", // Too Many Requests
    )

    /** "This video is unavailable" also covers real removals; these say it really is gone. */
    private val REALLY_GONE = listOf(
        "removed",
        "terminated",
        "no longer available",
        "copyright",
        "deleted",
        "does not exist",
    )

    /** True when yt-dlp's [stderr] says YouTube blocked the request rather than the video. */
    fun isBotCheck(stderr: String?): Boolean {
        val text = stderr ?: return false
        val lower = text.lowercase()
        if (ErrorMessages.isAgeRestricted(lower) || ErrorMessages.isPrivate(lower) ||
            ErrorMessages.isMembersOnly(lower) || ErrorMessages.isGeoBlocked(lower)
        ) return false
        if (BOT_SIGNS.any { it in lower }) return true
        if ("sign in to confirm" in lower) return true
        if ("LOGIN_REQUIRED" in text) return true
        if ("this video is unavailable" in lower && REALLY_GONE.none { it in lower }) return true
        // "This content isn't available, try again later": YouTube rate-limiting the session.
        if (("content isn't available" in lower || "content isn’t available" in lower) && "try again later" in lower) return true
        // HTTP 403 on every format, or formats withheld for want of a proof-of-origin token.
        if (EngineOutput.isForbidden(text)) return true
        if ("requested format is not available" in lower && ("po token" in lower || "po_token" in lower)) return true
        return false
    }
}
