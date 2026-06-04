# -*- coding: utf-8 -*-
"""Inference panel for WD14 / llama.cpp / cloud LLM tag reverse inference."""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QLineEdit, QTextEdit, QListWidget, QListWidgetItem,
    QSlider, QProgressBar, QMessageBox, QCheckBox, QFormLayout,
)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QFont
from typing import Optional, List
from .models import ImageItem
import requests
import json
import base64
import time


class InferPanelWidget(QWidget):
    """Tag inference panel supporting local APIs + cloud LLM (OpenAI/Tongyi etc.)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_image: Optional[ImageItem] = None
        self._current_tags: list = []
        self._batch_job_running = False
        self._batch_cancel = False
        self._wd14_models_info = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 1. Engine selection
        engine_row = QHBoxLayout()
        engine_row.addWidget(QLabel("推理引擎:"))
        self.engine_combo = QComboBox()
        self.engine_combo.addItems([
            "WD14 标签反推",
            "大模型反推 (设置API)",
            "手动输入",
            "自定义接口"
        ])
        self.engine_combo.currentIndexChanged.connect(self._on_engine_change)
        engine_row.addWidget(self.engine_combo)
        engine_row.addStretch()
        layout.addLayout(engine_row)

        # 2. API Configuration (WD14地址 或 自定义URL)
        self.api_url_row = QHBoxLayout()
        self.api_url_row.addWidget(QLabel("API 地址:"))
        self.api_input = QLineEdit("http://localhost:7860/wd14/predict")
        self.api_url_row.addWidget(self.api_input)
        layout.addLayout(self.api_url_row)

        # WD14 模型选择（仅WD14模式下显示）
        self._wd14_model_row = QHBoxLayout()
        self._wd14_model_row.addWidget(QLabel("模型:"))
        self._wd14_model_combo = QComboBox()
        self._wd14_model_combo.addItem("（点击 [获取模型列表] 按钮）")
        self._wd14_model_combo.currentTextChanged.connect(self._on_wd14_model_selected)
        self._wd14_model_row.addWidget(self._wd14_model_combo, 1)
        self._btn_fetch_wd14_models = QPushButton("📋 获取模型列表")
        self._btn_fetch_wd14_models.clicked.connect(self._fetch_wd14_models)
        self._wd14_model_row.addWidget(self._btn_fetch_wd14_models)
        layout.addLayout(self._wd14_model_row)
        self._wd14_model_desc = QLabel("需要先运行「启动WD14.bat」启动本地服务，然后点击「获取模型列表」")
        self._wd14_model_desc.setStyleSheet("color:#888; font-size:10px;")
        self._wd14_model_desc.setWordWrap(True)
        layout.addWidget(self._wd14_model_desc)
        self._wd14_model_combo.hide()
        self._wd14_model_desc.hide()
        self._btn_fetch_wd14_models.hide()

        # 3. Threshold / Parameters
        self.param_row = QHBoxLayout()
        self.param_row.addWidget(QLabel("置信度阈值:"))
        self.threshold_slider = QSlider(Qt.Horizontal)
        self.threshold_slider.setRange(5, 95)
        self.threshold_slider.setValue(35)
        self.param_row.addWidget(self.threshold_slider)
        self.lbl_threshold = QLabel("0.35")
        self.threshold_slider.valueChanged.connect(lambda v: self.lbl_threshold.setText(f"{v/100:.2f}"))
        self.param_row.addWidget(self.lbl_threshold)
        self.param_row.addStretch()
        layout.addLayout(self.param_row)

        # 4. Actions (Single + Batch)
        action_row = QHBoxLayout()
        self.btn_infer_single = QPushButton("🚀 单张反推")
        self.btn_infer_single.clicked.connect(self.run_single_inference)
        action_row.addWidget(self.btn_infer_single)

        self.btn_batch_infer = QPushButton("📦 批量反推")
        self.btn_batch_infer.clicked.connect(self.run_batch_inference)
        action_row.addWidget(self.btn_batch_infer)

        self.btn_cancel = QPushButton("❌ 取消")
        self.btn_cancel.clicked.connect(self.cancel_inference)
        self.btn_cancel.setEnabled(False)
        action_row.addWidget(self.btn_cancel)

        self.btn_clear = QPushButton("🗑 清空结果")
        self.btn_clear.clicked.connect(self.clear_results)
        action_row.addWidget(self.btn_clear)
        action_row.addStretch()
        layout.addLayout(action_row)

        # 5. Batch Settings (参考HTML工具的批量配置)
        batch_config_row = QHBoxLayout()
        batch_config_row.addWidget(QLabel("批量范围:"))
        self.batch_scope = QComboBox()
        self.batch_scope.addItems(["当前选中图片", "手动选择文件夹", "当前文件夹及子目录", "全部目录图片"])
        self.batch_scope.currentTextChanged.connect(self._save_batch_settings)
        batch_config_row.addWidget(self.batch_scope)

        batch_config_row.addWidget(QLabel("并发数:"))
        self.batch_concurrency = QComboBox()
        self.batch_concurrency.addItems(["1", "2", "4"])
        self.batch_concurrency.currentTextChanged.connect(self._save_batch_settings)
        batch_config_row.addWidget(self.batch_concurrency)

        batch_config_row.addWidget(QLabel("重试次数:"))
        self.batch_retry = QComboBox()
        self.batch_retry.addItems(["0", "1", "2"])
        self.batch_retry.currentTextChanged.connect(self._save_batch_settings)
        batch_config_row.addWidget(self.batch_retry)

        batch_config_row.addWidget(QLabel("标签模式:"))
        self.batch_tag_mode = QComboBox()
        self.batch_tag_mode.addItems(["追加到已有", "替换全部标签"])
        self.batch_tag_mode.currentTextChanged.connect(self._save_batch_settings)
        batch_config_row.addWidget(self.batch_tag_mode)
        batch_config_row.addWidget(QLabel(" "))
        btn_reset_batch = QPushButton("🔄 恢复默认")
        btn_reset_batch.setMaximumWidth(100)
        btn_reset_batch.clicked.connect(self._reset_batch_settings)
        batch_config_row.addWidget(btn_reset_batch)
        layout.addLayout(batch_config_row)

        # 从设置恢复批量配置
        from .image_grid import SETTINGS
        self._restore_batch_settings()

        # 阈值也保存
        self.threshold_slider.valueChanged.connect(self._save_batch_settings)

        # 6. Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        # 7. Results List（右键菜单：全选/取消/反选）
        self.results_list = QListWidget()
        self.results_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.results_list.customContextMenuRequested.connect(self._on_results_context_menu)
        layout.addWidget(self.results_list)

        # 8. Apply Buttons (for single result)
        apply_row = QHBoxLayout()
        self.btn_replace = QPushButton("🔄 替换当前图片标签")
        self.btn_replace.clicked.connect(lambda: self._apply_single_tags("replace"))
        apply_row.addWidget(self.btn_replace)
        self.btn_append = QPushButton("➕ 追加到当前图片")
        self.btn_append.clicked.connect(lambda: self._apply_single_tags("append"))
        apply_row.addStretch()
        layout.addLayout(apply_row)

        # 9. Prompt 模板管理
        self.prompt_row = QVBoxLayout()
        prompt_header = QHBoxLayout()
        self.prompt_label = QLabel("反推提示词 (仅大模型用):")
        prompt_header.addWidget(self.prompt_label)
        prompt_header.addStretch()
        # 模板选择
        self.prompt_template_combo = QComboBox()
        self.prompt_template_combo.setMinimumWidth(120)
        self.prompt_template_combo.setToolTip("选择提示词模板")
        self.prompt_template_combo.currentTextChanged.connect(self._on_prompt_template_changed)
        prompt_header.addWidget(QLabel("模板:"))
        prompt_header.addWidget(self.prompt_template_combo)
        # 保存模板按钮
        btn_save_template = QPushButton("💾 保存为模板")
        btn_save_template.clicked.connect(self._save_prompt_template)
        prompt_header.addWidget(btn_save_template)
        # 删除模板按钮
        btn_del_template = QPushButton("🗑")
        btn_del_template.setMaximumWidth(30)
        btn_del_template.clicked.connect(self._delete_prompt_template)
        prompt_header.addWidget(btn_del_template)
        self.prompt_row.addLayout(prompt_header)

        self.prompt_text = QTextEdit()
        self.prompt_text.setPlaceholderText("如：请分析这张图片，生成LoRA训练用的标签，按类别描述...")
        self.prompt_text.setPlainText("分析这张图片，生成用于AI绘图LoRA训练的正向标签，描述风格、内容、细节，用中文逗号分隔，重点描述画面主体、服装、背景、画质细节，不要解释。")
        self.prompt_row.addWidget(self.prompt_text)

        # 独立API配置（默认隐藏）
        self._independent_api_widget = QWidget()
        ial = QFormLayout(self._independent_api_widget)
        ial.setContentsMargins(0, 4, 0, 0)
        self._independent_api_check = QCheckBox("使用独立API配置（与设置中的API分开）")
        self._independent_api_check.toggled.connect(self._on_independent_api_toggled)
        ial.addRow(self._independent_api_check)
        self._indie_endpoint = QLineEdit()
        self._indie_endpoint.setPlaceholderText("https://api.openai.com/v1/chat/completions")
        self._indie_endpoint.setVisible(False)
        ial.addRow("独立端点:", self._indie_endpoint)
        self._indie_model = QLineEdit()
        self._indie_model.setPlaceholderText("gpt-4o")
        self._indie_model.setVisible(False)
        ial.addRow("独立模型:", self._indie_model)
        self._indie_key = QLineEdit()
        self._indie_key.setPlaceholderText("sk-...")
        self._indie_key.setEchoMode(QLineEdit.Password)
        self._indie_key.setVisible(False)
        ial.addRow("独立Key:", self._indie_key)
        self.prompt_row.addWidget(self._independent_api_widget)
        layout.addLayout(self.prompt_row)

        # 加载提示词模板
        self._load_prompt_templates()

        # 初始化显示/隐藏对应控件
        self._on_engine_change(0)

    def _on_engine_change(self, index):
        """根据选中的引擎调整UI"""
        engine = self.engine_combo.currentText()
        if "大模型" in engine:
            from .image_grid import SETTINGS
            provider = SETTINGS.get('api_provider', 'OpenAI')
            model = SETTINGS.get('api_model', 'gpt-4o')
            self.api_url_row.itemAt(0).widget().setText("使用设置中的API:")
            self.api_input.setText(f"{provider} / {model}")
            self.api_input.setReadOnly(True)
            self.prompt_label.setVisible(True)
            self.prompt_text.setVisible(True)
            self.prompt_template_combo.setVisible(True)
            self._independent_api_widget.setVisible(True)
            self._wd14_model_combo.setVisible(False)
            self._wd14_model_desc.setVisible(False)
            self._btn_fetch_wd14_models.setVisible(False)
        elif "WD14" in engine:
            self.api_url_row.itemAt(0).widget().setText("WD14 API 地址:")
            self.api_input.setReadOnly(False)
            self.api_input.setPlaceholderText("http://localhost:7860/wd14/predict")
            self.prompt_label.setVisible(False)
            self.prompt_text.setVisible(False)
            self.prompt_template_combo.setVisible(False)
            self._independent_api_widget.setVisible(False)
            self._wd14_model_combo.setVisible(True)
            self._wd14_model_desc.setVisible(True)
            self._btn_fetch_wd14_models.setVisible(True)
            self._wd14_model_desc.setText(
                "请确保已运行「启动WD14.bat」启动本地服务。\n"
                "然后点击「📋 获取模型列表」查看已安装的模型。\n"
                "模型存放位置: wd14/models/"
            )
        elif "自定义" in engine:
            self.api_url_row.itemAt(0).widget().setText("自定义 API 地址:")
            self.api_input.setReadOnly(False)
            self.api_input.setPlaceholderText("输入API接口地址")
            self.prompt_label.setVisible(True)
            self.prompt_text.setVisible(True)
            self._wd14_model_combo.setVisible(False)
            self._wd14_model_desc.setVisible(False)
            self._btn_fetch_wd14_models.setVisible(False)
        else:
            self.api_url_row.itemAt(0).widget().setText("API 地址:")
            self.api_input.setReadOnly(False)
            self.api_input.setPlaceholderText("输入API接口地址")
            self.prompt_label.setVisible(False)
            self.prompt_text.setVisible(False)
            self._wd14_model_combo.setVisible(False)
            self._wd14_model_desc.setVisible(False)
            self._btn_fetch_wd14_models.setVisible(False)

    def set_image(self, img: ImageItem):
        """设置当前单张图片（来自主界面）"""
        self._current_image = img
        self.results_list.clear()

    def run_single_inference(self):
        """单张图片反推"""
        if not self._current_image:
            QMessageBox.warning(self, "提示", "请先在数据集中选择一张图片")
            return

        engine = self.engine_combo.currentText()

        # 手动输入模式：弹出对话框直接输入标签
        if engine == "手动输入":
            from PySide6.QtWidgets import QInputDialog
            text, ok = QInputDialog.getText(self, "手动输入", "输入标签（逗号分隔）:")
            if ok and text:
                tags = [(t.strip(), 1.0) for t in text.split(",") if t.strip()]
                self._current_tags = tags
                self.results_list.clear()
                for tag, conf in tags:
                    item = QListWidgetItem(f"{tag}  ({conf*100:.0f}%)")
                    item.setData(Qt.UserRole, tag)
                    item.setCheckState(Qt.Checked)
                    self.results_list.addItem(item)
            return

        api_url = self.api_input.text().strip()
        if not api_url and engine != "大模型反推 (设置API)":
            QMessageBox.warning(self, "错误", "请输入API地址")
            return

        self.btn_infer_single.setEnabled(False)
        self.btn_batch_infer.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress_bar.setValue(0)
        self.results_list.clear()

        # 大模型模式：获取独立或共享的API配置
        llm_config = self._get_llm_config() if "大模型" in engine else (None, None, None)

        self._infer_thread = QThread()
        self._infer_worker = InferenceWorker(
            engine=engine,
            api_url=api_url,
            image_path=self._current_image.file_path,
            threshold=self.threshold_slider.value()/100,
            prompt=self.prompt_text.toPlainText().strip(),
            llm_endpoint=llm_config[0],
            llm_model=llm_config[1],
            llm_key=llm_config[2]
        )
        self._infer_worker.moveToThread(self._infer_thread)
        self._infer_worker.finished.connect(self._on_single_infer_done)
        self._infer_worker.error.connect(self._on_infer_error)
        self._infer_thread.started.connect(self._infer_worker.run)
        self._infer_thread.start()

    def _on_single_infer_done(self, tags: list):
        """单张反推完成，显示结果"""
        self._infer_thread.quit()
        self._current_tags = tags
        self.results_list.clear()
        for tag, conf in tags:
            item = QListWidgetItem(f"{tag}  ({conf*100:.0f}%)")
            item.setData(Qt.UserRole, tag)
            item.setCheckState(Qt.Checked)
            self.results_list.addItem(item)

        self.progress_bar.setValue(100)
        self.btn_infer_single.setEnabled(True)
        self.btn_batch_infer.setEnabled(True)
        self.btn_cancel.setEnabled(False)

    def run_batch_inference(self):
        """批量反推（参考HTML工具的批量功能）"""
        # 获取需要处理的图片列表
        from .main_window import MainWindow
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        parent = self.parent()
        images = []
        scope = self.batch_scope.currentText()
        
        if scope == "手动选择文件夹":
            # 弹出文件夹选择对话框，支持多选文件夹
            dir_paths, _ = QFileDialog.getOpenFileNames(
                self, "选择需要反推的文件夹", "", 
                "所有文件 (*);;目录 (*)", 
                options=QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
            )
            if not dir_paths:
                return
            # 扫描所有选中的文件夹，合并图片
            from .scanner import scan_directory
            for dir_path in dir_paths:
                tree = scan_directory(dir_path)
                if tree:
                    images.extend(tree.get_all_images())
        
        elif isinstance(parent, MainWindow):
            if scope == "当前选中图片":
                # 尝试获取选中的图片（简化：取当前图片列表中选中的，这里先取当前文件夹的）
                images = parent.current_images
            elif scope == "当前文件夹" or scope == "当前文件夹及子目录":
                images = parent.current_images
                # 如果是当前文件夹及子目录，需要递归获取子目录图片
                if scope == "当前文件夹及子目录" and hasattr(parent, 'current_node') and parent.current_node:
                    images = parent.current_node.get_all_images()
            else: # 全部目录图片
                if hasattr(parent, 'tree_root') and parent.tree_root:
                    images = parent.tree_root.get_all_images()
        
        if not images:
            QMessageBox.warning(self, "提示", "没有找到需要处理的图片")
            return

        # 开始批量反推
        self._batch_job_running = True
        self._batch_cancel = False
        self.btn_batch_infer.setEnabled(False)
        self.btn_infer_single.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress_bar.setValue(0)
        total = len(images)
        concurrency = int(self.batch_concurrency.currentText())
        retry = int(self.batch_retry.currentText())
        mode = self.batch_tag_mode.currentText()

        # 获取大模型配置
        llm_config = self._get_llm_config() if "大模型" in self.engine_combo.currentText() else (None, None, None)

        # 启动批量处理线程
        self._batch_thread = QThread()
        self._batch_worker = BatchInferenceWorker(
            engine=self.engine_combo.currentText(),
            api_url=self.api_input.text().strip(),
            images=images,
            threshold=self.threshold_slider.value()/100,
            concurrency=concurrency,
            retry=retry,
            mode=mode,
            prompt=self.prompt_text.toPlainText().strip(),
            llm_endpoint=llm_config[0],
            llm_model=llm_config[1],
            llm_key=llm_config[2]
        )
        self._batch_worker.moveToThread(self._batch_thread)
        self._batch_worker.progress.connect(self._on_batch_progress)
        self._batch_worker.finished.connect(self._on_batch_done)
        self._batch_worker.error.connect(self._on_infer_error)
        self._batch_thread.started.connect(self._batch_worker.run)
        self._batch_thread.start()

    def _on_batch_progress(self, current: int, total: int):
        """批量反推进度更新"""
        progress = int((current / total) * 100)
        self.progress_bar.setValue(progress)
        self.progress_bar.setFormat(f"{current}/{total} 张")

    def _on_batch_done(self, success_count: int, fail_count: int):
        """批量反推完成"""
        self._batch_thread.quit()
        self._batch_job_running = False
        self.btn_batch_infer.setEnabled(True)
        self.btn_infer_single.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress_bar.setFormat(f"完成: 成功 {success_count} 张，失败 {fail_count} 张")
        QMessageBox.information(self, "批量反推完成", f"成功 {success_count} 张，失败 {fail_count} 张")

    def cancel_inference(self):
        """取消当前反推任务"""
        if hasattr(self, '_batch_worker') and self._batch_worker:
            self._batch_worker._cancel = True
        self.btn_cancel.setEnabled(False)
        self.btn_infer_single.setEnabled(True)
        self.btn_batch_infer.setEnabled(True)

    def clear_results(self):
        """清空结果列表"""
        self.results_list.clear()
        self._current_tags = []
        self.progress_bar.setValue(0)

    def _apply_single_tags(self, mode: str):
        """将单张反推结果应用到当前图片"""
        if not self._current_image:
            return
        tags = []
        for i in range(self.results_list.count()):
            item = self.results_list.item(i)
            if item.checkState() == Qt.Checked:
                tags.append(item.data(Qt.UserRole))

        if not tags:
            return

        if mode == "replace":
            self._current_image.labels = list(tags)
        else:
            for t in tags:
                if t not in self._current_image.labels:
                    self._current_image.labels.append(t)

        QMessageBox.information(self, "完成", f"已{mode == 'replace' and '替换' or '追加'} {len(tags)} 个标签")

    # ===== 提示词模板管理 =====
    def _load_prompt_templates(self):
        """从设置加载提示词模板"""
        from .image_grid import SETTINGS
        templates = SETTINGS.get('infer_prompts', [])
        self._prompt_templates = list(templates)  # [{"name":..., "text":...}]
        self.prompt_template_combo.blockSignals(True)
        self.prompt_template_combo.clear()
        for t in self._prompt_templates:
            self.prompt_template_combo.addItem(t.get("name", "未命名"))
        if not self._prompt_templates:
            self.prompt_template_combo.addItem("（无模板）")
        self.prompt_template_combo.blockSignals(False)

    def _on_prompt_template_changed(self, name):
        """选择模板时加载对应的提示词"""
        if not name or name == "（无模板）":
            return
        for t in self._prompt_templates:
            if t.get("name") == name:
                self.prompt_text.setPlainText(t.get("text", ""))
                return

    def _save_prompt_template(self):
        """保存当前提示词为新模板"""
        from PySide6.QtWidgets import QInputDialog
        from .image_grid import SETTINGS
        current_text = self.prompt_text.toPlainText().strip()
        if not current_text:
            QMessageBox.warning(self, "提示", "提示词为空，无法保存")
            return
        name, ok = QInputDialog.getText(self, "保存模板", "模板名称:")
        if not ok or not name.strip():
            return
        name = name.strip()
        # 更新或新增
        found = False
        for t in self._prompt_templates:
            if t["name"] == name:
                t["text"] = current_text
                found = True
                break
        if not found:
            self._prompt_templates.append({"name": name, "text": current_text})
        # 保存到设置
        SETTINGS['infer_prompts'] = self._prompt_templates
        from .image_grid import save_settings
        save_settings()
        self._load_prompt_templates()
        # 选中刚保存的模板
        idx = self.prompt_template_combo.findText(name)
        if idx >= 0:
            self.prompt_template_combo.setCurrentIndex(idx)

    def _delete_prompt_template(self):
        """删除当前选中的模板"""
        name = self.prompt_template_combo.currentText()
        if not name or name == "（无模板）":
            return
        if QMessageBox.question(self, "确认", f"删除模板「{name}」?") != QMessageBox.Yes:
            return
        self._prompt_templates = [t for t in self._prompt_templates if t["name"] != name]
        from .image_grid import SETTINGS, save_settings
        SETTINGS['infer_prompts'] = self._prompt_templates
        save_settings()
        self._load_prompt_templates()

    def _on_independent_api_toggled(self, checked):
        """切换独立API配置的可见性"""
        self._indie_endpoint.setVisible(checked)
        self._indie_model.setVisible(checked)
        self._indie_key.setVisible(checked)

    def _get_llm_config(self):
        """获取大模型配置：优先独立配置，否则使用设置中的配置"""
        from .image_grid import SETTINGS
        if self._independent_api_check.isChecked():
            endpoint = self._indie_endpoint.text().strip()
            model = self._indie_model.text().strip()
            api_key = self._indie_key.text().strip()
            if endpoint and model and api_key:
                return endpoint, model, api_key
        endpoint = SETTINGS.get('api_endpoint', '')
        model = SETTINGS.get('api_model', 'gpt-4o')
        api_key = SETTINGS.get('api_key', '')
        return endpoint, model, api_key

    def _on_results_context_menu(self, pos):
        """反推结果列表右键菜单"""
        from PySide6.QtWidgets import QMenu
        menu = QMenu()
        menu.addAction("✅ 全选", lambda: self._toggle_all_results(True))
        menu.addAction("⬜ 取消全选", lambda: self._toggle_all_results(False))
        menu.addAction("🔄 反选", self._invert_results)
        menu.exec(self.results_list.viewport().mapToGlobal(pos))

    def _toggle_all_results(self, checked: bool):
        for i in range(self.results_list.count()):
            self.results_list.item(i).setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def _invert_results(self):
        for i in range(self.results_list.count()):
            item = self.results_list.item(i)
            item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)

    # ===== WD14 模型管理 =====
    def _fetch_wd14_models(self):
        """从 WD14 API 获取已安装的模型列表"""
        api_url = self.api_input.text().strip().rstrip('/')
        models_url = f"{api_url.replace('/wd14/predict', '')}/wd14/models"
        try:
            resp = requests.get(models_url, timeout=5)
            if resp.status_code != 200:
                QMessageBox.warning(self, "获取失败", f"无法连接 WD14 服务\n请确认已运行「启动WD14.bat」")
                return
            data = resp.json()
            models_data = data.get("models", {})
            current = data.get("current", "")

            self._wd14_model_combo.clear()
            self._wd14_models_info = {}

            for key, info in models_data.items():
                name = info.get("name", key)
                desc = info.get("desc", "")
                size = info.get("size", "")
                installed = info.get("installed", False)
                status = "✅" if installed else "⬇未下载"
                label = f"{status} {name} ({size})"
                self._wd14_model_combo.addItem(label)
                self._wd14_models_info[label] = {
                    "key": key, "name": name, "desc": desc,
                    "size": size, "installed": installed,
                    "repo": info.get("repo", ""),
                    "note": info.get("note", ""),
                }
                # 高亮当前使用的模型
                if key == current:
                    self._wd14_model_combo.setCurrentText(label)

            # 更新说明
            desc_parts = ["模型存放位置: wd14/models/"]
            for key, info in models_data.items():
                if info.get("installed"):
                    desc_parts.insert(0, f"✅ {info['name']} — {info['desc']}")
                elif not any("未下载" in p for p in desc_parts):
                    desc_parts.append("⬇ 未下载的模型请运行 wd14/安装WD14.bat 下载")
            self._wd14_model_desc.setText("\n".join(desc_parts))

        except Exception as e:
            QMessageBox.warning(self, "获取失败", f"无法连接 WD14 服务:\n{str(e)[:100]}\n请确认已运行「启动WD14.bat」")

    def _on_wd14_model_selected(self, text):
        """WD14 模型选择：未下载的模型提示下载"""
        if not text or "获取模型列表" in text:
            return
        info = self._wd14_models_info.get(text, {})
        if info and not info.get("installed", True):
            return  # 已安装，不弹窗
        if info:
            repo = info.get("repo", "")
            note = info.get("note", "")
            download_msg = (
                f"模型「{info['name']}」({info['size']}) 尚未下载。\n"
                f"说明: {note}\n"
                f"HuggingFace: {repo}\n"
                f"国内镜像: https://hf-mirror.com/{repo}\n\n"
                f"存放位置: wd14/models/{info['key']}/\n\n"
                f"下载后需重启 WD14 服务并选择该模型。"
            )
            reply = QMessageBox.question(self, "模型未下载",
                download_msg + "\n\n是否打开安装脚本？",
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                import os as _os
                script_path = _os.path.join(
                    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                    "wd14", "安装WD14.bat")
                if _os.path.exists(script_path) and hasattr(_os, 'startfile'):
                    _os.startfile(script_path)

    # ===== 批量设置持久化 =====
    def _save_batch_settings(self):
        """保存批量设置到 settings.json"""
        from .image_grid import SETTINGS, save_settings
        SETTINGS['batch_scope'] = self.batch_scope.currentText()
        SETTINGS['batch_concurrency'] = self.batch_concurrency.currentText()
        SETTINGS['batch_retry'] = self.batch_retry.currentText()
        SETTINGS['batch_tag_mode'] = self.batch_tag_mode.currentText()
        SETTINGS['batch_threshold'] = self.threshold_slider.value()
        save_settings()

    def _restore_batch_settings(self):
        """从 settings.json 恢复批量设置"""
        from .image_grid import SETTINGS
        scope = SETTINGS.get('batch_scope', '')
        if scope:
            idx = self.batch_scope.findText(scope)
            if idx >= 0: self.batch_scope.setCurrentIndex(idx)
        con = SETTINGS.get('batch_concurrency', '2')
        idx = self.batch_concurrency.findText(con)
        if idx >= 0: self.batch_concurrency.setCurrentIndex(idx)
        retry = SETTINGS.get('batch_retry', '1')
        idx = self.batch_retry.findText(retry)
        if idx >= 0: self.batch_retry.setCurrentIndex(idx)
        mode = SETTINGS.get('batch_tag_mode', '追加到已有')
        idx = self.batch_tag_mode.findText(mode)
        if idx >= 0: self.batch_tag_mode.setCurrentIndex(idx)
        thr = SETTINGS.get('batch_threshold', 35)
        self.threshold_slider.setValue(thr)

    def _reset_batch_settings(self):
        """恢复批量设置为默认值"""
        self.batch_scope.setCurrentIndex(2)      # 当前文件夹及子目录
        self.batch_concurrency.setCurrentIndex(1) # 2
        self.batch_retry.setCurrentIndex(1)       # 1
        self.batch_tag_mode.setCurrentIndex(0)    # 追加到已有
        self.threshold_slider.setValue(35)        # 0.35
        self._save_batch_settings()
        QMessageBox.information(self, "已恢复", "批量设置已恢复为默认值")

    def _on_infer_error(self, msg: str):
        """反推错误处理"""
        QMessageBox.warning(self, "反推失败", f"错误信息:\n{msg}")
        self.btn_infer_single.setEnabled(True)
        self.btn_batch_infer.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress_bar.setValue(0)


class InferenceWorker(QThread):
    """单张反推工作线程"""
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, engine: str, api_url: str, image_path: str, threshold: float, prompt: str,
                 llm_endpoint=None, llm_model=None, llm_key=None):
        super().__init__()
        self.engine = engine
        self.api_url = api_url
        self.image_path = image_path
        self.threshold = threshold
        self.prompt = prompt
        self.llm_endpoint = llm_endpoint
        self.llm_model = llm_model
        self.llm_key = llm_key

    def run(self):
        try:
            if "WD14" in self.engine:
                self._infer_wd14()
            elif "大模型" in self.engine or "自定义" in self.engine:
                self._infer_llm()
            else:
                self.error.emit(f"不支持的引擎: {self.engine}")
        except Exception as e:
            self.error.emit(str(e))

    def _infer_wd14(self):
        """WD14标签反推"""
        with open(self.image_path, "rb") as f:
            files = {"image": ("image.jpg", f, "image/jpeg")}
            resp = requests.post(self.api_url, files=files, timeout=30)
            result = resp.json()

        tags = []
        if "tags" in result:
            for tag, conf in result["tags"].items():
                if conf >= self.threshold:
                    tags.append((tag, conf))
        elif "caption" in result:
            caption = result["caption"]
            tags = [(t.strip(), 0.95) for t in caption.split(",") if t.strip()]
        
        self.finished.emit(tags)

    def _infer_llm(self):
        """大模型反推（使用传入的API配置）"""
        endpoint = self.llm_endpoint
        model = self.llm_model or 'gpt-4o'
        api_key = self.llm_key
        if not endpoint or not api_key:
            # 回退：从设置读取
            from .image_grid import SETTINGS
            endpoint = SETTINGS.get('api_endpoint', 'https://api.openai.com/v1/chat/completions')
            model = SETTINGS.get('api_model', 'gpt-4o')
            api_key = SETTINGS.get('api_key', '')
        if not endpoint or not api_key:
            self.error.emit("请在设置或反推页中配置API端点、模型和Key")
            return
        with open(self.image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode('utf-8')

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self.prompt or "Analyze this image and list all relevant tags for LoRA training dataset, comma separated, in English."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                    ]
                }
            ],
            "max_tokens": 512
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=60)
        result = resp.json()
        if "error" in result:
            self.error.emit(f"API错误: {result['error'].get('message', str(result['error']))}")
            return
        caption = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        tags = [(t.strip(), 0.9) for t in caption.split(",") if t.strip()]
        self.finished.emit(tags)


class BatchInferenceWorker(QThread):
    """批量反推工作线程，支持并发和取消"""
    progress = Signal(int, int)
    finished = Signal(int, int)
    error = Signal(str)

    def __init__(self, engine: str, api_url: str, images: list, threshold: float,
                 concurrency: int, retry: int, mode: str, prompt: str,
                 llm_endpoint=None, llm_model=None, llm_key=None):
        super().__init__()
        self.engine = engine
        self.api_url = api_url
        self.images = images
        self.threshold = threshold
        self.concurrency = concurrency
        self.retry = retry
        self.mode = mode
        self.prompt = prompt
        self.llm_endpoint = llm_endpoint
        self.llm_model = llm_model
        self.llm_key = llm_key
        self._cancel = False

    def run(self):
        from .image_grid import SETTINGS
        success = 0
        fail = 0
        total = len(self.images)
        try:
            for i in range(0, total, self.concurrency):
                if self._cancel:
                    break
                batch = self.images[i:i + self.concurrency]
                for img in batch:
                    if self._cancel:
                        break
                    ok = False
                    retry_attempt = 0
                    while retry_attempt <= self.retry:
                        try:
                            if "WD14" in self.engine:
                                with open(img.file_path, "rb") as f:
                                    files = {"image": ("image.jpg", f, "image/jpeg")}
                                    resp = requests.post(self.api_url, files=files, timeout=30)
                                    result = resp.json()
                                tags = []
                                if "tags" in result:
                                    for tag, conf in result["tags"].items():
                                        if conf >= self.threshold:
                                            tags.append((tag, conf))
                            elif "大模型" in self.engine or "自定义" in self.engine:
                                endpoint = self.llm_endpoint
                                model = self.llm_model or 'gpt-4o'
                                api_key = self.llm_key
                                if not endpoint or not api_key:
                                    endpoint = SETTINGS.get('api_endpoint', '')
                                    model = SETTINGS.get('api_model', 'gpt-4o')
                                    api_key = SETTINGS.get('api_key', '')
                                if not endpoint or not api_key:
                                    self.error.emit("请在设置或反推页中配置API")
                                    return
                                with open(img.file_path, "rb") as f:
                                    img_b64 = base64.b64encode(f.read()).decode('utf-8')
                                payload = {
                                    "model": model,
                                    "messages": [{"role": "user", "content": [
                                        {"type": "text", "text": self.prompt or "List all tags for this image, comma separated, English only."},
                                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                                    ]}],
                                    "max_tokens": 512
                                }
                                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                                resp = requests.post(endpoint, json=payload, headers=headers, timeout=60)
                                result = resp.json()
                                caption = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                                tags = [(t.strip(), 0.9) for t in caption.split(",") if t.strip()]
                            else:
                                tags = []
                            if tags:
                                tag_list = [t[0] for t in tags]
                                img.ensure_labels()
                                if "替换" in self.mode:
                                    img.labels = tag_list
                                else:
                                    for t in tag_list:
                                        if t not in img.labels:
                                            img.labels.append(t)
                            ok = True
                            success += 1
                            break
                        except Exception as e:
                            retry_attempt += 1
                            if retry_attempt > self.retry:
                                fail += 1
                                self.error.emit(f"{img.name}: {e}")
                            else:
                                time.sleep(0.5)
                self.progress.emit(min(i + len(batch), total), total)
            self.finished.emit(success, fail)
        except Exception as e:
            self.error.emit(str(e))