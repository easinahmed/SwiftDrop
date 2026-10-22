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
import com.swiftdrop.android.data.AppDatabase
import com.swiftdrop.android.data.DownloadGroupEntity
import com.swiftdrop.android.data.GroupSummary
import com.swiftdrop.android.data.Settings
import com.swiftdrop.android.ui.MainActivity
import java.util.UUID
import kotlin.math.roundToInt
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

object Notifications {

    const val CHANNEL_PROGRESS = "downloads"
    const val CHANNEL_RESULTS = "download_results"
    /** Used instead of [CHANNEL_PROGRESS] when progress notifications are off in Settings. */
    const val CHANNEL_QUIET = "downloads_quiet"

    fun progressId(downloadId: Long): Int = (100_000 + downloadId * 2).toInt()
    fun resultId(downloadId: Long): Int = (100_000 + downloadId * 2 + 1).toInt()
    fun groupId(groupId: Long): Int = (50_000_000 + groupId).toInt()

    /** Several songs finish at once; one at a time keeps the newest count on screen. */
    private val groupLock = Mutex()

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
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_QUIET, "Background downloads", NotificationManager.IMPORTANCE_MIN).apply {
                description = "Shown when progress notifications are off; Android needs one while downloading"
                setShowBadge(false)
            }
        )
    }

    /** "Show progress notifications" in Settings. */
    fun progressEnabled(context: Context): Boolean = Settings.get(context).current.progressNotifications

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
        if (!progressEnabled(context)) return quietNotification(context, workId)
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

    /** The one silent notification Android requires while a download runs with progress turned off. */
    private fun quietNotification(context: Context, workId: UUID): Notification =
        NotificationCompat.Builder(context, CHANNEL_QUIET)
            .setSmallIcon(R.drawable.ic_stat_download)
            .setContentTitle("Downloading")
            .setOngoing(true)
            .setSilent(true)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setCategory(NotificationCompat.CATEGORY_PROGRESS)
            .setContentIntent(openAppIntent(context))
            .addAction(
                R.drawable.ic_close,
                "Cancel",
                WorkManager.getInstance(context).createCancelPendingIntent(workId),
            )
            .build()

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
        if (!progressEnabled(context)) return
        notify(context, progressId(downloadId), progressNotification(context, workId, title, percent, speed))
    }

    fun showCompleted(
        context: Context,
        downloadId: Long,
        title: String,
        uri: Uri,
        mimeType: String,
        fileCount: Int,
        location: String,
        note: String? = null,
    ) {
        val view = Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, mimeType)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        val openFile = PendingIntent.getActivity(
            context,
            resultId(downloadId),
            view,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val where = "Saved to $location"
        val text = listOfNotNull(if (fileCount > 1) "$fileCount files" else null, where, note).joinToString(" · ")
        val notification = NotificationCompat.Builder(context, CHANNEL_RESULTS)
            .setSmallIcon(R.drawable.ic_stat_download)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
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

    // -- Spotify albums and playlists ---------------------------------------------------------------

    /** "Found 50 songs in Road Trip", right after the link is read. */
    suspend fun showGroupFound(context: Context, group: DownloadGroupEntity, songCount: Int) {
        val headline = if (group.partial) {
            "Found the first $songCount songs in ${group.name}"
        } else {
            "Found $songCount ${if (songCount == 1) "song" else "songs"} in ${group.name}"
        }
        groupLock.withLock {
            val summary = GroupSummary(songCount, 0, 0, 0, 0, songCount)
            notify(context, groupId(group.id), groupNotification(context, group, summary, headline))
        }
    }

    /** The album's or playlist's progress: "12 of 50 done · 1 not found", then the result. */
    suspend fun updateGroup(context: Context, groupId: Long) {
        val dao = AppDatabase.get(context).downloads()
        groupLock.withLock {
            val group = dao.getGroup(groupId) ?: return
            val summary = GroupSummary.of(dao.songsInGroup(groupId))
            // With progress notifications off, an album or playlist only reports when it's done.
            if (summary.isActive && !progressEnabled(context)) return
            notify(context, groupId(groupId), groupNotification(context, group, summary, null))
        }
    }

    fun clearGroup(context: Context, groupId: Long) = cancel(context, groupId(groupId))

    private fun groupNotification(
        context: Context,
        group: DownloadGroupEntity,
        summary: GroupSummary,
        headline: String?,
    ): Notification {
        val settings = Settings.get(context).current
        val where = MediaSaver.folderFor(settings, "audio/mp4", group.name).displayPath
        val builder = NotificationCompat.Builder(context, CHANNEL_RESULTS)
            .setSmallIcon(R.drawable.ic_stat_download)
            .setContentIntent(openAppIntent(context))
            .setOnlyAlertOnce(true)
        if (summary.isActive) {
            val text = if (headline != null) {
                "Downloading ${DownloadQueue.maxParallel(context)} at a time to $where"
            } else {
                summary.line()
            }
            val cancelAll = PendingIntent.getBroadcast(
                context,
                groupId(group.id),
                NotificationActionReceiver.cancelGroupIntent(context, group.id),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
            builder.setContentTitle(headline ?: group.name)
                .setContentText(text)
                .setProgress(summary.total, summary.finished, false)
                .setCategory(NotificationCompat.CATEGORY_PROGRESS)
                .addAction(R.drawable.ic_close, "Cancel all", cancelAll)
        } else {
            val missing = listOfNotNull(
                summary.notFound.takeIf { it > 0 }?.let { "$it not found" },
                summary.failed.takeIf { it > 0 }?.let { "$it failed" },
                summary.cancelled.takeIf { it > 0 }?.let { "$it cancelled" },
            )
            builder.setContentTitle("${group.name}: ${summary.done} of ${summary.total} songs saved")
                .setContentText((missing + where).joinToString(" · "))
                .setAutoCancel(true)
                .setCategory(NotificationCompat.CATEGORY_STATUS)
        }
        return builder.build()
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
