# -*- coding: utf-8 -*-
"""Theme color palettes for the application."""
from PySide6.QtGui import QPalette, QColor


def create_dark_palette():
    p = QPalette()
    p.setColor(QPalette.Window, QColor("#1a1a2e"))
    p.setColor(QPalette.WindowText, QColor("#eee"))
    p.setColor(QPalette.Base, QColor("#16213e"))
    p.setColor(QPalette.AlternateBase, QColor("#0f3460"))
    p.setColor(QPalette.Text, QColor("#eee"))
    p.setColor(QPalette.Button, QColor("#16213e"))
    p.setColor(QPalette.ButtonText, QColor("#eee"))
    p.setColor(QPalette.ToolTipBase, QColor("#333"))
    p.setColor(QPalette.ToolTipText, QColor("#eee"))
    p.setColor(QPalette.Highlight, QColor("#e94560"))
    p.setColor(QPalette.HighlightedText, QColor("#fff"))
    p.setColor(QPalette.Link, QColor("#4ecca3"))
    return p


def create_light_palette():
    p = QPalette()
    p.setColor(QPalette.Window, QColor("#f5f4f0"))
    p.setColor(QPalette.WindowText, QColor("#1a1a1a"))
    p.setColor(QPalette.Base, QColor("#ffffff"))
    p.setColor(QPalette.AlternateBase, QColor("#eae9e5"))
    p.setColor(QPalette.Text, QColor("#1a1a1a"))
    p.setColor(QPalette.Button, QColor("#ffffff"))
    p.setColor(QPalette.ButtonText, QColor("#1a1a1a"))
    p.setColor(QPalette.ToolTipBase, QColor("#fff"))
    p.setColor(QPalette.ToolTipText, QColor("#333"))
    p.setColor(QPalette.Highlight, QColor("#e94560"))
    p.setColor(QPalette.HighlightedText, QColor("#fff"))
    p.setColor(QPalette.Link, QColor("#27ae60"))
    return p


THEMES = {
    'dark': create_dark_palette,
    'light': create_light_palette,
}
