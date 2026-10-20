package com.swiftdrop.android.ui

import com.swiftdrop.android.data.DownloadEntity
import com.swiftdrop.android.data.DownloadGroupEntity
import com.swiftdrop.android.data.DownloadStatus
import com.swiftdrop.android.data.GroupSummary
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HomeItemTest {

    private fun row(id: Long, createdAt: Long, groupId: Long? = null, status: DownloadStatus = DownloadStatus.QUEUED) =
        DownloadEntity(id = id, url = "https://example.com/$id", quality = "AUDIO", status = status, createdAt = createdAt, groupId = groupId)

    private val group = DownloadGroupEntity(id = 7, sourceUrl = "https://open.spotify.com/album/x", name = "Road Trip", kind = "album", createdAt = 200)

    @Test
    fun songsSitUnderTheirAlbumInOrder_newestFirst() {
        val downloads = listOf(
            row(1, createdAt = 300),
            row(12, createdAt = 200, groupId = 7),
            row(11, createdAt = 200, groupId = 7),
            row(2, createdAt = 100),
        )
        val items = HomeItem.build(downloads, listOf(group))
        assertEquals(3, items.size)
        assertEquals(1L, (items[0] as HomeItem.Single).download.id)
        val album = items[1] as HomeItem.Group
        assertEquals(listOf(11L, 12L), album.songs.map { it.id })
        assertEquals(2L, (items[2] as HomeItem.Single).download.id)
    }

    @Test
    fun anAlbumWithoutSongs_isHidden() {
        assertEquals(emptyList<HomeItem>(), HomeItem.build(emptyList(), listOf(group)))
    }

    @Test
    fun summary_countsDoneNotFoundAndActive() {
        val songs = listOf(
            row(1, 0, 7, DownloadStatus.COMPLETED),
            row(2, 0, 7, DownloadStatus.COMPLETED),
            row(3, 0, 7, DownloadStatus.NO_MATCH),
            row(4, 0, 7, DownloadStatus.RUNNING),
            row(5, 0, 7, DownloadStatus.QUEUED),
        )
        val summary = GroupSummary.of(songs)
        assertEquals("2 of 5 done · 1 not found", summary.line())
        assertTrue(summary.isActive)
        assertEquals(0.6f, summary.fraction, 1e-6f)

        val finished = GroupSummary.of(songs.map { if (it.status.isActive) it.copy(status = DownloadStatus.CANCELLED) else it })
        assertFalse(finished.isActive)
        assertEquals("2 of 5 done · 1 not found · 2 cancelled", finished.line())
    }
}
