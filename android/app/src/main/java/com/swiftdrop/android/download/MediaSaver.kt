package com.swiftdrop.android.download

import android.Manifest
import android.content.ContentValues
import android.content.Context
import android.content.pm.PackageManager
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import androidx.annotation.RequiresApi
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import com.swiftdrop.android.core.SavePaths
import java.io.File
import java.io.IOException

/** Copies a finished file from app storage into the public Download/SwiftDrop folder. */
object MediaSaver {

    data class Saved(val uri: Uri, val displayName: String, val mimeType: String, val sizeBytes: Long)

    fun fileProviderAuthority(context: Context) = "${context.packageName}.files"

    /** Saves into Download/SwiftDrop, or Download/SwiftDrop/[folder] (an album or playlist). */
    fun save(context: Context, source: File, displayName: String, mimeType: String, folder: String? = null): Saved =
        if (SavePaths.usesMediaStore(Build.VERSION.SDK_INT)) {
            saveToMediaStore(context, source, displayName, mimeType, folder)
        } else {
            saveToLegacyFolder(context, source, displayName, mimeType, folder)
        }

    @RequiresApi(29)
    private fun saveToMediaStore(
        context: Context,
        source: File,
        displayName: String,
        mimeType: String,
        folder: String?,
    ): Saved {
        val resolver = context.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, displayName)
            put(MediaStore.Downloads.MIME_TYPE, mimeType)
            put(MediaStore.Downloads.RELATIVE_PATH, SavePaths.relativePath(folder))
            put(MediaStore.Downloads.IS_PENDING, 1)
        }
        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
            ?: throw IOException("Couldn't create the file in ${SavePaths.relativePath(folder)}.")
        try {
            val out = resolver.openOutputStream(uri) ?: throw IOException("Couldn't write to Download/SwiftDrop.")
            out.use { output -> source.inputStream().use { it.copyTo(output, BUFFER) } }
            resolver.update(uri, ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }, null, null)
        } catch (t: Throwable) {
            runCatching { resolver.delete(uri, null, null) }
            throw t
        }
        // MediaStore renames on collisions ("name (1).mp4"); report the name it actually used.
        val finalName = resolver.query(uri, arrayOf(MediaStore.Downloads.DISPLAY_NAME), null, null, null)
            ?.use { c -> if (c.moveToFirst()) c.getString(0) else null }
            ?: displayName
        return Saved(uri, finalName, mimeType, source.length())
    }

    @Suppress("DEPRECATION")
    private fun saveToLegacyFolder(
        context: Context,
        source: File,
        displayName: String,
        mimeType: String,
        folder: String?,
    ): Saved {
        val granted = ContextCompat.checkSelfPermission(context, Manifest.permission.WRITE_EXTERNAL_STORAGE) ==
            PackageManager.PERMISSION_GRANTED
        if (!granted) throw IOException("Storage permission is needed to save into Download/SwiftDrop. Open SwiftDrop and allow it.")
        val dir = SavePaths.legacyDirectory(Environment.getExternalStorageDirectory(), folder)
        if (!dir.isDirectory && !dir.mkdirs()) throw IOException("Couldn't create ${dir.path}.")
        val name = SavePaths.uniqueName(displayName) { File(dir, it).exists() }
        val target = File(dir, name)
        try {
            source.inputStream().use { input -> target.outputStream().use { input.copyTo(it, BUFFER) } }
        } catch (t: Throwable) {
            target.delete()
            throw t
        }
        MediaScannerConnection.scanFile(context, arrayOf(target.absolutePath), arrayOf(mimeType), null)
        val uri = FileProvider.getUriForFile(context, fileProviderAuthority(context), target)
        return Saved(uri, name, mimeType, target.length())
    }

    private const val BUFFER = 256 * 1024
}
