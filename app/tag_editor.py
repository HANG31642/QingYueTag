# -*- coding: utf-8 -*-
"""Tag editor — per-image tag groups, flat/group modes, batch operations."""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLabel, QListWidget, QListWidgetItem, QLineEdit,
    QFrame, QMenu, QInputDialog, QMessageBox, QFileDialog,
    QApplication, QSpinBox, QComboBox, QSplitter,
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QColor, QPixmap, QIcon
from .models import ImageItem
import json, os

# 翻译字典：从 trans_dict.json 加载（英文→中文）
import os as _os_lib

_TRANS_DICT_PATH = _os_lib.path.join(_os_lib.path.dirname(_os_lib.path.dirname(_os_lib.path.abspath(__file__))), "trans_dict.json")

def _load_trans_dict():
    """加载翻译字典（英文→中文）以及反向字典（中文→英文）"""
    en2cn = {}
    cn2en = {}
    if _os_lib.path.isfile(_TRANS_DICT_PATH):
        try:
            with open(_TRANS_DICT_PATH, 'r', encoding='utf-8') as f:
                en2cn = json.load(f)
                cn2en = {v: k for k, v in en2cn.items()}
        except: pass
    return en2cn, cn2en

def _save_trans_pair(en_word: str, cn_word: str):
    """追加一个翻译对到字典文件"""
    try:
        current = {}
        if _os_lib.path.isfile(_TRANS_DICT_PATH):
            with open(_TRANS_DICT_PATH, 'r', encoding='utf-8') as f:
                current = json.load(f)
        current[en_word] = cn_word
        with open(_TRANS_DICT_PATH, 'w', encoding='utf-8') as f:
            json.dump(current, f, ensure_ascii=False, indent=2, sort_keys=True)
    except: pass

TRANS, TRANS_REV = _load_trans_dict()


class TagEditorWidget(QWidget):
    dirty_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._images = []; self._all_imgs = []; self._selected = set()
        self._dirty = False; self._scope_all = False; self._current_img = None
        self._tag_mode = "flat"; self._tag_groups = {}
        self._clipboard = []; self._filter_tag = None; self._undo_stack = []; self._redo_stack = []
        self._stats = []

        # 外层布局，确保 QSplitter 正确填充
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        ml = QSplitter(Qt.Horizontal)
        ml.setHandleWidth(3)
        outer.addWidget(ml)

        # === Col2: Dataset thumbnails ===
        c2 = QFrame(); c2.setFrameShape(QFrame.StyledPanel); c2.setMinimumWidth(80)
        c2l = QVBoxLayout(c2); c2l.setContentsMargins(4, 4, 4, 4); c2l.setSpacing(4)
        c2l.addWidget(QLabel("数据集图片"))
        self._img_count_label = QLabel(""); self._img_count_label.setStyleSheet("font-size:10px;color:#888;")
        c2l.addWidget(self._img_count_label)
        self._img_list = QListWidget(); self._img_list.setIconSize(QSize(48,48))
        self._img_list.setSpacing(2); self._img_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._img_list.itemClicked.connect(self._on_img_click)
        c2l.addWidget(self._img_list, 1)
        ml.addWidget(c2)

        # === Col3: Selected image tags ===
        c3 = QFrame(); c3.setFrameShape(QFrame.StyledPanel); c3.setMinimumWidth(100)
        c3l = QVBoxLayout(c3); c3l.setContentsMargins(4, 4, 4, 4)
        self._col3_label = QLabel("选中图片标签"); c3l.addWidget(self._col3_label)
        self._cur_tag_list = QListWidget(); self._cur_tag_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._cur_tag_list.customContextMenuRequested.connect(self._tag_context_menu)
        c3l.addWidget(self._cur_tag_list)
        ml.addWidget(c3)

        # === Col4: Single-image operations ===
        c4 = QFrame(); c4.setFrameShape(QFrame.StyledPanel); c4.setMinimumWidth(120)
        c4l = QVBoxLayout(c4); c4l.setContentsMargins(4, 4, 4, 4); c4l.setSpacing(4)
        c4l.addWidget(QLabel("单图操作"))
        self._tag_input = QLineEdit(); self._tag_input.setPlaceholderText("输入标签名..."); c4l.addWidget(self._tag_input)
        # 翻译辅助区域
        trans_row1 = QHBoxLayout()
        self._trans_direction = QComboBox()
        self._trans_direction.addItems(["中→英", "英→中", "日→英", "任意→英"])
        self._trans_direction.setMaximumWidth(85)
        trans_row1.addWidget(self._trans_direction)
        self._trans_method = QComboBox()
        self._trans_method.addItems(["本地词典", "大模型API", "在线翻译"])
        self._trans_method.setMaximumWidth(85)
        # 从设置读取默认翻译方式
        from .image_grid import SETTINGS
        method_map = {'local': 0, 'llm': 1, 'online': 2}
        self._trans_method.setCurrentIndex(method_map.get(SETTINGS.get('trans_method', 'local'), 0))
        trans_row1.addWidget(self._trans_method)
        btn_translate = QPushButton("🌐 翻译")
        btn_translate.clicked.connect(self._do_translate)
        trans_row1.addWidget(btn_translate)
        c4l.addLayout(trans_row1)
        # 翻译结果 + 应用范围
        trans_row2 = QHBoxLayout()
        self._trans_result = QLabel("")
        self._trans_result.setStyleSheet("color:#4a9;font-size:11px;")
        self._trans_result.setWordWrap(True)
        trans_row2.addWidget(self._trans_result, 1)
        self._trans_apply = QComboBox()
        self._trans_apply.addItems(["当前图片", "选中图片", "本层全部"])
        self._trans_apply.setMaximumWidth(80)
        self._trans_apply.setToolTip("翻译后自动应用到此范围")
        trans_row2.addWidget(self._trans_apply)
        c4l.addLayout(trans_row2)
        btn_add = QPushButton("➕ 添加"); btn_add.clicked.connect(self._add_tag_current); c4l.addWidget(btn_add)
        btn_clear = QPushButton("🗑 清空"); btn_clear.clicked.connect(self._clear_current); c4l.addWidget(btn_clear)
        btn_copy = QPushButton("📋 复制"); btn_copy.clicked.connect(self._copy_current); c4l.addWidget(btn_copy)
        btn_paste = QPushButton("📌 粘贴"); btn_paste.clicked.connect(self._paste_current); c4l.addWidget(btn_paste)
        c4l.addWidget(QLabel("标签管理:"))
        btn_export = QPushButton("📤 导出"); btn_export.clicked.connect(self._export_tags); c4l.addWidget(btn_export)
        btn_import = QPushButton("📥 导入"); btn_import.clicked.connect(self._import_tags); c4l.addWidget(btn_import)
        # BooruDatasetTagManager 风格标签管理按钮
        btn_replace = QPushButton("🔄 批量替换"); btn_replace.clicked.connect(self.batch_replace_tags); c4l.addWidget(btn_replace)
        btn_dedup = QPushButton("♻ 去重"); btn_dedup.clicked.connect(self.deduplicate_tags); c4l.addWidget(btn_dedup)
        btn_sort = QPushButton("🔤 排序"); btn_sort.clicked.connect(self.sort_tags); c4l.addWidget(btn_sort)
        btn_merge = QPushButton("🔗 合并"); btn_merge.clicked.connect(self.merge_tags); c4l.addWidget(btn_merge)
        btn_retrans = QPushButton("🌐 重新翻译"); btn_retrans.clicked.connect(self._retranslate_all); c4l.addWidget(btn_retrans)
        c4l.addStretch()
        ml.addWidget(c4)

        # === Col5: Tag statistics ===
        c5 = QFrame(); c5.setFrameShape(QFrame.StyledPanel)
        c5l = QVBoxLayout(c5); c5l.setContentsMargins(4, 4, 4, 4); c5l.setSpacing(4)
        h5 = QHBoxLayout(); h5.addWidget(QLabel("标签统计"))
        self._scope_btn = QPushButton("📁 仅本层"); self._scope_btn.setCheckable(True)
        self._scope_btn.toggled.connect(self._on_scope); h5.addWidget(self._scope_btn)
        c5l.addLayout(h5)
        self._stat_search = QLineEdit(); self._stat_search.setPlaceholderText("搜索...")
        self._stat_search.textChanged.connect(self._filter_stats); c5l.addWidget(self._stat_search)
        self._stat_list = QListWidget()
        self._stat_list.itemClicked.connect(lambda it: self._add_tag_to_editor(it.data(Qt.UserRole)))
        self._stat_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._stat_list.customContextMenuRequested.connect(self._stat_context_menu)
        c5l.addWidget(self._stat_list)
        ml.addWidget(c5)

        # === Col6: Tag editor (flat/group) ===
        c6 = QFrame(); c6.setFrameShape(QFrame.StyledPanel)
        c6l = QVBoxLayout(c6); c6l.setContentsMargins(4, 4, 4, 4); c6l.setSpacing(6)

        # Mode switch + select
        top = QHBoxLayout()
        self._mode_btn = QPushButton("📋 平铺"); self._mode_btn.setCheckable(True)
        self._mode_btn.toggled.connect(self._on_mode); top.addWidget(self._mode_btn)
        self._sel_count = QLabel(""); self._sel_count.setStyleSheet("font-size:10px;color:#888;")
        top.addWidget(self._sel_count); top.addStretch()
        btn_all = QPushButton("全选"); top.addWidget(btn_all)
        btn_all.clicked.connect(lambda: self._select_all(True))
        btn_none = QPushButton("取消"); top.addWidget(btn_none)
        btn_none.clicked.connect(lambda: self._select_all(False))
        c6l.addLayout(top)

        # Group list (visible in group mode)
        self._group_widget = QWidget()
        gl = QVBoxLayout(self._group_widget); gl.setContentsMargins(0, 0, 0, 0); gl.setSpacing(4)
        gh = QHBoxLayout(); gh.addWidget(QLabel("组:"))
        self._group_list = QListWidget()
        self._group_list.setMinimumHeight(40)  # 保留最小高度，移除最大限制
        self._group_list.currentRowChanged.connect(self._on_group_select)
        gh.addWidget(self._group_list, 1)
        btn_ng = QPushButton("+"); btn_ng.setMaximumWidth(28); btn_ng.clicked.connect(self._new_group); gh.addWidget(btn_ng)
        btn_rn = QPushButton("✎"); btn_rn.setMaximumWidth(28); btn_rn.clicked.connect(self._rename_group); gh.addWidget(btn_rn)
        btn_dg = QPushButton("×"); btn_dg.setMaximumWidth(28); btn_dg.clicked.connect(self._del_group); gh.addWidget(btn_dg)
        gl.addLayout(gh); self._group_widget.setVisible(False)

        # 垂直分割器：组列表 ↔ 编辑器（可拖拽调整大小）
        self._group_edit_splitter = QSplitter(Qt.Vertical)
        self._group_edit_splitter.addWidget(self._group_widget)
        self._edit = QTextEdit(); self._edit.setFont(QFont("Microsoft YaHei", 11))
        self._edit.setPlaceholderText("tag1, tag2, ...")
        self._edit.setContextMenuPolicy(Qt.CustomContextMenu)
        self._edit.customContextMenuRequested.connect(self._edit_context_menu)
        self._group_edit_splitter.addWidget(self._edit)
        self._group_edit_splitter.setSizes([60, 300])
        c6l.addWidget(self._group_edit_splitter, 1)

        # Apply buttons
        ab = QHBoxLayout(); ab.addWidget(QLabel("应用到:"))
        for t, lbl in [("selected","🎯选中"),("direct","📁本层"),("all","📂全部")]:
            b = QPushButton(lbl); b.clicked.connect(lambda _,tt=t: self._apply(tt)); ab.addWidget(b)
        c6l.addLayout(ab)

        # 批量管理组标签区域（分组模式下：将整个标签组添加/移除到图片）
        self._batch_group_widget = QWidget()
        bgl = QVBoxLayout(self._batch_group_widget); bgl.setContentsMargins(0, 6, 0, 0); bgl.setSpacing(4)
        bgl.addWidget(QLabel("📦 批量管理整个标签组:"))
        bg_row1 = QHBoxLayout()
        bg_row1.addWidget(QLabel("操作组:"))
        self._batch_target_group = QComboBox()
        self._batch_target_group.setToolTip("选择要批量添加/移除的整个标签组")
        bg_row1.addWidget(self._batch_target_group, 1)
        bgl.addLayout(bg_row1)
        bg_row2 = QHBoxLayout()
        bg_row2.addWidget(QLabel("应用到:"))
        self._batch_scope_combo = QComboBox()
        self._batch_scope_combo.addItems(["当前图片", "选中图片", "当前文件夹", "含子文件夹"])
        bg_row2.addWidget(self._batch_scope_combo, 1)
        bgl.addLayout(bg_row2)
        bg_row3 = QHBoxLayout()
        btn_batch_add_group = QPushButton("➕ 添加整个组")
        btn_batch_add_group.clicked.connect(self._batch_add_group_tag)
        bg_row3.addWidget(btn_batch_add_group)
        btn_batch_remove_group = QPushButton("➖ 移除整个组")
        btn_batch_remove_group.clicked.connect(self._batch_remove_group_tag)
        bg_row3.addWidget(btn_batch_remove_group)
        bgl.addLayout(bg_row3)
        c6l.addWidget(self._batch_group_widget)
        self._batch_group_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self._batch_group_widget.customContextMenuRequested.connect(self._batch_group_context_menu)
        self._batch_group_widget.setVisible(False)  # 仅分组模式显示

        # Undo/Redo/Save
        ub = QHBoxLayout()
        for act in [("↩ 撤销", self._undo), ("↪ 重做", self._redo), ("💾 保存", self._save_all)]:
            b = QPushButton(act[0]); b.clicked.connect(act[1]); ub.addWidget(b)
        ub.addStretch(); c6l.addLayout(ub)
        ml.addWidget(c6)

        # 设置各列初始宽度（从左到右：缩略图列、标签列、操作列、统计列、编辑列）
        ml.setSizes([120, 150, 140, 200, 390])

    # ===== API =====
    def set_strip(self, strip): strip.image_selected.connect(lambda img: setattr(self, '_current_img', img) or self._show_current())

    def set_scope(self, direct, all_rec):
        self._images = list(direct); self._all_imgs = list(all_rec)
        self._selected.clear(); self._scope_all = False; self._filter_tag = None
        self._scope_btn.setChecked(False); self._scope_btn.setText("📁 仅本层")
        self._apply_scope()

    def set_images(self, images):
        self._images = list(images); self._all_imgs = list(images)
        self._selected.clear(); self._scope_btn.setVisible(False); self._filter_tag = None
        self._apply_scope()

    def show_no_scope(self, total):
        self._images.clear(); self._all_imgs.clear(); self._selected.clear()
        self._stat_list.clear(); self._edit.clear(); self._cur_tag_list.clear()
        self._img_list.clear(); self._sel_count.setText(f"⚠ 无直接图片（{total}张在子文件夹中）")

    def _imgs(self): return self._all_imgs if self._scope_all else self._images

    def _apply_scope(self):
        imgs = self._imgs()
        for img in imgs: img.ensure_labels()
        self._rebuild_stats(imgs); self._update_sel_label(); self._rebuild_img_list()

    def _on_scope(self, checked):
        self._scope_all = checked
        self._scope_btn.setText("📂 含子" if checked else "📁 仅本层")
        self._selected.clear(); self._filter_tag = None; self._apply_scope()

    # ===== Mode switch =====
    def _on_mode(self, checked):
        self._tag_mode = "group" if checked else "flat"
        self._mode_btn.setText("📂 分组" if checked else "📋 平铺")
        self._group_widget.setVisible(checked)
        self._batch_group_widget.setVisible(checked)  # 同步显示批量管理区域
        if checked and self._current_img:
            self._load_img_groups(self._current_img)
            self._sync_batch_group_combo()
        elif not checked and self._current_img:
            flat = set()
            for gt in self._tag_groups.values(): flat.update(gt)
            self._edit.setPlainText(", ".join(sorted(flat)))

    # ===== Col2: Image list =====
    def _rebuild_img_list(self):
        self._img_list.clear(); imgs = self._imgs()
        filtered = imgs
        if self._filter_tag: filtered = [img for img in imgs if self._filter_tag in img.labels]
        self._img_count_label.setText(f"{len(filtered)}/{len(imgs)} 张")
        for i, img in enumerate(filtered):
            idx = imgs.index(img)
            pix = QPixmap(img.file_path)
            icon = QIcon(pix.scaled(48,48,Qt.KeepAspectRatio,Qt.SmoothTransformation) if not pix.isNull() else QPixmap(48,48))
            it = QListWidgetItem(icon, img.name[:18]); it.setData(Qt.UserRole, idx)
            if idx in self._selected: it.setBackground(QColor("#533483"))
            self._img_list.addItem(it)

    def _on_img_click(self, item):
        idx = item.data(Qt.UserRole); imgs = self._imgs()
        if idx < 0 or idx >= len(imgs): return
        ctrl = QApplication.keyboardModifiers() & Qt.ControlModifier
        if ctrl:
            if idx in self._selected: self._selected.discard(idx)
            else: self._selected.add(idx)
        else: self._selected = {idx}
        self._current_img = imgs[idx]; self._update_sel_label()
        self._rebuild_img_list(); self._show_current()

    def _select_all(self, all_sel):
        self._selected = set(range(len(self._images))) if all_sel else set()
        self._update_sel_label(); self._rebuild_img_list()

    # ===== Col3: Show tags =====
    def _show_current(self):
        if not self._current_img:
            self._cur_tag_list.clear(); return
        img = self._current_img; img.ensure_labels()
        self._cur_tag_list.clear()

        if self._tag_mode == "group":
            # 分组显示模式：组名作为标题，组内标签缩进
            self._load_img_groups(img)
            grouped_set = set()
            for gn, gt in self._tag_groups.items():
                if gt:
                    # 组名标题行
                    group_item = QListWidgetItem(f"📂 {gn}")
                    group_item.setFlags(group_item.flags() & ~Qt.ItemIsSelectable)  # 组名不可选
                    font = group_item.font(); font.setBold(True)
                    group_item.setFont(font)
                    group_item.setForeground(QColor("#e94560"))
                    self._cur_tag_list.addItem(group_item)
                    grouped_set.update(gt)
                    # 组内标签（缩进显示）
                    for t in gt:
                        cn = TRANS.get(t, "")
                        txt = f"    {t}"
                        if cn: txt += f"  [{cn}]"
                        tag_item = QListWidgetItem(txt)
                        tag_item.setData(Qt.UserRole, t)
                        self._cur_tag_list.addItem(tag_item)
            # 未分组的独立标签
            remaining = [t for t in img.labels if t not in grouped_set and t not in self._tag_groups]
            if remaining:
                sep_item = QListWidgetItem("📋 未分组")
                sep_item.setFlags(sep_item.flags() & ~Qt.ItemIsSelectable)
                font = sep_item.font(); font.setBold(True)
                sep_item.setFont(font)
                sep_item.setForeground(QColor("#888"))
                self._cur_tag_list.addItem(sep_item)
                for t in remaining:
                    cn = TRANS.get(t, "")
                    txt = f"    {t}"
                    if cn: txt += f"  [{cn}]"
                    tag_item = QListWidgetItem(txt)
                    tag_item.setData(Qt.UserRole, t)
                    self._cur_tag_list.addItem(tag_item)
        else:
            # 通用平铺显示模式
            for t in img.labels:
                cn = TRANS.get(t, TRANS.get(t.lower(), ""))
                txt = f"{t}  [{cn}]" if cn else t
                tag_item = QListWidgetItem(txt)
                tag_item.setData(Qt.UserRole, t)
                self._cur_tag_list.addItem(tag_item)
            self._edit.setPlainText(", ".join(img.labels))

    def _load_img_groups(self, img):
        """Parse per-image groups from .txt — 兼容旧格式和新混排格式"""
        img.ensure_labels()
        groups = {}
        if not img.labels:
            self._tag_groups = groups
            self._refresh_group_list()
            return

        if img.txt_path and os.path.isfile(img.txt_path):
            try:
                with open(img.txt_path, 'r', encoding='utf-8-sig') as f:
                    content = f.read()
                # 先尝试解析旧格式 #组名: 标签
                if content.strip().startswith('#'):
                    for line in content.split('\n'):
                        line = line.strip()
                        if line.startswith('#') and ':' in line:
                            gn = line.split(':', 1)[0].strip('#').strip()
                            gt = [t.strip() for t in line.split(':', 1)[1].split(',') if t.strip()]
                            groups[gn] = gt
                # 再尝试解析主标签格式 组名, tag1, tag2（每组一行，换行分隔）
                if not groups:
                    for line in content.split('\n'):
                        line = line.strip()
                        if line and not line.startswith('#') and ',' in line and ':' not in line:
                            parts = [t.strip() for t in line.split(',') if t.strip()]
                            if parts:
                                gn = parts[0]
                                gt = parts[1:] if len(parts) > 1 else []
                                if gn not in groups:
                                    groups[gn] = gt
                                else:
                                    groups[gn].extend(gt)
                # 否则按新混排格式解析：组名是标签列表中已知的组名
                if not groups and self._tag_groups:
                    all_tags = [t.strip() for t in content.replace('\n', ',').split(',') if t.strip()]
                    current_group = None
                    for t in all_tags:
                        if t in self._tag_groups:
                            # 这是一个组名，切换到该组
                            current_group = t
                            if t not in groups:
                                groups[t] = []
                        elif current_group:
                            groups[current_group].append(t)
            except: pass

        if not groups and img.labels:
            # 全新图片：用全局组名匹配标签中的组名
            if self._tag_groups:
                all_labels = list(img.labels)
                current_group = None
                for t in all_labels:
                    if t in self._tag_groups:
                        current_group = t
                        if t not in groups:
                            groups[t] = []
                    elif current_group:
                        groups[current_group].append(t)
            # 如果还是空的，用默认分组
            if not groups:
                groups = {"角色":[],"服装":[],"背景":[],"其他":[]}
                for t in img.labels:
                    if any(k in t for k in ['girl','boy','man','woman','hair','eye','face','head','ear','tail','cat','dog','fox']):
                        groups["角色"].append(t)
                    elif any(k in t for k in ['dress','skirt','shirt','uniform','jacket','coat','hat','glasses','glove','shoe','sock','swim','ribbon','bow','tie','hoodie','sweater','kimono','jeans']):
                        groups["服装"].append(t)
                    elif any(k in t for k in ['background','outdoor','indoor','night','day','city','forest','sky','ocean','mountain','field','tree','flower','beach','water']):
                        groups["背景"].append(t)
                    else: groups["其他"].append(t)
            groups = {k:v for k,v in groups.items() if v}
        if not groups: groups = {"默认": []}
        self._tag_groups = groups
        self._refresh_group_list()
        if self._tag_groups: self._group_list.setCurrentRow(0)

    # ===== Col4: Single-image ops =====
    def _do_translate(self):
        """翻译标签名：翻译完成后按选择的范围自动应用到图片"""
        tag = self._tag_input.text().strip()
        if not tag:
            self._trans_result.setText("请先输入标签名")
            return
        direction = self._trans_direction.currentText()
        method_text = self._trans_method.currentText()

        method_map = {"本地词典": "local", "大模型API": "llm", "在线翻译": "online"}
        method = method_map.get(method_text, "local")

        translated = None
        if method == 'local':
            translated = self._translate_local(tag, direction)
        elif method == 'llm':
            translated = self._translate_llm(tag, direction)
        elif method == 'online':
            translated = self._translate_online(tag, direction)

        if not translated:
            return

        # 翻译成功，显示结果并填入输入框
        self._trans_result.setText(f"✅ {tag} → {translated}")
        self._tag_input.setText(translated)

        # 自动按选择的应用范围添加标签到图片
        apply_scope = self._trans_apply.currentText()
        imgs = []
        if apply_scope == "当前图片":
            if self._current_img:
                imgs = [self._current_img]
        elif apply_scope == "选中图片":
            imgs = [self._imgs()[i] for i in self._selected if i < len(self._imgs())]
        elif apply_scope == "本层全部":
            imgs = list(self._images)

        if imgs:
            self._save_undo()
            count = 0
            for img in imgs:
                img.ensure_labels()
                if translated not in img.labels:
                    img.labels.append(translated)
                    count += 1
            self._mark_dirty()
            self._apply_scope()
            self._show_current()
            self._trans_result.setText(f"✅ {tag} → {translated} （已添加到 {count} 张图片）")

    def _translate_local(self, tag: str, direction: str) -> str:
        """本地词典翻译（精确匹配），返回翻译结果或None"""
        if direction in ("中→英", "日→英", "任意→英"):
            result = TRANS_REV.get(tag, "")
            if result:
                return result
            self._trans_result.setText(f"❌ 词典中未找到「{tag}」")
            return None
        else:  # 英→中
            result = TRANS.get(tag, "")
            if result:
                return result
            self._trans_result.setText(f"❌ 词典中未找到「{tag}」")
            return None

    def _translate_llm(self, tag: str, direction: str) -> str:
        """大模型API翻译，返回翻译结果或None（从设置读取完整API配置）"""
        from .image_grid import SETTINGS
        from PySide6.QtWidgets import QInputDialog
        api_key = SETTINGS.get('api_key', '')
        endpoint = SETTINGS.get('api_endpoint', 'https://api.openai.com/v1/chat/completions')
        model = SETTINGS.get('api_model', 'gpt-4o')
        # 自动补全端点路径：base_url 后面补上 /v1/chat/completions
        endpoint = endpoint.rstrip('/')
        if not endpoint.endswith('chat/completions'):
            endpoint += '/v1/chat/completions'
        print(f"[翻译API] 开始翻译: tag={tag!r}, direction={direction!r}")
        print(f"[翻译API] 端点: {endpoint}, 模型: {model}, Key: {api_key[:10]}...")
        if not api_key:
            api_key, ok = QInputDialog.getText(self, "大模型翻译", "输入API Key:", text="sk-")
            if not ok or not api_key.strip():
                print("[翻译API] 用户取消输入API Key")
                return None
        if not endpoint:
            print("[翻译API] 端点为空，中止")
            self._trans_result.setText("❌ 请在设置中配置API端点")
            return None
        self._trans_result.setText("⏳ 翻译中...")
        try:
            import requests
            lang_map = {"中→英": ("中文", "英文"), "英→中": ("英文", "中文"),
                        "日→英": ("日文", "英文"), "任意→英": ("任意语言", "英文")}
            sl, tl = lang_map.get(direction, ("", "英文"))
            system_prompt = (
                "你是一个专业的AI绘画标签翻译器。你的唯一任务是把输入的标签名从一种语言翻译成另一种语言。"
                "直接返回翻译结果，不要添加任何解释、标点符号、换行或额外文字。只需一个词或短语。"
            )
            user_prompt = f"把这个{sl}标签翻译成{tl}（只输出翻译结果）：{tag}"
            payload = {"model": model,
                       "messages": [
                           {"role": "system", "content": system_prompt},
                           {"role": "user", "content": user_prompt}
                       ],
                       "max_tokens": 50, "temperature": 0.1}
            print(f"[翻译API] 请求体: {payload}")
            resp = requests.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=15
            )
            print(f"[翻译API] HTTP状态码: {resp.status_code}")
            print(f"[翻译API] 响应原始文本(头200): {resp.text[:200]}")
            result = resp.json()
            if "error" in result:
                err_msg = result['error'].get('message', str(result['error']))
                print(f"[翻译API] 返回错误: {err_msg}")
                self._trans_result.setText(f"❌ API错误: {err_msg[:60]}")
                return None
            # 兼容 OpenAI / 通义千问 / 其他格式
            choices = result.get("choices")
            if not choices:
                choices = result.get("output", {}).get("choices")
                print(f"[翻译API] 尝试兼容路径 output.choices: {choices}")
            if choices and len(choices) > 0:
                translated = choices[0].get("message", {}).get("content", "").strip()
                print(f"[翻译API] 原始翻译结果: {translated!r}")
                # 清理可能的额外前缀
                for prefix in ["翻译结果：", "翻译：", "译文：", "输出："]:
                    if translated.startswith(prefix):
                        translated = translated[len(prefix):].strip()
                if translated:
                    print(f"[翻译API] 最终翻译: {translated!r}")
                    return translated
            print(f"[翻译API] 未能解析翻译结果，完整响应: {result}")
            self._trans_result.setText(f"❌ 翻译失败，请检查API配置")
            return None
        except Exception as e:
            print(f"[翻译API] 异常: {e}")
            self._trans_result.setText(f"❌ API错误: {str(e)[:60]}")
            return None

    def _translate_online(self, tag: str, direction: str) -> str:
        """在线翻译（Google Translate 免费接口），返回翻译结果或None"""
        self._trans_result.setText("⏳ 翻译中...")
        print(f"[在线翻译] 开始: tag={tag!r}, direction={direction!r}")
        try:
            import requests
            lang_map = {"中→英": ("zh-CN", "en"), "英→中": ("en", "zh-CN"),
                        "日→英": ("ja", "en"), "任意→英": ("auto", "en")}
            sl, tl = lang_map.get(direction, ("auto", "en"))
            url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={sl}&tl={tl}&dt=t&q={requests.utils.quote(tag)}"
            resp = requests.get(url, timeout=10)
            print(f"[在线翻译] HTTP状态码: {resp.status_code}")
            result = resp.json()
            translated = result[0][0][0]
            return translated
        except Exception as e:
            self._trans_result.setText(f"❌ 翻译失败: {str(e)[:60]}")
            return None

    def _add_tag_current(self):
        tag = self._tag_input.text().strip()
        if not tag or not self._current_img: return
        self._current_img.ensure_labels()
        if tag not in self._current_img.labels: self._current_img.labels.append(tag)
        self._tag_input.clear(); self._show_current(); self._rebuild_stats(self._imgs()); self._mark_dirty()

    def _clear_current(self):
        if not self._current_img: return
        if QMessageBox.question(self, "确认", "清空当前图片所有标签?") != QMessageBox.Yes: return
        self._current_img.labels.clear(); self._show_current(); self._rebuild_stats(self._imgs()); self._mark_dirty()

    def _copy_current(self):
        if self._current_img: self._current_img.ensure_labels(); self._clipboard = list(self._current_img.labels)

    def _paste_current(self):
        if not self._clipboard: return
        mode = QMessageBox.question(self, "粘贴", "覆盖(=Yes)还是追加(=No)?", QMessageBox.Yes|QMessageBox.No)
        if mode == QMessageBox.Yes: self._current_img.labels = list(self._clipboard)
        else:
            for t in self._clipboard:
                if t not in self._current_img.labels: self._current_img.labels.append(t)
        self._show_current(); self._rebuild_stats(self._imgs()); self._mark_dirty()

    # ===== Col5: Stats =====
    def _rebuild_stats(self, images):
        tc = {}
        for img in images:
            for t in img.labels: tc[t] = tc.get(t, 0) + 1
        self._stats = sorted(tc.items(), key=lambda x: -x[1]); self._filter_stats("")

    def _filter_stats(self, text):
        fl = text.lower(); self._stat_list.clear()
        for tag, cnt in self._stats:
            if fl and fl not in tag.lower(): continue
            cn = TRANS.get(tag, TRANS.get(tag.lower(), "")); txt = f"{tag} ({cnt})"
            if cn: txt += f"  [{cn}]"
            self._stat_list.addItem(QListWidgetItem(txt))

    def _add_tag_to_editor(self, tag):
        if not tag: return
        if self._tag_mode == "group":
            row = self._group_list.currentRow()
            if row >= 0:
                key = list(self._tag_groups.keys())[row]
                if tag not in self._tag_groups[key]: self._tag_groups[key].append(tag)
                self._edit.setPlainText(", ".join(self._tag_groups[key]))
        else:
            text = self._edit.toPlainText()
            tags = [t.strip() for t in text.replace("\n",",").split(",") if t.strip()]
            if tag not in tags: tags.append(tag)
            self._edit.setPlainText(", ".join(tags))

    def _stat_context_menu(self, pos):
        it = self._stat_list.itemAt(pos)
        if not it: return
        tag = it.data(Qt.UserRole)
        # 如果 UserRole 为空，从 item 文本中提取标签名（去掉计数 " (12)" 后缀）
        if not tag:
            raw = it.text().strip()
            # 格式：标签名 (计数) 或 标签名
            if " (" in raw and raw.endswith(")"):
                tag = raw[:raw.rindex(" (")].strip()
            else:
                tag = raw
        if not tag or tag == "None":
            return
        menu = QMenu()
        menu.addAction("🔍 筛选含此标签的图片", lambda: self._filter_by_tag(tag))
        self._add_trans_menu(menu, tag)
        menu.addSeparator()
        menu.addAction("✏ 重命名", lambda: self._rename_global(tag))
        menu.addAction("❌ 全局删除", lambda: self._delete_global(tag))
        menu.exec(self._stat_list.viewport().mapToGlobal(pos))

    def _tag_context_menu(self, pos):
        it = self._cur_tag_list.itemAt(pos)
        if not it: return
        # 分组模式下标签文本前有缩进空格，需 strip
        raw = it.text().strip()
        # 检测是否为组名标题行（以 📂 开头）
        if raw.startswith("📂 ") or raw.startswith("📋 "):
            group_name = raw[2:].strip()  # 去掉 "📂 " 前缀
            self._group_context_menu(group_name, pos)
            return
        # 提取纯标签名（去掉中译部分 [中文]）
        tag = raw.split("  [")[0] if "  [" in raw else raw
        # 如果 item 有 UserRole 数据，优先使用（分组模式下 setData 了）
        if it.data(Qt.UserRole):
            tag = it.data(Qt.UserRole)
        menu = QMenu()
        menu.addAction("× 删除此标签", lambda: self._del_tag_from_current(tag))
        menu.addAction("✏ 编辑", lambda: self._edit_tag(tag))
        menu.addSeparator()
        self._add_trans_menu(menu, tag)
        # 移动到组子菜单（仅在分组模式下显示）
        if self._tag_mode == "group" and self._tag_groups:
            move_menu = menu.addMenu("📂 移动到组")
            selected_row = self._group_list.currentRow()
            for idx, (gname, gtags) in enumerate(self._tag_groups.items()):
                action = move_menu.addAction(f"{'● ' if idx == selected_row else '  '}{gname}")
                action.triggered.connect(lambda checked, t=tag, gn=gname: self._move_tag_to_group(t, gn))
        menu.exec(self._cur_tag_list.viewport().mapToGlobal(pos))

    def _group_context_menu(self, group_name: str, pos):
        """分组标题行的右键菜单：翻译组名+翻译组内标签"""
        menu = QMenu()
        # 翻译组名本身
        if group_name != "未分组":
            self._add_trans_menu(menu, group_name)
            menu.addSeparator()
        # 翻译组内所有标签
        if group_name in self._tag_groups:
            gtags = self._tag_groups[group_name]
            if gtags:
                trans_menu = menu.addMenu(f"🌐 翻译「{group_name}」组内标签")
                trans_menu.addAction(f"翻译为中文", lambda: self._batch_translate_group_for("cn", group_name))
                trans_menu.addAction(f"翻译为英文", lambda: self._batch_translate_group_for("en", group_name))
        menu.exec(self._cur_tag_list.viewport().mapToGlobal(pos))

    def _batch_translate_group_for(self, direction: str, group_name: str):
        """指定组名的批量翻译（用于右键菜单）"""
        # 临时切换到目标组
        prev = self._batch_target_group.currentText()
        idx = self._batch_target_group.findText(group_name)
        if idx >= 0:
            self._batch_target_group.setCurrentIndex(idx)
        self._batch_translate_group(direction)
        # 恢复原来的选择
        if prev and prev != group_name:
            idx = self._batch_target_group.findText(prev)
            if idx >= 0:
                self._batch_target_group.setCurrentIndex(idx)

    def _edit_context_menu(self, pos):
        """Col6 编辑器右键菜单（中文）+ 翻译选中的文本"""
        menu = QMenu()
        # 基础编辑操作（中文）
        menu.addAction("↩ 撤销", self._edit.undo)
        menu.addAction("↪ 重做", self._edit.redo)
        menu.addSeparator()
        menu.addAction("✂ 剪切", self._edit.cut)
        menu.addAction("📋 复制", self._edit.copy)
        menu.addAction("📌 粘贴", self._edit.paste)
        menu.addAction("🗑 删除", lambda: self._edit.textCursor().removeSelectedText())
        menu.addSeparator()
        menu.addAction("📄 全选", self._edit.selectAll)
        # 翻译选中文本
        selected = self._edit.textCursor().selectedText().strip()
        if selected:
            tags = [t.strip() for t in selected.replace("\n", ",").split(",") if t.strip()]
            if tags:
                menu.addSeparator()
                if len(tags) == 1:
                    self._add_trans_menu(menu, tags[0])
                else:
                    trans_menu = menu.addMenu(f"🌐 翻译选中的 {len(tags)} 个标签")
                    trans_menu.addAction("翻译为中文", lambda: self._translate_selected_tags(tags, "cn"))
                    trans_menu.addAction("翻译为英文", lambda: self._translate_selected_tags(tags, "en"))
        menu.exec(self._edit.mapToGlobal(pos))

    def _translate_selected_tags(self, tags: list, direction: str):
        """翻译编辑器中选中的多个标签：预览对照，确认后替换"""
        trans_map = {}
        api_dir = "英→中" if direction == "cn" else "中→英"
        for t in tags:
            tr = ""
            if direction == "cn":
                tr = TRANS.get(t, "")
                if not tr or tr == t:
                    tr = self._translate_tag_api(t, api_dir)
            else:
                tr = TRANS_REV.get(t, "")
                if not tr or tr == t:
                    tr = self._translate_tag_api(t, api_dir)
            if tr and tr != t:
                trans_map[t] = tr
        if not trans_map:
            QMessageBox.information(self, "提示", "选中的标签没有可翻译的结果")
            return
        # 预览对照
        preview = "\n".join(f"  {k} → {v}" for k, v in trans_map.items())
        if QMessageBox.question(self, "翻译预览",
            f"翻译对照如下：\n{preview}\n\n确定要替换吗？",
            QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        # 确认后替换
        text = self._edit.toPlainText()
        for old, new in trans_map.items():
            text = text.replace(old, new)
        self._edit.setPlainText(text)
        QMessageBox.information(self, "完成", f"已替换 {len(trans_map)} 个标签")

    def _filter_by_tag(self, tag):
        self._filter_tag = tag
        self._stat_search.setText(f"🔍 {tag}")
        self._rebuild_img_list()

    def _del_tag_from_current(self, tag):
        if not self._current_img: return
        self._current_img.labels = [t for t in self._current_img.labels if t != tag]
        self._show_current(); self._rebuild_stats(self._imgs()); self._mark_dirty()

    def _move_tag_to_group(self, tag: str, target_group: str):
        """将标签从当前组移动到目标组"""
        if not self._current_img:
            return
        # 从所有组中移除该标签
        for gtags in self._tag_groups.values():
            if tag in gtags:
                gtags.remove(tag)
        # 添加到目标组
        if tag not in self._tag_groups[target_group]:
            self._tag_groups[target_group].append(tag)
        # 刷新显示
        self._refresh_group_list()
        # 选中目标组并显示
        for idx, key in enumerate(self._tag_groups.keys()):
            if key == target_group:
                self._group_list.setCurrentRow(idx)
                break
        self._on_group_select(self._group_list.currentRow())
        self._mark_dirty()
        self._apply_scope()
        self._show_current()

    def _rename_global(self, old):
        new, ok = QInputDialog.getText(self, "重命名", f"{old} → ?")
        if not ok or not new.strip(): return
        new = new.strip()
        if QMessageBox.question(self, "确认", f"全部 {old} → {new}?") != QMessageBox.Yes: return
        for img in self._imgs(): img.ensure_labels(); img.labels = [new if t==old else t for t in img.labels]
        self._mark_dirty(); self._apply_scope(); self._show_current()

    def _delete_global(self, tag):
        if QMessageBox.question(self, "确认", f"从全部图片删除 {tag}?") != QMessageBox.Yes: return
        for img in self._imgs(): img.ensure_labels(); img.labels = [t for t in img.labels if t!=tag]
        self._mark_dirty(); self._apply_scope(); self._show_current()

    def _edit_tag(self, tag):
        new, ok = QInputDialog.getText(self, "编辑标签", "新值:", text=tag)
        if not ok or not new.strip(): return
        new = new.strip()
        for img in self._imgs(): img.ensure_labels(); img.labels = [new if t==tag else t for t in img.labels]
        self._mark_dirty(); self._apply_scope(); self._show_current()

    # ===== Col6: Tag groups (per-image) =====
    def _refresh_group_list(self):
        self._group_list.blockSignals(True); self._group_list.clear()
        for key, tags in self._tag_groups.items():
            self._group_list.addItem(f"{key} ({len(tags)})")
        self._group_list.blockSignals(False)
        # 同步批量管理的目标组下拉框
        if hasattr(self, '_batch_target_group'):
            self._sync_batch_group_combo()

    def _on_group_select(self, row):
        if row < 0 or row >= len(self._tag_groups): return
        key = list(self._tag_groups.keys())[row]
        self._edit.setPlainText(", ".join(self._tag_groups[key]))

    def _new_group(self):
        name, ok = QInputDialog.getText(self, "新建组", "组名:")
        if not ok or not name.strip(): return
        name = name.strip(); self._tag_groups[name] = []
        self._refresh_group_list()
        self._group_list.setCurrentRow(len(self._tag_groups)-1)

    def _rename_group(self):
        row = self._group_list.currentRow()
        if row < 0: return
        old_name = list(self._tag_groups.keys())[row]
        new_name, ok = QInputDialog.getText(self, "重命名组", f"将「{old_name}」改为:", text=old_name)
        if not ok or not new_name.strip() or new_name.strip() == old_name:
            return
        new_name = new_name.strip()
        # 保存旧组的标签，用新名重建
        tags = self._tag_groups.pop(old_name)
        self._tag_groups[new_name] = tags
        self._refresh_group_list()
        self._group_list.setCurrentRow(row)

    def _del_group(self):
        row = self._group_list.currentRow()
        if row < 0: return
        key = list(self._tag_groups.keys())[row]
        if QMessageBox.question(self, "确认", f"删除组 {key}？（组内标签不会被删除）") != QMessageBox.Yes: return
        del self._tag_groups[key]; self._refresh_group_list()

    # ===== Apply =====
    def _get_tags_from_editor(self):
        """Parse tags from editor based on current mode."""
        if self._tag_mode == "group":
            tags = set()
            for gt in self._tag_groups.values(): tags.update(gt)
            return tags
        else:
            text = self._edit.toPlainText()
            return set(t.strip() for t in text.replace("\n",",").split(",") if t.strip())

    def _apply(self, target):
        tags = self._get_tags_from_editor()
        if not tags: return
        if target == "selected" and self._selected:
            imgs = [self._images[i] for i in self._selected if i < len(self._images)]
        elif target == "direct" or (target == "selected" and not self._selected):
            imgs = list(self._images)
        elif target == "all": imgs = list(self._all_imgs)
        else: return
        for img in imgs:
            img.ensure_labels()
            for t in tags:
                if t not in img.labels: img.labels.append(t)
        self._mark_dirty(); self._apply_scope(); self._show_current()

    def _update_sel_label(self):
        n = len(self._selected); t = len(self._images)
        self._sel_count.setText(f"已选{n}/{t}" if n else f"共{t}张")

    def _mark_dirty(self):
        if not self._dirty: self._dirty = True; self.dirty_changed.emit(True)

    # ===== Save / Export / Import =====
    _save_format = "default"  # 类级变量：记录保存格式偏好

    def _format_tags(self, img: ImageItem, fmt: str = "default") -> str:
        """按指定格式生成标签文本
        - default: 逗号分隔，所有标签一行（组名混排在标签中）
        - group: 主标签格式，每组一行 组名, tag1, tag2（逗号分隔，换行分組）
        """
        img.ensure_labels()
        if fmt == "group" and self._tag_mode == "group" and self._tag_groups:
            lines = []
            grouped_tags = set()
            for gn, gt in self._tag_groups.items():
                if gt:
                    lines.append(f"{gn}, {', '.join(gt)}")
                    grouped_tags.update(gt)
            # 未分组的独立标签放最后一行
            remaining = [t for t in img.labels if t not in grouped_tags and t not in self._tag_groups]
            if remaining:
                lines.append(", ".join(remaining))
            return "\n".join(lines) if lines else ", ".join(img.labels)
        else:
            # 默认：逗号分隔
            if self._tag_mode == "group" and self._tag_groups:
                ordered = []
                grouped_tags = set()
                for gn, gt in self._tag_groups.items():
                    if gt:
                        ordered.append(gn)
                        ordered.extend(gt)
                        grouped_tags.update(gt)
                for t in img.labels:
                    if t not in grouped_tags and t not in self._tag_groups:
                        ordered.append(t)
                return ", ".join(ordered) if ordered else ""
            return ", ".join(img.labels)

    def _save_all(self):
        # 弹出格式选择
        fmt, ok = QInputDialog.getItem(self, "保存格式", "选择标签保存格式:",
            ["默认（逗号分隔一行）", "主标签（每组换行,逗号分隔）"], 0, False)
        if not ok:
            return
        fmt_key = "group" if "主标签" in fmt else "default"
        TagEditorWidget._save_format = fmt_key

        saved = 0
        for img in self._imgs(): img.ensure_labels()
        for img in self._imgs():
            tp = img.txt_path or img.file_path.rsplit(".",1)[0]+".txt"
            try:
                content = self._format_tags(img, fmt_key)
                with open(tp, "w", encoding="utf-8") as f: f.write(content)
                saved += 1
            except: pass
        self._dirty = False; self.dirty_changed.emit(False)
        QMessageBox.information(self, "保存完成", f"已保存 {saved} 个文件")

    def _export_tags(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出", "tags.json", "JSON(*.json);;CSV(*.csv);;TXT(*.txt)")
        if not path: return

        # JSON/CSV 保持原样，TXT 支持格式选择
        if path.endswith('.json'):
            data = {}
            for img in self._imgs(): img.ensure_labels(); data[img.file_path] = img.labels
            with open(path,'w',encoding='utf-8') as f: json.dump(data,f,ensure_ascii=False,indent=2)
            QMessageBox.information(self,"完成",f"导出{len(data)}条")
        elif path.endswith('.csv'):
            data = {}
            for img in self._imgs(): img.ensure_labels(); data[img.file_path] = img.labels
            with open(path,'w',encoding='utf-8') as f:
                for fp,tags in data.items(): f.write(f"{fp},{','.join(tags)}\n")
            QMessageBox.information(self,"完成",f"导出{len(data)}条")
        elif path.endswith('.txt'):
            fmt, ok = QInputDialog.getItem(self, "导出格式", "选择标签导出格式:",
                ["默认（逗号分隔一行）", "主标签（每组换行,逗号分隔）"], 0, False)
            if not ok: return
            fmt_key = "group" if "主标签" in fmt else "default"
            with open(path,'w',encoding='utf-8') as f:
                for img in self._imgs():
                    img.ensure_labels()
                    content = self._format_tags(img, fmt_key)
                    f.write(f"{img.file_path}: {content}\n")
            QMessageBox.information(self,"完成",f"导出{len(self._imgs())}条")

    def _import_tags(self):
        path, _ = QFileDialog.getOpenFileName(self,"导入","","JSON(*.json);;CSV(*.csv)")
        if not path: return
        mode = QMessageBox.question(self,"模式","覆盖(=Yes)/追加(=No)?",QMessageBox.Yes|QMessageBox.No)
        data = {}
        try:
            if path.endswith('.csv'):
                with open(path,'r',encoding='utf-8') as f:
                    for line in f:
                        parts = line.strip().split(',',1)
                        if len(parts)==2: data[parts[0]]=[t.strip() for t in parts[1].split(',') if t.strip()]
            else:
                with open(path,'r',encoding='utf-8') as f: data = json.load(f)
        except: QMessageBox.warning(self,"错误","无法解析文件"); return
        for img in self._imgs(): img.ensure_labels()
        for fp, tags in data.items():
            for img in self._imgs():
                if img.file_path == fp or fp in img.file_path:
                    if mode == QMessageBox.Yes: img.labels = tags
                    else:
                        for t in tags:
                            if t not in img.labels: img.labels.append(t)
        self._mark_dirty(); self._apply_scope(); self._show_current()
        QMessageBox.information(self,"完成",f"导入{len(data)}条")

    # ===== Undo/Redo =====
    def _save_undo(self):
        # Clear redo stack when new action is performed
        self._redo_stack.clear()
        state = {}
        for img in self._imgs(): img.ensure_labels(); state[img.file_path] = list(img.labels)
        self._undo_stack = self._undo_stack[-50:] + [state]

    def _undo(self):
        if not self._undo_stack: return
        # Save current state to redo stack before undo
        current_state = {}
        for img in self._imgs(): img.ensure_labels(); current_state[img.file_path] = list(img.labels)
        self._redo_stack.append(current_state)
        # Restore undo state
        state = self._undo_stack.pop()
        for img in self._imgs():
            if img.file_path in state: img.labels = list(state[img.file_path])
        self._mark_dirty(); self._apply_scope(); self._show_current()

    def _redo(self):
        if not self._redo_stack: return
        # Save current state to undo stack before redo
        current_state = {}
        for img in self._imgs(): img.ensure_labels(); current_state[img.file_path] = list(img.labels)
        self._undo_stack.append(current_state)
        # Restore redo state
        state = self._redo_stack.pop()
        for img in self._imgs():
            if img.file_path in state: img.labels = list(state[img.file_path])
        self._mark_dirty(); self._apply_scope(); self._show_current()

    # ===== 标签翻译 =====
    def _add_trans_menu(self, menu: QMenu, tag: str):
        """构建翻译子菜单：已有翻译只读查看，替换操作独立"""
        if not tag or tag == "None":
            return
        trans_menu = menu.addMenu("🌐 翻译此标签")
        found = False
        # 英→中
        cn = TRANS.get(tag, "")
        if cn and cn != tag:
            info_item = trans_menu.addAction(f"📖 中文: {cn}")
            info_item.setEnabled(False)  # 只读显示
            trans_menu.addAction(f"🔄 替换为「{cn}」", lambda: self._translate_replace(tag, cn))
            found = True
        # 中→英
        en = TRANS_REV.get(tag, "")
        if en and en != tag:
            info_item = trans_menu.addAction(f"📖 英文: {en}")
            info_item.setEnabled(False)  # 只读显示
            trans_menu.addAction(f"🔄 替换为「{en}」", lambda: self._translate_replace(tag, en))
            found = True
        if found:
            trans_menu.addSeparator()
        trans_menu.addAction("🔍 查询中文翻译", lambda: self._translate_show(tag, "cn"))
        trans_menu.addAction("🔍 查询英文翻译", lambda: self._translate_show(tag, "en"))

    def _translate_show(self, tag: str, direction: str):
        """查询翻译结果并显示，不替换"""
        # 先查词典
        if direction == "cn":
            tr = TRANS.get(tag, "")
            if not tr or tr == tag:
                tr = self._translate_tag_api(tag, "英→中")
        else:
            tr = TRANS_REV.get(tag, "")
            if not tr or tr == tag:
                tr = self._translate_tag_api(tag, "中→英")
        if tr and tr != tag:
            QMessageBox.information(self, "翻译对照",
                f"原词: {tag}\n翻译: {tr}\n\n该翻译仅作参考，未修改标签。\n如需替换请点击「🔄 替换」按钮或右键菜单中的替换选项。")
        else:
            QMessageBox.information(self, "翻译对照",
                f"「{tag}」: 未找到翻译结果")

    def _translate_replace(self, tag: str, translated: str):
        """用指定翻译直接替换标签"""
        if QMessageBox.question(self, "确认替换",
            f"将「{tag}」替换为「{translated}」？") != QMessageBox.Yes:
            return
        self._save_undo()
        count = 0
        for img in self._imgs():
            img.ensure_labels()
            if tag in img.labels:
                img.labels = [translated if t == tag else t for t in img.labels]
                count += 1
        self._mark_dirty(); self._apply_scope(); self._show_current()
        QMessageBox.information(self, "完成", f"已将 {count} 张图片中的「{tag}」替换为「{translated}」")

    def _save_api_translation(self, en_word: str, cn_word: str):
        """将API翻译结果追加到词典文件，下次可以直接用本地词典命中"""
        if en_word and cn_word and en_word != cn_word:
            # 英→中
            if any('\u4e00' <= c <= '\u9fff' for c in cn_word):
                _save_trans_pair(en_word, cn_word)
                TRANS[en_word] = cn_word
                TRANS_REV[cn_word] = en_word
            # 中→英
            elif any('\u4e00' <= c <= '\u9fff' for c in en_word):
                _save_trans_pair(cn_word, en_word)
                TRANS[cn_word] = en_word
                TRANS_REV[en_word] = cn_word

    def _translate_tag_api(self, tag: str, direction: str = "英→中") -> str:
        """使用配置的API翻译标签，返回翻译结果或空字符串（翻译结果自动存入词典）"""
        from .image_grid import SETTINGS
        method = SETTINGS.get('trans_method', 'local')
        print(f"[翻译调度] tag={tag!r}, direction={direction!r}, method={method!r}")
        if method == 'local':
            return ""
        result = None
        if method == 'llm':
            result = self._translate_llm(tag, direction) or ""
        elif method == 'online':
            result = self._translate_online(tag, direction) or ""
        if result:
            self._save_api_translation(tag, result)
        return result

    def _translate_single_tag(self, tag: str):
        """翻译单个标签为中文（词典优先，词典无则调用API）"""
        if not tag or tag == "None":
            return
        # 1. 精确匹配词典
        translated = TRANS.get(tag, "")
        if translated:
            pass
        elif tag in TRANS_REV:
            translated = tag  # 已是中文
        else:
            # 2. 词典没有，调用API翻译
            translated = self._translate_tag_api(tag, "英→中")
            if not translated:
                QMessageBox.information(self, "提示",
                    f"词典中未找到「{tag}」的翻译，API翻译也未配置或失败\n"
                    "请在设置中配置翻译方式（大模型API或在线翻译）")
                return

        if translated == tag:
            QMessageBox.information(self, "提示", f"「{tag}」已是中文，无需翻译")
            return

        if QMessageBox.question(self, "确认翻译",
            f"将「{tag}」翻译为「{translated}」并替换？") != QMessageBox.Yes:
            return

        self._save_undo()
        count = 0
        for img in self._imgs():
            img.ensure_labels()
            if tag in img.labels:
                img.labels = [translated if t == tag else t for t in img.labels]
                count += 1
        self._mark_dirty(); self._apply_scope(); self._show_current()
        QMessageBox.information(self, "完成", f"已将 {count} 张图片中的「{tag}」替换为「{translated}」")

    def _translate_single_tag_rev(self, tag: str):
        """翻译单个标签为英文（词典优先，词典无则调用API）"""
        if not tag or tag == "None":
            return
        # 1. 精确匹配词典（中文→英文）
        translated = TRANS_REV.get(tag, "")
        if translated:
            pass
        elif tag in TRANS:
            translated = tag  # 已是英文
        else:
            # 2. 词典没有，调用API翻译
            translated = self._translate_tag_api(tag, "中→英")
            if not translated:
                QMessageBox.information(self, "提示",
                    f"词典中未找到「{tag}」的翻译，API翻译也未配置或失败")
                return

        if translated == tag:
            QMessageBox.information(self, "提示", f"「{tag}」已是英文，无需翻译")
            return

        if QMessageBox.question(self, "确认翻译",
            f"将「{tag}」翻译为「{translated}」并替换？") != QMessageBox.Yes:
            return

        self._save_undo()
        count = 0
        for img in self._imgs():
            img.ensure_labels()
            if tag in img.labels:
                img.labels = [translated if t == tag else t for t in img.labels]
                count += 1
        self._mark_dirty(); self._apply_scope(); self._show_current()
        QMessageBox.information(self, "完成", f"已将 {count} 张图片中的「{tag}」替换为「{translated}」")

    def _retranslate_all(self):
        """重新翻译所有标签为中文：预览翻译对照，确认后才替换"""
        from .image_grid import SETTINGS
        use_api = SETTINGS.get('trans_method', 'local') != 'local'

        # 第一步：构建翻译映射
        trans_map = {}
        api_cache = {}
        for img in self._imgs():
            img.ensure_labels()
            for t in img.labels:
                if not t or t == "None" or t in trans_map:
                    continue
                cn = TRANS.get(t, "")
                if cn and cn != t:
                    trans_map[t] = cn
                elif use_api and t not in TRANS_REV:
                    tr = api_cache.get(t) or self._translate_tag_api(t, "英→中")
                    api_cache[t] = tr
                    if tr and tr != t:
                        trans_map[t] = tr

        if not trans_map:
            QMessageBox.information(self, "提示", "没有可翻译的标签")
            return

        # 显示预览
        preview = "\n".join(f"  {k} → {v}" for k, v in list(trans_map.items())[:20])
        if len(trans_map) > 20:
            preview += f"\n  ... 共 {len(trans_map)} 个翻译对照"
        if QMessageBox.question(self, "翻译预览",
            f"找到 {len(trans_map)} 个可翻译的标签：\n{preview}\n\n确定要全部替换吗？\n（点击「否」则仅查看，不修改标签）",
            QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return

        self._save_undo()
        total_replaced = 0
        for img in self._imgs():
            img.ensure_labels()
            new_labels = []
            changed = False
            for t in img.labels:
                if t in trans_map:
                    new_labels.append(trans_map[t])
                    changed = True
                else:
                    new_labels.append(t)
            if changed:
                img.labels = new_labels
                total_replaced += 1
        self._mark_dirty(); self._apply_scope(); self._show_current()
        QMessageBox.information(self, "完成", f"已替换 {total_replaced} 张图片的标签")

    def save_all(self): self._save_all()

    # ===== 批量管理组标签 =====
    def _batch_group_context_menu(self, pos):
        """批量管理区域的右键菜单"""
        menu = QMenu()
        # 当前选中的组
        current_group = self._batch_target_group.currentText()
        if current_group:
            menu.addAction(f"➕ 添加「{current_group}」到当前图片", lambda: self._batch_apply_group("add", "当前图片"))
            menu.addAction(f"➕ 添加「{current_group}」到选中图片", lambda: self._batch_apply_group("add", "选中图片"))
            menu.addAction(f"➕ 添加「{current_group}」到本层全部", lambda: self._batch_apply_group("add", "本层全部"))
            menu.addSeparator()
            menu.addAction(f"➖ 从当前图片移除「{current_group}」", lambda: self._batch_apply_group("remove", "当前图片"))
            menu.addAction(f"➖ 从选中图片移除「{current_group}」", lambda: self._batch_apply_group("remove", "选中图片"))
            menu.addAction(f"➖ 从本层全部移除「{current_group}」", lambda: self._batch_apply_group("remove", "本层全部"))
            menu.addSeparator()
            trans_menu = menu.addMenu("🌐 翻译组内标签")
            trans_menu.addAction(f"翻译「{current_group}」为中文", lambda: self._batch_translate_group("cn"))
            trans_menu.addAction(f"翻译「{current_group}」为英文", lambda: self._batch_translate_group("en"))
            menu.addSeparator()
        menu.addAction("➕ 新建标签组", self._new_group)
        if current_group:
            menu.addAction(f"✏ 重命名「{current_group}」", self._rename_group)
            menu.addAction(f"❌ 删除「{current_group}」", self._del_group)
        menu.exec(self._batch_group_widget.mapToGlobal(pos))

    def _batch_translate_group(self, direction: str):
        """翻译组内所有标签（cn=中文, en=英文），应用到所有图片中"""
        group_name = self._batch_target_group.currentText()
        if not group_name or group_name not in self._tag_groups:
            return
        gtags = self._tag_groups[group_name]
        if not gtags:
            QMessageBox.information(self, "提示", f"标签组「{group_name}」为空")
            return

        # 构建翻译映射（词典精确匹配+API兜底）
        trans_map = {}
        api_cache = {}
        for t in gtags:
            if direction == "cn":
                tr = TRANS.get(t, "")
                if tr and tr != t:
                    trans_map[t] = tr
                    continue
            else:
                tr = TRANS_REV.get(t, "")
                if tr and tr != t:
                    trans_map[t] = tr
                    continue
            # 词典没有，尝试API
            api_dir = "英→中" if direction == "cn" else "中→英"
            if t in api_cache:
                tr = api_cache[t]
            else:
                tr = self._translate_tag_api(t, api_dir)
                api_cache[t] = tr
            if tr and tr != t:
                trans_map[t] = tr

        if not trans_map:
            QMessageBox.information(self, "提示", f"组「{group_name}」中没有可翻译的标签")
            return

        verb = "中文" if direction == "cn" else "英文"
        preview = "\n".join(f"  {k} → {v}" for k, v in list(trans_map.items())[:10])
        if len(trans_map) > 10:
            preview += f"\n  ... 等共 {len(trans_map)} 个标签"
        if QMessageBox.question(self, "确认", f"将组「{group_name}」中 {len(trans_map)} 个标签翻译为{verb}并全局替换？\n\n{preview}") != QMessageBox.Yes:
            return

        self._save_undo()
        count = 0
        for img in self._imgs():
            img.ensure_labels()
            changed = False
            new_labels = []
            for t in img.labels:
                if t in trans_map:
                    new_labels.append(trans_map[t])
                    changed = True
                else:
                    new_labels.append(t)
            if changed:
                img.labels = new_labels
                count += 1
        self._mark_dirty(); self._apply_scope(); self._show_current()
        QMessageBox.information(self, "完成", f"已将组「{group_name}」翻译为{verb}，共影响 {count} 张图片")

    def _batch_apply_group(self, action: str, scope: str):
        """右键快捷批量操作：添加/移除整个组"""
        group_name = self._batch_target_group.currentText()
        if not group_name or group_name not in self._tag_groups:
            return
        gtags = self._tag_groups[group_name]
        if not gtags:
            QMessageBox.information(self, "提示", f"标签组「{group_name}」为空")
            return

        # 确定目标图片
        if scope == "当前图片":
            imgs = [self._current_img] if self._current_img else []
        elif scope == "选中图片":
            imgs = [self._imgs()[i] for i in self._selected if i < len(self._imgs())]
        else:  # 本层全部
            imgs = list(self._images)

        if not imgs:
            QMessageBox.information(self, "提示", f"没有目标图片（范围: {scope}）")
            return

        verb = "添加" if action == "add" else "移除"
        if QMessageBox.question(self, "确认", f"确定要{verb}标签组「{group_name}」（{len(gtags)}个标签）到{len(imgs)}张图片？") != QMessageBox.Yes:
            return

        self._save_undo()
        count = 0
        for img in imgs:
            img.ensure_labels()
            if action == "add":
                added = [t for t in gtags if t not in img.labels]
                if added:
                    img.labels.extend(added)
                    count += 1
            else:
                removed = [t for t in gtags if t in img.labels]
                if removed:
                    img.labels = [t for t in img.labels if t not in gtags]
                    count += 1
        self._mark_dirty(); self._apply_scope(); self._show_current()
        QMessageBox.information(self, "完成", f"已对 {count} 张图片完成「{verb}组」操作")

    def _sync_batch_group_combo(self):
        """同步批量管理的组下拉框"""
        current = self._batch_target_group.currentText()
        self._batch_target_group.blockSignals(True)
        self._batch_target_group.clear()
        for gn in self._tag_groups.keys():
            self._batch_target_group.addItem(gn)
        # 尝试恢复之前的选中项
        idx = self._batch_target_group.findText(current)
        if idx >= 0:
            self._batch_target_group.setCurrentIndex(idx)
        elif self._batch_target_group.count() > 0:
            self._batch_target_group.setCurrentIndex(0)
        self._batch_target_group.blockSignals(False)

    def _get_batch_scope_images(self) -> list:
        """获取批量操作的目标图片列表"""
        scope = self._batch_scope_combo.currentText()
        if scope == "当前图片":
            return [self._current_img] if self._current_img else []
        elif scope == "选中图片":
            return [self._imgs()[i] for i in self._selected if i < len(self._imgs())]
        elif scope == "当前文件夹":
            return list(self._images)
        elif scope == "含子文件夹":
            return list(self._all_imgs)
        return []

    def _batch_add_group_tag(self):
        """将整个标签组（组名+组内所有标签）批量添加到指定范围的图片"""
        group_name = self._batch_target_group.currentText()
        if not group_name or group_name not in self._tag_groups:
            QMessageBox.warning(self, "提示", "请先选择或创建一个组")
            return
        group_tags = self._tag_groups.get(group_name, [])
        if not group_tags:
            QMessageBox.warning(self, "提示", f"组「{group_name}」内没有标签")
            return

        imgs = self._get_batch_scope_images()
        if not imgs:
            QMessageBox.warning(self, "提示", "目标范围没有图片")
            return

        self._save_undo()
        count = 0
        tags_to_add = [group_name] + group_tags  # 组名 + 组内标签
        for img in imgs:
            img.ensure_labels()
            changed = False
            for t in tags_to_add:
                if t not in img.labels:
                    img.labels.append(t)
                    changed = True
            if changed:
                count += 1

        self._mark_dirty()
        self._apply_scope()
        self._show_current()
        QMessageBox.information(self, "完成",
            f"已将组「{group_name}」({len(tags_to_add)} 个标签) 添加到 {count} 张图片")

    def _batch_remove_group_tag(self):
        """从指定范围的图片中移除整个标签组（组名+组内标签）"""
        group_name = self._batch_target_group.currentText()
        if not group_name or group_name not in self._tag_groups:
            QMessageBox.warning(self, "提示", "请先选择一个组")
            return
        group_tags = self._tag_groups.get(group_name, [])
        tags_to_remove = [group_name] + group_tags

        imgs = self._get_batch_scope_images()
        if not imgs:
            QMessageBox.warning(self, "提示", "目标范围没有图片")
            return

        self._save_undo()
        count = 0
        for img in imgs:
            img.ensure_labels()
            removed_any = False
            for t in tags_to_remove:
                if t in img.labels:
                    img.labels.remove(t)
                    removed_any = True
            if removed_any:
                count += 1

        self._mark_dirty()
        self._apply_scope()
        self._show_current()
        QMessageBox.information(self, "完成",
            f"已从 {count} 张图片移除组「{group_name}」({len(tags_to_remove)} 个标签)")

    # ===== BooruDatasetTagManager 风格标签管理功能 =====

    def batch_replace_tags(self):
        """批量替换标签：输入旧标签→新标签（支持中→英翻译辅助）"""
        from PySide6.QtWidgets import QInputDialog
        # 第一步：输入要替换的标签
        old_tag, ok = QInputDialog.getText(self, "批量替换 - 步骤1/2", 
            "要替换的标签（支持中文，自动翻译为英文）:")
        if not ok or not old_tag.strip():
            return
        old_tag = old_tag.strip()
        
        # 翻译辅助：如果输入的是中文，查找对应英文
        suggested = old_tag
        cn_match = None
        # 先检查中文→英文
        if old_tag in TRANS_REV:
            cn_match = TRANS_REV[old_tag]
            suggested = cn_match
        # 再检查是否是英文（有对应中文）
        if old_tag in TRANS:
            suggested = old_tag  # 保持英文
        
        # 第二步：输入替换目标（默认显示翻译结果或原标签）
        hint = f"将「{old_tag}」替换为:"
        if cn_match and cn_match != old_tag:
            hint = f"将「{old_tag}」替换为（翻译: {old_tag}→{cn_match}）:"
        
        new_tag, ok = QInputDialog.getText(self, "批量替换 - 步骤2/2", hint, text=suggested)
        if not ok or not new_tag.strip():
            return
        new_tag = new_tag.strip()
        
        # 执行替换（用原始输入匹配标签，用新标签替换）
        search_tag = old_tag  # 默认用输入的
        # 如果输入中文且翻译存在，优先用中文搜索 + 英文替换
        # 同时也尝试用英文标签搜索
        search_tags = {old_tag}
        if cn_match:
            search_tags.add(cn_match)
        if old_tag in TRANS:
            # 输入的是英文，也加上中文搜索
            search_tags.add(TRANS[old_tag])
        
        self._save_undo()
        count = 0
        for img in self._imgs():
            img.ensure_labels()
            replaced = False
            for st in search_tags:
                if st in img.labels:
                    img.labels = [new_tag if t == st else t for t in img.labels]
                    replaced = True
            if replaced:
                count += 1
        self._mark_dirty(); self._apply_scope(); self._show_current()
        QMessageBox.information(self, "完成", f"已将 {count} 张图片中的「{old_tag}」替换为「{new_tag}」")

    def deduplicate_tags(self):
        """删除每张图片标签列表中的重复标签"""
        if QMessageBox.question(self, "确认", "删除当前范围内所有图片的重复标签？") != QMessageBox.Yes:
            return
        self._save_undo()
        count = 0
        for img in self._imgs():
            img.ensure_labels()
            seen = set()
            unique = []
            for t in img.labels:
                if t not in seen:
                    seen.add(t)
                    unique.append(t)
            if len(unique) != len(img.labels):
                img.labels = unique
                count += 1
        self._mark_dirty(); self._apply_scope(); self._show_current()
        QMessageBox.information(self, "完成", f"已对 {count} 张图片去重")

    def sort_tags(self):
        """按字母顺序排列每张图片的标签"""
        if QMessageBox.question(self, "确认", "按字母顺序排列当前范围内所有图片的标签？") != QMessageBox.Yes:
            return
        self._save_undo()
        for img in self._imgs():
            img.ensure_labels()
            img.labels.sort()
        self._mark_dirty(); self._apply_scope(); self._show_current()
        QMessageBox.information(self, "完成", f"已对 {len(self._imgs())} 张图片的标签排序")

    def merge_tags(self):
        """合并标签：将标签A合并到标签B（保留B，删除A）"""
        from PySide6.QtWidgets import QInputDialog
        tag_a, ok = QInputDialog.getText(self, "合并标签", "要被合并的标签（将被删除）:")
        if not ok or not tag_a.strip():
            return
        tag_b, ok = QInputDialog.getText(self, "合并标签", f"合并到标签（保留「{tag_a}」→）:", text=tag_a)
        if not ok or not tag_b.strip():
            return
        if tag_a.strip() == tag_b.strip():
            QMessageBox.warning(self, "提示", "两个标签相同，无需合并")
            return
        self._save_undo()
        count = 0
        for img in self._imgs():
            img.ensure_labels()
            if tag_a in img.labels:
                # 删除tag_a，如果tag_b不在列表中则添加
                img.labels = [t for t in img.labels if t != tag_a]
                if tag_b not in img.labels:
                    img.labels.append(tag_b)
                count += 1
        self._mark_dirty(); self._apply_scope(); self._show_current()
        QMessageBox.information(self, "完成", f"已将 {count} 张图片中的「{tag_a}」合并为「{tag_b}」")
