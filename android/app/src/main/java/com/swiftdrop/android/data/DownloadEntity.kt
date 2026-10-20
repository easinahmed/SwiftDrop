package com.swiftdrop.android.data

import androidx.room.Entity
import androidx.room.PrimaryKey

enum class DownloadStatus { QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED;

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
)
