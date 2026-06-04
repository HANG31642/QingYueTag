# -*- coding: utf-8 -*-
"""Batch processor for renaming, resizing, converting images and tags."""
import os
import shutil
from PIL import Image
from typing import List

# 备份根目录（项目根目录下的"备份"文件夹）
_BACKUP_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "备份")


class BatchRenamer:
    """批量重命名：支持多种命名模式"""
    MODE_PREFIX_NUM = "prefix_num"       # 自定义前缀_序号
    MODE_ORIG_NUM = "orig_num"           # 原名_序号
    MODE_PREFIX_DATE = "prefix_date"     # 自定义前缀_日期时间
    MODE_FOLDER_NUM = "folder_num"       # 文件夹名_序号

    def __init__(self, mode: str = "prefix_num", custom_text: str = "image",
                 start_num: int = 1, keep_ext: bool = True):
        self.mode = mode
        self.custom_text = custom_text.strip() or "image"
        self.start_num = start_num
        self.keep_ext = keep_ext

    def process(self, image_paths: List[str], backup_dir: str = None,
                progress_callback=None) -> List[dict]:
        results = []
        total = len(image_paths)

        from datetime import datetime
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_name = os.path.basename(os.path.dirname(image_paths[0])) if image_paths else "folder"

        sorted_imgs = sorted(image_paths)
        for count, img_path in enumerate(sorted_imgs):
            idx = count + self.start_num
            img_ext = os.path.splitext(img_path)[1].lower()
            base_name = os.path.splitext(os.path.basename(img_path))[0]

            if self.mode == "prefix_num":
                new_base = f"{self.custom_text}_{idx:03d}"
            elif self.mode == "orig_num":
                new_base = f"{base_name}_{idx:03d}"
            elif self.mode == "prefix_date":
                new_base = f"{self.custom_text}_{date_str}"
            elif self.mode == "folder_num":
                new_base = f"{folder_name}_{idx:03d}"
            else:
                new_base = f"{self.custom_text}_{idx:03d}"

            new_img_name = f"{new_base}{img_ext}" if self.keep_ext else f"{new_base}.{self.custom_text.lower()}"
            new_img_path = os.path.join(os.path.dirname(img_path), new_img_name)

            # 备份原文件（按所在文件夹名分组）
            if backup_dir:
                folder = os.path.basename(os.path.dirname(img_path)) or "root"
                dest_dir = os.path.join(backup_dir, folder)
                os.makedirs(dest_dir, exist_ok=True)
                shutil.copy2(img_path, os.path.join(dest_dir, os.path.basename(img_path)))
            os.rename(img_path, new_img_path)
            results.append({"old": img_path, "new": new_img_path, "type": "image"})

            # 同步重命名 .txt 标签文件
            label_old = os.path.splitext(img_path)[0] + ".txt"
            if os.path.exists(label_old):
                label_new = os.path.splitext(new_img_path)[0] + ".txt"
                if backup_dir:
                    folder = os.path.basename(os.path.dirname(label_old)) or "root"
                    dest_dir = os.path.join(backup_dir, folder)
                    os.makedirs(dest_dir, exist_ok=True)
                    shutil.copy2(label_old, os.path.join(dest_dir, os.path.basename(label_old)))
                os.rename(label_old, label_new)
                results.append({"old": label_old, "new": label_new, "type": "label"})

            if progress_callback:
                progress_callback(count + 1, total)

        return results


class BatchScaler:
    """Batch resize images, keep aspect ratio."""
    def __init__(self, width: int, height: int, keep_ratio: bool = True):
        self.width = width
        self.height = height
        self.keep_ratio = keep_ratio

    def process(self, image_paths: List[str], backup_dir: str = None,
                progress_callback=None) -> List[dict]:
        results = []
        total = len(image_paths)
        for count, img_path in enumerate(image_paths):
            # 备份（按所在文件夹名分组）
            if backup_dir:
                folder = os.path.basename(os.path.dirname(img_path)) or "root"
                dest_dir = os.path.join(backup_dir, folder)
                os.makedirs(dest_dir, exist_ok=True)
                shutil.copy2(img_path, os.path.join(dest_dir, os.path.basename(img_path)))
            
            try:
                with Image.open(img_path) as img:
                    if self.keep_ratio:
                        # Calculate new size keeping aspect ratio
                        ratio = min(self.width / img.width, self.height / img.height)
                        new_size = (int(img.width * ratio), int(img.height * ratio))
                        resized = img.resize(new_size, Image.Resampling.LANCZOS)
                    else:
                        resized = img.resize((self.width, self.height), Image.Resampling.LANCZOS)
                    # Overwrite original (or save as new, here overwrite for simplicity)
                    resized.save(img_path, quality=95)
                    results.append({"path": img_path, "action": "resize", "status": "success"})
            except Exception as e:
                results.append({"path": img_path, "action": "resize", "status": "fail", "error": str(e)})
            if progress_callback:
                progress_callback(count + 1, total)
        
        return results


class BatchConverter:
    """Batch convert images to WebP format."""
    def __init__(self, quality: int = 80):
        self.quality = quality

    def process(self, image_paths: List[str], backup_dir: str = None, delete_original: bool = False,
                progress_callback=None) -> List[dict]:
        results = []
        total = len(image_paths)
        for count, img_path in enumerate(image_paths):
            ext = os.path.splitext(img_path)[1].lower()
            if ext == ".webp":
                results.append({"path": img_path, "action": "convert", "status": "skip", "reason": "already webp"})
                continue

            webp_path = os.path.splitext(img_path)[0] + ".webp"
            # 备份（按所在文件夹名分组）
            if backup_dir:
                folder = os.path.basename(os.path.dirname(img_path)) or "root"
                dest_dir = os.path.join(backup_dir, folder)
                os.makedirs(dest_dir, exist_ok=True)
                shutil.copy2(img_path, os.path.join(dest_dir, os.path.basename(img_path)))
            
            try:
                with Image.open(img_path) as img:
                    img.save(webp_path, "WEBP", quality=self.quality)
                results.append({"old": img_path, "new": webp_path, "type": "convert", "status": "success"})
                # Delete original if requested
                if delete_original:
                    os.remove(img_path)
                    results.append({"path": img_path, "action": "delete", "status": "success"})
                # Handle label file: if exists, no need to change, path stays same
            except Exception as e:
                results.append({"path": img_path, "action": "convert", "status": "fail", "error": str(e)})
            if progress_callback:
                progress_callback(count + 1, total)
        
        return results
