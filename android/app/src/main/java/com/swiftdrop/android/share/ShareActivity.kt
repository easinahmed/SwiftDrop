package com.swiftdrop.android.share

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import com.swiftdrop.android.SwiftDropApp
import com.swiftdrop.android.core.LinkExtractor
import com.swiftdrop.android.core.SavePaths
import com.swiftdrop.android.data.Settings
import com.swiftdrop.android.download.Downloads
import com.swiftdrop.android.spotify.SpotifyLinks
import kotlinx.coroutines.launch

/**
 * Invisible share target: "Share → SwiftDrop" or "Open with SwiftDrop".
 * Queues the download at the default quality and gets out of the way immediately.
 * A Spotify song, album or playlist is read in the background and saved as audio.
 */
class ShareActivity : ComponentActivity() {

    private val permissionRequest =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { finish() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Re-created while a permission dialog is up: the download is already queued.
        if (savedInstanceState != null) return

        val url = linkFrom(intent)
        if (url == null) {
            Toast.makeText(this, "No link to download", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        val refusal = SpotifyLinks.refusal(url)
        if (refusal != null) {
            Toast.makeText(this, refusal, Toast.LENGTH_LONG).show()
            finish()
            return
        }

        val app = applicationContext
        SwiftDropApp.scope.launch { Downloads.enqueue(app, url) }
        val started = if (SpotifyLinks.isSpotify(url)) "Getting Spotify songs…" else "Downloading with SwiftDrop…"
        Toast.makeText(this, started, Toast.LENGTH_SHORT).show()

        val permission = permissionToAsk()
        if (permission != null) {
            // The dialog needs this activity alive; finish() runs in the result callback.
            permissionRequest.launch(permission)
        } else {
            finish()
        }
    }

    private fun linkFrom(intent: Intent?): String? = when (intent?.action) {
        Intent.ACTION_SEND ->
            LinkExtractor.firstUrl(intent.getCharSequenceExtra(Intent.EXTRA_TEXT))
                ?: LinkExtractor.firstUrl(intent.getStringExtra(Intent.EXTRA_SUBJECT))
        Intent.ACTION_VIEW -> LinkExtractor.firstUrl(intent.dataString)
        else -> null
    }

    /** Notifications (asked once, Android 13+) or legacy storage (Android 8–9, needed to save). */
    private fun permissionToAsk(): String? {
        val settings = Settings.get(this)
        if (Build.VERSION.SDK_INT >= 33 && !settings.notificationPermissionAsked &&
            !granted(Manifest.permission.POST_NOTIFICATIONS)
        ) {
            settings.notificationPermissionAsked = true
            return Manifest.permission.POST_NOTIFICATIONS
        }
        if (SavePaths.needsLegacyWritePermission(Build.VERSION.SDK_INT) &&
            !granted(Manifest.permission.WRITE_EXTERNAL_STORAGE)
        ) {
            return Manifest.permission.WRITE_EXTERNAL_STORAGE
        }
        return null
    }

    private fun granted(permission: String) =
        ContextCompat.checkSelfPermission(this, permission) == PackageManager.PERMISSION_GRANTED
}
