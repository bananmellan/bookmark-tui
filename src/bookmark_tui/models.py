"""Data model for a bookmark."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Bookmark:
    """One bookmark.

    `id` is a stable integer identity. `category` is the folder path
    (e.g. "food/recipes/vegetarian"), empty for uncategorized.
    """

    id: int
    url: str
    title: str = ""
    category: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Bookmark":
        if not isinstance(raw, dict):
            raise ValueError("bookmark must be an object")
        return cls(
            id=int(raw["id"]),
            url=str(raw.get("url") or ""),
            title=str(raw.get("title") or ""),
            category=str(raw.get("category") or ""),
        )
