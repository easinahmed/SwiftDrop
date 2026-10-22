package com.swiftdrop.android.youtube

/**
 * One cookie line for a Netscape cookies.txt. [toString] never includes the value: cookies are
 * a login, and must not end up in logs or crash reports.
 */
class CookieEntry(
    val domain: String,
    val includeSubdomains: Boolean,
    val path: String,
    val secure: Boolean,
    /** Unix time in seconds; 0 = session cookie. */
    val expires: Long,
    val name: String,
    val value: String,
) {
    override fun toString(): String = "CookieEntry(domain=$domain, name=$name, value=<${value.length} chars>)"
}

/**
 * Writes the Netscape cookies.txt that yt-dlp reads with `--cookies`.
 *
 * Android's CookieManager only gives "name=value; name2=value2" for a URL, without domain, path or
 * expiry, so each cookie is written for the whole site (".youtube.com", path "/", secure) with a
 * far-off expiry. `__Host-` cookies are tied to their exact host by definition, so they stay there.
 */
object CookiesTxt {

    const val HEADER = "# Netscape HTTP Cookie File"
    private const val ONE_YEAR_SECONDS = 365L * 24 * 60 * 60

    /** Pairs from a Cookie header ("a=b; c=d"). Blank names are dropped; values may contain '='. */
    fun parseHeader(header: String?): List<Pair<String, String>> =
        header.orEmpty().split(';').mapNotNull { part ->
            val trimmed = part.trim()
            val eq = trimmed.indexOf('=')
            if (eq <= 0) return@mapNotNull null
            trimmed.substring(0, eq).trim() to trimmed.substring(eq + 1).trim()
        }

    /**
     * Entries for the cookies CookieManager returned for [host] (e.g. "www.youtube.com"), scoped to
     * [siteDomain] (e.g. "youtube.com").
     */
    fun entries(host: String, siteDomain: String, cookieHeader: String?, nowSeconds: Long): List<CookieEntry> =
        parseHeader(cookieHeader).map { (name, value) ->
            val hostOnly = name.startsWith("__Host-")
            CookieEntry(
                domain = if (hostOnly) host else ".$siteDomain",
                includeSubdomains = !hostOnly,
                path = "/",
                secure = true,
                expires = nowSeconds + ONE_YEAR_SECONDS,
                name = name,
                value = value,
            )
        }

    /** The file's text. Drops cookies that would break the tab-separated format; keeps the first of duplicates. */
    fun write(entries: List<CookieEntry>): String = buildString {
        append(HEADER).append('\n')
        append("# Written by SwiftDrop for yt-dlp. Do not share this file.\n")
        val seen = HashSet<Triple<String, String, String>>()
        for (e in entries) {
            if (!isWritable(e)) continue
            if (!seen.add(Triple(e.domain, e.path, e.name))) continue
            append(e.domain).append('\t')
            append(if (e.includeSubdomains) "TRUE" else "FALSE").append('\t')
            append(e.path).append('\t')
            append(if (e.secure) "TRUE" else "FALSE").append('\t')
            append(e.expires).append('\t')
            append(e.name).append('\t')
            append(e.value).append('\n')
        }
    }

    /**
     * True when [text] holds a signed-in session for [siteDomain] (e.g. "youtube.com"). Google's own
     * cookies arrive first during sign-in; YouTube's only once the browser has been sent back to it.
     */
    fun hasLogin(text: String, siteDomain: String): Boolean =
        text.lineSequence()
            .filter { it.isNotBlank() && !it.startsWith("#") }
            .map { it.split('\t') }
            .filter { it.size == 7 && it[0].trimStart('.').let { d -> d == siteDomain || d.endsWith(".$siteDomain") } }
            .any { it[5] in LOGIN_COOKIES }

    /** Cookies Google sets only for a signed-in account. */
    val LOGIN_COOKIES = setOf("SID", "SAPISID", "__Secure-1PSID", "__Secure-3PSID", "LOGIN_INFO")

    private fun isWritable(e: CookieEntry): Boolean {
        val fields = listOf(e.domain, e.path, e.name, e.value)
        return e.name.isNotEmpty() && e.domain.isNotEmpty() && fields.none { f -> f.any { it == '\t' || it == '\n' || it == '\r' } }
    }
}
