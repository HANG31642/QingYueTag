# -*- coding: utf-8 -*-
"""Main window - the central application window."""
import os, sys
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QTreeWidget, QTreeWidgetItem,
    QFileDialog, QMessageBox, QLabel, QSplitter, QStatusBar,
    QToolBar, QLineEdit, QApplication, QFrame, QSizePolicy, QProgressBar,
)
from PySide6.QtCore import Qt, Signal, Slot, QSize, QThread, QTimer, QObject
from .models import TreeNode, ImageItem
from .scanner import scan_directory, ScanWorker
from .image_grid import VirtualImageGrid, MiniImageStrip, SettingsDialog, SETTINGS
from .tag_editor import TagEditorWidget
from .crop_editor import CropEditorWidget
from .infer_panel import InferPanelWidget
from .batch_processor import BatchRenamer, BatchScaler, BatchConverter
from .ai_chat import AIChatPanel
from .image_processor import ImageProcessorWidget

class BatchWorker(QObject):
    """离线线程批量操作 worker，通过 progress 信号更新进度"""
    progress = Signal(int, int)  # (current, total)
    finished = Signal(object)    # result
    error = Signal(str)

    def __init__(self, processor, method_name, args):
        super().__init__()
        self._processor = processor
        self._method = method_name
        self._args = args

    @Slot()
    def run(self):
        try:
            fn = getattr(self._processor, self._method)
            result = fn(*self._args, progress_callback=self._on_progress)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, current, total):
        self.progress.emit(current, total)


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("清月的打标工具")
        self.resize(1400, 900)
        self.setMinimumSize(1000, 700)

        self.tree_root: TreeNode = None
        self.current_node: TreeNode = None
        self.current_images: list = []        # all images for grid display
        self.current_scope: list = []         # direct images for tag operations
        self.processed_images: set = set()
        self.setup_ui()

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.btn_open = QPushButton("📂 打开数据集")
        self.btn_open.clicked.connect(self.on_open_dataset)
        toolbar.addWidget(self.btn_open)
        toolbar.addSeparator()
        self.btn_settings = QPushButton("⚙ 设置")
        self.btn_settings.clicked.connect(self.on_settings)
        toolbar.addWidget(self.btn_settings)
        self.btn_ai = QPushButton("🤖 问一问AI")
        self.btn_ai.clicked.connect(lambda: self.tab_widget.setCurrentIndex(4))
        toolbar.addWidget(self.btn_ai)
        toolbar.addSeparator()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 搜索...")
        self.search_input.setMaximumWidth(200)
        toolbar.addWidget(self.search_input)
        toolbar.addWidget(QLabel("  "))

        self.lbl_dataset = QLabel("")
        self.lbl_dataset.setStyleSheet("color: #888; font-size: 11px;")
        toolbar.addWidget(self.lbl_dataset)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)

        self.btn_save = QPushButton("✅ 已保存")
        self.btn_save.clicked.connect(self.on_save)
        toolbar.addWidget(self.btn_save)

        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        tree_panel = QWidget()
        tree_layout = QVBoxLayout(tree_panel)
        tree_layout.setContentsMargins(4, 4, 4, 4)
        tree_layout.addWidget(QLabel("📂 目录树"))

        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderHidden(True)
        self.tree_widget.setIndentation(16)
        self.tree_widget.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree_widget.itemClicked.connect(self.on_tree_click)
        self.tree_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_widget.customContextMenuRequested.connect(self._on_tree_context_menu)
        tree_layout.addWidget(self.tree_widget)
        splitter.addWidget(tree_panel)

        # 共享图片条（裁切/标签/反推三页共用，只有一份实例）
        self.shared_strip = MiniImageStrip()
        self.shared_strip.image_selected.connect(self._on_shared_strip_click)
        self.shared_strip.image_right_clicked.connect(self._on_image_context_menu)

        # 右侧面板：共享strip + tab页
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self.shared_strip)
        self.tab_widget = QTabWidget()
        self.tab_widget.setMovable(True)  # 允许拖拽调整顺序
        self.tab_widget.tabBar().tabMoved.connect(self._on_tab_moved)
        right_layout.addWidget(self.tab_widget, 1)
        splitter.addWidget(right_panel)

        self.image_grid = VirtualImageGrid()
        self.image_grid.image_double_clicked.connect(self.crop_load_image)
        self.image_grid.image_context_menu.connect(self._on_image_context_menu)

        # 数据集页面板
        dataset_panel = QWidget()
        dataset_layout = QVBoxLayout(dataset_panel)
        dataset_layout.setContentsMargins(4, 4, 4, 0)
        dataset_layout.setSpacing(4)
        ds_toolbar = QHBoxLayout()
        ds_toolbar.addWidget(QLabel("📁 数据集操作:"))
        btn_rename = QPushButton("✏️ 重命名"); btn_rename.clicked.connect(self.on_batch_rename)
        ds_toolbar.addWidget(btn_rename)
        btn_resize = QPushButton("📐 缩放"); btn_resize.clicked.connect(self.on_batch_resize)
        ds_toolbar.addWidget(btn_resize)
        btn_convert = QPushButton("🔄 格式转换"); btn_convert.clicked.connect(self.on_batch_convert)
        ds_toolbar.addWidget(btn_convert)
        ds_toolbar.addStretch()
        dataset_layout.addLayout(ds_toolbar)
        dataset_layout.addWidget(self.image_grid, 1)
        self.tab_widget.addTab(dataset_panel, "📁 数据集")

        # 裁切面板（不含strip，用共享条）
        crop_panel = QWidget()
        crop_layout = QVBoxLayout(crop_panel)
        crop_layout.setContentsMargins(0, 0, 0, 0)
        crop_layout.setSpacing(0)
        self.crop_editor = CropEditorWidget()
        self.crop_editor.exported.connect(self._on_crop_exported)
        crop_layout.addWidget(self.crop_editor)
        self.tab_widget.addTab(crop_panel, "✂️ 裁切")

        # 标签面板（不含strip，用共享条）
        label_panel = QWidget()
        label_layout = QVBoxLayout(label_panel)
        label_layout.setContentsMargins(0, 0, 0, 0)
        label_layout.setSpacing(0)
        self.tag_editor = TagEditorWidget()
        self.tag_editor.set_strip(self.shared_strip)
        label_layout.addWidget(self.tag_editor)
        self.tab_widget.addTab(label_panel, "🏷️ 标签")

        # 反推面板（不含strip，用共享条）
        infer_panel = QWidget()
        infer_layout = QVBoxLayout(infer_panel)
        infer_layout.setContentsMargins(0, 0, 0, 0)
        infer_layout.setSpacing(0)
        self.infer_panel = InferPanelWidget()
        infer_layout.addWidget(self.infer_panel)
        self.tab_widget.addTab(infer_panel, "🤖 反推")

        # AI 聊天面板
        self.ai_chat_panel = AIChatPanel()
        self.tab_widget.addTab(self.ai_chat_panel, "💬 问一问AI")

        self.image_processor = ImageProcessorWidget()
        self.tab_widget.addTab(self.image_processor, "🎨 图像处理")

        splitter.setSizes([220, 1100])

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._progress_bar = QProgressBar()
        self._progress_bar.setMaximumWidth(200)
        self._progress_bar.setMaximumHeight(16)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(False)
        self._progress_bar.setTextVisible(True)
        self.status_bar.addPermanentWidget(self._progress_bar)
        self.status_bar.showMessage("就绪 - 点击「打开数据集」开始")

    def on_open_dataset(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择数据集根目录")
        if not dir_path:
            return
        print(f"[APP] Opening: {dir_path}")
        self.status_bar.showMessage("扫描目录...")
        QApplication.processEvents()

        self._scanning = True

        # Scan in background thread
        self._scan_worker = ScanWorker()
        self._scan_thread = QThread()
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_worker.finished.connect(self._on_scan_done)
        self._scan_worker.dir_found.connect(self._on_dir_found)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_thread.started.connect(lambda: self._scan_worker.scan(dir_path))
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._scan_thread.start()

    def _on_dir_found(self, node, count, total):
        """扫描进度更新"""
        self.status_bar.showMessage(f"扫描中... 已找到 {node.total_images} 张图片")

    def _on_scan_progress(self, current, total):
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(int(current / total * 100) if total else 0)
        self._progress_bar.setFormat(f"{current}/{total}" if total else "")
        self.status_bar.showMessage(f"扫描中... {current}/{total}")

    def _on_scan_done(self, tree):
        self._scan_thread.quit()
        self._progress_bar.setVisible(False)
        if not tree:
            self.status_bar.showMessage("就绪")
            QMessageBox.warning(self, "错误", "目录为空或无法访问")
            return
        self.tree_root = tree
        print(f"[APP] Root: {tree.name}, children={len(tree.children)}, total_imgs={tree.total_images}")
        from .image_grid import MiniImageStrip
        MiniImageStrip._thumb_cache.clear()
        self._rebuild_tree()
        self.image_grid.clear()
        self._scanning = False
        self.status_bar.showMessage(f"完成: {tree.total_images} 张图片, {len(tree.children)} 个文件夹")
        self.lbl_dataset.setText(f"● {tree.name} ({tree.total_images}张)")
        # 自动导航到根节点（显示根目录的直接图片）
        root_item = self.tree_widget.topLevelItem(0)
        if root_item:
            self.tree_widget.setCurrentItem(root_item)
            self._navigate_to(root_item)

    def _rebuild_tree(self):
        """构建目录树：根节点作为顶级项，子文件夹递归展开"""
        self.tree_widget.clear()
        if not self.tree_root:
            return
        # 根节点本身也加入树（递归添加所有子节点）
        root_item = self._add_tree_item(self.tree_root, None)
        root_item.setExpanded(True)

    def _add_tree_item(self, node: TreeNode, parent):
        if parent is None:
            item = QTreeWidgetItem(self.tree_widget)
        else:
            item = QTreeWidgetItem(parent)
        item.setText(0, f"{node.name} ({node.total_images})")
        item.setData(0, Qt.UserRole, node)
        item.setExpanded(True)
        for child in node.children:
            self._add_tree_item(child, item)
        return item

    def _navigate_to(self, item: QTreeWidgetItem):
        if not item:
            print("[APP] navigate_to: item is None")
            return
        node = item.data(0, Qt.UserRole)
        if not node:
            print("[APP] navigate_to: node is None")
            return
        self.current_node = node

        # 按需加载：选中哪个文件夹就只加载该文件夹的图片（不自动递归子文件夹）
        # 直接图片用于网格显示；子文件夹图片仅用于标签统计范围
        self.current_images = list(node.images)   # 网格只显示本层直接图片
        self.current_scope = list(node.images)    # 标签编辑只作用于本层图片
        self.current_all = node.get_all_images()  # 全部子文件夹图片（标签统计可选范围）

        print(f"[APP] navigate: {node.name} dir={len(node.images)} all={len(self.current_all)}")
        self.image_grid.set_images(self.current_images)
        if node.images:
            self.tag_editor.set_scope(self.current_scope, self.current_all)
        elif node.children:
            # 该文件夹无直接图片但有子文件夹：提示用户点击子文件夹
            self.tag_editor.show_no_scope(0)
            sub_count = node.total_images
            self.status_bar.showMessage(f"{node.name}: 无直接图片，请展开并点击子文件夹查看（共 {sub_count} 张在子目录）")
        else:
            self.tag_editor.show_no_scope(0)

        self.lbl_dataset.setText(f"● {node.name} ({len(self.current_images)}张)")
        if node.images:
            self.status_bar.showMessage(f"{node.name}: {len(self.current_images)} 张图片")
        self._update_all_strips()

    def on_tree_click(self, item, col):
        """点击树节点：普通点击导航到该文件夹，Ctrl+点击合并多选文件夹"""
        ctrl_held = QApplication.keyboardModifiers() & Qt.ControlModifier
        if ctrl_held:
            # 多选后合并加载所有选中文件夹的图片
            selected = self.tree_widget.selectedItems()
            if not selected:
                return
            images = []
            scope = []
            all_imgs = []
            names = []
            for it in selected:
                nd = it.data(0, Qt.UserRole)
                if nd:
                    images.extend(nd.images)
                    scope.extend(nd.images)
                    all_imgs.extend(nd.get_all_images())
                    names.append(nd.name)
            self.current_node = selected[0].data(0, Qt.UserRole)  # 第一个作为当前节点
            self.current_images = images
            self.current_scope = scope
            self.current_all = all_imgs
            self.image_grid.set_images(images)
            if images:
                self.tag_editor.set_scope(scope, all_imgs)
            self.lbl_dataset.setText(f"● 多选({len(selected)}): {len(images)}张")
            self.status_bar.showMessage(f"已合并 {len(selected)} 个文件夹: {', '.join(names[:3])}... 共 {len(images)} 张")
            self._update_all_strips()
        else:
            self._navigate_to(item)

    def _on_tab_moved(self, from_idx, to_idx):
        """Tab移动后的处理：数据集Tab固定在第一位"""
        # 检查数据集Tab是否被移走，如果被移走了就强制移回第一位
        if self.tab_widget.tabText(0) != "📁 数据集":
            self.tab_widget.tabBar().blockSignals(True)
            # 找到数据集Tab的当前位置并移回0
            for i in range(self.tab_widget.count()):
                if self.tab_widget.tabText(i) == "📁 数据集":
                    self.tab_widget.tabBar().moveTab(i, 0)
                    break
            self.tab_widget.tabBar().blockSignals(False)

    def _on_shared_strip_click(self, img: ImageItem):
        """共享图片条点击：根据当前Tab分发到对应页面"""
        tab = self.tab_widget.currentIndex()
        if tab == 1:  # 裁切
            self.crop_load_image(img)
        elif tab == 2:  # 标签
            self.label_load_image(img)
        elif tab == 3:  # 反推
            self.infer_load_image(img)
        elif tab == 5:  # 图像处理
            self.image_processor.load_image(img)

    def _on_crop_exported(self, export_dir):
        """After crop export, refresh tree and select the export folder."""
        if not self.tree_root: return
        from .scanner import scan_directory
        from .image_grid import MiniImageStrip
        MiniImageStrip._thumb_cache.clear()
        self.tree_root = scan_directory(self.tree_root.path)
        self._rebuild_tree()
        self.image_grid.clear()
        self._select_tree_path(export_dir)

    def _select_tree_path(self, target_path):
        def _search(parent):
            for i in range(parent.childCount()):
                ch = parent.child(i); node = ch.data(0, Qt.UserRole)
                if node and node.path == target_path:
                    self.tree_widget.setCurrentItem(ch); self._navigate_to(ch); return True
                if ch.childCount() and _search(ch): return True
            return False
        for i in range(self.tree_widget.topLevelItemCount()):
            it = self.tree_widget.topLevelItem(i); node = it.data(0, Qt.UserRole)
            if node and node.path == target_path:
                self.tree_widget.setCurrentItem(it); self._navigate_to(it); return
            if it.childCount() and _search(it): return

    def _update_all_strips(self):
        """导航到新文件夹时：更新共享图片条"""
        self.shared_strip.set_images(self.current_images)

    def crop_load_image(self, img: ImageItem):
        self.crop_editor.load_image(img)
        self.tab_widget.setCurrentIndex(1)  # switch to crop tab

    def label_load_image(self, img: ImageItem):
        # Switch to image in the tag editor
        self.tag_editor._current_img = img
        self.tag_editor._show_current()
        self.tab_widget.setCurrentIndex(2)  # switch to labels tab

    def infer_load_image(self, img: ImageItem):
        self.infer_panel.set_image(img)
        self.tab_widget.setCurrentIndex(3)  # switch to infer tab

    def on_save(self):
        self.tag_editor.save_all()
        self.status_bar.showMessage("已保存")

    def _start_batch_op(self, processor, method_name, args, done_callback):
        """通用批量操作：启动线程+显示进度条"""
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._progress_bar.setFormat("%p%")
        self.status_bar.showMessage("处理中...")
        self._batch_thread = QThread()
        self._batch_worker = BatchWorker(processor, method_name, args)
        self._batch_worker.moveToThread(self._batch_thread)
        self._batch_worker.progress.connect(self._on_batch_progress)
        self._batch_worker.finished.connect(lambda res: self._on_batch_done(res, done_callback))
        self._batch_worker.error.connect(self._on_batch_error)
        self._batch_thread.started.connect(self._batch_worker.run)
        self._batch_thread.start()

    def _on_batch_progress(self, current, total):
        self._progress_bar.setValue(int(current / total * 100))
        self._progress_bar.setFormat(f"{current}/{total}")

    def _on_batch_done(self, result, callback):
        self._batch_thread.quit()
        self._progress_bar.setVisible(False)
        self.status_bar.showMessage("就绪")
        if callback:
            callback(result)

    def _on_batch_error(self, msg):
        self._batch_thread.quit()
        self._progress_bar.setVisible(False)
        self.status_bar.showMessage("就绪")
        QMessageBox.critical(self, "错误", f"操作失败: {msg}")

    def on_batch_rename(self):
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        if getattr(self, '_scanning', False):
            QMessageBox.warning(self, "提示", "目录扫描未完成，请等待扫描结束后再操作")
            return
        if not self.current_node:
            QMessageBox.warning(self, "提示", "请先选择一个文件夹")
            return
        images = self.current_images
        if not images:
            QMessageBox.warning(self, "提示", "当前文件夹没有图片")
            return

        # 命名模式选择
        mode, ok = QInputDialog.getItem(self, "批量重命名 - 命名方式",
            "选择命名方式:",
            ["自定义前缀 + 序号 (image_001)", "原名 + 序号 (原文件名_001)",
             "自定义前缀 + 日期时间", "文件夹名 + 序号"], 0, False)
        if not ok:
            return

        custom_text = ""
        if "自定义前缀" in mode:
            custom_text, ok = QInputDialog.getText(self, "批量重命名", "输入前缀:", text="image")
            if not ok or not custom_text.strip():
                return

        # 确定模式
        if "自定义前缀 + 序号" in mode or mode.startswith("自定义前缀 + 序号"):
            m_key, need_num = "prefix_num", True
        elif "原名 + 序号" in mode:
            m_key, need_num = "orig_num", True
        elif "自定义前缀 + 日期时间" in mode:
            m_key, need_num = "prefix_date", False
        elif "文件夹名 + 序号" in mode:
            m_key, need_num = "folder_num", True
        else:
            m_key, need_num = "prefix_num", True

        start_num = 1
        if need_num:
            start_num, ok = QInputDialog.getInt(self, "批量重命名", "起始序号:", 1, 1, 9999)
            if not ok:
                return

        img_paths = [img.file_path for img in images]
        # 询问是否备份
        backup_choice = QMessageBox.question(self, "备份确认",
            "是否需要备份原文件？\n\n✅ Yes = 备份后重命名\n❌ No  = 直接重命名（不备份）",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        backup_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "备份", "batch_rename") if backup_choice == QMessageBox.Yes else None

        def _done(result):
            self._on_crop_exported(self.current_node.path)
            msg = "已备份到 备份/batch_rename/" if backup_dir else "未备份"
            QMessageBox.information(self, "完成", f"重命名 {len(result)} 个文件（{msg}）")

        renamer = BatchRenamer(mode=m_key, custom_text=custom_text, start_num=start_num)
        self._start_batch_op(renamer, "process", (img_paths, backup_dir), _done)

    def on_batch_resize(self):
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        if getattr(self, '_scanning', False):
            QMessageBox.warning(self, "提示", "目录扫描未完成，请等待扫描结束后再操作")
            return
        if not self.current_node:
            QMessageBox.warning(self, "提示", "请先选择一个文件夹")
            return
        images = self.current_images
        if not images:
            QMessageBox.warning(self, "提示", "当前文件夹没有图片")
            return
        max_side, ok = QInputDialog.getInt(self, "批量缩放", "最长边像素（等比缩放，不裁切不填充）:", 1024, 128, 4096)
        if not ok:
            return
        img_paths = [img.file_path for img in images]
        backup_choice = QMessageBox.question(self, "备份确认",
            "是否需要备份原文件？\n✅ Yes = 备份后缩放  ❌ No = 直接缩放",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        backup_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "备份", "batch_resize") if backup_choice == QMessageBox.Yes else None

        def _done(result):
            success = sum(1 for r in result if r["status"] == "success")
            fail = sum(1 for r in result if r["status"] == "fail")
            msg = "已备份" if backup_dir else "未备份"
            QMessageBox.information(self, "完成", f"缩放完成: 成功 {success}, 失败 {fail}（{msg}）")
            self.image_grid.clear()
            self.image_grid.set_images(self.current_images)

        scaler = BatchScaler(max_side, max_side, keep_ratio=True)
        self._start_batch_op(scaler, "process", (img_paths, backup_dir), _done)

    def on_batch_convert(self):
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        if getattr(self, '_scanning', False):
            QMessageBox.warning(self, "提示", "目录扫描未完成，请等待扫描结束后再操作")
            return
        if not self.current_node:
            QMessageBox.warning(self, "提示", "请先选择一个文件夹")
            return
        images = self.current_images
        if not images:
            QMessageBox.warning(self, "提示", "当前文件夹没有图片")
            return
        quality, ok = QInputDialog.getInt(self, "格式转换", "WebP质量 (0-100):", 80, 0, 100)
        if not ok:
            return
        delete_original, ok = QInputDialog.getItem(self, "格式转换", "删除原始文件?", ["否", "是"], 0)
        if not ok:
            return
        img_paths = [img.file_path for img in images]
        backup_choice = QMessageBox.question(self, "备份确认",
            "是否需要备份原文件？\n✅ Yes = 备份后转换  ❌ No = 直接转换",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        backup_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "备份", "batch_convert") if backup_choice == QMessageBox.Yes else None

        def _done(result):
            success = sum(1 for r in result if r["status"] == "success")
            skip = sum(1 for r in result if r["status"] == "skip")
            fail = sum(1 for r in result if r["status"] == "fail")
            msg = "已备份" if backup_dir else "未备份"
            QMessageBox.information(self, "完成", f"转换完成: 成功 {success}, 跳过 {skip}, 失败 {fail}（{msg}）")
            self._on_crop_exported(self.current_node.path)

        converter = BatchConverter(quality=quality)
        self._start_batch_op(converter, "process",
            (img_paths, backup_dir, (delete_original == "是")), _done)

    # ===== 右键菜单 =====

    def _on_image_context_menu(self, img, global_pos):
        """图片右键菜单（根据当前Tab动态构建）"""
        from PySide6.QtWidgets import QMenu
        if not img:
            return
        tab = self.tab_widget.currentIndex()
        menu = QMenu()

        # 共用项
        def _add_common():
            menu.addAction("📋 复制图片路径", lambda: QApplication.clipboard().setText(img.file_path))
            if hasattr(os, 'startfile'):
                menu.addAction("📂 在资源管理器打开", lambda: os.startfile(os.path.dirname(img.file_path)))

        if tab == 0:  # 数据集页
            menu.addAction("🏷️ 在标签页编辑", lambda: self.label_load_image(img))
            menu.addAction("✂️ 裁切此图", lambda: self.crop_load_image(img))
            menu.addAction("🤖 反推此图", lambda: self.infer_load_image(img))
            menu.addSeparator()
            _add_common()

        elif tab == 1:  # 裁切页
            menu.addAction("🏷️ 在标签页编辑", lambda: self.label_load_image(img))
            menu.addAction("🤖 反推此图", lambda: self.infer_load_image(img))
            menu.addSeparator()
            _add_common()

        elif tab == 2:  # 标签页
            menu.addAction("✂️ 裁切此图", lambda: self.crop_load_image(img))
            menu.addAction("🤖 反推此图", lambda: self.infer_load_image(img))
            menu.addSeparator()
            _add_common()

        elif tab == 3:  # 反推页
            menu.addAction("🏷️ 在标签页编辑", lambda: self.label_load_image(img))
            menu.addAction("✂️ 裁切此图", lambda: self.crop_load_image(img))
            menu.addSeparator()
            _add_common()

        elif tab == 4:  # AI聊天页
            _add_common()

        elif tab == 5:  # 图像处理页
            menu.addAction("🏷️ 在标签页编辑", lambda: self.label_load_image(img))
            menu.addAction("✂️ 裁切此图", lambda: self.crop_load_image(img))
            menu.addSeparator()
            _add_common()

        menu.exec(global_pos)

    def _on_tree_context_menu(self, pos):
        """目录树右键菜单"""
        from PySide6.QtWidgets import QMenu, QInputDialog
        item = self.tree_widget.itemAt(pos)
        if not item:
            return
        node = item.data(0, Qt.UserRole)
        if not node:
            return
        menu = QMenu()
        menu.addAction("📁 打开此文件夹", lambda: self._navigate_to(item))
        menu.addSeparator()
        if hasattr(os, 'startfile'):
            menu.addAction("📂 在资源管理器打开", lambda: os.startfile(node.path))
        menu.exec(self.tree_widget.viewport().mapToGlobal(pos))

    def on_settings(self):
        dlg = SettingsDialog(self)
        dlg.exec()
        # 关闭设置后刷新网格（缩略图尺寸或列数可能变化）
        if self.current_images:
            self.image_grid.clear()
            self.image_grid.set_images(self.current_images)
