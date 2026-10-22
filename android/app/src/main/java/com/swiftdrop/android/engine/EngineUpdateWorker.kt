package com.swiftdrop.android.engine

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.swiftdrop.android.data.Settings
import com.swiftdrop.android.download.Downloads
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.flow.first

/**
 * Keeps yt-dlp fresh while the app isn't opened: looks once a day and updates when the engine is
 * more than three days old ("Auto-update engine" in Settings), never mid-download.
 */
class EngineUpdateWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        if (!Settings.get(applicationContext).current.engineAutoUpdate) return Result.success()
        val busy = WorkManager.getInstance(applicationContext)
            .getWorkInfosByTagFlow(Downloads.TAG)
            .first()
            .any { it.state == WorkInfo.State.RUNNING }
        if (busy) return Result.success() // tomorrow, or the next app start
        Engine.awaitReady()
        Engine.updateIfStale(applicationContext)
        return Result.success()
    }

    companion object {
        private const val UNIQUE_NAME = "engine-weekly-update"

        /** Call at start-up and whenever "Wi-Fi only" changes. */
        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<EngineUpdateWorker>(1, TimeUnit.DAYS)
                .setInitialDelay(6, TimeUnit.HOURS)
                .setConstraints(
                    Constraints.Builder()
                        .setRequiredNetworkType(
                            if (Settings.get(context).current.wifiOnly) NetworkType.UNMETERED else NetworkType.CONNECTED
                        )
                        .setRequiresBatteryNotLow(true)
                        .build()
                )
                .build()
            WorkManager.getInstance(context)
                .enqueueUniquePeriodicWork(UNIQUE_NAME, ExistingPeriodicWorkPolicy.UPDATE, request)
        }
    }
}
