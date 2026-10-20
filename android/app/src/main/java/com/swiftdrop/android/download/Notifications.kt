package com.swiftdrop.android.download

import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.ForegroundInfo
import androidx.work.WorkManager
import com.swiftdrop.android.R
import com.swiftdrop.android.core.SavePaths
import com.swiftdrop.android.ui.MainActivity
import java.util.UUID
import kotlin.math.roundToInt

object Notifications {

    const val CHANNEL_PROGRESS = "downloads"
    const val CHANNEL_RESULTS = "download_results"

    fun progressId(downloadId: Long): Int = (100_000 + downloadId * 2).toInt()
    fun resultId(downloadId: Long): Int = (100_000 + downloadId * 2 + 1).toInt()

    fun createChannels(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_PROGRESS, "Downloads in progress", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Progress of running downloads"
                setShowBadge(false)
            }
        )
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_RESULTS, "Finished downloads", NotificationManager.IMPORTANCE_DEFAULT).apply {
                description = "Saved files and download errors"
            }
        )
    }

    fun canPost(context: Context): Boolean {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) return false
        return NotificationManagerCompat.from(context).areNotificationsEnabled()
    }

    private fun openAppIntent(context: Context): PendingIntent = PendingIntent.getActivity(
        context,
        0,
        Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
    )

    fun progressNotification(
        context: Context,
        workId: UUID,
        title: String,
        percent: Float?,
        speed: String?,
    ): Notification {
        val text = when {
            percent == null -> "Preparing…"
            speed != null -> "${percent.roundToInt()}% · $speed"
            else -> "${percent.roundToInt()}%"
        }
        return NotificationCompat.Builder(context, CHANNEL_PROGRESS)
            .setSmallIcon(R.drawable.ic_stat_download)
            .setContentTitle(title)
            .setContentText(text)
            .setProgress(100, percent?.roundToInt() ?: 0, percent == null)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setSilent(true)
            .setCategory(NotificationCompat.CATEGORY_PROGRESS)
            .setContentIntent(openAppIntent(context))
            .addAction(
                R.drawable.ic_close,
                "Cancel",
                WorkManager.getInstance(context).createCancelPendingIntent(workId),
            )
            .build()
    }

    fun foregroundInfo(
        context: Context,
        downloadId: Long,
        workId: UUID,
        title: String,
        percent: Float?,
        speed: String?,
    ): ForegroundInfo {
        val notification = progressNotification(context, workId, title, percent, speed)
        return if (Build.VERSION.SDK_INT >= 29) {
            ForegroundInfo(progressId(downloadId), notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            ForegroundInfo(progressId(downloadId), notification)
        }
    }

    fun showProgress(context: Context, downloadId: Long, workId: UUID, title: String, percent: Float?, speed: String?) {
        notify(context, progressId(downloadId), progressNotification(context, workId, title, percent, speed))
    }

    fun showCompleted(context: Context, downloadId: Long, title: String, uri: Uri, mimeType: String, fileCount: Int) {
        val view = Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, mimeType)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        val openFile = PendingIntent.getActivity(
            context,
            resultId(downloadId),
            view,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val where = "Saved to ${SavePaths.RELATIVE_PATH}"
        val text = if (fileCount > 1) "$fileCount files · $where" else where
        val notification = NotificationCompat.Builder(context, CHANNEL_RESULTS)
            .setSmallIcon(R.drawable.ic_stat_download)
            .setContentTitle(title)
            .setContentText(text)
            .setContentIntent(openFile)
            .setAutoCancel(true)
            .setCategory(NotificationCompat.CATEGORY_STATUS)
            .build()
        cancel(context, progressId(downloadId))
        notify(context, resultId(downloadId), notification)
    }

    fun showFailed(context: Context, downloadId: Long, title: String, error: String) {
        val retry = PendingIntent.getBroadcast(
            context,
            resultId(downloadId),
            NotificationActionReceiver.retryIntent(context, downloadId),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(context, CHANNEL_RESULTS)
            .setSmallIcon(R.drawable.ic_stat_download)
            .setContentTitle("Couldn't download: $title")
            .setContentText(error)
            .setStyle(NotificationCompat.BigTextStyle().bigText(error))
            .setContentIntent(openAppIntent(context))
            .setAutoCancel(true)
            .addAction(R.drawable.ic_refresh, "Retry", retry)
            .setCategory(NotificationCompat.CATEGORY_ERROR)
            .build()
        cancel(context, progressId(downloadId))
        notify(context, resultId(downloadId), notification)
    }

    fun clear(context: Context, downloadId: Long) {
        cancel(context, progressId(downloadId))
        cancel(context, resultId(downloadId))
    }

    fun clearProgress(context: Context, downloadId: Long) = cancel(context, progressId(downloadId))

    fun clearResult(context: Context, downloadId: Long) = cancel(context, resultId(downloadId))

    private fun cancel(context: Context, id: Int) = NotificationManagerCompat.from(context).cancel(id)

    @SuppressLint("MissingPermission") // checked by canPost()
    private fun notify(context: Context, id: Int, notification: Notification) {
        if (!canPost(context)) return
        try {
            NotificationManagerCompat.from(context).notify(id, notification)
        } catch (_: SecurityException) {
            // Permission revoked between the check and the call; nothing to show.
        }
    }
}
