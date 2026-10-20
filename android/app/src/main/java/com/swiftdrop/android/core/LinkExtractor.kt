package com.swiftdrop.android.core

/**
 * Pulls the first http(s) link out of shared text and drops tracking parameters.
 *
 * Apps share text in many shapes: YouTube sends "Title https://youtu.be/ID?si=…",
 * Chrome sends the bare URL, chat apps wrap it in prose and punctuation. Pure Kotlin
 * (no android.net.Uri) so it is unit-testable on the JVM.
 */
object LinkExtractor {

    private val URL_REGEX = Regex("""(?i)\bhttps?://[^\s<>"'`{}|\\^]+""")

    /** Characters that end a sentence rather than a URL when they trail the match. */
    private const val TRAILING_PUNCTUATION = ".,;:!?'\"”’»…]}>"

    /** Tracking keys removed from every link. */
    private val GLOBAL_TRACKING = setOf(
        "fbclid", "gclid", "dclid", "gbraid", "wbraid", "msclkid", "yclid",
        "igshid", "igsh", "mibextid", "mc_cid", "mc_eid", "_hsenc", "_hsmi",
    )

    /** Keys that are tracking only on specific hosts (they can mean something elsewhere). */
    private val YOUTUBE_TRACKING = setOf("si", "feature", "pp", "embeds_referring_euri", "source_ve_path")
    private val SPOTIFY_TRACKING = setOf("si", "context", "nd")
    private val TWITTER_TRACKING = setOf("s", "t", "ref_src", "ref_url")
    private val TIKTOK_TRACKING = setOf("_r", "_t", "is_from_webapp", "sender_device", "is_copy_url", "share_app_id")

    /** Returns the first http(s) URL in [text] with tracking parameters removed, or null. */
    fun firstUrl(text: CharSequence?): String? {
        if (text.isNullOrBlank()) return null
        for (match in URL_REGEX.findAll(text)) {
            val candidate = trimTrailing(match.value)
            if (hostOf(candidate).isNotEmpty()) return stripTracking(candidate)
        }
        return null
    }

    internal fun trimTrailing(url: String): String {
        var end = url.length
        while (end > 0) {
            val c = url[end - 1]
            if (c == ')') {
                // Keep a closing paren only if it balances one inside the URL (Wikipedia-style links).
                val body = url.substring(0, end)
                if (body.count { it == ')' } > body.count { it == '(' }) {
                    end--
                    continue
                }
                break
            }
            if (c in TRAILING_PUNCTUATION) end-- else break
        }
        return url.substring(0, end)
    }

    /** Lower-cased host without "www.", port or credentials; empty when there is none. */
    fun hostOf(url: String): String {
        val afterScheme = url.substringAfter("://", missingDelimiterValue = "")
        val authority = afterScheme.takeWhile { it != '/' && it != '?' && it != '#' }
        val host = authority.substringAfterLast('@').substringBefore(':').lowercase()
        return host.removePrefix("www.").trimEnd('.')
    }

    fun stripTracking(url: String): String {
        val hashIndex = url.indexOf('#')
        val fragment = if (hashIndex >= 0) url.substring(hashIndex) else ""
        val withoutFragment = if (hashIndex >= 0) url.substring(0, hashIndex) else url
        val queryIndex = withoutFragment.indexOf('?')
        if (queryIndex < 0) return url

        val base = withoutFragment.substring(0, queryIndex)
        val host = hostOf(base)
        val kept = withoutFragment.substring(queryIndex + 1)
            .split('&')
            .filter { it.isNotEmpty() && !isTracking(host, it.substringBefore('=')) }
        val query = if (kept.isEmpty()) "" else "?" + kept.joinToString("&")
        return base + query + fragment
    }

    private fun isTracking(host: String, rawKey: String): Boolean {
        val key = rawKey.lowercase()
        if (key.startsWith("utm_") || key in GLOBAL_TRACKING) return true
        return when {
            isYouTube(host) -> key in YOUTUBE_TRACKING
            host == "spotify.com" || host.endsWith(".spotify.com") -> key in SPOTIFY_TRACKING
            host in setOf("twitter.com", "mobile.twitter.com", "x.com") -> key in TWITTER_TRACKING
            host == "tiktok.com" || host.endsWith(".tiktok.com") -> key in TIKTOK_TRACKING
            else -> false
        }
    }

    fun isYouTube(host: String): Boolean =
        host == "youtu.be" || host == "youtube.com" || host.endsWith(".youtube.com") ||
            host == "youtube-nocookie.com" || host.endsWith(".youtube-nocookie.com")
}
