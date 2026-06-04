"""Recursive directory scanner with threaded worker."""
import os
from typing import Optional
from PySide6.QtCore import QObject, Signal, Slot
from .models import TreeNode, ImageItem, IMAGE_EXTS


class ScanWorker(QObject):
    finished = Signal(object)
    progress = Signal(str)
    dir_found = Signal(object, int, int)  # (node, current_count, total_estimate)

    _cancel = False

    @Slot(str)
    def scan(self, dir_path: str):
        self._cancel = False
        try:
            tree = scan_directory(dir_path, self)
            self.finished.emit(tree)
        except Exception as e:
            self.finished.emit(None)

    def cancel(self):
        self._cancel = True


def scan_directory(root_path: str, worker=None) -> Optional[TreeNode]:
    """Recursively scan a directory and build a tree of images."""
    if not os.path.isdir(root_path):
        return None

    root_name = os.path.basename(root_path)
    root = TreeNode(root_name, root_path)

    try:
        _scan_dir(root_path, root, worker)
        root.total_images
        if worker:
            worker.dir_found.emit(root, root.total_images, root.total_images)
    except PermissionError:
        pass

    return root


def _scan_dir(dir_path: str, node: TreeNode, worker=None):
    """Scan a single directory, adding images and recursing into subdirs."""
    if worker and worker._cancel:
        return
    try:
        entries = os.scandir(dir_path)
    except PermissionError:
        return

    for entry in entries:
        try:
            if entry.is_dir(follow_symlinks=False):
                child = TreeNode(entry.name, entry.path)
                _scan_dir(entry.path, child, worker)
                if child.images or child.children:
                    node.add_child(child)
                    if worker:
                        worker.dir_found.emit(child, child.total_images, 0)

            elif entry.is_file(follow_symlinks=False):
                ext = os.path.splitext(entry.name)[1].lower()
                if ext in IMAGE_EXTS:
                    base = os.path.splitext(entry.name)[0]
                    txt_path = os.path.join(dir_path, base + '.txt')
                    if not os.path.isfile(txt_path): txt_path = None
                    img = ImageItem(
                        name=entry.name,
                        base_name=base,
                        file_path=entry.path,
                        txt_path=txt_path,
                        labels=[],
                    )
                    node.images.append(img)
        except OSError:
            continue
