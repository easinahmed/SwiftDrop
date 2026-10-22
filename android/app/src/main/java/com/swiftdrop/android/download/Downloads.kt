package com.swiftdrop.android.download

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.ListenableWorker
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequest
import androidx.work.WorkManager
import androidx.work.await
import androidx.work.workDataOf
import com.swiftdrop.android.core.Quality
import com.swiftdrop.android.data.AppDatabase
import com.swiftdrop.android.data.DownloadEntity
import com.swiftdrop.android.data.Settings
import com.swiftdrop.android.spotify.SpotifyLinks
import kotlin.reflect.KClass

/** Queue operations shared by the share sheet, the app UI and notification actions. */
object Downloads {

    const val TAG = "swiftdrop-download"

    fun workName(id: Long) = "download-$id"

    /**
     * Records a new download and queues it; [DownloadQueue] starts it when a slot is free. Returns
     * the history row id. A Spotify link is first read (a quick job that lists its songs); each
     * song then waits for its turn like any other download.
     */
    suspend fun enqueue(context: Context, url: String, quality: Quality = Settings.get(context).current.quality): Long {
        val app = context.applicationContext
        val dao = AppDatabase.get(app).downloads()
        if (SpotifyLinks.isSpotify(url)) {
            val id = dao.insert(
                DownloadEntity(
                    url = url,
                    quality = Quality.AUDIO.name,
                    site = SPOTIFY,
                    kind = DownloadEntity.KIND_SPOTIFY_LINK,
                )
            )
            schedule(app, id, SpotifyResolveWorker::class)
            return id
        }
        val id = dao.insert(DownloadEntity(url = url, quality = quality.name))
        DownloadQueue.pump(app)
        return id
    }

    suspend fun retry(context: Context, id: Long) {
        val app = context.applicationContext
        val dao = AppDatabase.get(app).downloads()
        val item = dao.get(id) ?: return
        if (item.status.isActive) return
        Notifications.clear(app, id)
        dao.resetForRetry(id, item.quality)
        when {
            item.isSpotifyLink -> schedule(app, id, SpotifyResolveWorker::class)
            else -> {
                item.groupId?.let { Notifications.updateGroup(app, it) }
                DownloadQueue.pump(app)
            }
        }
    }

    suspend fun cancel(context: Context, id: Long) {
        val app = context.applicationContext
        val dao = AppDatabase.get(app).downloads()
        // Marked first, so the slot it frees isn't handed straight back to it.
        dao.markCancelledIfActive(id)
        WorkManager.getInstance(app).cancelUniqueWork(workName(id))
        Notifications.clearProgress(app, id)
        val item = dao.get(id)
        item?.groupId?.let { Notifications.updateGroup(app, it) }
        if (item?.isSpotifyLink != true) DownloadQueue.pump(app)
    }

    /** Removes the entry from the history. The saved file stays where it was saved. */
    suspend fun remove(context: Context, id: Long) {
        val app = context.applicationContext
        val dao = AppDatabase.get(app).downloads()
        val item = dao.get(id)
        if (item?.status?.isActive == true) cancel(app, id)
        dao.delete(id)
        Notifications.clear(app, id)
        val groupId = item?.groupId ?: return
        if (dao.songsInGroup(groupId).isEmpty()) {
            dao.deleteGroup(groupId)
            Notifications.clearGroup(app, groupId)
        }
    }

    /** Cancels the songs of an album or playlist that haven't finished. */
    suspend fun cancelGroup(context: Context, groupId: Long) = DownloadQueue.cancelGroup(context, groupId)

    /** Removes an album or playlist and its songs from the history. The files stay. */
    suspend fun removeGroup(context: Context, groupId: Long) {
        val app = context.applicationContext
        val dao = AppDatabase.get(app).downloads()
        DownloadQueue.cancelGroup(app, groupId)
        dao.songsInGroup(groupId).forEach { Notifications.clear(app, it.id) }
        dao.deleteGroupSongs(groupId)
        dao.deleteGroup(groupId)
        Notifications.clearGroup(app, groupId)
    }

    internal suspend fun schedule(
        context: Context,
        id: Long,
        worker: KClass<out ListenableWorker> = DownloadWorker::class,
    ) {
        val wifiOnly = Settings.get(context).current.wifiOnly
        val request = OneTimeWorkRequest.Builder(worker.java)
            .setInputData(workDataOf(DownloadWorker.KEY_DOWNLOAD_ID to id))
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(if (wifiOnly) NetworkType.UNMETERED else NetworkType.CONNECTED)
                    .build()
            )
            .addTag(TAG)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(workName(id), ExistingWorkPolicy.REPLACE, request).await()
    }

    /** Clears the list of finished, failed and cancelled downloads. Files stay where they were saved. */
    suspend fun clearHistory(context: Context) {
        val app = context.applicationContext
        val dao = AppDatabase.get(app).downloads()
        dao.deleteInactive()
        dao.deleteEmptyGroups()
    }

    const val SPOTIFY = "Spotify"
}
