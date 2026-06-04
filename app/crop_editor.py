# -*- coding: utf-8 -*-
"""Crop editor with canvas, aspect ratio lock, queue with thumbnails."""
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QSpinBox, QListWidget, QListWidgetItem,
    QSplitter, QScrollArea, QFrame, QFileDialog, QMessageBox,
    QSlider, QCheckBox, QGridLayout, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QRect, QSize, QPoint
from PySide6.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QBrush, QFont, QIcon
from typing import Optional
from .models import ImageItem


class CropCanvas(QWidget):
    crop_changed = Signal(QRect)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pix: Optional[QPixmap] = None
        self.crop_rect = QRect(50, 50, 400, 400)
        self.aspect_ratio = 0
        self.dragging = False
        self.drag_handle = ""
        self.drag_start = QPoint()
        self.drag_orig = QRect()
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_canvas_context_menu)

    def set_image(self, pix: QPixmap):
        self._pix = pix
        self.crop_rect = QRect(50, 50, min(400, pix.width()), min(400, pix.height()))
        self.update()

    def set_aspect_ratio(self, ratio: float):
        self.aspect_ratio = ratio
        if ratio > 0 and self._pix:
            w = self.crop_rect.width()
            h = int(w / ratio)
            if self.crop_rect.y() + h > self._pix.height(): h = self.crop_rect.height(); w = int(h * ratio)
            self.crop_rect.setWidth(w); self.crop_rect.setHeight(h)
        self.update()

    def set_crop_size(self, w: int, h: int):
        self.crop_rect.setWidth(min(w, self._pix.width() - self.crop_rect.x()) if self._pix else w)
        self.crop_rect.setHeight(min(h, self._pix.height() - self.crop_rect.y()) if self._pix else h)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.SmoothPixmapTransform)
        if not self._pix or self._pix.isNull():
            p.setPen(QColor("#888"))
            p.drawText(self.rect(), Qt.AlignCenter, "双击数据集中的图片载入")
            return
        scaled = self._pix.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        sx = (self.width() - scaled.width()) // 2; sy = (self.height() - scaled.height()) // 2
        p.drawPixmap(sx, sy, scaled)
        # Map crop rect to display coords
        scale = min(self.width() / self._pix.width(), self.height() / self._pix.height(), 1.0)
        off_x = (self.width() - self._pix.width() * scale) / 2; off_y = (self.height() - self._pix.height() * scale) / 2
        cr = QRect(int(self.crop_rect.x()*scale+off_x), int(self.crop_rect.y()*scale+off_y),
                    int(self.crop_rect.width()*scale), int(self.crop_rect.height()*scale))
        # Dim outside
        p.setBrush(QColor(0,0,0,128)); p.setPen(Qt.NoPen)
        p.drawRect(0, 0, self.width(), cr.top()); p.drawRect(0, cr.bottom(), self.width(), self.height()-cr.bottom())
        p.drawRect(0, cr.top(), cr.left(), cr.height()); p.drawRect(cr.right(), cr.top(), self.width()-cr.right(), cr.height())
        # Border + handles
        p.setPen(QPen(QColor("#e94560"), 2)); p.setBrush(Qt.NoBrush); p.drawRect(cr)
        p.setBrush(QColor("white")); p.setPen(QPen(QColor("#e94560"), 1))
        for pt in [cr.topLeft(), cr.topRight(), cr.bottomLeft(), cr.bottomRight(),
                   QPoint(cr.center().x(), cr.top()), QPoint(cr.center().x(), cr.bottom()),
                   QPoint(cr.left(), cr.center().y()), QPoint(cr.right(), cr.center().y())]:
            p.drawRect(pt.x()-4, pt.y()-4, 8, 8)
        # Info
        p.fillRect(4, 4, 240, 20, QColor(0,0,0,180)); p.setPen(QColor("white")); p.setFont(QFont("Segoe UI", 10))
        p.drawText(8, 18, f"({self.crop_rect.x()},{self.crop_rect.y()}) {self.crop_rect.width()}x{self.crop_rect.height()}")

    def _to_img(self, pos): return QPoint(int((pos.x()-(self.width()-self._pix.width()*min(self.width()/self._pix.width(),self.height()/self._pix.height(),1.0))/2)/(min(self.width()/self._pix.width(),self.height()/self._pix.height(),1.0))), int((pos.y()-(self.height()-self._pix.height()*min(self.width()/self._pix.width(),self.height()/self._pix.height(),1.0))/2)/(min(self.width()/self._pix.width(),self.height()/self._pix.height(),1.0)))) if self._pix else pos

    def mousePressEvent(self, event):
        if not self._pix: return
        pos = self._to_img(event.position().toPoint()); cr = self.crop_rect
        handles = {"nw":cr.topLeft(),"ne":cr.topRight(),"sw":cr.bottomLeft(),"se":cr.bottomRight(),
                   "n":QPoint(cr.center().x(),cr.top()),"s":QPoint(cr.center().x(),cr.bottom()),
                   "w":QPoint(cr.left(),cr.center().y()),"e":QPoint(cr.right(),cr.center().y())}
        for n, p in handles.items():
            if (pos-p).manhattanLength() < 12: self.dragging=True; self.drag_handle=n; self.drag_start=pos; self.drag_orig=QRect(cr); return
        if cr.contains(pos): self.dragging=True; self.drag_handle="move"; self.drag_start=pos; self.drag_orig=QRect(cr)

    def mouseMoveEvent(self, event):
        if not self.dragging or not self._pix: return
        pos = self._to_img(event.position().toPoint()); dx=pos.x()-self.drag_start.x(); dy=pos.y()-self.drag_start.y(); cr=QRect(self.drag_orig)
        h=self.drag_handle
        if h=="move": cr.translate(dx,dy)
        elif h=="se": cr.setWidth(max(10,cr.width()+dx)); cr.setHeight(max(10,cr.height()+dy))
        elif h=="nw": cr.setX(cr.x()+dx); cr.setY(cr.y()+dy); cr.setWidth(max(10,cr.width()-dx)); cr.setHeight(max(10,cr.height()-dy))
        elif h=="ne": cr.setY(cr.y()+dy); cr.setWidth(max(10,cr.width()+dx)); cr.setHeight(max(10,cr.height()-dy))
        elif h=="sw": cr.setX(cr.x()+dx); cr.setWidth(max(10,cr.width()-dx)); cr.setHeight(max(10,cr.height()+dy))
        elif h in ("e",): cr.setWidth(max(10,cr.width()+dx))
        elif h in ("w",): cr.setX(cr.x()+dx); cr.setWidth(max(10,cr.width()-dx))
        elif h in ("s",): cr.setHeight(max(10,cr.height()+dy))
        elif h in ("n",): cr.setY(cr.y()+dy); cr.setHeight(max(10,cr.height()-dy))
        if self.aspect_ratio>0 and h!="move": cr.setHeight(int(cr.width()/self.aspect_ratio)) if "e" in h or "w" in h else cr.setWidth(int(cr.height()*self.aspect_ratio))
        w=self._pix.width(); h2=self._pix.height()
        cr.setX(max(0,cr.x())); cr.setY(max(0,cr.y())); cr.setWidth(min(cr.width(),w-cr.x())); cr.setHeight(min(cr.height(),h2-cr.y()))
        self.crop_rect=cr; self.crop_changed.emit(cr); self.update()

    def mouseReleaseEvent(self, event): self.dragging = False
    def _on_canvas_context_menu(self, pos):
        """裁切画布右键菜单"""
        from PySide6.QtWidgets import QMenu
        menu = QMenu()
        menu.addAction("🔄 重置裁切框", self._reset_crop_rect)
        menu.addSeparator()
        ratio_menu = menu.addMenu("📐 锁定比例")
        for label, r in [("自由", 0), ("1:1", 1.0), ("3:2", 1.5), ("4:3", 1.333), ("16:9", 1.778)]:
            ratio_menu.addAction(label, lambda r=r: self.set_aspect_ratio(r))
        menu.exec(self.mapToGlobal(pos))

    def _reset_crop_rect(self):
        if self._pix:
            self.crop_rect = QRect(50, 50, min(400, self._pix.width()), min(400, self._pix.height()))
            self.update()

    def get_crop_pixmap(self): return self._pix.copy(self.crop_rect) if self._pix else QPixmap()


class CropEditorWidget(QWidget):
    exported = Signal(str)  # path of export folder

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_img = None
        self.crop_queue = []
        layout = QHBoxLayout(self); layout.setContentsMargins(8, 8, 8, 8)
        self.canvas = CropCanvas(); layout.addWidget(self.canvas, 1)
        controls = QWidget(); controls.setMaximumWidth(300); cl = QVBoxLayout(controls); cl.setSpacing(8)

        # Ratio
        rl = QHBoxLayout(); rl.addWidget(QLabel("比例:"))
        self.ratio_combo = QComboBox(); self.ratio_combo.addItems(["自由","1:1","3:2","4:3","16:9","9:16","2:3","3:4"])
        self.ratio_combo.currentTextChanged.connect(self._on_ratio_changed); rl.addWidget(self.ratio_combo); cl.addLayout(rl)

        # Size
        sl = QHBoxLayout(); sl.addWidget(QLabel("尺寸:"))
        self.spin_w = QSpinBox(); self.spin_w.setRange(64,4096); self.spin_w.setValue(512)
        self.spin_w.valueChanged.connect(lambda v: self.canvas.set_crop_size(v, self.spin_h.value()))
        sl.addWidget(self.spin_w); sl.addWidget(QLabel("×"))
        self.spin_h = QSpinBox(); self.spin_h.setRange(64,4096); self.spin_h.setValue(512)
        self.spin_h.valueChanged.connect(lambda v: self.canvas.set_crop_size(self.spin_w.value(), v))
        sl.addWidget(self.spin_h); cl.addLayout(sl)

        # Quick size
        ql = QHBoxLayout()
        for s in [256,512,768,1024]:
            btn = QPushButton(f"{s}²"); btn.clicked.connect(lambda _,x=s: self._quick(x)); ql.addWidget(btn)
        cl.addLayout(ql)

        # Actions
        al = QHBoxLayout()
        btn_add = QPushButton("➕ 添加裁切"); btn_add.clicked.connect(self._add_crop); al.addWidget(btn_add)
        btn_export = QPushButton("📦 导出全部"); btn_export.setStyleSheet("background:#4ecca3;color:#000;")
        btn_export.clicked.connect(self._export_all); al.addWidget(btn_export); cl.addLayout(al)

        # Queue with thumbnails
        cl.addWidget(QLabel("裁切队列 (0):"))
        self.queue_list = QListWidget(); self.queue_list.setIconSize(QSize(64,64)); self.queue_list.setMaximumHeight(240)
        cl.addWidget(self.queue_list)
        layout.addWidget(controls)
        self.canvas.crop_changed.connect(self._update_spinboxes)
        # Image info label
        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color:#888;font-size:11px;")
        cl.addWidget(self._info_label)

    def load_image(self, img: ImageItem):
        self.current_img = img
        pix = QPixmap(img.file_path)
        self.canvas.set_image(pix)
        self.crop_queue.clear(); self.queue_list.clear(); self._update_queue_label()
        # Show image info
        sz = os.path.getsize(img.file_path)
        size_str = f"{sz/1024:.0f}KB" if sz < 1048576 else f"{sz/1048576:.1f}MB"
        self._info_label.setText(f"📷 {os.path.basename(img.file_path)}\n   尺寸: {pix.width()}×{pix.height()}  |  大小: {size_str}")

    def _on_ratio_changed(self, text):
        ratios = {"自由":0,"1:1":1,"3:2":3/2,"4:3":4/3,"16:9":16/9,"9:16":9/16,"2:3":2/3,"3:4":3/4}
        self.canvas.set_aspect_ratio(ratios.get(text,0))

    def _quick(self, size):
        self.spin_w.setValue(size); self.spin_h.setValue(size); self.ratio_combo.setCurrentText("1:1")
        self.canvas.set_crop_size(size, size)

    def _update_spinboxes(self, _rect):
        self.spin_w.blockSignals(True); self.spin_w.setValue(self.canvas.crop_rect.width())
        self.spin_h.blockSignals(True); self.spin_h.setValue(self.canvas.crop_rect.height())
        self.spin_w.blockSignals(False); self.spin_h.blockSignals(False)

    def _add_crop(self):
        if not self.current_img: return
        cr = self.canvas.crop_rect
        out_w, out_h = self.spin_w.value(), self.spin_h.value()
        self.crop_queue.append((QRect(cr), out_w, out_h))
        # Create thumbnail for queue
        thumb_pix = QPixmap(self.current_img.file_path)
        if not thumb_pix.isNull():
            thumb = thumb_pix.copy(cr).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:
            thumb = QPixmap(64, 64); thumb.fill(QColor("#16213e"))
        item = QListWidgetItem(f"#{len(self.crop_queue)}: {cr.width()}×{cr.height()} → {out_w}×{out_h}")
        item.setIcon(QIcon(thumb))
        self.queue_list.addItem(item)
        self._update_queue_label()

    def _update_queue_label(self):
        for l in self.findChildren(QLabel):
            if "裁切队列" in (l.text() or ""): l.setText(f"裁切队列 ({len(self.crop_queue)}):"); break

    def _export_all(self):
        if not self.crop_queue or not self.current_img: QMessageBox.information(self, "提示", "没有裁切"); return
        dn = os.path.splitext(self.current_img.name)[0]
        ed = os.path.join(os.path.dirname(self.current_img.file_path), dn)
        os.makedirs(ed, exist_ok=True)
        fp = self.canvas._pix if self.canvas._pix else QPixmap(self.current_img.file_path)
        for i,(cr,ow,oh) in enumerate(self.crop_queue):
            pix = fp.copy(cr).scaled(ow, oh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pix.save(os.path.join(ed, f"crop_{i+1:03d}.png"))
            if self.current_img.labels:
                with open(os.path.join(ed, f"crop_{i+1:03d}.txt"), "w", encoding="utf-8") as f:
                    f.write(", ".join(self.current_img.labels))
        QMessageBox.information(self, "完成", f"导出 {len(self.crop_queue)} 个到 {ed}")
        self.crop_queue.clear(); self.queue_list.clear(); self._update_queue_label()
        self.exported.emit(ed)

    def hideEvent(self, event):
        """退出裁切页时释放原图缓存"""
        self.canvas._pix = None
        self.canvas.update()
        super().hideEvent(event)

    def showEvent(self, event):
        """进入裁切页时，如原图已释放则重新加载"""
        if self.canvas._pix is None and self.current_img:
            self.canvas.set_image(QPixmap(self.current_img.file_path))
        super().showEvent(event)
