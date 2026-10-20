package com.swiftdrop.android.download

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.swiftdrop.android.SwiftDropApp
import kotlinx.coroutines.launch

/** Handles the "Retry" action on a failed-download notification. */
class NotificationActionReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != ACTION_RETRY) return
        val id = intent.getLongExtra(EXTRA_DOWNLOAD_ID, -1L)
        if (id < 0) return
        val pending = goAsync()
        SwiftDropApp.scope.launch {
            try {
                Downloads.retry(context, id)
            } finally {
                pending.finish()
            }
        }
    }

    companion object {
        const val ACTION_RETRY = "com.swiftdrop.android.action.RETRY"
        private const val EXTRA_DOWNLOAD_ID = "download_id"

        fun retryIntent(context: Context, downloadId: Long): Intent =
            Intent(context, NotificationActionReceiver::class.java)
                .setAction(ACTION_RETRY)
                .putExtra(EXTRA_DOWNLOAD_ID, downloadId)
    }
}
