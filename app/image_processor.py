# -*- coding: utf-8 -*-
"""图像处理页 — 涂抹抹除、部位标识、对比度调节"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSlider, QComboBox, QGraphicsView, QGraphicsScene,
    QGraphicsPixmapItem, QSplitter, QColorDialog, QMessageBox,
    QFileDialog, QSpinBox, QGroupBox, QFormLayout, QCheckBox,
    QTextEdit, QApplication, QLineEdit, QScrollArea,
)
from PySide6.QtCore import Qt, Signal, QPointF, QRectF, QSize, QEvent, QThread
from PySide6.QtGui import (
    QPixmap, QImage, QPainter, QPen, QColor, QBrush,
    QPainterPath, QFont,
)
from .models import ImageItem
import os


class ImageProcessorWidget(QWidget):
    """图像处理面板：涂抹、标识、调色"""

    image_loaded = Signal(object)  # 发送加载的 ImageItem

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_img: ImageItem = None
        self._original_pix: QPixmap = None
        self._brush_size = 20
        self._brush_color = QColor(255, 0, 0, 180)
        self._eraser_mode = False
        self._drawing = False
        self._paths = []          # 所有绘制的路径
        self._redo_stack = []     # 撤销的路径
        self._selection_rect = None  # 选区矩形 (QRectF)
        self._sel_start = None       # 选区起始点

        # 主水平分割
        splitter = QSplitter(Qt.Horizontal)

        # === 左侧：图片选择列表 ===
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.addWidget(QLabel("📁 当前图片"))
        self._img_label = QLabel("无图片")
        self._img_label.setWordWrap(True)
        self._img_label.setStyleSheet("color:#888; font-size:11px;")
        left_layout.addWidget(self._img_label)
        left_layout.addStretch()
        splitter.addWidget(left_panel)

        # === 中央：画布 ===
        self._scene = QGraphicsScene()
        self._view = QGraphicsView(self._scene)
        self._view.setRenderHint(QPainter.SmoothPixmapTransform)
        self._view.setDragMode(QGraphicsView.NoDrag)
        self._view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self._view.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self._view.viewport().installEventFilter(self)
        self._pixmap_item = QGraphicsPixmapItem()
        self._overlay_item = QGraphicsPixmapItem()  # 涂抹叠加层
        self._scene.addItem(self._pixmap_item)
        self._scene.addItem(self._overlay_item)
        self._overlay_item.setZValue(1)
        splitter.addWidget(self._view)

        # === 右侧：操作面板 ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(6, 6, 6, 6)
        right_layout.setSpacing(8)

        # 图片导航
        nav_row = QHBoxLayout()
        self.btn_prev = QPushButton("◀ 上一张")
        self.btn_prev.clicked.connect(self._prev_image)
        nav_row.addWidget(self.btn_prev)
        self.btn_next = QPushButton("下一张 ▶")
        self.btn_next.clicked.connect(self._next_image)
        nav_row.addWidget(self.btn_next)
        right_layout.addLayout(nav_row)

        # 工具模式
        tool_group = QGroupBox("🔧 工具")
        tool_layout = QFormLayout(tool_group)
        self._tool_combo = QComboBox()
        self._tool_combo.addItems(["🖌 涂抹/标识", "🧹 橡皮擦", "✋ 拖拽画布", "📐 选区裁切"])
        tool_layout.addRow("模式:", self._tool_combo)
        right_layout.addWidget(tool_group)

        # 裁切按钮（选区模式下可用）
        crop_btn_row = QHBoxLayout()
        self._btn_crop_selection = QPushButton("✂️ 裁切选区")
        self._btn_crop_selection.clicked.connect(self._crop_selection)
        crop_btn_row.addWidget(self._btn_crop_selection)
        self._btn_crop_reset = QPushButton("↩ 取消选区")
        self._btn_crop_reset.clicked.connect(self._clear_selection)
        crop_btn_row.addWidget(self._btn_crop_reset)
        right_layout.addLayout(crop_btn_row)

        # 笔刷设置
        brush_group = QGroupBox("🖌 笔刷")
        brush_layout = QFormLayout(brush_group)
        self._size_slider = QSlider(Qt.Horizontal)
        self._size_slider.setRange(5, 100)
        self._size_slider.setValue(20)
        self._size_slider.valueChanged.connect(lambda v: setattr(self, '_brush_size', v))
        brush_layout.addRow("大小:", self._size_slider)

        self._opacity_slider = QSlider(Qt.Horizontal)
        self._opacity_slider.setRange(20, 255)
        self._opacity_slider.setValue(180)
        self._opacity_slider.valueChanged.connect(self._on_opacity_change)
        brush_layout.addRow("不透明度:", self._opacity_slider)

        self.btn_color = QPushButton("🎨 选择颜色")
        self.btn_color.clicked.connect(self._pick_color)
        brush_layout.addRow("颜色:", self.btn_color)
        right_layout.addWidget(brush_group)

        # 调整
        adj_group = QGroupBox("🌓 调整")
        adj_layout = QFormLayout(adj_group)
        self._brightness_slider = QSlider(Qt.Horizontal)
        self._brightness_slider.setRange(-100, 100)
        self._brightness_slider.setValue(0)
        self._brightness_slider.valueChanged.connect(self._apply_adjustments)
        adj_layout.addRow("亮度:", self._brightness_slider)

        self._contrast_slider = QSlider(Qt.Horizontal)
        self._contrast_slider.setRange(-100, 100)
        self._contrast_slider.setValue(0)
        self._contrast_slider.valueChanged.connect(self._apply_adjustments)
        adj_layout.addRow("对比度:", self._contrast_slider)
        right_layout.addWidget(adj_group)

        # 导出路径设置
        exp_group = QGroupBox("📤 导出路径")
        exp_layout = QVBoxLayout(exp_group)
        exp_row = QHBoxLayout()
        self._export_dir_label = QLabel("未设置")
        self._export_dir_label.setStyleSheet("color:#888; font-size:10px;")
        self._export_dir_label.setWordWrap(True)
        exp_row.addWidget(self._export_dir_label, 1)
        btn_set_dir = QPushButton("📁 选择")
        btn_set_dir.clicked.connect(self._set_export_dir)
        exp_row.addWidget(btn_set_dir)
        exp_layout.addLayout(exp_row)
        right_layout.addWidget(exp_group)
        # 恢复上次设置的导出路径
        from .image_grid import SETTINGS
        self._export_dir = SETTINGS.get('export_dir', '')
        if self._export_dir:
            self._export_dir_label.setText(self._export_dir)
            self._export_dir_label.setStyleSheet("color:#4a9; font-size:10px;")

        # 操作按钮
        op_group = QGroupBox("💾 操作")
        op_layout = QVBoxLayout(op_group)
        op_btns1 = QHBoxLayout()
        btn_undo = QPushButton("↩ 撤销")
        btn_undo.clicked.connect(self._undo)
        op_btns1.addWidget(btn_undo)
        btn_redo = QPushButton("↪ 重做")
        btn_redo.clicked.connect(self._redo)
        op_btns1.addWidget(btn_redo)
        op_layout.addLayout(op_btns1)
        op_btns2 = QHBoxLayout()
        btn_reset = QPushButton("🔄 重置")
        btn_reset.clicked.connect(self._reset)
        op_btns2.addWidget(btn_reset)
        btn_save = QPushButton("💾 导出")
        btn_save.clicked.connect(self._save)
        op_btns2.addWidget(btn_save)
        op_layout.addLayout(op_btns2)
        right_layout.addWidget(op_group)

        # 处理反推（图像处理专属tag生成）
        infer_group = QGroupBox("🤖 处理反推")
        infer_layout = QVBoxLayout(infer_group)
        infer_layout.addWidget(QLabel("处理方案:"))
        self._process_type_combo = QComboBox()
        self._process_type_combo.addItems([
            "轮廓描边处理",
            "半透明色块分区",
            "局部明暗差异化",
            "外围模糊隔离",
            "全景+局部特写拼贴",
            "局部锐化+边缘柔光",
            "箭头点位标注"
        ])
        self._process_type_combo.currentIndexChanged.connect(self._on_process_type_changed)
        infer_layout.addWidget(self._process_type_combo)

        # 提示词模板管理
        tmpl_row = QHBoxLayout()
        tmpl_row.addWidget(QLabel("模板:"))
        self._process_tmpl_combo = QComboBox()
        self._process_tmpl_combo.setMinimumWidth(80)
        self._process_tmpl_combo.currentTextChanged.connect(self._on_process_tmpl_changed)
        tmpl_row.addWidget(self._process_tmpl_combo, 1)
        btn_save_tmpl = QPushButton("💾")
        btn_save_tmpl.setMaximumWidth(30)
        btn_save_tmpl.clicked.connect(self._save_process_tmpl)
        tmpl_row.addWidget(btn_save_tmpl)
        btn_del_tmpl = QPushButton("🗑")
        btn_del_tmpl.setMaximumWidth(30)
        btn_del_tmpl.clicked.connect(self._delete_process_tmpl)
        tmpl_row.addWidget(btn_del_tmpl)
        infer_layout.addLayout(tmpl_row)

        infer_layout.addWidget(QLabel("提示词:"))
        self._process_prompt = QTextEdit()
        self._process_prompt.setMaximumHeight(80)
        self._process_prompt.setPlaceholderText("处理方案对应的反推提示词...")
        infer_layout.addWidget(self._process_prompt)

        infer_btn_row = QHBoxLayout()
        btn_infer = QPushButton("🚀 反推标签")
        btn_infer.clicked.connect(self._run_process_infer)
        infer_btn_row.addWidget(btn_infer)
        btn_copy_tag = QPushButton("📋 复制")
        btn_copy_tag.clicked.connect(self._copy_infer_result)
        infer_btn_row.addWidget(btn_copy_tag)
        infer_layout.addLayout(infer_btn_row)

        self._process_infer_result = QLabel("")
        self._process_infer_result.setWordWrap(True)
        self._process_infer_result.setStyleSheet("color:#4a9; font-size:10px; background:#1a1a2e; padding:4px;")
        infer_layout.addWidget(self._process_infer_result)
        right_layout.addWidget(infer_group)

        # 初始化处理类型提示词和模板
        self._on_process_type_changed(0)
        self._load_process_templates()

        # 正则化 + 部位标签处理
        reg_group = QGroupBox("📐 正则化 & 部位标注")
        reg_group.setToolTip(
            "【正则化】最长边等比缩放+简化标签 → 防止过拟合/概念漂移\n"
            "【部位训练】填写触发词+部件名 → 生成部件聚焦标签\n"
            "  部位聚焦: 触发词 + (部件:1.3加权) + 细节 + 画质\n"
            "  部位正则化: 仅通用部件词 + 画质，不写触发词\n"
            "部位训练配合裁切/涂抹聚焦目标区域效果更佳。"
        )
        reg_layout = QVBoxLayout(reg_group)
        reg_layout.addWidget(QLabel("最长边:"))
        self._reg_size_combo = QComboBox()
        self._reg_size_combo.addItems(["512×512", "768×768", "1024×1024", "自定义"])
        self._reg_size_combo.currentTextChanged.connect(self._on_reg_size_changed)
        reg_layout.addWidget(self._reg_size_combo)

        self._reg_custom_size = QSpinBox()
        self._reg_custom_size.setRange(128, 4096)
        self._reg_custom_size.setValue(512)
        self._reg_custom_size.setVisible(False)
        reg_layout.addWidget(self._reg_custom_size)

        reg_layout.addWidget(QLabel("标注模板:"))
        self._reg_tag_template = QComboBox()
        self._reg_tag_template.addItems([
            "极简（仅主体+画质）",
            "简化（主体+基本属性）",
            "通用（主体+风格+画质）",
            "旧版兼容（1girl/1boy风格）",
            "部位聚焦（触发词+部件+细节）",
            "部位正则化（通用部件+画质）"
        ])
        reg_layout.addWidget(self._reg_tag_template)

        # 部位训练关键词
        part_row = QHBoxLayout()
        part_row.addWidget(QLabel("触发词:"))
        self._reg_trigger = QLineEdit()
        self._reg_trigger.setPlaceholderText("如: my_char")
        part_row.addWidget(self._reg_trigger)
        part_row.addWidget(QLabel("部件:"))
        self._reg_part = QLineEdit()
        self._reg_part.setPlaceholderText("如: hands, eyes")
        part_row.addWidget(self._reg_part)
        reg_layout.addLayout(part_row)

        reg_btn_row = QHBoxLayout()
        btn_reg_process = QPushButton("⚡ 一键正则化")
        btn_reg_process.clicked.connect(self._run_regularization)
        reg_btn_row.addWidget(btn_reg_process)
        btn_reg_tag = QPushButton("📋 复制标注")
        btn_reg_tag.clicked.connect(self._copy_reg_tags)
        reg_btn_row.addWidget(btn_reg_tag)
        reg_layout.addLayout(reg_btn_row)

        self._reg_result = QLabel("")
        self._reg_result.setWordWrap(True)
        self._reg_result.setStyleSheet("color:#c9a; font-size:10px; background:#1a1a2e; padding:4px;")
        reg_layout.addWidget(self._reg_result)
        right_layout.addWidget(reg_group)

        right_layout.addStretch()

        # 右侧面板包裹在滚动区域中（避免内容过多时压缩）
        scroll_right = QScrollArea()
        scroll_right.setWidgetResizable(True)
        scroll_right.setWidget(right_panel)
        scroll_right.setMinimumWidth(220)
        splitter.addWidget(scroll_right)
        splitter.setSizes([100, 480, 240])

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(splitter)

    def load_image(self, img: ImageItem):
        """加载图片"""
        if img is None:
            return
        self._current_img = img
        self._original_pix = QPixmap(img.file_path)
        if self._original_pix.isNull():
            return
        self._img_label.setText(f"📷 {img.name}\n{self._original_pix.width()}×{self._original_pix.height()}")
        self._pixmap_item.setPixmap(self._original_pix)
        self._scene.setSceneRect(QRectF(self._original_pix.rect()))
        self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)
        self._create_overlay()
        self._paths.clear()
        self._redo_stack.clear()
        self._brightness_slider.setValue(0)
        self._contrast_slider.setValue(0)
        self._redraw_overlay()

    def _create_overlay(self):
        """创建透明的涂抹叠加层"""
        if self._original_pix:
            overlay = QPixmap(self._original_pix.size())
            overlay.fill(QColor(0, 0, 0, 0))
            self._overlay_item.setPixmap(overlay)

    def _next_image(self):
        """加载数据集的下一张图片"""
        parent = self._find_main_window()
        if parent and hasattr(parent, 'current_images') and parent.current_images:
            imgs = parent.current_images
            if self._current_img in imgs:
                idx = imgs.index(self._current_img)
                if idx + 1 < len(imgs):
                    self.load_image(imgs[idx + 1])

    def _prev_image(self):
        parent = self._find_main_window()
        if parent and hasattr(parent, 'current_images') and parent.current_images:
            imgs = parent.current_images
            if self._current_img in imgs:
                idx = imgs.index(self._current_img)
                if idx > 0:
                    self.load_image(imgs[idx - 1])

    def _find_main_window(self):
        p = self.parent()
        while p:
            from .main_window import MainWindow
            if isinstance(p, MainWindow):
                return p
            p = p.parent()
        return None

    # ===== 鼠标事件 =====
    def eventFilter(self, obj, event):
        if obj == self._view.viewport():
            mode = self._tool_combo.currentText()

            # 选区裁切模式
            if "选区" in mode:
                if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.LeftButton:
                    self._sel_start = self._view.mapToScene(event.pos())
                    self._selection_rect = QRectF(self._sel_start, self._sel_start)
                    self._redraw_overlay()
                    return True
                elif event.type() == QEvent.Type.MouseMove and self._sel_start is not None:
                    end = self._view.mapToScene(event.pos())
                    self._selection_rect = QRectF(self._sel_start, end).normalized()
                    self._redraw_overlay()
                    return True
                elif event.type() == QEvent.Type.MouseButtonRelease and self._sel_start is not None:
                    end = self._view.mapToScene(event.pos())
                    self._selection_rect = QRectF(self._sel_start, end).normalized()
                    self._sel_start = None
                    self._redraw_overlay()
                    return True
                elif event.type() == QEvent.Type.Wheel:
                    factor = 1.15 if event.angleDelta().y() > 0 else 0.87
                    self._view.scale(factor, factor)
                    return True
                return super().eventFilter(obj, event)

            # 涂抹/橡皮擦模式
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.LeftButton:
                if "拖拽" in mode:
                    self._view.setDragMode(QGraphicsView.ScrollHandDrag)
                    return False
                self._drawing = True
                self._current_path = QPainterPath()
                pos = self._view.mapToScene(event.pos())
                self._current_path.moveTo(pos)
                return True
            elif event.type() == QEvent.Type.MouseMove and self._drawing:
                pos = self._view.mapToScene(event.pos())
                self._current_path.lineTo(pos)
                self._redraw_overlay()
                return True
            elif event.type() == QEvent.Type.MouseButtonRelease and self._drawing:
                self._drawing = False
                pos = self._view.mapToScene(event.pos())
                self._current_path.lineTo(pos)
                self._paths.append({
                    "path": self._current_path,
                    "color": self._brush_color if "橡皮" not in mode else QColor(0, 0, 0, 0),
                    "size": self._brush_size,
                    "eraser": "橡皮" in mode
                })
                self._redo_stack.clear()
                self._redraw_overlay()
                return True
            elif event.type() == QEvent.Type.Wheel:
                factor = 1.15 if event.angleDelta().y() > 0 else 0.87
                self._view.scale(factor, factor)
                return True
        return super().eventFilter(obj, event)

    def _redraw_overlay(self):
        """重新绘制涂抹叠加层和当前正在绘制的路径"""
        if not self._original_pix:
            return
        overlay = QPixmap(self._original_pix.size())
        overlay.fill(QColor(0, 0, 0, 0))
        painter = QPainter(overlay)
        painter.setRenderHint(QPainter.Antialiasing)
        alpha = self._opacity_slider.value()

        # 绘制已保存的路径
        for item in self._paths:
            path = item["path"]
            if item["eraser"]:
                pen = QPen(QColor(0, 0, 0, 0), item["size"], Qt.SolidLine, Qt.RoundCap)
                painter.setCompositionMode(QPainter.CompositionMode_Clear)
            else:
                c = QColor(item["color"])
                c.setAlpha(alpha)
                pen = QPen(c, item["size"], Qt.SolidLine, Qt.RoundCap)
                painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.setPen(pen)
            painter.drawPath(path)

        # 绘制当前正在画的路径
        if self._drawing and hasattr(self, '_current_path'):
            mode = self._tool_combo.currentText()
            if "橡皮" in mode:
                pen = QPen(QColor(0, 0, 0, 0), self._brush_size, Qt.SolidLine, Qt.RoundCap)
                painter.setCompositionMode(QPainter.CompositionMode_Clear)
            else:
                c = QColor(self._brush_color)
                c.setAlpha(alpha)
                pen = QPen(c, self._brush_size, Qt.SolidLine, Qt.RoundCap)
                painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.setPen(pen)
            painter.drawPath(self._current_path)

        # 绘制选区矩形
        if self._selection_rect and not self._selection_rect.isEmpty():
            pen = QPen(QColor(100, 200, 255, 200), 2, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(QColor(100, 200, 255, 30))
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.drawRect(self._selection_rect)

        painter.end()
        self._overlay_item.setPixmap(overlay)

    # ===== 调整 =====
    def _apply_adjustments(self):
        if not self._original_pix:
            return
        brightness = self._brightness_slider.value()
        contrast = self._contrast_slider.value()
        if brightness == 0 and contrast == 0:
            self._pixmap_item.setPixmap(self._original_pix)
            return
        img = self._original_pix.toImage().convertToFormat(QImage.Format_ARGB32)
        for y in range(img.height()):
            for x in range(img.width()):
                pixel = img.pixelColor(x, y)
                if brightness != 0:
                    r = max(0, min(255, pixel.red() + brightness))
                    g = max(0, min(255, pixel.green() + brightness))
                    b = max(0, min(255, pixel.blue() + brightness))
                    pixel.setRed(r); pixel.setGreen(g); pixel.setBlue(b)
                if contrast != 0:
                    factor = (259 * (contrast + 255)) / (255 * (259 - contrast))
                    r = max(0, min(255, int(factor * (pixel.red() - 128) + 128)))
                    g = max(0, min(255, int(factor * (pixel.green() - 128) + 128)))
                    b = max(0, min(255, int(factor * (pixel.blue() - 128) + 128)))
                    pixel.setRed(r); pixel.setGreen(g); pixel.setBlue(b)
                img.setPixelColor(x, y, pixel)
        self._pixmap_item.setPixmap(QPixmap.fromImage(img))

    # ===== 操作 =====
    def _pick_color(self):
        color = QColorDialog.getColor(self._brush_color, self, "选择涂抹颜色")
        if color.isValid():
            self._brush_color = color
            self.btn_color.setStyleSheet(f"background-color:{color.name()}; color:white;")

    def _on_opacity_change(self, v):
        self._redraw_overlay()

    def _undo(self):
        if self._paths:
            self._redo_stack.append(self._paths.pop())
            self._redraw_overlay()

    def _redo(self):
        if self._redo_stack:
            self._paths.append(self._redo_stack.pop())
            self._redraw_overlay()

    def _reset(self):
        if QMessageBox.question(self, "确认", "重置所有涂抹和调整？") == QMessageBox.Yes:
            self._paths.clear()
            self._redo_stack.clear()
            self._selection_rect = None
            self._sel_start = None
            self._brightness_slider.setValue(0)
            self._contrast_slider.setValue(0)
            if self._original_pix:
                self._pixmap_item.setPixmap(self._original_pix)
                self._create_overlay()
                self._redraw_overlay()

    def _set_export_dir(self):
        """设置导出目录"""
        d = QFileDialog.getExistingDirectory(self, "选择导出目录", self._export_dir or "")
        if d:
            self._export_dir = d
            self._export_dir_label.setText(d)
            self._export_dir_label.setStyleSheet("color:#4a9; font-size:10px;")
            from .image_grid import SETTINGS, save_settings
            SETTINGS['export_dir'] = d
            save_settings()

    def _save(self):
        """导出处理后的图片到预设目录（未预设则弹窗选择）"""
        if not self._current_img or not self._original_pix:
            return

        export_dir = self._export_dir
        if not export_dir:
            export_dir = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not export_dir:
            return

        # 渲染最终图片
        result = QImage(self._original_pix.size(), QImage.Format_ARGB32)
        result.fill(QColor(0, 0, 0, 0))
        painter = QPainter(result)
        painter.drawPixmap(0, 0, self._pixmap_item.pixmap())
        painter.drawPixmap(0, 0, self._overlay_item.pixmap())
        painter.end()

        # 导出到选定目录
        saved_count = 0
        base = self._current_img.base_name
        ext = os.path.splitext(self._current_img.file_path)[1] or ".png"
        export_path = os.path.join(export_dir, f"{base}{ext}")
        # 避免覆盖：若已有同名文件，加序号
        counter = 1
        while os.path.exists(export_path):
            export_path = os.path.join(export_dir, f"{base}_{counter}{ext}")
            counter += 1
        result.save(export_path)

        # 同时复制标签文件
        if self._current_img.txt_path and os.path.exists(self._current_img.txt_path):
            import shutil
            tag_export = os.path.join(export_dir, f"{base}.txt")
            counter2 = 1
            while os.path.exists(tag_export):
                tag_export = os.path.join(export_dir, f"{base}_{counter2}.txt")
                counter2 += 1
            shutil.copy2(self._current_img.txt_path, tag_export)
            QMessageBox.information(self, "完成",
                f"已导出到:\n{export_path}\n{tag_export}")
        else:
            QMessageBox.information(self, "完成",
                f"已导出到:\n{export_path}")

    # ===== 处理反推（专属tag生成）=====

    # 7种处理方案的提示词模板
    _PROCESS_PROMPTS = {
        "轮廓描边处理": (
            "你是AI绘图训练标签专家。基于这张经过轮廓描边处理的图片生成正向tag。"
            "处理方式：对关键部件（如金属锁扣、皮质提手）边缘用细线描边。"
            "规则：只写实物特征，不写outline/edge line/stroke等描边词。重点部位加权1.2~1.3。"
            "固定负面：outline, colored overlay, arrow, drawn lines, mark number, glow, annotation"
            "输出格式：逗号分隔的英文tag，不要解释。"
        ),
        "半透明色块分区": (
            "你是AI绘图训练标签专家。基于这张经过半透明色块覆盖处理的图片生成正向tag。"
            "处理方式：关键区域叠加半透明色块标记，不遮挡原纹理。"
            "规则：只写实物特征，不写color overlay/translucent block/color patch等标记词。重点部件加权1.2~1.3。"
            "固定负面：outline, colored overlay, arrow, drawn lines, mark number, glow, annotation"
            "输出格式：逗号分隔的英文tag，不要解释。"
        ),
        "局部明暗差异化": (
            "你是AI绘图训练标签专家。基于这张经过局部亮度调节的图片生成正向tag。"
            "处理方式：关键部件单独提亮，周围区域压暗，背景不变。"
            "规则：只写实物特征，不写partial bright/dark surrounding/brightness adjusted等调光词。重点部件加权1.25~1.3。"
            "固定负面：outline, colored overlay, arrow, drawn lines, mark number, glow, annotation"
            "输出格式：逗号分隔的英文tag，不要解释。"
        ),
        "外围模糊隔离": (
            "你是AI绘图训练标签专家。基于这张经过背景模糊处理的图片生成正向tag。"
            "处理方式：保留主体完整清晰，背景做模糊处理。"
            "规则：只用原生词汇blurry background，不写gaussian blur/lens blur等处理词。主体部件加权1.2~1.3。"
            "固定负面：outline, colored overlay, arrow, drawn lines, mark number, glow, annotation"
            "输出格式：逗号分隔的英文tag，不要解释。"
        ),
        "全景+局部特写拼贴": (
            "你是AI绘图训练标签专家。基于这张全景+特写拼贴图片生成正向tag。"
            "处理方式：主画面完整物体，右下角嵌入局部放大特写。"
            "规则：只写实物特征，不写collage/split picture/inset/picture-in-picture等拼贴词。特写部件加权1.25~1.3。"
            "输出格式：逗号分隔的英文tag，不要解释。"
        ),
        "局部锐化+边缘柔光": (
            "你是AI绘图训练标签专家。基于这张经过局部锐化和柔光处理的图片生成正向tag。"
            "处理方式：关键部件纹路锐化，边缘微弱柔光。"
            "规则：只写实物特征，不写edge glow/soft light around/sharpened等处理词。重点部件加权1.2~1.3。"
            "固定负面：outline, colored overlay, arrow, drawn lines, mark number, glow, annotation"
            "输出格式：逗号分隔的英文tag，不要解释。"
        ),
        "箭头点位标注": (
            "你是AI绘图训练标签专家。基于这张带箭头标注的图片生成正向tag。"
            "处理方式：画面空白处画箭头指向关键结构。"
            "规则：只写实物特征，不写arrow/pointer/mark/indicator等标注词。被指向部件加权1.25~1.3。"
            "固定负面：outline, colored overlay, arrow, drawn lines, mark number, glow, annotation"
            "输出格式：逗号分隔的英文tag，不要解释。"
        ),
    }

    def _on_process_type_changed(self, idx):
        """切换处理方案时更新提示词"""
        name = self._process_type_combo.currentText()
        prompt = self._PROCESS_PROMPTS.get(name, "")
        self._process_prompt.setPlainText(prompt)

    # ===== 模板管理 =====

    def _load_process_templates(self):
        """加载处理反推的提示词模板"""
        from .image_grid import SETTINGS
        self._process_templates = list(SETTINGS.get('process_prompts', []))
        self._process_tmpl_combo.blockSignals(True)
        self._process_tmpl_combo.clear()
        self._process_tmpl_combo.addItem("（无模板）")
        for t in self._process_templates:
            self._process_tmpl_combo.addItem(t.get("name", ""))
        self._process_tmpl_combo.blockSignals(False)

    def _on_process_tmpl_changed(self, name):
        """选择模板时加载对应的提示词"""
        if not name or name == "（无模板）":
            return
        for t in self._process_templates:
            if t.get("name") == name:
                self._process_prompt.setPlainText(t.get("text", ""))
                return

    def _save_process_tmpl(self):
        """保存当前提示词为模板"""
        from PySide6.QtWidgets import QInputDialog
        from .image_grid import SETTINGS, save_settings
        current = self._process_prompt.toPlainText().strip()
        if not current:
            QMessageBox.warning(self, "提示", "提示词为空，无法保存")
            return
        name, ok = QInputDialog.getText(self, "保存模板", "模板名称:")
        if not ok or not name.strip():
            return
        name = name.strip()
        found = False
        for t in self._process_templates:
            if t["name"] == name:
                t["text"] = current
                found = True
                break
        if not found:
            self._process_templates.append({"name": name, "text": current})
        SETTINGS['process_prompts'] = self._process_templates
        save_settings()
        self._load_process_templates()
        idx = self._process_tmpl_combo.findText(name)
        if idx >= 0:
            self._process_tmpl_combo.setCurrentIndex(idx)

    def _delete_process_tmpl(self):
        """删除当前选中的模板"""
        from .image_grid import SETTINGS, save_settings
        name = self._process_tmpl_combo.currentText()
        if not name or name == "（无模板）":
            return
        if QMessageBox.question(self, "确认", f"删除模板「{name}」?") != QMessageBox.Yes:
            return
        self._process_templates = [t for t in self._process_templates if t["name"] != name]
        SETTINGS['process_prompts'] = self._process_templates
        save_settings()
        self._load_process_templates()

    def _run_process_infer(self):
        """调用API生成处理后的tag（与反推页共用API配置）"""
        if not self._current_img:
            QMessageBox.warning(self, "提示", "请先加载一张图片")
            return

        from .image_grid import SETTINGS
        endpoint = SETTINGS.get('api_endpoint', '')
        model = SETTINGS.get('api_model', 'gpt-4o')
        api_key = SETTINGS.get('api_key', '')
        if not endpoint or not api_key:
            QMessageBox.warning(self, "提示", "请在设置中配置API（端点+模型+Key）")
            return

        prompt = self._process_prompt.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "提示", "请先选择处理方案")
            return

        self._process_infer_result.setText("⏳ 反推中...")

        # 后台线程调用API
        self._infer_thread = QThread()
        self._infer_worker = _ProcessInferWorker(endpoint, model, api_key,
            self._current_img.file_path, prompt)
        self._infer_worker.moveToThread(self._infer_thread)
        self._infer_worker.finished.connect(self._on_process_infer_done)
        self._infer_worker.error.connect(self._on_process_infer_error)
        self._infer_thread.started.connect(self._infer_worker.run)
        self._infer_thread.finished.connect(self._infer_thread.deleteLater)
        self._infer_thread.start()

    def _on_process_infer_done(self, tags_text):
        self._infer_thread.quit()
        self._process_infer_result.setText(f"✅ {tags_text}")

    def _on_process_infer_error(self, err):
        self._infer_thread.quit()
        self._process_infer_result.setText(f"❌ {err}")

    def _copy_infer_result(self):
        text = self._process_infer_result.text().replace("✅ ", "").replace("❌ ", "")
        if text and text != "⏳ 反推中...":
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "完成", "已复制到剪贴板")


    # ===== 选区裁切 =====

    def _crop_selection(self):
        """裁切选区：将选区内的图像裁剪出来"""
        if not self._selection_rect or self._selection_rect.isEmpty():
            QMessageBox.warning(self, "提示", "请先在画布上拖拽框选目标区域")
            return
        if not self._original_pix:
            return

        rect = self._selection_rect.toRect()
        # 确保矩形在原图范围内
        r = QRectF(self._original_pix.rect()).intersected(QRectF(rect))
        if r.isEmpty():
            return
        rect = r.toRect()

        # 从原图裁切（含涂抹层）
        cropped = self._original_pix.copy(rect)
        # 叠加涂抹层
        if self._overlay_item.pixmap():
            overlay_crop = self._overlay_item.pixmap().copy(rect)
            result = QPixmap(cropped.size())
            result.fill(QColor(0, 0, 0, 0))
            p = QPainter(result)
            p.drawPixmap(0, 0, cropped)
            p.drawPixmap(0, 0, overlay_crop)
            p.end()
            cropped = result

        self._pixmap_item.setPixmap(cropped)
        self._scene.setSceneRect(QRectF(cropped.rect()))
        self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)
        self._create_overlay()
        self._paths.clear()
        self._redo_stack.clear()
        self._selection_rect = None
        self._redraw_overlay()

    def _clear_selection(self):
        self._selection_rect = None
        self._sel_start = None
        self._redraw_overlay()

    # ===== 正则化处理 =====

    def _on_reg_size_changed(self, text):
        self._reg_custom_size.setVisible(text == "自定义")

    def _run_regularization(self):
        """一键正则化：最长边等比缩放 + 生成通用简化标签（防过拟合）"""
        if not self._current_img or not self._original_pix:
            QMessageBox.warning(self, "提示", "请先加载一张图片")
            return

        # 确定目标尺寸
        size_text = self._reg_size_combo.currentText()
        if size_text == "自定义":
            target = self._reg_custom_size.value()
        else:
            target = int(size_text.split("×")[0])

        # 按最长边等比缩放（兼容桶训练，不填充/裁切）
        scaled = self._original_pix.scaled(target, target, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        self._pixmap_item.setPixmap(scaled)
        self._scene.setSceneRect(QRectF(scaled.rect()))
        self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)
        self._create_overlay()
        self._redraw_overlay()

        # 生成正则化标签
        reg_tags = self._generate_reg_tags()
        self._reg_result.setText(reg_tags)
        self._reg_tags = reg_tags

    def _generate_reg_tags(self) -> str:
        """根据标注模板生成正则化/部位标签"""
        template = self._reg_tag_template.currentText()
        img = self._current_img
        img.ensure_labels()
        labels = img.labels if img.labels else ["object"]

        quality_words = {"masterpiece", "best_quality", "highres", "absurdres",
                        "simple_background", "white_background", "outdoors", "indoors"}
        subject = "object"
        for t in labels:
            if t not in quality_words:
                subject = t
                break

        trigger = self._reg_trigger.text().strip() or "trigger_word"
        part = self._reg_part.text().strip() or "detail"

        if "部位聚焦" in template:
            # 触发词 + 部件词(加权) + 细节 + 画质
            return (f"{trigger}, ({part}:1.3), {subject}, "
                    f"detailed {part}, sharp focus, simple background, "
                    f"masterpiece, best quality")
        elif "部位正则化" in template:
            # 通用部件词 + 画质（不写触发词，让模型保持部件通用认知）
            return f"{part}, simple background, masterpiece, best quality"
        elif "极简" in template:
            return f"{subject}, simple background, masterpiece, best quality"
        elif "简化" in template:
            return f"{subject}, simple background, from side, masterpiece, best quality"
        elif "通用" in template:
            return f"{subject}, plain background, neutral lighting, centered, best quality, highres"
        elif "旧版" in template:
            return f"{subject}, simple background, 1girl, solo, masterpiece, best quality"
        return ", ".join(labels)

    def _copy_reg_tags(self):
        if hasattr(self, '_reg_tags') and self._reg_tags:
            QApplication.clipboard().setText(self._reg_tags)
            QMessageBox.information(self, "完成", "已复制正则化标注")

    # ===== 处理反推（专属tag生成）=====


class _ProcessInferWorker(QThread):
    """处理反推工作线程"""
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, endpoint, model, api_key, image_path, prompt):
        super().__init__()
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.image_path = image_path
        self.prompt = prompt

    def run(self):
        try:
            import base64
            with open(self.image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode('utf-8')
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": self.prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                ]}],
                "max_tokens": 300, "temperature": 0.3
            }
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            resp = __import__('requests').post(self.endpoint, json=payload, headers=headers, timeout=60)
            result = resp.json()
            if "error" in result:
                self.error.emit(result["error"].get("message", str(result["error"])))
                return
            tags = result["choices"][0]["message"]["content"].strip()
            self.finished.emit(tags)
        except Exception as e:
            self.error.emit(str(e)[:200])
