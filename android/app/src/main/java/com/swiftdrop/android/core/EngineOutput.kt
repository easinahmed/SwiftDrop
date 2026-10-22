package com.swiftdrop.android.core

/** Parsing helpers for yt-dlp's console output. */
object EngineOutput {

    private val SPEED = Regex("""\bat\s+~?\s*([\d.]+\s*[KMGT]?i?B/s)""")

    /** "1.23MiB/s" from "[download]  12.3% of 10.00MiB at 1.23MiB/s ETA 00:05", else null. */
    fun speed(line: String?): String? =
        line?.let { SPEED.find(it)?.groupValues?.get(1)?.replace(" ", "") }

    /** YouTube refused the stream address (HTTP 403), which a fresh extraction usually fixes. */
    fun isForbidden(stderr: String?): Boolean =
        stderr != null && (stderr.contains("HTTP Error 403") || stderr.contains("403: Forbidden"))

    /** "1.23MiB/s" in yt-dlp's style from bytes per second; null when nothing has moved yet. */
    fun formatSpeed(bytesPerSecond: Long): String? {
        if (bytesPerSecond <= 0) return null
        val units = listOf("B/s", "KiB/s", "MiB/s", "GiB/s")
        var value = bytesPerSecond.toDouble()
        var unit = 0
        while (value >= 1024 && unit < units.lastIndex) {
            value /= 1024
            unit++
        }
        return String.format(java.util.Locale.US, "%.2f%s", value, units[unit])
    }

    /** A one-line, human-readable reason from yt-dlp's stderr. */
    fun readableError(stderr: String?): String = ErrorMessages.readable(stderr)
}
