package com.swiftdrop.android.ui

import android.content.ActivityNotFoundException
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import com.swiftdrop.android.data.DownloadEntity
import com.swiftdrop.android.share.ShareActivity

object FileActions {

    fun open(context: Context, item: DownloadEntity) {
        val uri = item.fileUri?.let(Uri::parse) ?: return
        val intent = Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, item.mimeType ?: "*/*")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        try {
            context.startActivity(intent)
        } catch (_: ActivityNotFoundException) {
            Toast.makeText(context, "No app here can open this file", Toast.LENGTH_SHORT).show()
        } catch (_: SecurityException) {
            Toast.makeText(context, "The file was moved or deleted", Toast.LENGTH_SHORT).show()
        }
    }

    fun share(context: Context, item: DownloadEntity) {
        val uri = item.fileUri?.let(Uri::parse) ?: return
        val send = Intent(Intent.ACTION_SEND)
            .setType(item.mimeType ?: "*/*")
            .putExtra(Intent.EXTRA_STREAM, uri)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        context.startActivity(Intent.createChooser(send, item.title ?: item.fileName ?: "Share"))
    }

    /** Opens a web page in the user's browser, never in SwiftDrop's own "Open with" handler. */
    fun openWebsite(context: Context, url: String) {
        val uri = Uri.parse(url)
        val viaBrowser = Intent(Intent.ACTION_VIEW, uri).apply {
            selector = Intent.makeMainSelectorActivity(Intent.ACTION_MAIN, Intent.CATEGORY_APP_BROWSER)
        }
        try {
            context.startActivity(viaBrowser)
        } catch (_: ActivityNotFoundException) {
            val chooser = Intent.createChooser(Intent(Intent.ACTION_VIEW, uri), null)
                .putExtra(Intent.EXTRA_EXCLUDE_COMPONENTS, arrayOf(ComponentName(context, ShareActivity::class.java)))
            try {
                context.startActivity(chooser)
            } catch (_: ActivityNotFoundException) {
                Toast.makeText(context, url, Toast.LENGTH_LONG).show()
            }
        }
    }
}
