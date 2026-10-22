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
import android.util.Log
import android.webkit.MimeTypeMap
import androidx.annotation.RequiresApi
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.documentfile.provider.DocumentFile
import com.swiftdrop.android.core.SaveFolder
import com.swiftdrop.android.core.SaveFolders
import com.swiftdrop.android.core.SavePaths
import com.swiftdrop.android.data.AppSettings
import com.swiftdrop.android.data.Settings
import java.io.File
import java.io.IOException

/**
 * Copies a finished file from app storage to where the user wants it: Download/SwiftDrop through
 * MediaStore (the default), or a folder picked in Settings through the Storage Access Framework.
 */
object MediaSaver {

    private const val TAG = "SwiftDropSaver"

    data class Saved(
        val uri: Uri,
        val displayName: String,
        val mimeType: String,
        val sizeBytes: Long,
        /** "Download/SwiftDrop/Music", shown in the list and the notification. */
        val location: String,
        /** The chosen folder couldn't be written, so the file went to Download/SwiftDrop instead. */
        val fellBackToDefault: Boolean = false,
    )

    fun fileProviderAuthority(context: Context) = "${context.packageName}.files"

    /** Where a file of [mimeType] goes under the current settings; [collection] is an album or playlist. */
    fun folderFor(settings: AppSettings, mimeType: String, collection: String?): SaveFolder =
        SaveFolders.plan(
            mimeType = mimeType,
            treeUri = settings.downloadTree,
            treeLabel = settings.downloadTreeLabel,
            separateFolders = settings.separateFolders,
            groupFolders = settings.groupFolders,
            collection = collection,
        )

    /** Saves [source] as [displayName] under the current settings. */
    fun save(context: Context, source: File, displayName: String, mimeType: String, collection: String? = null): Saved =
        save(context, source, displayName, mimeType, folderFor(Settings.get(context).current, mimeType, collection))

    fun save(context: Context, source: File, displayName: String, mimeType: String, folder: SaveFolder): Saved {
        if (folder.treeUri != null) {
            try {
                return saveToTree(context, source, displayName, mimeType, folder)
            } catch (e: FolderUnavailableException) {
                Log.w(TAG, "Chosen folder unavailable; saving to ${SavePaths.RELATIVE_PATH}")
                val fallback = folder.copy(treeUri = null, baseLabel = SavePaths.RELATIVE_PATH)
                return saveDefault(context, source, displayName, mimeType, fallback).copy(fellBackToDefault = true)
            }
        }
        return saveDefault(context, source, displayName, mimeType, folder)
    }

    private fun saveDefault(context: Context, source: File, displayName: String, mimeType: String, folder: SaveFolder): Saved =
        if (SavePaths.usesMediaStore(Build.VERSION.SDK_INT)) {
            saveToMediaStore(context, source, displayName, mimeType, folder)
        } else {
            saveToLegacyFolder(context, source, displayName, mimeType, folder)
        }

    class FolderUnavailableException : IOException("The chosen download folder isn't available.")

    /** True while SwiftDrop may still write to the picked folder [treeUri]. */
    fun canWriteTree(context: Context, treeUri: Uri): Boolean =
        context.contentResolver.persistedUriPermissions.any { it.uri == treeUri && it.isWritePermission }

    private fun saveToTree(context: Context, source: File, displayName: String, mimeType: String, folder: SaveFolder): Saved {
        val treeUri = Uri.parse(folder.treeUri)
        if (!canWriteTree(context, treeUri)) throw FolderUnavailableException()
        val root = DocumentFile.fromTreeUri(context, treeUri)
        if (root == null || !root.exists() || !root.isDirectory) throw FolderUnavailableException()
        var dir: DocumentFile = root
        for (name in folder.subfolders) {
            dir = dir.findFile(name)?.takeIf { it.isDirectory }
                ?: dir.createDirectory(name)
                ?: throw IOException("Couldn't create the folder \"$name\" in ${folder.baseLabel}.")
        }
        // The provider appends an extension when the type it derives from the name disagrees with
        // the one passed in ("song.opus.ogg"); passing its own idea of the type avoids that.
        val providerType = MimeTypeMap.getSingleton()
            .getMimeTypeFromExtension(displayName.substringAfterLast('.', "").lowercase())
            ?: "application/octet-stream"
        val document = dir.createFile(providerType, displayName)
            ?: throw IOException("Couldn't create the file in ${folder.displayPath}.")
        try {
            val out = context.contentResolver.openOutputStream(document.uri, "w")
                ?: throw IOException("Couldn't write to ${folder.displayPath}.")
            out.use { output -> source.inputStream().use { it.copyTo(output, BUFFER) } }
        } catch (t: Throwable) {
            runCatching { document.delete() }
            throw t
        }
        // The provider renames on collisions ("name (1).mp4"); report the name it actually used.
        return Saved(document.uri, document.name ?: displayName, mimeType, source.length(), folder.displayPath)
    }

    @RequiresApi(29)
    private fun saveToMediaStore(
        context: Context,
        source: File,
        displayName: String,
        mimeType: String,
        folder: SaveFolder,
    ): Saved {
        val resolver = context.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, displayName)
            put(MediaStore.Downloads.MIME_TYPE, mimeType)
            put(MediaStore.Downloads.RELATIVE_PATH, folder.relativePath)
            put(MediaStore.Downloads.IS_PENDING, 1)
        }
        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
            ?: throw IOException("Couldn't create the file in ${folder.relativePath}.")
        try {
            val out = resolver.openOutputStream(uri) ?: throw IOException("Couldn't write to ${folder.relativePath}.")
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
        return Saved(uri, finalName, mimeType, source.length(), folder.displayPath)
    }

    @Suppress("DEPRECATION")
    private fun saveToLegacyFolder(
        context: Context,
        source: File,
        displayName: String,
        mimeType: String,
        folder: SaveFolder,
    ): Saved {
        val granted = ContextCompat.checkSelfPermission(context, Manifest.permission.WRITE_EXTERNAL_STORAGE) ==
            PackageManager.PERMISSION_GRANTED
        if (!granted) throw IOException("Storage permission is needed to save into Download/SwiftDrop. Open SwiftDrop and allow it.")
        val dir = File(Environment.getExternalStorageDirectory(), folder.relativePath)
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
        return Saved(uri, name, mimeType, target.length(), folder.displayPath)
    }

    private const val BUFFER = 256 * 1024
}
