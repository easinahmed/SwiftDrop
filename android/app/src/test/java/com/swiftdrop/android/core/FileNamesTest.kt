package com.swiftdrop.android.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FileNamesTest {

    @Test
    fun illegalCharacters_areReplaced() {
        assertEquals("AC DC Live at River Plate", FileNames.sanitizeBase("AC/DC: Live at River Plate"))
        assertEquals("What is this", FileNames.sanitizeBase("What is <this>?"))
        assertEquals("a b c d", FileNames.sanitizeBase("a\\b|c*\"d\""))
    }

    @Test
    fun controlCharactersAndWhitespace_areCollapsed() {
        assertEquals("line one line two", FileNames.sanitizeBase("line one\n\tline\u0000two"))
        assertEquals("spaced out", FileNames.sanitizeBase("   spaced    out   "))
    }

    @Test
    fun leadingAndTrailingDots_areRemoved() {
        assertEquals("hidden", FileNames.sanitizeBase("...hidden..."))
    }

    @Test
    fun emptyOrNull_fallsBack() {
        assertEquals(FileNames.FALLBACK_BASE, FileNames.sanitizeBase(null))
        assertEquals(FileNames.FALLBACK_BASE, FileNames.sanitizeBase(""))
        assertEquals(FileNames.FALLBACK_BASE, FileNames.sanitizeBase("///???"))
    }

    @Test
    fun unicodeAndEmoji_areKept() {
        assertEquals("Café 東京 🎵", FileNames.sanitizeBase("Café 東京 🎵"))
    }

    @Test
    fun longNames_areTruncatedWithoutSplittingSurrogatePairs() {
        val long = "a".repeat(119) + "😀" + "tail"
        val result = FileNames.sanitizeBase(long)
        assertTrue(result.length <= FileNames.MAX_BASE_LENGTH)
        assertFalse(Character.isHighSurrogate(result.last()))
        assertEquals(FileNames.MAX_BASE_LENGTH, FileNames.sanitizeBase("b".repeat(500)).length)
    }

    @Test
    fun displayName_joinsBaseAndCleanExtension() {
        assertEquals("My Video.mp4", FileNames.displayName("My Video", "mp4"))
        assertEquals("My Video.m4a", FileNames.displayName("My Video", ".M4A"))
        assertEquals("My Video", FileNames.displayName("My Video", null))
        assertEquals("Title.mp4", FileNames.displayName("Title", "m/p\"4"))
    }
}
