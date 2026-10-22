package com.swiftdrop.android.core

/** Which kind-of-file folder a download goes to when "Separate folders" is on. */
enum class MediaCategory(val folder: String) {
    VIDEO("Videos"),
    MUSIC("Music"),
    OTHER("Other");

    companion object {
        fun of(mimeType: String?): MediaCategory = when {
            mimeType == null -> OTHER
            mimeType.startsWith("video/") -> VIDEO
            mimeType.startsWith("audio/") -> MUSIC
            else -> OTHER
        }
    }
}

/** The folder choice for one saved file: the base folder plus the sub-folders below it. */
data class SaveFolder(
    /** null = Download/SwiftDrop (MediaStore); else a tree URI picked in Settings. */
    val treeUri: String?,
    /** How the base folder is shown: "Download/SwiftDrop" or the picked folder's label. */
    val baseLabel: String,
    /** Folders created under the base, outermost first, e.g. ["Music", "Road Trip"]. */
    val subfolders: List<String>,
) {
    /** "Download/SwiftDrop/Music/Road Trip": where the user will find the file. */
    val displayPath: String get() = (listOf(baseLabel) + subfolders).joinToString("/")

    /** MediaStore RELATIVE_PATH for the default base folder. */
    val relativePath: String get() = (listOf(SavePaths.RELATIVE_PATH) + subfolders).joinToString("/")
}

/**
 * Decides where a finished file goes, from the Downloads settings:
 *  - base: Download/SwiftDrop, or the folder chosen with "Choose folder…";
 *  - then "Videos" / "Music" / "Other" when "Separate folders" is on;
 *  - then the album's or playlist's own folder when "Albums and playlists in their own folder" is on.
 */
object SaveFolders {

    fun plan(
        mimeType: String?,
        treeUri: String?,
        treeLabel: String?,
        separateFolders: Boolean,
        groupFolders: Boolean,
        collection: String?,
    ): SaveFolder {
        val subfolders = buildList {
            if (separateFolders) add(MediaCategory.of(mimeType).folder)
            if (groupFolders && !collection.isNullOrBlank()) add(FileNames.sanitizeBase(collection))
        }
        val base = if (treeUri == null) SavePaths.RELATIVE_PATH else treeLabel ?: CHOSEN_FOLDER
        return SaveFolder(treeUri, base, subfolders)
    }

    const val CHOSEN_FOLDER = "Chosen folder"
    private const val SD_CARD = "SD card"

    /**
     * A readable name for a folder picked with ACTION_OPEN_DOCUMENT_TREE, from its tree document id:
     * "primary:Movies/Clips" → "Movies/Clips", "primary:" → "Internal storage",
     * "1A2B-3C4D:Music" → "Music (SD card)", "raw:/storage/emulated/0/Download/X" → "Download/X".
     */
    fun treeLabel(treeDocumentId: String?): String {
        val id = treeDocumentId?.trim().orEmpty()
        if (id.isEmpty()) return CHOSEN_FOLDER
        val volume = id.substringBefore(':', "")
        val path = id.substringAfter(':', id).trim('/')
        return when {
            volume == "raw" -> path.substringAfter("storage/emulated/0/", path).trim('/').ifEmpty { CHOSEN_FOLDER }
            volume == "primary" -> path.ifEmpty { "Internal storage" }
            volume == "home" -> listOf("Documents", path).filter { it.isNotEmpty() }.joinToString("/")
            volume == "downloads" || id == "downloads" -> listOf("Download", path.takeIf { volume.isNotEmpty() }.orEmpty())
                .filter { it.isNotEmpty() && it != "downloads" }.joinToString("/")
            VOLUME_ID.matches(volume) -> if (path.isEmpty()) SD_CARD else "$path ($SD_CARD)"
            volume.isEmpty() -> path.substringAfterLast('/').ifEmpty { CHOSEN_FOLDER }
            else -> path.ifEmpty { CHOSEN_FOLDER }
        }
    }

    private val VOLUME_ID = Regex("^[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}$")
}
