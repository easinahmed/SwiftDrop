package com.swiftdrop.android.core

/** YouTube video ids from the link shapes apps share. */
object YouTubeIds {

    private val ID = Regex("^[A-Za-z0-9_-]{11}$")
    private val PATH_ID = Regex("^(?:shorts|embed|live|v|e)/([^/?#]+)")

    /** "dQw4w9WgXcQ" from watch?v=, youtu.be/, /shorts/, /embed/ or /live/ links; else null. */
    fun videoId(url: String): String? {
        val host = LinkExtractor.hostOf(url)
        if (!LinkExtractor.isYouTube(host)) return null
        val afterHost = url.substringAfter("://", "").substringAfter('/', "").substringBefore('#')
        val path = afterHost.substringBefore('?')
        val query = afterHost.substringAfter('?', "")
        val candidate = if (host == "youtu.be") {
            path.substringBefore('/')
        } else {
            query.split('&').firstOrNull { it.startsWith("v=") }?.substringAfter("v=")
                ?: PATH_ID.find(path)?.groupValues?.get(1)
        }
        return candidate?.takeIf { ID.matches(it) }
    }

    fun thumbnail(videoId: String): String = "https://i.ytimg.com/vi/$videoId/hqdefault.jpg"

    fun isYouTubeUrl(url: String): Boolean = LinkExtractor.isYouTube(LinkExtractor.hostOf(url))
}
