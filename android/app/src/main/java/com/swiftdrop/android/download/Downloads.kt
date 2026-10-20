package com.swiftdrop.android.download

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.workDataOf
import com.swiftdrop.android.core.Quality
import com.swiftdrop.android.data.AppDatabase
import com.swiftdrop.android.data.DownloadEntity
import com.swiftdrop.android.data.Settings

/** Queue operations shared by the share sheet, the app UI and notification actions. */
object Downloads {

    const val TAG = "swiftdrop-download"

    private fun workName(id: Long) = "download-$id"

    /** Records a new download and schedules it. Returns the history row id. */
    suspend fun enqueue(context: Context, url: String, quality: Quality = Settings.get(context).quality.value): Long {
        val app = context.applicationContext
        val id = AppDatabase.get(app).downloads().insert(DownloadEntity(url = url, quality = quality.name))
        schedule(app, id)
        return id
    }

    suspend fun retry(context: Context, id: Long) {
        val app = context.applicationContext
        val dao = AppDatabase.get(app).downloads()
        val item = dao.get(id) ?: return
        if (item.status.isActive) return
        Notifications.clear(app, id)
        dao.resetForRetry(id, item.quality)
        schedule(app, id)
    }

    suspend fun cancel(context: Context, id: Long) {
        val app = context.applicationContext
        WorkManager.getInstance(app).cancelUniqueWork(workName(id))
        AppDatabase.get(app).downloads().markCancelledIfActive(id)
        Notifications.clearProgress(app, id)
    }

    /** Removes the entry from the history. The saved file stays in Download/SwiftDrop. */
    suspend fun remove(context: Context, id: Long) {
        val app = context.applicationContext
        val dao = AppDatabase.get(app).downloads()
        if (dao.get(id)?.status?.isActive == true) cancel(app, id)
        dao.delete(id)
        Notifications.clear(app, id)
    }

    private fun schedule(context: Context, id: Long) {
        val wifiOnly = Settings.get(context).wifiOnly.value
        val request = OneTimeWorkRequestBuilder<DownloadWorker>()
            .setInputData(workDataOf(DownloadWorker.KEY_DOWNLOAD_ID to id))
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(if (wifiOnly) NetworkType.UNMETERED else NetworkType.CONNECTED)
                    .build()
            )
            .addTag(TAG)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(workName(id), ExistingWorkPolicy.REPLACE, request)
    }
}
