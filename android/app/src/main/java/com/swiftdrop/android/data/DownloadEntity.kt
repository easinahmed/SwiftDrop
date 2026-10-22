package com.swiftdrop.android.data

import androidx.room.Entity
import androidx.room.PrimaryKey

enum class DownloadStatus { QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED,
    /** A Spotify song with no recording on YouTube that matches well enough; nothing was downloaded. */
    NO_MATCH;

    val isActive: Boolean get() = this == QUEUED || this == RUNNING
}

@Entity(tableName = "downloads")
data class DownloadEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val url: String,
    val quality: String,
    val title: String? = null,
    val site: String? = null,
    val thumbnailUrl: String? = null,
    val status: DownloadStatus = DownloadStatus.QUEUED,
    /** 0..100 */
    val progress: Float = 0f,
    val speed: String? = null,
    val error: String? = null,
    val fileUri: String? = null,
    val fileName: String? = null,
    val mimeType: String? = null,
    val sizeBytes: Long = 0,
    val createdAt: Long = System.currentTimeMillis(),
    val updatedAt: Long = System.currentTimeMillis(),
    /** null: a link yt-dlp downloads; [KIND_SPOTIFY_LINK] or [KIND_SPOTIFY_SONG]. */
    val kind: String? = null,
    /** The Spotify album or playlist ([DownloadGroupEntity]) this song belongs to. */
    val groupId: Long? = null,
    /** The album or playlist name: its own folder when that setting is on. */
    val folder: String? = null,
    /** The Spotify song and, once found, its YouTube match (SongState JSON). */
    val spotify: String? = null,
    /** Where the finished file went, as shown to the user ("Download/SwiftDrop/Music"). Null before 1.2. */
    val savedTo: String? = null,
) {
    val isSpotifySong: Boolean get() = kind == KIND_SPOTIFY_SONG
    val isSpotifyLink: Boolean get() = kind == KIND_SPOTIFY_LINK

    companion object {
        /** A shared Spotify link whose songs are still being read. */
        const val KIND_SPOTIFY_LINK = "spotify_link"
        /** One Spotify song, downloaded from its YouTube match. */
        const val KIND_SPOTIFY_SONG = "spotify_song"
    }
}

/** A Spotify album or playlist: a header over its songs in the Downloads list. */
@Entity(tableName = "download_groups")
data class DownloadGroupEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val sourceUrl: String,
    val name: String,
    /** "album" | "playlist" */
    val kind: String,
    val imageUrl: String? = null,
    /** Spotify listed only the first 100 songs (its embed page's limit for playlists). */
    val partial: Boolean = false,
    val createdAt: Long = System.currentTimeMillis(),
)
