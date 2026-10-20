package com.swiftdrop.android.core

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SavePathsTest {

    @Test
    fun relativePath_isDownloadSwiftDrop() {
        assertEquals("Download/SwiftDrop", SavePaths.RELATIVE_PATH)
    }

    @Test
    fun mediaStoreFromApi29_legacyFolderBelow() {
        assertFalse(SavePaths.usesMediaStore(26))
        assertFalse(SavePaths.usesMediaStore(28))
        assertTrue(SavePaths.usesMediaStore(29))
        assertTrue(SavePaths.usesMediaStore(36))
        assertTrue(SavePaths.needsLegacyWritePermission(28))
        assertFalse(SavePaths.needsLegacyWritePermission(29))
    }

    @Test
    fun legacyDirectory_isUnderExternalRoot() {
        assertEquals(
            File("/storage/emulated/0/Download/SwiftDrop"),
            SavePaths.legacyDirectory(File("/storage/emulated/0")),
        )
    }

    @Test
    fun uniqueName_appendsCounterBeforeExtension() {
        val taken = setOf("clip.mp4", "clip (1).mp4")
        assertEquals("new.mp4", SavePaths.uniqueName("new.mp4") { it in taken })
        assertEquals("clip (2).mp4", SavePaths.uniqueName("clip.mp4") { it in taken })
        assertEquals("README (1)", SavePaths.uniqueName("README") { it == "README" })
    }

    @Test
    fun mimeTypes() {
        assertEquals("video/mp4", SavePaths.mimeType("a.mp4"))
        assertEquals("video/mp4", SavePaths.mimeType("A.MP4"))
        assertEquals("audio/mp4", SavePaths.mimeType("song.m4a"))
        assertEquals("video/webm", SavePaths.mimeType("x.webm"))
        assertEquals("application/octet-stream", SavePaths.mimeType("noext"))
        assertEquals("application/octet-stream", SavePaths.mimeType("weird.xyz"))
    }
}
