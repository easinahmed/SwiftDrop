package com.swiftdrop.android.youtube

import android.content.Context
import android.util.Log
import android.webkit.CookieManager
import android.webkit.WebStorage
import java.io.File
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * The optional YouTube sign-in: the WebView's youtube.com and google.com cookies, saved as a
 * private cookies.txt in no-backup storage and passed to yt-dlp for YouTube links only.
 * Cookie values are never logged.
 */
object YouTubeAccount {

    private const val TAG = "SwiftDropYouTube"
    private const val FILE_NAME = "youtube-cookies.txt"

    const val LOGIN_URL = "https://accounts.google.com/ServiceLogin?continue=https://www.youtube.com"

    /** URL → the site its cookies are scoped to. */
    private val SOURCES = listOf(
        "https://www.youtube.com" to "youtube.com",
        "https://m.youtube.com" to "youtube.com",
        "https://music.youtube.com" to "youtube.com",
        "https://accounts.google.com" to "google.com",
        "https://www.google.com" to "google.com",
    )

    private val _signedIn = MutableStateFlow<Boolean?>(null)
    /** null until first checked. */
    val signedIn: StateFlow<Boolean?> = _signedIn.asStateFlow()

    fun cookieFile(context: Context): File = File(context.applicationContext.noBackupFilesDir, FILE_NAME)

    /** The cookies file when signed in, else null. */
    fun cookieFileIfSignedIn(context: Context): File? = cookieFile(context).takeIf { it.isFile && it.length() > 0 }

    fun refresh(context: Context) {
        _signedIn.value = cookieFileIfSignedIn(context) != null
    }

    /**
     * Writes the WebView's current Google/YouTube cookies to the cookies file. Returns false (and
     * writes nothing) when they don't contain a signed-in session yet. Main thread (CookieManager).
     */
    fun exportFromWebView(context: Context): Boolean {
        val manager = CookieManager.getInstance()
        manager.flush()
        val now = System.currentTimeMillis() / 1000
        val entries = SOURCES.flatMap { (url, site) ->
            val host = url.substringAfter("://")
            CookiesTxt.entries(host, site, manager.getCookie(url), now)
        }
        val text = CookiesTxt.write(entries)
        if (!CookiesTxt.hasLogin(text, "youtube.com")) return false
        val file = cookieFile(context)
        val temp = File(file.parentFile, "$FILE_NAME.tmp")
        try {
            temp.delete()
            temp.createNewFile()
            makePrivate(temp)
            temp.writeText(text)
            if (!temp.renameTo(file)) {
                file.delete()
                if (!temp.renameTo(file)) throw java.io.IOException("rename failed")
            }
            makePrivate(file)
        } catch (e: Exception) {
            Log.w(TAG, "Couldn't save the YouTube sign-in (${e.javaClass.simpleName})")
            temp.delete()
            return false
        }
        Log.i(TAG, "YouTube sign-in saved (${entries.size} cookies)")
        _signedIn.value = true
        return true
    }

    /** Forgets the account: deletes the file and every WebView cookie and site storage. */
    fun signOut(context: Context, done: () -> Unit = {}) {
        cookieFile(context).delete()
        _signedIn.value = false
        WebStorage.getInstance().deleteAllData()
        CookieManager.getInstance().removeAllCookies {
            CookieManager.getInstance().flush()
            done()
        }
    }

    private fun makePrivate(file: File) {
        file.setReadable(false, false)
        file.setWritable(false, false)
        file.setExecutable(false, false)
        file.setReadable(true, true)
        file.setWritable(true, true)
    }
}
