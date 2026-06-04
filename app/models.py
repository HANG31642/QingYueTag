# -*- coding: utf-8 -*-
"""Data models for the LoRA Dataset Tool."""
import os
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ImageItem:
    """Represents a single image file with its labels."""
    name: str
    base_name: str
    file_path: str
    txt_path: Optional[str] = None
    labels: List[str] = field(default_factory=list)
    _loaded: bool = False

    def ensure_labels(self):
        if self._loaded: return
        self._loaded = True
        if not self.txt_path: return
        try:
            with open(self.txt_path, "r", encoding="utf-8-sig") as f:
                self.labels = [t.strip() for t in f.read().split(",") if t.strip()]
        except: pass
    thumbnail_path: Optional[str] = None  # cache


class TreeNode:
    """Node in the directory tree."""
    def __init__(self, name: str, path: str, parent: Optional['TreeNode'] = None):
        self.name = name
        self.path = path
        self.parent = parent
        self.children: List['TreeNode'] = []
        self.images: List[ImageItem] = []
        self._total_images: Optional[int] = None

    def add_child(self, child: 'TreeNode'):
        child.parent = self
        self.children.append(child)

    @property
    def total_images(self) -> int:
        if self._total_images is None:
            self._total_images = len(self.images) + sum(c.total_images for c in self.children)
        return self._total_images

    def get_all_images(self) -> List[ImageItem]:
        result = list(self.images)
        for c in self.children:
            result.extend(c.get_all_images())
        return result

    def invalidate_cache(self):
        self._total_images = None
        for c in self.children:
            c.invalidate_cache()


# Common image format extensions
IMAGE_EXTS = {
    '.jpg', '.jpeg', '.jpe', '.jfif',
    '.png', '.webp', '.bmp', '.dib',
    '.tif', '.tiff', '.gif', '.avif',
    '.heic', '.heif', '.jp2', '.j2k',
}
