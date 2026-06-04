# -*- coding: utf-8 -*-
"""Image grid — QListView virtual scrolling + MiniImageStrip + settings."""
import math
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListView, QStyledItemDelegate,
    QLabel, QScrollArea, QHBoxLayout, QDialog, QFormLayout,
    QSpinBox, QComboBox, QPushButton, QDialogButtonBox, QStyle,
    QLineEdit, QGroupBox, QApplication, QMessageBox, QCheckBox,
)
from PySide6.QtCore import (
    Qt, QAbstractListModel, QModelIndex, Signal, QTimer, QSize,
    QThreadPool, QRunnable, QMetaObject, Q_ARG, Slot, QEvent,
)
from PySide6.QtGui import QPixmap, QFont, QPainter, QColor, QPen, QImageReader
from typing import List, Optional, Dict
import json
from .models import ImageItem

_DEFAULT = {'thumb_size': 150, 'columns': 4, 'lang': 'zh', 'theme': 'dark',
            'trans_method': 'local', 'trans_api_key': '',
            'api_provider': 'OpenAI', 'api_endpoint': 'https://api.openai.com/v1/chat/completions',
            'api_model': 'gpt-4o', 'api_key': '',
            'infer_prompts': [], 'process_prompts': [],
            'export_dir': '',
            'spacing': 2, 'label_height': 10, 'compact': True,
            'batch_scope': '当前文件夹及子目录', 'batch_concurrency': '2',
            'batch_retry': '1', 'batch_tag_mode': '追加到已有', 'batch_threshold': 35}

# 预设 API 配置
API_PROVIDERS = {
    "OpenAI": {
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "models": ["gpt-4o", "gpt-4-vision-preview", "gpt-4-turbo", "gpt-3.5-turbo"]
    },
    "通义千问 (阿里云)": {
        "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "models": ["qwen-vl-plus", "qwen-vl-max", "qwen-plus"]
    },
    "百度文心一言": {
        "endpoint": "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/completions",
        "models": ["ernie-4.0-8k", "ernie-3.5-8k"]
    },
    "DeepSeek": {
        "endpoint": "https://api.deepseek.com/v1/chat/completions",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"]
    },
    "本地 llama.cpp": {
        "endpoint": "http://127.0.0.1:8080/v1/chat/completions",
        "models": ["llava-v1.6", "minicpm-v", "自定义模型"]
    },
    "自定义接口": {
        "endpoint": "",
        "models": ["自定义模型"]
    }
}
SETTINGS = dict(_DEFAULT)

def load_settings():
    global SETTINGS
    try:
        with open('settings.json', 'r', encoding='utf-8') as f:
            saved = json.load(f)
            for k in _DEFAULT: SETTINGS[k] = saved.get(k, _DEFAULT[k])
    except: pass

def save_settings():
    try:
        with open('settings.json', 'w', encoding='utf-8') as f:
            json.dump(dict(SETTINGS), f)
    except: pass


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings / 设置")
        layout = QFormLayout(self)
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["zh (中文)", "en (English)"])
        self.lang_combo.setCurrentIndex(0 if SETTINGS['lang'] == 'zh' else 1)
        layout.addRow("语言:", self.lang_combo)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["暗色 Dark", "亮色 Light"])
        self.theme_combo.setCurrentIndex(0 if SETTINGS['theme'] == 'dark' else 1)
        layout.addRow("主题:", self.theme_combo)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(80, 300); self.size_spin.setValue(SETTINGS['thumb_size']); self.size_spin.setSingleStep(20)
        layout.addRow("缩略图大小:", self.size_spin)
        self.spacing_spin = QSpinBox()
        self.spacing_spin.setRange(0, 20); self.spacing_spin.setValue(SETTINGS.get('spacing', 2))
        self.spacing_spin.setToolTip("缩略图之间的间距（像素），0=最紧凑")
        layout.addRow("图片间距:", self.spacing_spin)
        self.label_h_spin = QSpinBox()
        self.label_h_spin.setRange(6, 30); self.label_h_spin.setValue(SETTINGS.get('label_height', 10))
        self.label_h_spin.setToolTip("文件名区域高度（像素）")
        layout.addRow("标签高度:", self.label_h_spin)

        # API 配置组（翻译+反推共用）
        api_group = QGroupBox("🌐 API 与翻译配置")
        api_layout = QFormLayout(api_group)

        self.trans_method_combo = QComboBox()
        self.trans_method_combo.addItems(["本地词典", "大模型API", "在线翻译"])
        methods_map = {'local': 0, 'llm': 1, 'online': 2}
        self.trans_method_combo.setCurrentIndex(methods_map.get(SETTINGS.get('trans_method', 'local'), 0))
        api_layout.addRow("翻译方式:", self.trans_method_combo)

        # 服务商选择
        self.api_provider_combo = QComboBox()
        prov_keys = list(API_PROVIDERS.keys())
        self.api_provider_combo.addItems(prov_keys)
        # 从设置恢复服务商：优先用索引，兼容旧英文简写
        cur_prov = SETTINGS.get('api_provider', 'OpenAI')
        idx = 0
        # 先尝试在 key 列表中精确查找
        try:
            idx = prov_keys.index(cur_prov)
        except ValueError:
            pass
        # 如果没找到（可能是旧的英文简写），尝试模糊匹配
        if idx == 0 and cur_prov not in prov_keys:
            short_map = {'openai': 'OpenAI', 'tongyi': '通义千问 (阿里云)',
                         'baidu': '百度文心一言', 'llama': '本地 llama.cpp',
                         'custom': '自定义接口'}
            full_name = short_map.get(cur_prov, 'OpenAI')
            try:
                idx = prov_keys.index(full_name)
            except ValueError:
                idx = 0
        self.api_provider_combo.setCurrentIndex(idx)
        self.api_provider_combo.currentIndexChanged.connect(self._on_api_provider_changed)
        api_layout.addRow("服务商:", self.api_provider_combo)

        # 端点 URL
        self.api_endpoint = QLineEdit()
        self.api_endpoint.setText(SETTINGS.get('api_endpoint', ''))
        self.api_endpoint.setPlaceholderText("https://api.openai.com/v1/chat/completions")
        api_layout.addRow("API 端点:", self.api_endpoint)

        # 模型选择
        model_row = QHBoxLayout()
        self.api_model_combo = QComboBox()
        self.api_model_combo.setEditable(True)
        self.api_model_combo.setInsertPolicy(QComboBox.NoInsert)
        model_row.addWidget(self.api_model_combo, 1)
        self.btn_test_conn = QPushButton("🔌 测试连接")
        self.btn_test_conn.clicked.connect(self._test_api_connection)
        model_row.addWidget(self.btn_test_conn)
        api_layout.addRow("模型:", model_row)

        # API Key
        self.api_key_input = QLineEdit()
        self.api_key_input.setText(SETTINGS.get('api_key', ''))
        self.api_key_input.setPlaceholderText("sk-...")
        self.api_key_input.setEchoMode(QLineEdit.Password)
        api_layout.addRow("API Key:", self.api_key_input)

        layout.addRow(api_group)
        # 初始化模型列表
        self._on_api_provider_changed(self.api_provider_combo.currentIndex())
        # 恢复已保存的模型选择
        saved_model = SETTINGS.get('api_model', '')
        if saved_model:
            idx = self.api_model_combo.findText(saved_model)
            if idx >= 0:
                self.api_model_combo.setCurrentIndex(idx)
            else:
                self.api_model_combo.setEditText(saved_model)

        # 自动保存：所有控件变更时即时写入设置
        self.lang_combo.currentIndexChanged.connect(self._auto_save)
        self.theme_combo.currentIndexChanged.connect(self._auto_save)
        self.size_spin.valueChanged.connect(self._auto_save)
        self.spacing_spin.valueChanged.connect(self._auto_save)
        self.label_h_spin.valueChanged.connect(self._auto_save)
        self.trans_method_combo.currentIndexChanged.connect(self._auto_save)
        self.api_provider_combo.currentIndexChanged.connect(self._auto_save)
        self.api_endpoint.textChanged.connect(self._auto_save)
        self.api_model_combo.currentTextChanged.connect(self._auto_save)
        self.api_key_input.textChanged.connect(self._auto_save)
        # 主题变更即时应用
        self.theme_combo.currentIndexChanged.connect(self._apply_theme_now)

        btn_about = QPushButton("📖 关于")
        btn_about.clicked.connect(self._about)
        btn_reset = QPushButton("🔄 恢复默认")
        btn_reset.clicked.connect(self._reset_defaults)
        btn_save = QPushButton("💾 保存")
        btn_save.clicked.connect(self._manual_save)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        btns.addButton(btn_about, QDialogButtonBox.ActionRole)
        btns.addButton(btn_reset, QDialogButtonBox.ActionRole)
        btns.addButton(btn_save, QDialogButtonBox.ActionRole)
        layout.addRow(btns)

    def _auto_save(self):
        """自动保存所有设置到文件"""
        SETTINGS['lang'] = 'zh' if 'zh' in self.lang_combo.currentText() else 'en'
        SETTINGS['theme'] = 'dark' if 'Dark' in self.theme_combo.currentText() else 'light'
        SETTINGS['thumb_size'] = self.size_spin.value()
        SETTINGS['spacing'] = self.spacing_spin.value()
        SETTINGS['label_height'] = self.label_h_spin.value()
        methods_rev = {0: 'local', 1: 'llm', 2: 'online'}
        SETTINGS['trans_method'] = methods_rev.get(self.trans_method_combo.currentIndex(), 'local')
        prov_keys = list(API_PROVIDERS.keys())
        idx = self.api_provider_combo.currentIndex()
        SETTINGS['api_provider'] = prov_keys[idx] if 0 <= idx < len(prov_keys) else '自定义接口'
        SETTINGS['api_endpoint'] = self.api_endpoint.text().strip()
        SETTINGS['api_model'] = self.api_model_combo.currentText().strip()
        SETTINGS['api_key'] = self.api_key_input.text().strip()
        save_settings()

    def _about(self):
        """显示关于对话框"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.about(self, "关于 清月的打标工具",
            """<h2>清月的打标工具 v1.0</h2>
<hr>
<p><b>程序功能：</b></p>
<ul>
<li>数据集浏览：目录树导航 + 虚拟滚动缩略图网格</li>
<li>标签编辑：平铺/分组模式、批量管理、标签统计、导入导出</li>
<li>裁切编辑：选区裁切、亮度/对比度调节、涂抹抹除</li>
<li>标签反推：WD14 本地反推 / 大模型 API / 自定义接口</li>
<li>AI 聊天：对话交流、图片生成、标签修改</li>
<li>批量操作：重命名、缩放、格式转换（带进度条）</li>
<li>标签翻译：本地词典 + 大模型 API / 在线翻译兜底</li>
</ul>
<hr>
<p><b>简易使用说明：</b></p>
<ol>
<li>点击「打开数据集」选择图片文件夹</li>
<li>左侧目录树选择文件夹查看图片</li>
<li>双击图片进入裁切页面</li>
<li>右键图片选择进入标签/反推页面</li>
<li>标签页右键标签可翻译、删除、移动分组</li>
<li>反推页选择引擎后点击单张/批量反推</li>
<li>数据集操作栏可批量重命名/缩放/格式转换</li>
<li>所有设置自动保存，可在设置页调整</li>
</ol>
<hr>
<p><b>程序名：</b>清月的打标工具</p>
<p><b>作者：</b>清月</p>
<p><b>所有者：</b>清月</p>
<p><b>联系方式：</b>3301682512@qq.com</p>
<hr>
<p><b>使用开源项目：</b></p>
<ul>
<li>Python 3.11+ (PSF License)</li>
<li>PySide6 (LGPL-3.0)</li>
<li>Pillow (Historical Permission Notice)</li>
<li>requests (Apache-2.0)</li>
<li>ONNX Runtime (MIT)</li>
<li>WD14 Tagger (SmilingWolf, Apache-2.0)</li>
</ul>
<p><b>制作工具：</b>Reasonix Code (AI 辅助编程)</p>""")

    def _reset_defaults(self):
        """恢复所有设置为默认值"""
        if QMessageBox.question(self, "确认", "恢复所有设置为默认值？\n（语言/主题/缩略图/API配置等将重置）") != QMessageBox.Yes:
            return
        # 断开自动保存信号避免逐项触发
        self._disconnect_auto_save()
        global SETTINGS
        SETTINGS = dict(_DEFAULT)
        # 更新所有控件
        self.lang_combo.setCurrentIndex(0)
        self.theme_combo.setCurrentIndex(0)
        self.size_spin.setValue(_DEFAULT['thumb_size'])
        self.spacing_spin.setValue(_DEFAULT['spacing'])
        self.label_h_spin.setValue(_DEFAULT['label_height'])
        self.trans_method_combo.setCurrentIndex(0)
        self.api_provider_combo.setCurrentIndex(0)
        self._on_api_provider_changed(0)
        self.api_key_input.setText('')
        self._apply_theme_now()
        save_settings()
        self._reconnect_auto_save()
        QMessageBox.information(self, "完成", "已恢复默认设置")

    def _disconnect_auto_save(self):
        self.lang_combo.currentIndexChanged.disconnect(self._auto_save)
        self.theme_combo.currentIndexChanged.disconnect(self._auto_save)
        self.size_spin.valueChanged.disconnect(self._auto_save)
        self.spacing_spin.valueChanged.disconnect(self._auto_save)
        self.label_h_spin.valueChanged.disconnect(self._auto_save)
        self.trans_method_combo.currentIndexChanged.disconnect(self._auto_save)
        self.api_provider_combo.currentIndexChanged.disconnect(self._auto_save)
        self.api_endpoint.textChanged.disconnect(self._auto_save)
        self.api_model_combo.currentTextChanged.disconnect(self._auto_save)
        self.api_key_input.textChanged.disconnect(self._auto_save)

    def _reconnect_auto_save(self):
        self.lang_combo.currentIndexChanged.connect(self._auto_save)
        self.theme_combo.currentIndexChanged.connect(self._auto_save)
        self.size_spin.valueChanged.connect(self._auto_save)
        self.spacing_spin.valueChanged.connect(self._auto_save)
        self.label_h_spin.valueChanged.connect(self._auto_save)
        self.trans_method_combo.currentIndexChanged.connect(self._auto_save)
        self.api_provider_combo.currentIndexChanged.connect(self._auto_save)
        self.api_endpoint.textChanged.connect(self._auto_save)
        self.api_model_combo.currentTextChanged.connect(self._auto_save)
        self.api_key_input.textChanged.connect(self._auto_save)

    def _manual_save(self):
        """手动保存并提示"""
        self._auto_save()
        QMessageBox.information(self, "已保存", "设置已保存到 settings.json")

    def _apply_theme_now(self):
        """即时切换主题"""
        from .themes import THEMES
        theme_name = 'dark' if 'Dark' in self.theme_combo.currentText() else 'light'
        QApplication.instance().setPalette(THEMES.get(theme_name, THEMES['dark'])())

    def _on_api_provider_changed(self, index):
        """服务商变更时更新模型列表和端点"""
        name = self.api_provider_combo.currentText()
        info = API_PROVIDERS.get(name, {})
        # 更新端点
        if info.get("endpoint"):
            self.api_endpoint.setText(info["endpoint"])
        # 更新模型列表
        self.api_model_combo.clear()
        for m in info.get("models", ["自定义模型"]):
            self.api_model_combo.addItem(m)
        self.api_model_combo.setCurrentIndex(0)

    def _test_api_connection(self):
        """测试API连接，获取可用模型列表"""
        endpoint = self.api_endpoint.text().strip()
        api_key = self.api_key_input.text().strip()
        if not endpoint:
            QMessageBox.warning(self, "提示", "请先填写API端点")
            return
        # 从chat/completions端点提取base URL
        base_url = endpoint.rsplit('/v1/', 1)[0] + '/v1' if '/v1/' in endpoint else endpoint.rsplit('/chat/', 1)[0] if '/chat/' in endpoint else endpoint.rstrip('/')
        models_url = f"{base_url}/models"

        self.btn_test_conn.setText("⏳ 测试中...")
        self.btn_test_conn.setEnabled(False)
        QApplication.processEvents()

        try:
            import requests
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            resp = requests.get(models_url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                models = []
                if "data" in data:
                    models = [m["id"] for m in data["data"] if not m.get("id", "").startswith(("whisper", "tts", "dall-e", "davinci", "babbage", "ada"))]
                elif "models" in data:
                    models = data["models"] if isinstance(data["models"], list) else [data["models"]]
                if models:
                    self.api_model_combo.clear()
                    for m in models[:50]:  # 限制50个
                        self.api_model_combo.addItem(m)
                    QMessageBox.information(self, "成功", f"获取到 {len(models)} 个模型")
                else:
                    QMessageBox.information(self, "提示", "连接成功，但未获取到模型列表，请手动输入模型ID")
            else:
                QMessageBox.warning(self, "获取失败",
                    f"HTTP {resp.status_code}\n请确认端点地址和Key正确，或手动输入模型ID。\n\n常见端点格式:\nOpenAI: https://api.openai.com/v1\n通义千问: https://dashscope.aliyuncs.com/compatible-mode/v1\nllama.cpp: http://127.0.0.1:8080/v1")
        except Exception as e:
            QMessageBox.warning(self, "连接失败",
                f"无法连接到API:\n{str(e)[:200]}\n\n请手动输入模型ID或检查端点地址。")
        finally:
            self.btn_test_conn.setText("🔌 测试连接")
            self.btn_test_conn.setEnabled(True)

class ImageListModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._images: List[ImageItem] = []
        self._pixmaps: Dict[int, QPixmap] = {}
        self._ph = QPixmap(150, 150); self._ph.fill(QColor(0, 0, 0, 0))
        self._gen_key = "0"

    def rowCount(self, parent=QModelIndex()): return len(self._images)
    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._images): return None
        img = self._images[index.row()]
        if role == Qt.DisplayRole: return img.name
        if role == Qt.DecorationRole: return self._pixmaps.get(index.row(), self._ph)
        if role == Qt.UserRole: return img
        if role == Qt.ToolTipRole:
            img.ensure_labels()
            return f"{img.name}\n标签: {len(img.labels)}"
        return None

    def set_images(self, images): self.beginResetModel(); self._images = list(images); self._pixmaps.clear(); self.endResetModel()
    def set_thumbnail(self, row, pix): self._pixmaps[row] = pix; self.dataChanged.emit(self.index(row, 0), self.index(row, 0), [Qt.DecorationRole])
    def image_at(self, row): return self._images[row] if 0 <= row < len(self._images) else None

    @Slot(int, str, QPixmap)
    def _on_thumb(self, idx, gen_key, pix):
        if gen_key != self._gen_key: return
        self.set_thumbnail(idx, pix)


class ThumbDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent); self._size = SETTINGS['thumb_size']
    def paint(self, painter, option, index):
        painter.save(); r = option.rect; sz = self._size
        pix = index.data(Qt.DecorationRole)
        if pix and not pix.isNull():
            margin = 3
            max_w = r.width() - margin * 2
            max_h = sz - margin * 2
            pix2 = pix.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            # 水平+垂直居中在 sz×r.width() 区域内
            px = r.x() + (r.width() - pix2.width()) // 2
            py = r.y() + (sz - pix2.height()) // 2
            painter.drawPixmap(px, py, pix2)
        # 文件名（缩略图下方紧贴）
        name = (index.data(Qt.DisplayRole) or "")[:18]
        painter.setPen(QColor("#999"))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(r.adjusted(2, sz, -2, 0), Qt.AlignCenter, name)
        # 标签数量徽章
        img = index.data(Qt.UserRole)
        if img and img.labels:
            badge_w = 30; badge_h = 14
            badge_x = r.x() + r.width() - badge_w - 4
            badge_y = r.y() + 2
            painter.fillRect(badge_x, badge_y, badge_w, badge_h, QColor(0, 0, 0, 160))
            painter.setPen(QColor("#ccc"))
            painter.setFont(QFont("Segoe UI", 7))
            painter.drawText(badge_x, badge_y, badge_w, badge_h, Qt.AlignCenter, f"🏷{len(img.labels)}")
        painter.restore()
    def sizeHint(self, o, i):
        s = self._size
        # 文件名高度 + 行间距（避免文件名与下一行图片连在一起）
        return QSize(s, s + SETTINGS.get('label_height', 10) + 4)


class _ThumbTask(QRunnable):
    def __init__(self, idx, path, gen_key, model):
        super().__init__(); self.idx = idx; self.path = path; self.gen_key = gen_key; self._model = model
    def run(self):
        if self._model._gen_key != self.gen_key: return  # aborted
        try:
            s = SETTINGS['thumb_size']
            reader = QImageReader(self.path)
            reader.setScaledSize(QSize(s, s))
            reader.setAutoTransform(True)
            thumb = QPixmap.fromImageReader(reader)
            if not thumb.isNull():
                QMetaObject.invokeMethod(self._model, '_on_thumb', Qt.QueuedConnection,
                    Q_ARG(int, self.idx), Q_ARG(str, self.gen_key), Q_ARG(QPixmap, thumb))
        except: pass


class VirtualImageGrid(QWidget):
    image_clicked = Signal(object); image_double_clicked = Signal(object)
    image_context_menu = Signal(object, object)  # img, global_pos
    def __init__(self, parent=None):
        super().__init__(parent)
        self._list = QListView(); self._list.setViewMode(QListView.IconMode)
        self._list.setResizeMode(QListView.Adjust); self._list.setMovement(QListView.Static)
        self._list.setSelectionMode(QListView.SingleSelection); self._list.setUniformItemSizes(True); self._list.setWrapping(True)
        self._model = ImageListModel(); self._delegate = ThumbDelegate()
        self._list.setModel(self._model); self._list.setItemDelegate(self._delegate)
        self._list.doubleClicked.connect(lambda i: self.image_double_clicked.emit(self._model.image_at(i.row())))
        self._list.clicked.connect(lambda i: self.image_clicked.emit(self._model.image_at(i.row())))
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        layout = QVBoxLayout(self); layout.setContentsMargins(4, 4, 4, 4); layout.addWidget(self._list)
        self._pool = QThreadPool.globalInstance(); self._pool.setMaxThreadCount(4)
        self._gen = 0; self._loaded = set()
        self._scroll_timer = QTimer(self); self._scroll_timer.setInterval(80)
        self._scroll_timer.setSingleShot(True); self._scroll_timer.timeout.connect(self._schedule_visible)
        self._list.verticalScrollBar().valueChanged.connect(lambda _: self._scroll_timer.start())

    def set_images(self, images):
        self._gen += 1; self._loaded.clear()
        # Cancel old tasks: gen_key check + clear pool queue
        self._pool.clear()
        self._model._gen_key = str(self._gen)
        self._model.set_images(images)
        sz = SETTINGS['thumb_size']; self._delegate._size = sz
        spacing = SETTINGS.get('spacing', 2)
        label_h = SETTINGS.get('label_height', 10) + 4  # +4px 行间距
        row_h = sz + label_h
        grid_w = sz + max(0, spacing)
        self._list.setIconSize(QSize(sz, sz)); self._list.setGridSize(QSize(grid_w, row_h))
        if images: QTimer.singleShot(5, self._schedule_visible)
        QTimer.singleShot(100, self._update_grid)

    def _update_grid(self):
        """viewport 就绪后重新设置网格"""
        sz = SETTINGS['thumb_size']
        spacing = SETTINGS.get('spacing', 2)
        label_h = SETTINGS.get('label_height', 10) + 4
        row_h = sz + label_h
        grid_w = sz + max(0, spacing)
        self._list.setGridSize(QSize(grid_w, row_h))

    def _visible_range(self):
        sz = SETTINGS['thumb_size']
        spacing = SETTINGS.get('spacing', 2)
        label_h = SETTINGS.get('label_height', 10) + 4
        row_h = sz + label_h
        cell_w = sz + max(0, spacing)
        vw = self._list.viewport().width()
        cols = max(1, vw // max(cell_w, 1)) if vw > 0 else 4
        rows = max(1, self._list.viewport().height() // row_h + 1)
        y = self._list.verticalScrollBar().value()
        first = max(0, (y // row_h) * cols - cols * 2)
        last = min(len(self._model._images), first + cols * (rows + 4))
        return first, last

    def _schedule_visible(self):
        gen_key = str(self._gen)
        imgs = self._model._images
        if not imgs: return
        first, last = self._visible_range()
        # 只保留可见区域附近的缓存（±100张），超出即释放
        keep_s, keep_e = max(0, first - 100), min(len(imgs), last + 100)
        for k in list(self._model._pixmaps):
            if k < keep_s or k > keep_e: del self._model._pixmaps[k]

        # 逐批加载可见区域，一次只提交少量任务（模拟Windows渐进加载）
        submitted = 0
        batch_limit = 8  # 每批最多8张
        preload_end = min(last + 6, len(imgs))  # 仅比可见区域多预加载6张
        for i in range(first, preload_end):
            if submitted >= batch_limit:
                break
            if i not in self._loaded and i < len(imgs):
                self._loaded.add(i)
                task = _ThumbTask(i, imgs[i].file_path, gen_key, self._model)
                task.setAutoDelete(True)
                self._pool.start(task)
                submitted += 1

        # 如果可见区域内还有未加载完成的，延迟再触发加载
        still_missing = any(
            i < len(imgs) and i >= first and i < preload_end and i not in self._model._pixmaps
            for i in range(first, preload_end)
        )
        if still_missing:
            QTimer.singleShot(80, self._schedule_visible)

    def _on_context_menu(self, pos):
        index = self._list.indexAt(pos)
        img = self._model.image_at(index.row()) if index.isValid() else None
        self.image_context_menu.emit(img, self._list.viewport().mapToGlobal(pos))

    def clear(self): self._gen += 1; self._loaded.clear(); self._model.set_images([])
    @property
    def images(self): return list(self._model._images)


class MiniImageStrip(QWidget):
    image_selected = Signal(object)
    image_right_clicked = Signal(object, object)  # img, global_pos
    _thumb_cache = {}  # 全局缩略图缓存 {file_path: QPixmap}
    def __init__(self, parent=None):
        super().__init__(parent); self.setFixedHeight(56)
        self._images = []; self._labels = []; self._gen = 0
        self._cached_images = None
        layout = QHBoxLayout(self); layout.setContentsMargins(4, 2, 4, 2)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setFixedHeight(50)
        self._scroll.viewport().installEventFilter(self)
        layout.addWidget(self._scroll)
        self._strip = QWidget(); self._strip_layout = QHBoxLayout(self._strip)
        self._strip_layout.setContentsMargins(0, 0, 0, 0); self._strip_layout.setSpacing(3)
        self._scroll.setWidget(self._strip); self._li = 0

    def set_images(self, images):
        # 缓存判断：如果是同一个图片列表（引用相同），不重建
        if images is self._cached_images:
            return
        self._cached_images = images
        self._gen += 1; gen = self._gen; self._images = list(images); self._labels.clear()
        while self._strip_layout.count() > 1:
            w = self._strip_layout.takeAt(0)
            if w.widget(): w.widget().deleteLater()
        if not images:
            self._strip.adjustSize()
            return
        for i, img in enumerate(images):
            lbl = QLabel(); lbl.setFixedSize(44, 44); lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("border:2px solid #2a2a4a; border-radius:4px;")
            lbl.setToolTip(f"{img.name}\n{len(img.labels)} tags")
            ii = i; lbl.mousePressEvent = lambda e, ii=ii, im=img: self._click(ii, im, e)
            self._labels.append(lbl); self._strip_layout.insertWidget(self._strip_layout.count() - 1, lbl)
        self._li = 0
        self._strip.adjustSize()  # 更新内部widget尺寸以触发滚动条
        QTimer.singleShot(20, lambda: self._load(gen))

    def eventFilter(self, obj, event):
        """将滚轮事件转为水平滚动"""
        if obj == self._scroll.viewport() and event.type() == QEvent.Type.Wheel:
            delta = event.angleDelta().y()
            bar = self._scroll.horizontalScrollBar()
            bar.setValue(bar.value() - delta)
            return True
        return super().eventFilter(obj, event)

    def _click(self, idx, img, event):
        if event.button() == Qt.LeftButton:
            for i, lbl in enumerate(self._labels):
                lbl.setStyleSheet("border:2px solid #e94560; border-radius:4px;" if i == idx else "border:2px solid #2a2a4a; border-radius:4px;")
            self.image_selected.emit(img)
        elif event.button() == Qt.RightButton:
            if idx < len(self._labels):
                self.image_right_clicked.emit(img, self._labels[idx].mapToGlobal(event.pos()))

    def _load(self, gen):
        if gen != self._gen: return
        batch = 50; count = 0
        while self._li < len(self._images) and count < batch and gen == self._gen:
            img = self._images[self._li]; idx = self._li; self._li += 1; count += 1
            try:
                # 全局缓存命中
                if img.file_path in MiniImageStrip._thumb_cache:
                    pix = MiniImageStrip._thumb_cache[img.file_path]
                else:
                    reader = QImageReader(img.file_path)
                    reader.setScaledSize(QSize(40, 40))
                    pix = QPixmap.fromImageReader(reader)
                    if not pix.isNull():
                        MiniImageStrip._thumb_cache[img.file_path] = pix
                        # 缓存上限 2000 张，超出清空一半
                        if len(MiniImageStrip._thumb_cache) > 2000:
                            keys = list(MiniImageStrip._thumb_cache.keys())[:1000]
                            for k in keys:
                                del MiniImageStrip._thumb_cache[k]
                if not pix.isNull() and idx < len(self._labels):
                    self._labels[idx].setPixmap(pix)
            except: pass
        if self._li < len(self._images) and gen == self._gen:
            QTimer.singleShot(80, lambda: self._load(gen))
