# -*- coding: utf-8 -*-
"""Unit tests for data models (TreeNode, ImageItem)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tempfile
from app.models import TreeNode, ImageItem


def test_image_item_lazy_labels():
    """Test ImageItem label lazy loading: initial empty, load from txt on demand."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a mock txt label file
        img_path = os.path.join(tmpdir, "test.jpg")
        txt_path = os.path.join(tmpdir, "test.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("1girl, smile, blush")
        
        # Create ImageItem with empty labels
        img = ImageItem(name="test.jpg", base_name="test", file_path=img_path, txt_path=txt_path)
        assert img.labels == []
        assert not img._loaded
        
        # Call ensure_labels to load
        img.ensure_labels()
        assert img.labels == ["1girl", "smile", "blush"]
        assert img._loaded
        
        # Second call should not change
        img.ensure_labels()
        assert img.labels == ["1girl", "smile", "blush"]


def test_image_item_no_txt():
    """Test ImageItem without txt file: labels remain empty."""
    with tempfile.TemporaryDirectory() as tmpdir:
        img_path = os.path.join(tmpdir, "test.jpg")
        # No txt path
        img = ImageItem(name="test.jpg", base_name="test", file_path=img_path, txt_path=None)
        img.ensure_labels()
        assert img.labels == []


def test_tree_node_total_images():
    """Test TreeNode total images calculation (lazy and pre-cached)."""
    # Create test structure: root → sub1 (2 images), sub2 (subsub (3 images) + 1 image)
    root = TreeNode(name="root", path="/root")
    sub1 = TreeNode(name="sub1", path="/root/sub1")
    sub1.images = [ImageItem("1.jpg", "1", "/root/sub1/1.jpg"), ImageItem("2.jpg", "2", "/root/sub1/2.jpg")]
    
    sub2 = TreeNode(name="sub2", path="/root/sub2")
    subsub = TreeNode(name="subsub", path="/root/sub2/subsub")
    subsub.images = [ImageItem("a.jpg", "a", "/root/sub2/subsub/a.jpg"), ImageItem("b.jpg", "b", "/root/sub2/subsub/b.jpg"), ImageItem("c.jpg", "c", "/root/sub2/subsub/c.jpg")]
    sub2.images = [ImageItem("x.jpg", "x", "/root/sub2/x.jpg")]
    sub2.children.append(subsub)
    
    root.children = [sub1, sub2]
    
    # Lazy calculation first
    assert root._total_images is None
    assert root.total_images == 6, "Expected total_images = 6"
    assert root._total_images == 6
    
    # Pre-calculate and test again
    assert root.total_images == 6
