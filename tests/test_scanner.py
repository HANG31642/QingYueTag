# -*- coding: utf-8 -*-
"""Unit tests for directory scanner (scan_directory, _scan_dir)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tempfile
from app.scanner import scan_directory


def test_scan_empty_dir():
    """Test scanning an empty directory returns root with 0 images."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tree = scan_directory(tmpdir)
        assert tree.name == os.path.basename(tmpdir)
        assert tree.total_images == 0
        assert len(tree.children) == 0


def test_scan_single_level():
    """Test scanning a directory with only images (no subdirs)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create 3 image files and 1 txt file (not scanned)
        for i in range(3):
            img_path = os.path.join(tmpdir, f"img{i}.jpg")
            open(img_path, "a").close()
        txt_path = os.path.join(tmpdir, "labels.txt")
        open(txt_path, "a").close()
        
        tree = scan_directory(tmpdir)
        assert tree.total_images == 3
        assert len(tree.images) == 3
        assert len(tree.children) == 0
        # Check image names
        img_names = [img.name for img in tree.images]
        assert set(img_names) == {"img0.jpg", "img1.jpg", "img2.jpg"}


def test_scan_multi_level():
    """Test scanning a directory with nested subdirectories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Root has 1 image, sub1 has 2, sub2 has subsub with 3 + 1 image
        open(os.path.join(tmpdir, "root_img.jpg"), "a").close()
        
        sub1 = os.path.join(tmpdir, "sub1")
        os.mkdir(sub1)
        open(os.path.join(sub1, "sub1_1.jpg"), "a").close()
        open(os.path.join(sub1, "sub1_2.jpg"), "a").close()
        
        sub2 = os.path.join(tmpdir, "sub2")
        os.mkdir(sub2)
        open(os.path.join(sub2, "sub2_img.jpg"), "a").close()
        
        subsub = os.path.join(sub2, "subsub")
        os.mkdir(subsub)
        open(os.path.join(subsub, "ss1.webp"), "a").close()
        open(os.path.join(subsub, "ss2.png"), "a").close()
        open(os.path.join(subsub, "ss3.bmp"), "a").close()
        
        tree = scan_directory(tmpdir)
        # Total: root 1 + sub1 2 + sub2 (1 + subsub 3) = 1+2+4=7
        assert tree.total_images == 7
        assert len(tree.images) == 1
        assert len(tree.children) == 2  # sub1, sub2
        # Check sub2's total: 1 + 3 =4
        sub2_node = next(c for c in tree.children if c.name == "sub2")
        assert sub2_node.total_images == 4
        # Check subsub has 3
        subsub_node = sub2_node.children[0]
        assert subsub_node.total_images == 3


def test_scan_unsupported_format():
    """Test scanning skips non-image files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Non-image files: txt, pdf, exe
        open(os.path.join(tmpdir, "doc.pdf"), "a").close()
        open(os.path.join(tmpdir, "note.txt"), "a").close()
        open(os.path.join(tmpdir, "app.exe"), "a").close()
        open(os.path.join(tmpdir, "valid.jpg"), "a").close()
        
        tree = scan_directory(tmpdir)
        assert tree.total_images == 1
        assert tree.images[0].name == "valid.jpg"
