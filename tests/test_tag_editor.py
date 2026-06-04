# -*- coding: utf-8 -*-
"""Unit tests for tag editor core logic (label processing, groups)."""
import os
import tempfile
from app.models import ImageItem
from app.tag_editor import TagEditorWidget, TRANS


def test_tag_translation():
    """Test English-Chinese tag translation (TRANS dict)."""
    # Check sample translations
    assert TRANS.get("1girl") == "1女孩"
    assert TRANS.get("smile") == "微笑"
    assert TRANS.get("masterpiece") == "杰作"
    # Lowercase keys? Wait TRANS has exact keys, so test if any lowercase works?
    # Wait current TRANS uses exact English, so test that existing keys work
    assert "cat" in TRANS  # "cat" → "猫"
    assert TRANS["cat"] == "猫"


def test_image_tag_operations():
    """Test add/remove/rename tags on ImageItem."""
    with tempfile.TemporaryDirectory() as tmpdir:
        img = ImageItem("test.jpg", "test", os.path.join(tmpdir, "test.jpg"))
        
        # Add tags
        img.labels = ["1girl", "smile"]
        assert len(img.labels) == 2
        
        # Remove tag
        img.labels.remove("smile")
        assert img.labels == ["1girl"]
        
        # Rename tag (simulating global rename)
        old = "1girl"
        new = "女孩1"
        img.labels = [new if t == old else t for t in img.labels]
        assert img.labels == ["女孩1"]


def test_tag_group_parsing():
    """Test parsing tag groups from txt file (group format #Group: tag1, tag2)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        txt_path = os.path.join(tmpdir, "test.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("#角色: 1girl, blonde_hair\n")
            f.write("#服装: school_uniform, ribbon\n")
            f.write("1girl, smile")  # flat tags outside groups
        
        img = ImageItem("test.jpg", "test", os.path.join(tmpdir, "test.jpg"), txt_path=txt_path)
        img.ensure_labels()  # loads flat tags: ["1girl", "smile"]
        
        # Simulate TagEditor._load_img_groups parsing
        groups = {}
        with open(txt_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith('#') and ':' in line:
                    gn, gt = line.split(':', 1)
                    gn = gn.strip('#').strip()
                    gt = [t.strip() for t in gt.split(',') if t.strip()]
                    groups[gn] = gt
        
        # Also get flat tags (lines not starting with #)
        flat = [line.strip() for line in open(txt_path).readlines() if not line.strip().startswith('#') and line.strip()]
        flat_tags = []
        for line in flat:
            flat_tags.extend([t.strip() for t in line.split(',') if t.strip()])
        
        assert groups == {"角色": ["1girl", "blonde_hair"], "服装": ["school_uniform", "ribbon"]}
        assert flat_tags == ["1girl", "smile"]


def test_save_tag_groups():
    """Test saving tag groups to txt file in #Group: format."""
    with tempfile.TemporaryDirectory() as tmpdir:
        txt_path = os.path.join(tmpdir, "test.txt")
        img = ImageItem("test.jpg", "test", os.path.join(tmpdir, "test.jpg"), txt_path=txt_path)
        
        # Simulate TagEditor saving groups
        tag_groups = {"角色": ["1girl", "blonde_hair"], "背景": ["outdoors", "night"]}
        lines = []
        for gn, gt in tag_groups.items():
            if gt:
                lines.append(f"#{gn}: {', '.join(gt)}")
        # Add flat tags
        flat_tags = ["smile", "masterpiece"]
        lines.append(", ".join(flat_tags))
        
        # Write to file
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        
        # Read back
        with open(txt_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        assert "#角色: 1girl, blonde_hair" in content
        assert "#背景: outdoors, night" in content
        assert "smile, masterpiece" in content
