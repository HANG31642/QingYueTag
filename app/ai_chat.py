# -*- coding: utf-8 -*-
"""AI 聊天面板 — 支持多轮对话、图片上传、图像生成"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTextEdit, QListWidget, QListWidgetItem, QSplitter,
    QLineEdit, QFileDialog, QMessageBox, QScrollArea, QFrame,
    QComboBox, QApplication,
)
from PySide6.QtCore import Qt, Signal, QThread, QTimer, QSize, QEvent
from PySide6.QtGui import QFont, QPixmap, QTextCursor, QColor, QIcon
import json
import base64
import requests
import time
import os

# 备份根目录
_BACKUP_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "备份")


class AIChatPanel(QWidget):
    """AI 对话面板：左侧历史 + 右侧聊天"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._conversations = {}  # {"对话名": [{"role":"user/assistant","content":"..."}]}
        self._current_conv = "新对话"
        self._conversations["新对话"] = []
        self._conv_order = ["新对话"]
        self._pending_image = None  # 待发送的图片路径
        self._dataset_context = ""  # 当前数据集上下文信息

        # 主水平分割
        splitter = QSplitter(Qt.Horizontal)

        # === 左侧：对话历史 ===
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(4)
        left_header = QHBoxLayout()
        left_header.addWidget(QLabel("💬 对话历史"))
        btn_new_conv = QPushButton("＋ 新对话")
        btn_new_conv.clicked.connect(self._new_conversation)
        left_header.addWidget(btn_new_conv)
        left_layout.addLayout(left_header)
        self._history_list = QListWidget()
        self._history_list.itemClicked.connect(self._on_history_clicked)
        self._history_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._history_list.customContextMenuRequested.connect(self._history_context_menu)
        left_layout.addWidget(self._history_list)
        self._refresh_history()
        splitter.addWidget(left_panel)

        # === 右侧：聊天区域 ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 4, 4, 4)
        right_layout.setSpacing(6)

        # 聊天消息显示区
        self._chat_display = QTextEdit()
        self._chat_display.setReadOnly(True)
        self._chat_display.setFont(QFont("Microsoft YaHei", 11))
        self._chat_display.setContextMenuPolicy(Qt.CustomContextMenu)
        self._chat_display.customContextMenuRequested.connect(self._on_chat_context_menu)
        right_layout.addWidget(self._chat_display, 1)

        # 图片预览区
        self._image_preview = QLabel("")
        self._image_preview.setMaximumHeight(120)
        self._image_preview.setAlignment(Qt.AlignCenter)
        self._image_preview.setStyleSheet("border:1px dashed #555; border-radius:6px;")
        self._image_preview.setVisible(False)
        right_layout.addWidget(self._image_preview)

        # 输入区
        input_row = QHBoxLayout()
        self._chat_input = QTextEdit()
        self._chat_input.setPlaceholderText("输入消息... (/generate 生图, /stats 数据统计, /tags 标签分析)")
        self._chat_input.setMaximumHeight(100)
        self._chat_input.setFont(QFont("Microsoft YaHei", 11))
        # Ctrl+Enter 发送
        self._chat_input.installEventFilter(self)
        input_row.addWidget(self._chat_input, 1)

        btn_layout = QVBoxLayout()
        btn_send = QPushButton("🚀 发送")
        btn_send.clicked.connect(self._send_message)
        btn_layout.addWidget(btn_send)
        btn_upload = QPushButton("📎 图片")
        btn_upload.clicked.connect(self._upload_image)
        btn_layout.addWidget(btn_upload)
        btn_clear_attach = QPushButton("✕")
        btn_clear_attach.setMaximumWidth(28)
        btn_clear_attach.clicked.connect(self._clear_attachment)
        btn_layout.addWidget(btn_clear_attach)
        input_row.addLayout(btn_layout)

        right_layout.addLayout(input_row)

        # 安全提示
        safety_label = QLabel("⚠ AI可修改标签 — 每次操作前弹窗确认（✅执行 / 📦备份后执行 / ❌取消）")
        safety_label.setStyleSheet("color:#888; font-size:10px;")
        safety_label.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(safety_label)

        splitter.addWidget(right_panel)
        splitter.setSizes([180, 600])

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(splitter)

        self._load_history()

    def eventFilter(self, obj, event):
        """Ctrl+Enter 发送消息"""
        if obj == self._chat_input and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Return and event.modifiers() & Qt.ControlModifier:
                self._send_message()
                return True
        return super().eventFilter(obj, event)

    # ===== 对话历史管理 =====
    def _refresh_history(self):
        self._history_list.clear()
        for name in self._conv_order:
            item = QListWidgetItem(name)
            if name == self._current_conv:
                font = item.font(); font.setBold(True)
                item.setFont(font)
            self._history_list.addItem(item)
        # 选中当前对话
        for i in range(self._history_list.count()):
            if self._history_list.item(i).text() == self._current_conv:
                self._history_list.setCurrentRow(i)
                break

    def _new_conversation(self):
        name = f"对话 {len(self._conv_order)+1}"
        self._conversations[name] = []
        self._conv_order.append(name)
        self._current_conv = name
        self._refresh_history()
        self._chat_display.clear()
        self._pending_image = None
        self._image_preview.setVisible(False)

    def _on_history_clicked(self, item):
        name = item.text()
        if name == self._current_conv:
            return
        self._current_conv = name
        self._refresh_history()
        self._render_messages()
        self._pending_image = None
        self._image_preview.setVisible(False)

    def _history_context_menu(self, pos):
        item = self._history_list.itemAt(pos)
        if not item:
            return
        name = item.text()
        if name == "新对话":
            return
        from PySide6.QtWidgets import QMenu
        menu = QMenu()
        menu.addAction("🗑 删除对话", lambda: self._delete_conversation(name))
        menu.exec(self._history_list.viewport().mapToGlobal(pos))

    def _on_chat_context_menu(self, pos):
        """聊天显示区右键菜单"""
        from PySide6.QtWidgets import QMenu
        menu = QMenu()
        menu.addAction("📋 复制所选文字", self._chat_display.copy)
        menu.addAction("📋 复制全部对话", lambda: QApplication.clipboard().setText(
            self._chat_display.toPlainText()))
        menu.exec(self._chat_display.viewport().mapToGlobal(pos))

    def _delete_conversation(self, name):
        if name not in self._conversations:
            return
        del self._conversations[name]
        self._conv_order.remove(name)
        if self._current_conv == name:
            self._current_conv = self._conv_order[0] if self._conv_order else "新对话"
        self._refresh_history()
        self._render_messages()

    def _render_messages(self):
        """渲染当前对话的所有消息到显示区（使用HTML格式）"""
        self._chat_display.clear()
        html_parts = ['<body style="color:#ddd; font-family:Microsoft YaHei;">']
        msgs = self._conversations.get(self._current_conv, [])
        for m in msgs:
            role = m["role"]
            content = m.get("content", "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            image = m.get("image", None)
            if role == "user":
                html_parts.append('<p><b style="color:#4a9eff;">🧑 你:</b></p>')
                if image and os.path.exists(image):
                    html_parts.append(f'<p><img src="{image}" width="200"></p>')
            else:
                html_parts.append('<p><b style="color:#50c878;">🤖 AI:</b></p>')
                if image and os.path.exists(image):
                    html_parts.append(f'<p><img src="{image}" width="300"></p>')
            html_parts.append(f'<p style="margin-left:8px;">{content}</p>')
            html_parts.append('<hr style="border:0; height:1px; background:#333;">')
        html_parts.append('</body>')
        self._chat_display.setHtml("\n".join(html_parts))

    # ===== 图片上传 =====
    def _upload_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择图片", "",
            "图片 (*.png *.jpg *.jpeg *.webp *.gif *.bmp)")
        if not path:
            return
        self._pending_image = path
        pix = QPixmap(path)
        if not pix.isNull():
            self._image_preview.setPixmap(pix.scaledToHeight(110, Qt.SmoothTransformation))
            self._image_preview.setVisible(True)

    def _clear_attachment(self):
        self._pending_image = None
        self._image_preview.setVisible(False)
        self._image_preview.clear()

    # ===== 发送消息 =====
    def _send_message(self):
        text = self._chat_input.toPlainText().strip()
        image = self._pending_image
        if not text and not image:
            return

        # 数据安全提醒（AI可以修改文件，但每次操作都会弹窗确认）
        modify_keywords = ["修改标签", "删除标签", "替换标签", "重命名", "删除文件",
                          "改标签", "删标签", "改文件名", "删除图片", "添加标签"]
        unsafe_found = [kw for kw in modify_keywords if kw in text]
        if unsafe_found:
            reply = QMessageBox.question(self, "数据安全提醒",
                f"您的消息中包含可能修改数据的指令: {', '.join(unsafe_found)}\n\n"
                "AI会建议修改操作，每次执行前都会弹窗让您选择：\n"
                "✅ 直接执行 / 📦 备份后执行 / ❌ 取消\n\n"
                "仍要发送消息？",
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

        # 添加用户消息
        self._conversations[self._current_conv].append({
            "role": "user", "content": text, "image": image
        })
        self._render_messages()
        self._chat_input.clear()
        self._clear_attachment()
        self._save_history()

        # 判断本地快捷命令
        if text.startswith("/generate ") or text.startswith("/gen "):
            self._generate_image(text.replace("/generate ", "").replace("/gen ", ""))
        elif text == "/stats":
            ctx = self._get_dataset_context()
            reply = ctx if ctx else "暂无数据集信息，请先打开数据集。"
            self._conversations[self._current_conv].append({"role": "assistant", "content": reply})
            self._render_messages()
            self._save_history()
        elif text == "/tags":
            self._show_tag_summary()
        else:
            # 调用大模型API进行对话
            self._call_llm(text, image)

    def _get_dataset_context(self) -> str:
        """获取当前数据集上下文信息，供AI参考"""
        parent = self.parent()
        if parent is None:
            return ""
        try:
            from .main_window import MainWindow
            # 向上查找 MainWindow
            while parent and not isinstance(parent, MainWindow):
                parent = parent.parent()
            if not parent:
                return ""

            ctx_parts = ["[当前数据集上下文信息]"]
            # 数据集根目录
            if hasattr(parent, 'tree_root') and parent.tree_root:
                ctx_parts.append(f"数据集: {parent.tree_root.name}")
                ctx_parts.append(f"总图片数: {parent.tree_root.total_images}")

            # 当前文件夹
            if hasattr(parent, 'current_node') and parent.current_node:
                ctx_parts.append(f"当前文件夹: {parent.current_node.name}")
                ctx_parts.append(f"当前文件夹直接图片数: {len(parent.current_images)}")
                # 当前图片的前10个标签（采样）
                sample_labels = set()
                for img in parent.current_images[:30]:
                    img.ensure_labels()
                    sample_labels.update(img.labels)
                if sample_labels:
                    top_labels = sorted(sample_labels)[:30]
                    ctx_parts.append(f"标签样例: {', '.join(top_labels)}")

            # 标签统计
            tag_editor = getattr(parent, 'tag_editor', None)
            if tag_editor and hasattr(tag_editor, '_stats') and tag_editor._stats:
                top = tag_editor._stats[:20]
                stats_str = ", ".join(f"{t}({c})" for t, c in top)
                ctx_parts.append(f"标签频次TOP20: {stats_str}")

            return "\n".join(ctx_parts)
        except:
            return ""

    def _show_tag_summary(self):
        """本地显示标签摘要（不调API）"""
        ctx = self._get_dataset_context()
        if not ctx:
            reply = "暂无数据集信息，请先打开数据集。"
        else:
            reply = f"📊 标签摘要:\n{ctx}"
        self._conversations[self._current_conv].append({"role": "assistant", "content": reply})
        self._render_messages()
        self._save_history()

    def _call_llm(self, text, image_path=None):
        """调用大模型API"""
        from .image_grid import SETTINGS
        endpoint = SETTINGS.get('api_endpoint', '')
        model = SETTINGS.get('api_model', 'gpt-4o')
        api_key = SETTINGS.get('api_key', '')
        if not endpoint or not api_key:
            self._conversations[self._current_conv].append({"role": "assistant", "content": "❌ 请在设置中配置API（端点+模型+Key）"})
            self._render_messages()
            return

        self._conversations[self._current_conv].append({"role": "assistant", "content": "⏳ 思考中..."})
        self._render_messages()
        self._chat_display.repaint()

        # 构造 messages（含数据集上下文）
        ctx = self._get_dataset_context()
        messages = []
        if ctx:
            messages.append({
                "role": "system",
                "content": (
                    f"你是LoRA数据集管理助手。以下是用户当前数据集的信息，请基于此回答问题：\n{ctx}\n\n"
                    "【重要】你可以建议修改文件。在回复中插入操作指令来执行修改，格式如下（每条指令独占一行）：\n"
                    "  [ADD_TAG:标签名]        — 将标签添加到当前图片\n"
                    "  [REMOVE_TAG:标签名]      — 从当前图片删除标签\n"
                    "  [REPLACE_TAG:旧→新]      — 替换当前图片中的标签\n"
                    "  [ADD_GLOBAL_TAG:标签名]   — 将标签添加到当前文件夹所有图片\n"
                    "  [REMOVE_GLOBAL_TAG:标签名] — 从当前文件夹所有图片删除标签\n"
                    "用户会确认后才执行。在建议修改时请先解释原因，再用指令格式给出操作。"
                )
            })
        for m in self._conversations[self._current_conv][-10:]:  # 最近10条
            msg_content = []
            if m.get("image"):
                try:
                    with open(m["image"], "rb") as f:
                        img_b64 = base64.b64encode(f.read()).decode('utf-8')
                    msg_content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                    })
                except:
                    pass
            if m.get("content"):
                msg_content.append({"type": "text", "text": m["content"]})
            messages.append({"role": "user", "content": msg_content})

        # 在后台线程中执行
        self._llm_thread = QThread()
        self._llm_worker = _LLMChatWorker(endpoint, model, api_key, messages)
        self._llm_worker.moveToThread(self._llm_thread)
        self._llm_worker.finished.connect(self._on_llm_done)
        self._llm_worker.error.connect(self._on_llm_error)
        self._llm_thread.started.connect(self._llm_worker.run)
        self._llm_thread.finished.connect(self._llm_thread.deleteLater)
        self._llm_thread.start()

    def _on_llm_done(self, reply):
        self._llm_thread.quit()
        # 移除"思考中"消息
        msgs = self._conversations[self._current_conv]
        if msgs and msgs[-1].get("role") == "assistant" and "⏳" in msgs[-1].get("content", ""):
            msgs.pop()

        # 解析回复中的操作指令
        import re
        operations = []
        clean_reply = []
        for line in reply.split('\n'):
            match = re.match(r'\[(ADD_TAG|REMOVE_TAG|REPLACE_TAG|ADD_GLOBAL_TAG|REMOVE_GLOBAL_TAG):(.+)\]', line.strip())
            if match:
                op_type = match.group(1)
                op_arg = match.group(2)
                operations.append({"type": op_type, "arg": op_arg})
            else:
                clean_reply.append(line)
        display_text = '\n'.join(clean_reply).strip()

        msgs.append({"role": "assistant", "content": display_text, "operations": operations if operations else None})
        self._render_messages()
        self._save_history()

        # 如果有操作指令，弹出安全确认对话框
        if operations:
            self._confirm_operations(operations)

    def _confirm_operations(self, operations):
        """弹出安全确认对话框，让用户选择执行/备份后执行/取消"""
        import shutil
        op_descriptions = []
        for op in operations:
            t = op["type"]
            a = op["arg"]
            if t == "ADD_TAG":
                op_descriptions.append(f"➕ 添加标签「{a}」到当前图片")
            elif t == "REMOVE_TAG":
                op_descriptions.append(f"➖ 从当前图片删除标签「{a}」")
            elif t == "REPLACE_TAG":
                parts = a.split("→") if "→" in a else a.split("->")
                old = parts[0].strip() if parts else a
                new = parts[1].strip() if len(parts) > 1 else old
                op_descriptions.append(f"🔄 替换标签「{old}」→「{new}」")
            elif t == "ADD_GLOBAL_TAG":
                op_descriptions.append(f"➕ 添加标签「{a}」到当前文件夹所有图片")
            elif t == "REMOVE_GLOBAL_TAG":
                op_descriptions.append(f"➖ 从当前文件夹所有图片删除标签「{a}」")

        op_text = "\n".join(f"  {d}" for d in op_descriptions)

        # 三选一对话框
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("🔐 文件修改确认")
        msg_box.setText(f"AI 建议执行以下操作:\n\n{op_text}\n\n请选择处理方式:")
        btn_exec = msg_box.addButton("✅ 直接执行", QMessageBox.AcceptRole)
        btn_backup = msg_box.addButton("📦 备份后执行", QMessageBox.ActionRole)
        btn_cancel = msg_box.addButton("❌ 取消", QMessageBox.RejectRole)
        msg_box.setDefaultButton(btn_cancel)
        msg_box.exec()

        clicked = msg_box.clickedButton()
        if clicked == btn_cancel:
            self._conversations[self._current_conv].append({
                "role": "system", "content": "⚠ 操作已取消"
            })
            self._render_messages()
            self._save_history()
            return

        do_backup = (clicked == btn_backup)

        # 获取 MainWindow 引用以执行实际文件操作
        mw = self._find_main_window()
        if not mw:
            QMessageBox.warning(self, "错误", "无法获取数据集引用")
            return

        results = []
        for op in operations:
            try:
                result = self._execute_operation(op, mw, do_backup)
                results.append(result)
            except Exception as e:
                results.append(f"❌ 失败: {str(e)[:80]}")

        result_text = "\n".join(results)
        self._conversations[self._current_conv].append({
            "role": "system", "content": f"📋 执行结果:\n{result_text}"
        })
        self._render_messages()
        self._save_history()

        # 刷新数据集UI
        if hasattr(mw, 'tag_editor'):
            mw.tag_editor._apply_scope()
            mw.tag_editor._show_current()
        if hasattr(mw, 'image_grid') and mw.current_images:
            mw.image_grid.set_images(mw.current_images)

    def _find_main_window(self):
        """向上查找 MainWindow"""
        parent = self.parent()
        while parent:
            from .main_window import MainWindow
            if isinstance(parent, MainWindow):
                return parent
            parent = parent.parent()
        return None

    def _execute_operation(self, op, mw, do_backup):
        """执行单个文件操作"""
        import shutil

        if not hasattr(mw, 'current_images') or not mw.current_images:
            return f"⚠ 当前文件夹无图片"

        t = op["type"]
        a = op["arg"]

        if t in ("ADD_TAG", "REMOVE_TAG", "REPLACE_TAG"):
            # 作用于当前图片
            img = mw.current_images[0] if mw.current_images else None
            if not img:
                return f"⚠ 无当前图片"
            img.ensure_labels()

            # 备份
            if do_backup:
                # 保存当前标签到 .txt（确保最新状态）
                tp = img.txt_path or img.file_path.rsplit(".",1)[0]+".txt"
                if not os.path.exists(tp):
                    with open(tp, "w", encoding="utf-8") as f:
                        f.write(", ".join(img.labels))
                backup_dir = os.path.join(_BACKUP_ROOT, "ai_operations")
                folder = os.path.basename(os.path.dirname(img.file_path)) or "root"
                dest_dir = os.path.join(backup_dir, folder)
                os.makedirs(dest_dir, exist_ok=True)
                shutil.copy2(tp, os.path.join(dest_dir, f"{img.base_name}_{int(time.time()*1000)}.txt"))

            if t == "ADD_TAG":
                if a not in img.labels:
                    img.labels.append(a)
                    return f"✅ 已添加「{a}」"
                return f"ℹ 「{a}」已存在，跳过"
            elif t == "REMOVE_TAG":
                if a in img.labels:
                    img.labels.remove(a)
                    return f"✅ 已删除「{a}」"
                return f"ℹ 未找到「{a}」，跳过"
            elif t == "REPLACE_TAG":
                parts = a.split("→") if "→" in a else a.split("->")
                old = parts[0].strip()
                new = parts[1].strip() if len(parts) > 1 else old
                if old in img.labels:
                    img.labels = [new if t == old else t for t in img.labels]
                    return f"✅ 已替换「{old}」→「{new}」"
                return f"ℹ 未找到「{old}」，跳过"

        elif t in ("ADD_GLOBAL_TAG", "REMOVE_GLOBAL_TAG"):
            count = 0
            for img in mw.current_images:
                img.ensure_labels()
                if do_backup:
                    tp = img.txt_path or img.file_path.rsplit(".",1)[0]+".txt"
                    if not os.path.exists(tp):
                        with open(tp, "w", encoding="utf-8") as f:
                            f.write(", ".join(img.labels))
                    backup_dir = os.path.join(_BACKUP_ROOT, "ai_operations")
                    folder = os.path.basename(os.path.dirname(img.file_path)) or "root"
                    dest_dir = os.path.join(backup_dir, folder)
                    os.makedirs(dest_dir, exist_ok=True)
                    shutil.copy2(tp, os.path.join(dest_dir, f"{img.base_name}_{int(time.time()*1000)}.txt"))

                if t == "ADD_GLOBAL_TAG":
                    if a not in img.labels:
                        img.labels.append(a)
                        count += 1
                else:  # REMOVE_GLOBAL_TAG
                    if a in img.labels:
                        img.labels.remove(a)
                        count += 1
            return f"✅ 已处理 {count}/{len(mw.current_images)} 张图片"
        return f"⚠ 未知操作: {t}"

    def _on_llm_error(self, err):
        self._llm_thread.quit()
        msgs = self._conversations[self._current_conv]
        if msgs and msgs[-1].get("role") == "assistant" and "⏳" in msgs[-1].get("content", ""):
            msgs.pop()
        msgs.append({"role": "assistant", "content": f"❌ 请求失败: {err}"})
        self._render_messages()
        self._save_history()

    def _generate_image(self, prompt):
        """图像生成（DALL-E兼容接口）"""
        from .image_grid import SETTINGS
        api_key = SETTINGS.get('api_key', '')
        if not api_key:
            self._conversations[self._current_conv].append({"role": "assistant", "content": "❌ 请在设置中配置API Key"})
            self._render_messages()
            return

        self._conversations[self._current_conv].append({"role": "assistant", "content": "🎨 生成图片中..."})
        self._render_messages()
        self._chat_display.repaint()

        self._gen_thread = QThread()
        self._gen_worker = _ImageGenWorker(api_key, prompt)
        self._gen_worker.moveToThread(self._gen_thread)
        self._gen_worker.finished.connect(self._on_gen_done)
        self._gen_worker.error.connect(self._on_gen_error)
        self._gen_thread.started.connect(self._gen_worker.run)
        self._gen_thread.finished.connect(self._gen_thread.deleteLater)
        self._gen_thread.start()

    def _on_gen_done(self, image_path):
        self._gen_thread.quit()
        msgs = self._conversations[self._current_conv]
        if msgs and msgs[-1].get("role") == "assistant" and "🎨" in msgs[-1].get("content", ""):
            msgs.pop()
        msgs.append({"role": "assistant", "content": "生成的图片:", "image": image_path})
        self._render_messages()
        self._save_history()

    def _on_gen_error(self, err):
        self._gen_thread.quit()
        msgs = self._conversations[self._current_conv]
        if msgs and msgs[-1].get("role") == "assistant" and "🎨" in msgs[-1].get("content", ""):
            msgs.pop()
        msgs.append({"role": "assistant", "content": f"❌ 生图失败: {err}"})
        self._render_messages()
        self._save_history()

    # ===== 持久化（含自动备份） =====
    def _save_history(self):
        try:
            import shutil
            path = "ai_history.json"
            # 备份旧文件
            if os.path.exists(path):
                backup_dir = os.path.join(_BACKUP_ROOT, "ai_history")
                if not os.path.exists(backup_dir):
                    os.makedirs(backup_dir)
                backup_path = os.path.join(backup_dir, f"ai_history_{int(time.time())}.json")
                shutil.copy2(path, backup_path)

            data = {"conversations": self._conversations, "order": self._conv_order, "current": self._current_conv}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except:
            pass

    def _load_history(self):
        try:
            if os.path.exists("ai_history.json"):
                with open("ai_history.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._conversations = data.get("conversations", {"新对话": []})
                self._conv_order = data.get("order", ["新对话"])
                self._current_conv = data.get("current", "新对话")
                if "新对话" not in self._conversations:
                    self._conversations["新对话"] = []
                if "新对话" not in self._conv_order:
                    self._conv_order.insert(0, "新对话")
                self._refresh_history()
                self._render_messages()
        except:
            pass


class _LLMChatWorker(QThread):
    """LLM 对话工作线程"""
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, endpoint, model, api_key, messages):
        super().__init__()
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.messages = messages

    def run(self):
        try:
            payload = {
                "model": self.model,
                "messages": self.messages,
                "max_tokens": 1024,
                "temperature": 0.7
            }
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            resp = requests.post(self.endpoint, json=payload, headers=headers, timeout=60)
            result = resp.json()
            if "error" in result:
                self.error.emit(result["error"].get("message", str(result["error"])))
                return
            reply = result["choices"][0]["message"]["content"]
            self.finished.emit(reply)
        except Exception as e:
            self.error.emit(str(e)[:200])


class _ImageGenWorker(QThread):
    """图像生成工作线程（DALL-E兼容接口）"""
    finished = Signal(str)  # 返回保存的图片路径
    error = Signal(str)

    def __init__(self, api_key, prompt):
        super().__init__()
        self.api_key = api_key
        self.prompt = prompt

    def run(self):
        try:
            # 尝试 DALL-E 接口
            from .image_grid import SETTINGS
            endpoint_base = SETTINGS.get('api_endpoint', '').rsplit('/v1/', 1)[0]
            gen_url = f"{endpoint_base}/v1/images/generations"

            payload = {
                "model": "dall-e-3",
                "prompt": self.prompt,
                "n": 1,
                "size": "1024x1024",
                "response_format": "b64_json"
            }
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            resp = requests.post(gen_url, json=payload, headers=headers, timeout=120)
            result = resp.json()

            if "error" in result:
                self.error.emit(result["error"].get("message", str(result["error"])))
                return

            # 保存图片（避免覆盖已有文件）
            b64_data = result["data"][0].get("b64_json", "")
            if b64_data:
                img_data = base64.b64decode(b64_data)
                base_name = f"generated_{int(time.time())}"
                save_path = f"{base_name}.png"
                # 如果文件已存在，自动加序号
                counter = 1
                while os.path.exists(save_path):
                    save_path = f"{base_name}_{counter}.png"
                    counter += 1
                with open(save_path, "wb") as f:
                    f.write(img_data)
                self.finished.emit(save_path)
            else:
                self.error.emit("未返回图片数据")
        except Exception as e:
            self.error.emit(str(e)[:200])
