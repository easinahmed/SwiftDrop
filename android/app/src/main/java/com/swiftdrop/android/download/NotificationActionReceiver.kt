package com.swiftdrop.android.download

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.swiftdrop.android.SwiftDropApp
import kotlinx.coroutines.launch

/** "Retry" on a failed download, and "Cancel all" on a Spotify album or playlist. */
class NotificationActionReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val action: suspend () -> Unit = when (intent.action) {
            ACTION_RETRY -> {
                val id = intent.getLongExtra(EXTRA_DOWNLOAD_ID, -1L)
                if (id < 0) return
                suspend { Downloads.retry(context, id) }
            }
            ACTION_CANCEL_GROUP -> {
                val groupId = intent.getLongExtra(EXTRA_GROUP_ID, -1L)
                if (groupId < 0) return
                suspend { Downloads.cancelGroup(context, groupId) }
            }
            else -> return
        }
        val pending = goAsync()
        SwiftDropApp.scope.launch {
            try {
                action()
            } finally {
                pending.finish()
            }
        }
    }

    companion object {
        const val ACTION_RETRY = "com.swiftdrop.android.action.RETRY"
        const val ACTION_CANCEL_GROUP = "com.swiftdrop.android.action.CANCEL_GROUP"
        private const val EXTRA_DOWNLOAD_ID = "download_id"
        private const val EXTRA_GROUP_ID = "group_id"

        fun cancelGroupIntent(context: Context, groupId: Long): Intent =
            Intent(context, NotificationActionReceiver::class.java)
                .setAction(ACTION_CANCEL_GROUP)
                .putExtra(EXTRA_GROUP_ID, groupId)

        fun retryIntent(context: Context, downloadId: Long): Intent =
            Intent(context, NotificationActionReceiver::class.java)
                .setAction(ACTION_RETRY)
                .putExtra(EXTRA_DOWNLOAD_ID, downloadId)
    }
}
