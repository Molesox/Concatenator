#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication
from ui_mainwindow import MainWindow


def main():
    # Déclare organisation et application pour QSettings
    QCoreApplication.setOrganizationName("ConcatTools")
    QCoreApplication.setApplicationName("ConcatFiles")

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()