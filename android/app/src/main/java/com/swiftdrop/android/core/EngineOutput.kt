package com.swiftdrop.android.core

/** Parsing helpers for yt-dlp's console output. */
object EngineOutput {

    private val SPEED = Regex("""\bat\s+~?\s*([\d.]+\s*[KMGT]?i?B/s)""")
    private val ERROR_PREFIX = Regex("""^ERROR:\s*(\[[^\]]+]\s*)?([\w-]{6,}:\s*)?""")

    /** "1.23MiB/s" from "[download]  12.3% of 10.00MiB at 1.23MiB/s ETA 00:05", else null. */
    fun speed(line: String?): String? =
        line?.let { SPEED.find(it)?.groupValues?.get(1)?.replace(" ", "") }

    /** A one-line, human-readable reason from yt-dlp's stderr. */
    fun readableError(stderr: String?): String {
        val lines = stderr.orEmpty().lines().map { it.trim() }.filter { it.isNotEmpty() }
        val error = lines.lastOrNull { it.startsWith("ERROR:") }
            ?: lines.lastOrNull { !it.startsWith("WARNING:") }
            ?: return "Download failed."
        val message = error.replace(ERROR_PREFIX, "").trim()
        val friendly = when {
            message.contains("Unsupported URL", ignoreCase = true) -> "This link isn't supported."
            message.contains("Sign in to confirm", ignoreCase = true) ->
                "YouTube wants a sign-in check for this video. Try again later or update the engine in Settings."
            message.contains("Private video", ignoreCase = true) -> "This video is private."
            message.contains("HTTP Error 404", ignoreCase = true) -> "The file wasn't found (HTTP 404)."
            message.contains("Unable to download webpage", ignoreCase = true) ||
                message.contains("Failed to resolve", ignoreCase = true) ||
                message.contains("Network is unreachable", ignoreCase = true) ->
                "Couldn't reach the site. Check your connection and retry."
            else -> message
        }
        return friendly.take(300).ifEmpty { "Download failed." }
    }
}
