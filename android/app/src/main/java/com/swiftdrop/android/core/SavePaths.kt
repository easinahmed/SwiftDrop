package com.swiftdrop.android.core

import java.io.File

/**
 * Where finished downloads go: Download/SwiftDrop.
 *
 * API 29+ inserts into MediaStore.Downloads with [RELATIVE_PATH] (no storage permission).
 * API 26–28 writes the public folder directly (WRITE_EXTERNAL_STORAGE, maxSdkVersion 28).
 */
object SavePaths {

    const val DOWNLOADS_DIR = "Download" // == Environment.DIRECTORY_DOWNLOADS
    const val FOLDER = "SwiftDrop"
    const val RELATIVE_PATH = "$DOWNLOADS_DIR/$FOLDER"
    const val MEDIASTORE_MIN_SDK = 29

    fun usesMediaStore(sdkInt: Int): Boolean = sdkInt >= MEDIASTORE_MIN_SDK

    fun needsLegacyWritePermission(sdkInt: Int): Boolean = !usesMediaStore(sdkInt)

    /** Public folder used on API 26–28, under the external storage root. */
    fun legacyDirectory(externalStorageRoot: File): File =
        File(File(externalStorageRoot, DOWNLOADS_DIR), FOLDER)

    /** "name.ext", then "name (1).ext", "name (2).ext", … until [exists] says it is free. */
    fun uniqueName(fileName: String, exists: (String) -> Boolean): String {
        if (!exists(fileName)) return fileName
        val dot = fileName.lastIndexOf('.')
        val base = if (dot > 0) fileName.substring(0, dot) else fileName
        val ext = if (dot > 0) fileName.substring(dot) else ""
        var n = 1
        while (true) {
            val candidate = "$base ($n)$ext"
            if (!exists(candidate)) return candidate
            n++
        }
    }

    private val MIME_TYPES = mapOf(
        "mp4" to "video/mp4",
        "m4v" to "video/mp4",
        "webm" to "video/webm",
        "mkv" to "video/x-matroska",
        "mov" to "video/quicktime",
        "3gp" to "video/3gpp",
        "ts" to "video/mp2t",
        "flv" to "video/x-flv",
        "avi" to "video/x-msvideo",
        "m4a" to "audio/mp4",
        "aac" to "audio/aac",
        "mp3" to "audio/mpeg",
        "opus" to "audio/ogg",
        "ogg" to "audio/ogg",
        "oga" to "audio/ogg",
        "wav" to "audio/x-wav",
        "flac" to "audio/flac",
        "jpg" to "image/jpeg",
        "jpeg" to "image/jpeg",
        "png" to "image/png",
        "gif" to "image/gif",
        "webp" to "image/webp",
        "pdf" to "application/pdf",
        "zip" to "application/zip",
        "apk" to "application/vnd.android.package-archive",
    )

    fun mimeType(fileName: String): String =
        MIME_TYPES[fileName.substringAfterLast('.', "").lowercase()] ?: "application/octet-stream"
}
