# ============ main.py ============
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QSize, QSettings   # ← QSettings
from ui_mainwindow import MainWindow, ico
from typing import Optional, cast

def main() -> int:
    QCoreApplication.setOrganizationName("ConcatTools")
    QCoreApplication.setApplicationName("Concatenator")
    QCoreApplication.setApplicationVersion("1.0.5")

    app = QApplication(sys.argv)
    app.setWindowIcon(ico("app.svg", QSize(24, 24)))

    win = MainWindow()
    win.show()
    return app.exec()

if __name__ == "__main__":
    sys.exit(main())
