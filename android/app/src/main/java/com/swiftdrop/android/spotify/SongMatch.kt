package com.swiftdrop.android.spotify

import java.text.Normalizer
import java.util.Locale
import kotlin.coroutines.cancellation.CancellationException
import kotlin.math.abs
import kotlin.math.max

/** A YouTube (Music) recording that might be a Spotify song. */
data class Candidate(
    val videoId: String,
    val title: String,
    /** Seconds; YouTube Music search results have none until looked up in detail. */
    val duration: Double?,
    val artists: List<String> = emptyList(),
    val channel: String = "",
    /** From YouTube Music (official audio). */
    val music: Boolean = false,
    val album: String? = null,
)

/**
 * Decides whether a YouTube result is the same recording as a Spotify song. A port of the
 * desktop `match_score` (swiftdrop/providers/spotify.py) with the same rules and thresholds:
 * length within max(4 s, 3 %), ≥ 80 % of the song name's words, a Spotify artist named,
 * and no live/remix/cover/… marker the Spotify title doesn't have too.
 */
object SongMatch {

    const val SEARCH_RESULTS = 8
    /** YouTube Music results looked up in detail per song (each takes a second or two). */
    const val MUSIC_LOOKUPS = 3

    private val FEATURING = Regex(
        """[\s\p{Zs}]*[(\[](?:feat|ft|featuring|with)\.?[\s\p{Zs}][^)\]]*[)\]]""",
        RegexOption.IGNORE_CASE,
    )

    /** Words that mark another version of a song; accepted only when the Spotify title has it too. */
    val VERSION_WORDS = listOf(
        "live", "remix", "cover", "karaoke", "instrumental", "acoustic", "sped up", "slowed", "nightcore", "8d",
        "reverb", "reaction", "reacts", "react", "tutorial", "lesson", "mashup", "extended", "demo", "1 hour",
        "bass boosted",
    )

    /** Python's str.casefold(), closely enough for titles and names. */
    fun fold(text: String): String = text.uppercase(Locale.ROOT).lowercase(Locale.ROOT)

    /** Python's `re.findall(r"\w+", NFKC(text).casefold())`: letters, numbers and "_". */
    fun words(text: String): List<String> {
        val folded = fold(Normalizer.normalize(text, Normalizer.Form.NFKC))
        val words = mutableListOf<String>()
        val current = StringBuilder()
        var i = 0
        while (i < folded.length) {
            val cp = folded.codePointAt(i)
            if (isWordChar(cp)) {
                current.appendCodePoint(cp)
            } else if (current.isNotEmpty()) {
                words += current.toString()
                current.setLength(0)
            }
            i += Character.charCount(cp)
        }
        if (current.isNotEmpty()) words += current.toString()
        return words
    }

    private fun isWordChar(cp: Int): Boolean {
        if (cp == '_'.code || Character.isLetter(cp)) return true
        return when (Character.getType(cp).toByte()) {
            Character.DECIMAL_DIGIT_NUMBER, Character.LETTER_NUMBER, Character.OTHER_NUMBER -> true
            else -> false
        }
    }

    /** The song name without "(feat. …)" or " - Remastered 2011"-style suffixes. */
    fun coreTitle(title: String): String {
        val stripped = title.replace(FEATURING, "")
        return stripped.split(" - ", limit = 2)[0].trim().ifEmpty { stripped }
    }

    /** Share of the song name's words found in a candidate title (0 when under 80 %). */
    fun titleMatches(track: SpotifyTrack, title: String): Double {
        val wanted = words(coreTitle(track.title))
        if (wanted.isEmpty()) return 0.0
        val have = words(title).toSet()
        val share = wanted.count { it in have }.toDouble() / wanted.size
        return if (share >= 0.8) share else 0.0
    }

    private fun hasPhrase(words: List<String>, phrase: String): Boolean =
        " ${words.joinToString(" ")} ".contains(" $phrase ")

    /** How well a YouTube result matches a Spotify song; null when it isn't the same recording. */
    fun score(track: SpotifyTrack, candidate: Candidate): Double? {
        val candidateDuration = candidate.duration ?: return null
        var gap = 0.0
        val trackDuration = track.duration
        if (trackDuration != null) {
            gap = abs(candidateDuration - trackDuration)
            if (gap > max(4.0, trackDuration * 0.03)) return null
        }
        val titleShare = titleMatches(track, candidate.title)
        if (titleShare == 0.0) return null
        val candidateWords = words(candidate.title)
        val trackWords = words(track.title)
        if (VERSION_WORDS.any { hasPhrase(candidateWords, it) && !hasPhrase(trackWords, it) }) return null
        val listed = candidate.artists.map(::fold).toSet()
        val haystack = words((listOf(candidate.title, candidate.channel) + candidate.artists).joinToString(" ")).toSet()
        val named = track.artists.filter { haystack.containsAll(words(it)) }
        if (track.artists.isNotEmpty() && named.isEmpty()) return null
        var score = titleShare - gap / 10
        if (candidate.music) score += 0.5
        if (track.artists.any { fold(it) in listed }) score += 0.3
        return score
    }
}

/** YouTube Music and YouTube search (yt-dlp on the phone, fakes in tests). */
interface SongSearch {
    /** YouTube Music "Songs" results: ids and titles only. */
    suspend fun music(query: String): List<Candidate>

    /** One YouTube Music song with its length, artists and album. */
    suspend fun details(videoId: String): Candidate

    /** Plain YouTube search results, with lengths and channels. */
    suspend fun videos(query: String): List<Candidate>
}

class SongMatcher(private val search: SongSearch) {

    /** The best YouTube recording of a Spotify song, or null when nothing matches well enough. */
    suspend fun find(track: SpotifyTrack): Candidate? {
        val artists = track.artists.take(2).joinToString(" ")
        val title = SongMatch.coreTitle(track.title)
        // YouTube Music lists official album audio first, but its search results carry no
        // lengths: look up the few whose titles fit.
        var looked = 0
        for (result in safely { search.music("$artists $title") }) {
            if (looked >= SongMatch.MUSIC_LOOKUPS) break
            if (SongMatch.titleMatches(track, result.title) == 0.0) continue
            looked++
            val candidate = try {
                search.details(result.videoId)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                continue
            }
            if (SongMatch.score(track, candidate) != null) return candidate
        }
        return safely { search.videos("$artists - $title") }
            .mapNotNull { candidate -> SongMatch.score(track, candidate)?.let { it to candidate } }
            .maxByOrNull { it.first }
            ?.second
    }

    private suspend fun safely(search: suspend () -> List<Candidate>): List<Candidate> = try {
        search()
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        emptyList()
    }
}
