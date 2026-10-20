package com.swiftdrop.android.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface DownloadDao {

    @Query("SELECT * FROM downloads ORDER BY createdAt DESC")
    fun observeAll(): Flow<List<DownloadEntity>>

    @Query("SELECT * FROM downloads WHERE id = :id")
    suspend fun get(id: Long): DownloadEntity?

    @Insert
    suspend fun insert(entity: DownloadEntity): Long

    @Insert
    suspend fun insertAll(entities: List<DownloadEntity>): List<Long>

    @Query("DELETE FROM downloads WHERE id = :id")
    suspend fun delete(id: Long)

    @Query(
        "UPDATE downloads SET status = 'QUEUED', progress = 0, speed = NULL, error = NULL, " +
            "quality = :quality, updatedAt = :now WHERE id = :id"
    )
    suspend fun resetForRetry(id: Long, quality: String, now: Long = System.currentTimeMillis())

    @Query("UPDATE downloads SET status = :status, speed = NULL, updatedAt = :now WHERE id = :id")
    suspend fun setStatus(id: Long, status: DownloadStatus, now: Long = System.currentTimeMillis())

    @Query(
        "UPDATE downloads SET status = 'CANCELLED', speed = NULL, updatedAt = :now " +
            "WHERE id = :id AND status IN ('QUEUED', 'RUNNING')"
    )
    suspend fun markCancelledIfActive(id: Long, now: Long = System.currentTimeMillis())

    @Query("UPDATE downloads SET status = 'FAILED', error = :error, speed = NULL, updatedAt = :now WHERE id = :id")
    suspend fun setFailed(id: Long, error: String, now: Long = System.currentTimeMillis())

    @Query(
        "UPDATE downloads SET status = 'NO_MATCH', error = :error, progress = 0, speed = NULL, updatedAt = :now " +
            "WHERE id = :id"
    )
    suspend fun setNoMatch(id: Long, error: String, now: Long = System.currentTimeMillis())

    @Query(
        "UPDATE downloads SET title = COALESCE(:title, title), site = COALESCE(:site, site), " +
            "thumbnailUrl = COALESCE(:thumbnailUrl, thumbnailUrl), updatedAt = :now WHERE id = :id"
    )
    suspend fun setMetadata(
        id: Long,
        title: String?,
        site: String?,
        thumbnailUrl: String?,
        now: Long = System.currentTimeMillis(),
    )

    @Query("UPDATE downloads SET progress = :progress, speed = :speed, updatedAt = :now WHERE id = :id")
    suspend fun setProgress(id: Long, progress: Float, speed: String?, now: Long = System.currentTimeMillis())

    @Query(
        "UPDATE downloads SET status = 'COMPLETED', progress = 100, speed = NULL, error = NULL, " +
            "fileUri = :fileUri, fileName = :fileName, mimeType = :mimeType, sizeBytes = :sizeBytes, " +
            "updatedAt = :now WHERE id = :id"
    )
    suspend fun setCompleted(
        id: Long,
        fileUri: String,
        fileName: String,
        mimeType: String,
        sizeBytes: Long,
        now: Long = System.currentTimeMillis(),
    )

    // -- Spotify ---------------------------------------------------------------------------------

    @Query("UPDATE downloads SET spotify = :spotify, updatedAt = :now WHERE id = :id")
    suspend fun setSpotify(id: Long, spotify: String, now: Long = System.currentTimeMillis())

    @Query("SELECT * FROM downloads WHERE kind = 'spotify_song' AND status = 'RUNNING'")
    suspend fun runningSongs(): List<DownloadEntity>

    /** Oldest share first, then album/playlist order. */
    @Query(
        "SELECT * FROM downloads WHERE kind = 'spotify_song' AND status = 'QUEUED' " +
            "ORDER BY createdAt ASC, id ASC LIMIT :limit"
    )
    suspend fun nextQueuedSongs(limit: Int): List<DownloadEntity>

    @Query("SELECT * FROM downloads WHERE groupId = :groupId ORDER BY id ASC")
    suspend fun songsInGroup(groupId: Long): List<DownloadEntity>

    @Query(
        "UPDATE downloads SET status = 'CANCELLED', speed = NULL, updatedAt = :now " +
            "WHERE groupId = :groupId AND status IN ('QUEUED', 'RUNNING')"
    )
    suspend fun cancelGroupSongs(groupId: Long, now: Long = System.currentTimeMillis())

    @Query("DELETE FROM downloads WHERE groupId = :groupId")
    suspend fun deleteGroupSongs(groupId: Long)

    @Query("SELECT * FROM download_groups")
    fun observeGroups(): Flow<List<DownloadGroupEntity>>

    @Query("SELECT * FROM download_groups WHERE id = :id")
    suspend fun getGroup(id: Long): DownloadGroupEntity?

    @Insert
    suspend fun insertGroup(group: DownloadGroupEntity): Long

    @Query("DELETE FROM download_groups WHERE id = :id")
    suspend fun deleteGroup(id: Long)
}
