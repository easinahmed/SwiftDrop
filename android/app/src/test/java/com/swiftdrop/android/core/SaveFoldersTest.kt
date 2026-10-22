package com.swiftdrop.android.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SaveFoldersTest {

    private fun plan(
        mime: String = "video/mp4",
        tree: String? = null,
        label: String? = null,
        separate: Boolean = false,
        group: Boolean = true,
        collection: String? = null,
    ) = SaveFolders.plan(mime, tree, label, separate, group, collection)

    @Test
    fun default_isDownloadSwiftDrop() {
        val folder = plan()
        assertNull(folder.treeUri)
        assertEquals(emptyList<String>(), folder.subfolders)
        assertEquals("Download/SwiftDrop", folder.relativePath)
        assertEquals("Download/SwiftDrop", folder.displayPath)
    }

    @Test
    fun separateFolders_byKindOfFile() {
        assertEquals("Download/SwiftDrop/Videos", plan(mime = "video/webm", separate = true).relativePath)
        assertEquals("Download/SwiftDrop/Music", plan(mime = "audio/mpeg", separate = true).relativePath)
        assertEquals("Download/SwiftDrop/Other", plan(mime = "image/jpeg", separate = true).relativePath)
        assertEquals("Download/SwiftDrop/Other", plan(mime = "application/octet-stream", separate = true).relativePath)
    }

    @Test
    fun albumsAndPlaylists_getTheirOwnFolder_whenOn() {
        assertEquals("Download/SwiftDrop/Road Trip", plan(mime = "audio/mp4", collection = "Road Trip").relativePath)
        assertEquals(
            "Download/SwiftDrop/Music/AC DC Hits",
            plan(mime = "audio/mp4", separate = true, collection = "AC/DC: Hits").relativePath,
        )
        assertEquals("Download/SwiftDrop", plan(mime = "audio/mp4", group = false, collection = "Road Trip").relativePath)
        assertEquals("Download/SwiftDrop", plan(mime = "audio/mp4", collection = "  ").relativePath)
    }

    @Test
    fun chosenFolder_keepsSubfoldersAndShowsItsLabel() {
        val folder = plan(
            mime = "audio/mp4",
            tree = "content://com.android.externalstorage.documents/tree/primary%3AMusic%2FRips",
            label = "Music/Rips",
            separate = true,
            collection = "Road Trip",
        )
        assertEquals("content://com.android.externalstorage.documents/tree/primary%3AMusic%2FRips", folder.treeUri)
        assertEquals(listOf("Music", "Road Trip"), folder.subfolders)
        assertEquals("Music/Rips/Music/Road Trip", folder.displayPath)
        assertEquals("Chosen folder", plan(tree = "content://x/tree/y", label = null).displayPath)
    }

    @Test
    fun treeLabels() {
        assertEquals("Movies/Clips", SaveFolders.treeLabel("primary:Movies/Clips"))
        assertEquals("Internal storage", SaveFolders.treeLabel("primary:"))
        assertEquals("Music (SD card)", SaveFolders.treeLabel("1A2B-3C4D:Music"))
        assertEquals("SD card", SaveFolders.treeLabel("1A2B-3C4D:"))
        assertEquals("Download/Clips", SaveFolders.treeLabel("raw:/storage/emulated/0/Download/Clips"))
        assertEquals("Documents/Notes", SaveFolders.treeLabel("home:Notes"))
        assertEquals("Download", SaveFolders.treeLabel("downloads"))
        assertEquals("Chosen folder", SaveFolders.treeLabel(null))
        assertEquals("Chosen folder", SaveFolders.treeLabel(""))
    }

    @Test
    fun mediaCategory() {
        assertEquals(MediaCategory.VIDEO, MediaCategory.of("video/x-matroska"))
        assertEquals(MediaCategory.MUSIC, MediaCategory.of("audio/ogg"))
        assertEquals(MediaCategory.OTHER, MediaCategory.of(null))
    }
}
