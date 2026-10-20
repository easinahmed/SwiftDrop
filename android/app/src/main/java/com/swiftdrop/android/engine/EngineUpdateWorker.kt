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

/** Keeps yt-dlp fresh: checks the stable channel at most once a week, never mid-download. */
class EngineUpdateWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val settings = Settings.get(applicationContext)
        val now = System.currentTimeMillis()
        if (now - settings.lastEngineCheck < MIN_INTERVAL_MS) return Result.success()

        val busy = WorkManager.getInstance(applicationContext)
            .getWorkInfosByTagFlow(Downloads.TAG)
            .first()
            .any { it.state == WorkInfo.State.RUNNING }
        if (busy) return Result.retry()

        return when (Engine.update(applicationContext)) {
            is EngineUpdateResult.Failed -> Result.retry()
            else -> {
                settings.lastEngineCheck = now
                Result.success()
            }
        }
    }

    companion object {
        private const val UNIQUE_NAME = "engine-weekly-update"
        private val MIN_INTERVAL_MS = TimeUnit.DAYS.toMillis(6) + TimeUnit.HOURS.toMillis(12)

        /** Call at start-up and whenever "Wi-Fi only" changes; keeps the existing weekly cadence. */
        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<EngineUpdateWorker>(7, TimeUnit.DAYS)
                .setInitialDelay(1, TimeUnit.DAYS)
                .setConstraints(
                    Constraints.Builder()
                        .setRequiredNetworkType(
                            if (Settings.get(context).wifiOnly.value) NetworkType.UNMETERED else NetworkType.CONNECTED
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
