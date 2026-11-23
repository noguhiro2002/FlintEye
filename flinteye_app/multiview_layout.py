"""Source identity and slot order shared by both Multiview compositors."""
from flinteye_app.camera_audio import LIVE_PREFIX


def public_source(path: str) -> str:
    path = path.strip().strip("/")
    for prefix in ("__mv_buffer/", "__mv_input/"):
        if path.casefold().startswith(prefix):
            path = path[len(prefix):]
    return path


def is_public_source(path: str, output_prefix: str) -> bool:
    name = path.strip().strip("/").casefold()
    prefix = output_prefix.casefold()
    return bool(name) and name != prefix and not name.startswith((
        prefix + "_", LIVE_PREFIX + "/", "__mv_input/", "__mv_buffer/",
    ))


def unique_sources(paths: list[str], output_prefix: str, limit: int) -> list[str]:
    ordered: dict[str, str] = {}
    for path in paths:
        public = public_source(path)
        if is_public_source(public, output_prefix):
            ordered.setdefault(public.casefold(), path)
    return list(ordered.values())[:limit]


def source_pages(
    sources: list[str], tile_count: int, placements: list[list[str | None]] | None
) -> list[list[str | None]]:
    if placements is not None:
        return placements
    return [sources[start : start + tile_count] for start in range(0, len(sources), tile_count)]


def parse_placements(value: str | None, tile_count: int) -> list[list[str | None]] | None:
    if not value:
        return None
    import json

    pages = json.loads(value)
    if not isinstance(pages, list) or any(
        not isinstance(page, list) or len(page) != tile_count or
        any(path is not None and (not isinstance(path, str) or not path) for path in page)
        for page in pages
    ):
        raise ValueError("Multiview placements must contain one source or null per slot")
    return pages
