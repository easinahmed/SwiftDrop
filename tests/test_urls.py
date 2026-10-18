import pytest

from swiftdrop.urls import (
    InvalidUrlError,
    dedupe_key,
    display_domain,
    extract_urls,
    normalize_url,
    parse_url_list,
)


def test_extracts_urls_from_mixed_text():
    text = """
    Check this out: https://example.com/video.mp4, and also (https://example.org/a_(b)).
    www.example.net/page
    youtube.com/watch?v=dQw4w9WgXcQ!
    [md](https://example.com/md-link)
    not a link: e.g. notes.txt
    """
    assert extract_urls(text) == [
        "https://example.com/video.mp4",
        "https://example.org/a_(b)",
        "https://www.example.net/page",
        "https://youtube.com/watch?v=dQw4w9WgXcQ",
        "https://example.com/md-link",
    ]


def test_ignores_empty_lines_and_whitespace():
    result = parse_url_list("\n\n   \nhttps://a.example.com/x\n\n\t\n")
    assert [u.url for u in result.urls] == ["https://a.example.com/x"]


def test_normalize_lowercases_host_strips_fragment_and_tracking():
    url = normalize_url("HTTPS://Example.COM:443/Path/File.MP4?utm_source=x&id=5&fbclid=abc#frag")
    assert url == "https://example.com/Path/File.MP4?id=5"


def test_normalize_preserves_signed_query_exactly():
    raw = "https://cdn.example.com/v.mp4?Expires=1&Signature=a%2Bb%3D&Key-Pair-Id=K"
    assert normalize_url(raw) == raw


def test_normalize_keeps_encoded_slashes():
    assert normalize_url("https://example.com/a%2Fb") == "https://example.com/a%2Fb"


def test_normalize_encodes_spaces_and_unicode_path():
    assert normalize_url("https://example.com/my file é.mp4") == "https://example.com/my%20file%20%C3%A9.mp4"


def test_normalize_idn_host():
    assert normalize_url("https://bücher.example/x") == "https://xn--bcher-kva.example/x"


@pytest.mark.parametrize(
    "raw",
    [
        "ftp://example.com/file",
        "javascript:alert(1)//x",
        "https://user:pass@example.com/x",
        "https:///nohost",
        "https://localhost:99999/x",
        "file:///etc/passwd",
        "https://" + "a" * 9000 + ".com/",
    ],
)
def test_rejects_invalid(raw):
    with pytest.raises(InvalidUrlError):
        normalize_url(raw)


def test_allows_localhost_and_ip():
    assert normalize_url("http://127.0.0.1:8000/a.mp4") == "http://127.0.0.1:8000/a.mp4"
    assert normalize_url("http://localhost/a") == "http://localhost/a"


def test_youtube_variants_share_dedupe_key():
    variants = [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?si=tracking",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ&feature=share",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
    ]
    keys = {dedupe_key(normalize_url(v)) for v in variants}
    assert keys == {"youtube:dQw4w9WgXcQ"}


def test_generic_dedupe_ignores_www_trailing_slash_and_param_order():
    a = dedupe_key(normalize_url("https://www.example.com/path/?b=2&a=1"))
    b = dedupe_key(normalize_url("http://example.com/path?a=1&b=2"))
    assert a == b


def test_parse_reports_duplicates_and_invalid():
    text = "\n".join(
        [
            "https://example.com/a.mp4",
            "https://example.com/a.mp4",
            "https://EXAMPLE.com/a.mp4#x",
            "ftp://example.com/b",
            "https://example.com/c.jpg",
        ]
    )
    result = parse_url_list(text)
    assert [u.url for u in result.urls] == ["https://example.com/a.mp4", "https://example.com/c.jpg"]
    assert len(result.duplicates) == 2
    assert len(result.invalid) == 1
    assert result.total_found == 5


def test_parse_known_keys_marks_duplicates():
    known = {dedupe_key("https://example.com/a.mp4")}
    result = parse_url_list("https://example.com/a.mp4 https://example.com/b.mp4", known_keys=known)
    assert [u.url for u in result.urls] == ["https://example.com/b.mp4"]
    assert len(result.duplicates) == 1


def test_bulk_parse_150_urls_is_fast():
    import time

    text = "\n".join(f"https://cdn{i % 7}.example.com/media/file-{i}.mp4" for i in range(1500))
    start = time.perf_counter()
    result = parse_url_list(text)
    assert len(result.urls) == 1500
    assert time.perf_counter() - start < 2.0


def test_display_domain():
    assert display_domain("https://www.example.com/x") == "example.com"
    assert display_domain("https://cdn.example.com/x") == "cdn.example.com"
