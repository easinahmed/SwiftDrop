package com.swiftdrop.android.core

/** Turns video titles into file names that every Android storage backend accepts. */
object FileNames {

    const val MAX_BASE_LENGTH = 120
    const val FALLBACK_BASE = "SwiftDrop download"

    private val ILLEGAL = Regex("""[\\/:*?"<>|\u0000-\u001F\u007F]""")
    private val WHITESPACE = Regex("""\s+""")
    private val EXTENSION = Regex("""[^a-z0-9]""")

    /** Sanitised name without extension; never empty, never longer than [MAX_BASE_LENGTH] chars. */
    fun sanitizeBase(raw: String?): String {
        var name = (raw ?: "")
            .replace(ILLEGAL, " ")
            .replace(WHITESPACE, " ")
            .trim()
            .trim('.', ' ')
        if (name.length > MAX_BASE_LENGTH) {
            var cut = MAX_BASE_LENGTH
            // Never split a surrogate pair (emoji) in half.
            if (Character.isHighSurrogate(name[cut - 1])) cut--
            name = name.substring(0, cut).trimEnd('.', ' ')
        }
        return name.ifEmpty { FALLBACK_BASE }
    }

    /** Lower-case alphanumeric extension without the dot, or "" when unusable. */
    fun sanitizeExtension(raw: String?): String =
        (raw ?: "").trim().removePrefix(".").lowercase().replace(EXTENSION, "").take(10)

    /** "Title.ext" built from a title and an extension. */
    fun displayName(title: String?, extension: String?): String {
        val base = sanitizeBase(title)
        val ext = sanitizeExtension(extension)
        return if (ext.isEmpty()) base else "$base.$ext"
    }
}
