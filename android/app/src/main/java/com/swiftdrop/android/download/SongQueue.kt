package com.swiftdrop.android.download

import android.content.Context
import androidx.work.WorkInfo
import androidx.work.WorkManager
import com.swiftdrop.android.data.AppDatabase
import com.swiftdrop.android.data.DownloadStatus
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * Spotify songs download at most [MAX_PARALLEL] at a time: an album or playlist queues every
 * song (QUEUED in the database), and [pump] hands the next ones to WorkManager (RUNNING) as
 * slots free up. Called after a link is read, when a song finishes, and on cancel or retry.
 */
object SongQueue {

    const val MAX_PARALLEL = 3

    private val lock = Mutex()

    suspend fun pump(context: Context) {
        val app = context.applicationContext
        val dao = AppDatabase.get(app).downloads()
        val workManager = WorkManager.getInstance(app)
        lock.withLock {
            var busy = 0
            for (song in dao.runningSongs()) {
                val work = workManager.getWorkInfosForUniqueWorkFlow(Downloads.workName(song.id)).first()
                when {
                    work.any { !it.state.isFinished } -> busy++
                    // Its work is gone (cancelled, or cleared with the app's data): free the slot.
                    work.any { it.state == WorkInfo.State.CANCELLED } -> dao.markCancelledIfActive(song.id)
                    else -> dao.setStatus(song.id, DownloadStatus.QUEUED)
                }
            }
            val free = MAX_PARALLEL - busy
            if (free <= 0) return
            for (song in dao.nextQueuedSongs(free)) {
                dao.setStatus(song.id, DownloadStatus.RUNNING)
                Downloads.schedule(app, song.id)
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
