package com.swiftdrop.android.download

import android.content.Context
import androidx.work.WorkInfo
import androidx.work.WorkManager
import com.swiftdrop.android.data.AppDatabase
import com.swiftdrop.android.data.DownloadStatus
import com.swiftdrop.android.data.Settings
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * Runs at most "Max simultaneous downloads" (Settings, 1–5) at a time. Every link and every Spotify
 * song waits as QUEUED in the database; [pump] hands the next ones to WorkManager (RUNNING) as
 * slots free up. Called when something is queued, when a download finishes, on cancel and retry,
 * when the setting changes, and at start-up.
 */
object DownloadQueue {

    private val lock = Mutex()

    fun maxParallel(context: Context): Int = Settings.get(context).current.maxParallel

    suspend fun pump(context: Context) {
        val app = context.applicationContext
        val dao = AppDatabase.get(app).downloads()
        val workManager = WorkManager.getInstance(app)
        lock.withLock {
            var busy = 0
            for (item in dao.runningDownloads()) {
                val work = workManager.getWorkInfosForUniqueWorkFlow(Downloads.workName(item.id)).first()
                when {
                    work.any { !it.state.isFinished } -> busy++
                    // Its work is gone (cancelled, or cleared with the app's data): free the slot.
                    work.any { it.state == WorkInfo.State.CANCELLED } -> dao.markCancelledIfActive(item.id)
                    else -> dao.setStatus(item.id, DownloadStatus.QUEUED)
                }
            }
            val free = maxParallel(app) - busy
            if (free <= 0) return
            for (item in dao.nextQueued(free)) {
                dao.setStatus(item.id, DownloadStatus.RUNNING)
                Downloads.schedule(app, item.id)
            }
        }
    }

    /** Cancels an album's or playlist's remaining songs; finished ones stay. */
    suspend fun cancelGroup(context: Context, groupId: Long) {
        val app = context.applicationContext
        val dao = AppDatabase.get(app).downloads()
        lock.withLock {
            val active = dao.songsInGroup(groupId).filter { it.status.isActive }
            dao.cancelGroupSongs(groupId)
            val workManager = WorkManager.getInstance(app)
            for (song in active) {
                workManager.cancelUniqueWork(Downloads.workName(song.id))
                Notifications.clearProgress(app, song.id)
            }
        }
        Notifications.updateGroup(app, groupId)
        pump(app)
    }
}
