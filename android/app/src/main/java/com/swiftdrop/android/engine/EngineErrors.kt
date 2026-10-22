package com.swiftdrop.android.engine

import java.io.FileNotFoundException
import java.io.IOException
import java.net.UnknownHostException

/** Plain-language reasons for a failed engine update (pure, unit-tested). */
object EngineErrors {

    const val OFFLINE = "No internet connection. Try again when you're online."
    const val RATE_LIMITED =
        "GitHub is limiting update checks from this network right now. SwiftDrop will try again later, " +
            "or tap Update now in about an hour."
    const val UNREACHABLE = "Couldn't reach GitHub to download the update. Try again later."
    const val BUSY = "Downloads are running. Update the engine when they finish."

    /** The library wraps everything in "failed to update youtube-dl"; say what actually went wrong. */
    fun describeUpdateFailure(t: Throwable): String {
        val causes = generateSequence(t) { it.cause }.take(10).toList()
        val text = causes.joinToString("\n") { it.message.orEmpty() }
        return when {
            causes.any { it is UnknownHostException } -> OFFLINE
            // GitHub answers 403 (sometimes 429) when it rate-limits unauthenticated API calls.
            "403" in text || "429" in text || "rate limit" in text.lowercase() -> RATE_LIMITED
            causes.any { it is FileNotFoundException } -> UNREACHABLE
            causes.any { it is IOException } -> UNREACHABLE
            else -> t.message?.lineSequence()?.firstOrNull()?.take(200)?.ifBlank { null } ?: "Update failed."
        }
    }

    /** True when automatic updates should wait: the last attempt was recent, or the last success is fresh. */
    fun isStale(lastUpdate: Long, now: Long, maxAgeMs: Long): Boolean = now - lastUpdate >= maxAgeMs
}
