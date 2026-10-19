"""Direct HTTP(S) file downloads (videos, audio, images, documents, archives)."""

from __future__ import annotations

from collections.abc import Callable

from swiftdrop.cancel import CancelToken
from swiftdrop.engine.http import HttpDownloader, HttpResult
from swiftdrop.engine.progress import ProgressUpdate
from swiftdrop.engine.segmented import SegmentedDownloader, SegmentedUnavailable
from swiftdrop.errors import failure
from swiftdrop.filenames import (
    DEFAULT_STEM,
    choose_filename,
    filename_from_url,
    kind_for_extension,
    kind_for_mime,
    split_ext,
)
from swiftdrop.models import InspectResult, MediaKind
from swiftdrop.providers.base import DownloadOutcome, JobContext
from swiftdrop.settings import Settings


def _pick_name(url: str, final_url: str | None, disposition: str | None, content_type: str | None) -> str:
    name = choose_filename(url=url, content_disposition=disposition, content_type=content_type)
    if split_ext(name)[0] == DEFAULT_STEM and final_url and final_url != url and filename_from_url(final_url):
        name = choose_filename(url=final_url, content_disposition=disposition, content_type=content_type)
    return name


def _override(meta: dict[str, object]) -> str | None:
    """A file name the user chose (browser confirm window); already sanitised when stored."""
    value = meta.get("filename_override")
    return value if isinstance(value, str) and value.strip() else None


def _kind(name: str, content_type: str | None) -> MediaKind:
    kind = kind_for_mime(content_type)
    if kind in (MediaKind.OTHER, MediaKind.UNKNOWN):
        by_ext = kind_for_extension(split_ext(name)[1])
        if by_ext != MediaKind.UNKNOWN:
            return by_ext
    return kind


class DirectProvider:
    name = "direct"

    def __init__(
        self,
        downloader_factory: Callable[[], HttpDownloader],
        segmented_factory: Callable[[int], SegmentedDownloader] | None = None,
    ) -> None:
        self._factory = downloader_factory
        self._segmented_factory = segmented_factory

    def inspect(self, url: str, token: CancelToken, settings: Settings) -> InspectResult:
        probe = self._factory().probe(url, token)
        if probe.is_html:
            raise failure("not_media", f"Content-Type: {probe.content_type}")
        name = _pick_name(url, probe.url, probe.content_disposition, probe.content_type)
        return InspectResult(
            provider=self.name,
            title=name,
            kind=_kind(name, probe.content_type),
            size=probe.content_length,
            filename=name,
            resolved_url=probe.url,
            content_type=probe.content_type,
        )

    def download(self, ctx: JobContext) -> DownloadOutcome:
        state = ctx.meta.setdefault("http", {})
        part = ctx.staging_dir / "download.part"
        announced = {"done": bool(ctx.meta.get("announced"))}

        def on_progress(update: ProgressUpdate) -> None:
            if not announced["done"] and state.get("final_url"):
                name = _override(ctx.meta) or _pick_name(
                    ctx.url, state.get("final_url"), state.get("content_disposition"), state.get("content_type")
                )
                ctx.set_info(
                    title=name,
                    filename=name,
                    kind=_kind(name, state.get("content_type")),
                    resumable=bool(state.get("accept_ranges")),
                )
                announced["done"] = True
                ctx.meta["announced"] = True
                ctx.checkpoint()
            ctx.report(update)

        ctx.report(ProgressUpdate(phase="Connecting"))
        result: HttpResult | None = None
        # A partial file from a single-connection run is continued the same way, not restarted.
        single_partial = part.exists() and part.stat().st_size > 0 and not state.get("segments")
        if self._segmented_factory is not None and not single_partial:
            segmented = self._segmented_factory(ctx.settings.connections_per_download)
            try:
                result = segmented.download(ctx.url, part, ctx.token, on_progress, state)
            except SegmentedUnavailable:
                result = None  # small file or no usable ranges: one connection, from zero
        if result is None:
            result = self._factory().download(ctx.url, part, ctx.token, on_progress, state)
        ctx.checkpoint()
        name = _override(ctx.meta) or _pick_name(
            ctx.url, result.final_url, result.content_disposition, result.content_type
        )
        kind = _kind(name, result.content_type)
        ctx.report(ProgressUpdate(phase="Saving"))
        final_path = ctx.finalize(part, name, kind)
        return DownloadOutcome(filepath=final_path, size=result.size, kind=kind, sha256=result.sha256)
