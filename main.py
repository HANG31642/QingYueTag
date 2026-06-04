# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""LoRA Dataset Tool - Qt/PySide6 desktop application."""
import sys, os, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from app.main_window import MainWindow
from app.themes import THEMES
from app.image_grid import SETTINGS, load_settings
load_settings()


def main():
    """Application entry point."""
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

        app = QApplication(sys.argv)
        app.setApplicationName("LoRA 数据集工具")
        app.setStyle("Fusion")
        theme = SETTINGS.get("theme", "dark")
        app.setPalette(THEMES.get(theme, THEMES["dark"])())

        print("[APP] Creating MainWindow...")
        window = MainWindow()
        print("[APP] MainWindow ok, showing...")
        window.show()
        print("[APP] Event loop...")
        sys.exit(app.exec())
    except Exception as e:
        print(f"[FATAL] {e}")
        traceback.print_exc()
        input("Press Enter to exit...")
        sys.exit(1)


if __name__ == "__main__":
    main()
