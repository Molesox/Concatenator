# ============ main.py ============
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QSize, QSettings   # ← QSettings
from ui_mainwindow import MainWindow, ico
from typing import Optional, cast
 

try:
    from qt_material import apply_stylesheet, list_themes
except Exception:
    apply_stylesheet = None
    def list_themes(): return []

def load_saved_theme() -> Optional[str]:
    """Lit le thème sauvé (si présent)."""
    s = QSettings()
    s.beginGroup("ui")
    t = cast(Optional[str], s.value("theme", None, str))
    s.endGroup()
    return t

def main() -> int:
    QCoreApplication.setOrganizationName("ConcatTools")
    QCoreApplication.setApplicationName("Concatenator")
    QCoreApplication.setApplicationVersion("1.0.5")

    app = QApplication(sys.argv)

    # (Optionnel) style de base avant le thème
    # from PySide6.QtWidgets import QStyleFactory
    # app.setStyle(QStyleFactory.create("Fusion"))

    # 🔹 applique le dernier thème choisi, si lib dispo
    if apply_stylesheet:
        saved = load_saved_theme()
        if saved:
            try:
                apply_stylesheet(app, theme=saved)
            except Exception:
                pass

    app.setWindowIcon(ico("app.svg", QSize(24, 24)))

    win = MainWindow(apply_stylesheet=apply_stylesheet, list_themes=list_themes)
    win.show()
    return app.exec()

if __name__ == "__main__":
    sys.exit(main())
