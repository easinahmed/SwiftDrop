package com.swiftdrop.android.download

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkInfo
import androidx.work.WorkerParameters
import com.swiftdrop.android.core.FileNames
import com.swiftdrop.android.core.Quality
import com.swiftdrop.android.data.AppDatabase
import com.swiftdrop.android.data.DownloadEntity
import com.swiftdrop.android.data.DownloadGroupEntity
import com.swiftdrop.android.data.DownloadStatus
import com.swiftdrop.android.spotify.SongState
import com.swiftdrop.android.spotify.SpotifyClient
import com.swiftdrop.android.spotify.SpotifyCollection
import com.swiftdrop.android.spotify.SpotifyException
import com.swiftdrop.android.spotify.SpotifyLink
import com.swiftdrop.android.spotify.SpotifyTrack
import kotlin.coroutines.cancellation.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.runInterruptible
import kotlinx.coroutines.withContext

/**
 * Reads a shared Spotify link (a few seconds): a song becomes one queued download; an album or
 * playlist becomes a group with one queued download per song. [SongQueue] then runs them,
 * a few at a time, through [DownloadWorker].
 */
class SpotifyResolveWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    private val downloadId = inputData.getLong(DownloadWorker.KEY_DOWNLOAD_ID, -1L)
    private val dao by lazy { AppDatabase.get(applicationContext).downloads() }

    override suspend fun doWork(): Result {
        val item = dao.get(downloadId) ?: return Result.failure()
        if (!item.status.isActive) return Result.success() // cancelled before it started
        val ctx = applicationContext
        dao.setStatus(downloadId, DownloadStatus.RUNNING)
        Notifications.clearResult(ctx, downloadId)
        return try {
            val (link, content) = runInterruptible(Dispatchers.IO) { SpotifyClient.load(item.url) }
            when (content) {
                is SpotifyTrack -> addSong(item, link, content)
                is SpotifyCollection -> {
                    if (content.tracks.isEmpty()) {
                        return fail(item, "This Spotify ${content.kind} has no songs SwiftDrop can download.")
                    }
                    addGroup(link, content)
                }
            }
            // The song rows are new, with their own work: this job's unique work name (its row's)
            // must not be reused while it is still running, or WorkManager would cancel it.
            dao.delete(downloadId)
            SongQueue.pump(ctx)
            Result.success()
        } catch (e: CancellationException) {
            withContext(NonCancellable) {
                if (stopReason == WorkInfo.STOP_REASON_CANCELLED_BY_APP) dao.markCancelledIfActive(downloadId)
                else dao.setStatus(downloadId, DownloadStatus.QUEUED) // stopped by the system; WorkManager runs it again
            }
            throw e
        } catch (e: SpotifyException) {
            fail(item, e.message ?: SpotifyException.UNSUPPORTED_TITLE)
        } catch (e: Exception) {
            Log.w(TAG, "Couldn't read Spotify link $downloadId", e)
            fail(item, e.message?.takeIf { it.isNotBlank() } ?: "Couldn't read this Spotify link.")
        }
    }

    /** A single song takes the place of the "Getting Spotify songs…" row. */
    private suspend fun addSong(item: DownloadEntity, link: SpotifyLink, track: SpotifyTrack) {
        dao.insert(
            DownloadEntity(
                url = link.url,
                quality = Quality.AUDIO.name,
                title = track.display,
                site = Downloads.SPOTIFY,
                thumbnailUrl = track.image,
                kind = DownloadEntity.KIND_SPOTIFY_SONG,
                spotify = SongState(track).toJson(),
                createdAt = item.createdAt,
            )
        )
    }

    private suspend fun addGroup(link: SpotifyLink, collection: SpotifyCollection) {
        val now = System.currentTimeMillis()
        val group = DownloadGroupEntity(
            sourceUrl = link.url,
            name = collection.name,
            kind = collection.kind,
            imageUrl = collection.image,
            partial = collection.partial,
            createdAt = now,
        )
        val groupId = dao.insertGroup(group)
        val folder = FileNames.sanitizeBase(collection.name)
        dao.insertAll(
            collection.tracks.map { track ->
                DownloadEntity(
                    url = SpotifyLink("track", track.id).url,
                    quality = Quality.AUDIO.name,
                    title = track.display,
                    site = Downloads.SPOTIFY,
                    kind = DownloadEntity.KIND_SPOTIFY_SONG,
                    groupId = groupId,
                    folder = folder,
                    spotify = SongState(track).toJson(),
                    createdAt = now,
                    updatedAt = now,
                )
            }
        )
        Notifications.showGroupFound(applicationContext, group.copy(id = groupId), collection.tracks.size)
    }

    private suspend fun fail(item: DownloadEntity, message: String): Result {
        withContext(NonCancellable) { dao.setFailed(downloadId, message) }
        Notifications.showFailed(applicationContext, downloadId, item.title ?: "Spotify link", message)
        return Result.failure()
    }

    private companion object {
        const val TAG = "SwiftDropSpotify"
    }
}
