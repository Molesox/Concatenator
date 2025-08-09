#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication
from ui_mainwindow import MainWindow
from ui_mainwindow import ico
from PySide6.QtCore import QSize

def main():
    # Déclare organisation et application pour QSettings
    QCoreApplication.setOrganizationName("ConcatTools")
    QCoreApplication.setApplicationName("Concatenator")
    QCoreApplication.setApplicationVersion("1.0.4")


    app = QApplication(sys.argv)
    app.setWindowIcon(ico("app.svg", QSize(24, 24)))

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()