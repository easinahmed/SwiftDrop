package com.swiftdrop.android.ui

import com.swiftdrop.android.data.DownloadEntity
import com.swiftdrop.android.data.DownloadGroupEntity
import com.swiftdrop.android.data.GroupSummary

/** One entry in the Downloads list: a download, or a Spotify album/playlist with its songs. */
sealed interface HomeItem {
    val createdAt: Long

    data class Single(val download: DownloadEntity) : HomeItem {
        override val createdAt: Long get() = download.createdAt
    }

    data class Group(val group: DownloadGroupEntity, val songs: List<DownloadEntity>) : HomeItem {
        override val createdAt: Long get() = group.createdAt
        val summary: GroupSummary = GroupSummary.of(songs)
    }

    companion object {
        /** Newest first; songs in album/playlist order; groups whose songs were all removed are hidden. */
        fun build(downloads: List<DownloadEntity>, groups: List<DownloadGroupEntity>): List<HomeItem> {
            val songsByGroup = downloads.filter { it.groupId != null }.groupBy { it.groupId }
            val singles = downloads.filter { it.groupId == null }.map(::Single)
            val grouped = groups.mapNotNull { group ->
                songsByGroup[group.id]?.sortedBy { it.id }?.let { Group(group, it) }
            }
            return (singles + grouped).sortedByDescending { it.createdAt }
        }
    }
}
