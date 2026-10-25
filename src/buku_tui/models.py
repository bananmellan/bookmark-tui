from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BookmarkRef:
    """One bookmark, as shown in the list.

    `index` is the buku database index — the stable identity used for
    `buku -o <index>`. The cache stores only non-sensitive metadata:
    index, title, url, tags and description.
    """

    index: int
    url: str
    title: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "url": self.url,
            "title": self.title,
            "tags": list(self.tags),
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, raw) -> "BookmarkRef":
        if not isinstance(raw, dict):
            raise ValueError("bookmark ref must be an object")
        index = raw.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or index < 1:
            raise ValueError("bookmark ref requires a positive integer index")
        url = str(raw.get("url") or "")
        if not url:
            raise ValueError("bookmark ref requires a url")
        tags_raw = raw.get("tags")
        tags = (
            tuple(str(t) for t in tags_raw if isinstance(t, str) and t)
            if isinstance(tags_raw, list)
            else ()
        )
        return cls(
            index=index,
            url=url,
            title=str(raw.get("title") or ""),
            tags=tags,
            description=str(raw.get("description") or ""),
        )
