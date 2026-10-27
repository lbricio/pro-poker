"""Ponto de entrada do app."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from pokertrainer.engine import rank_table
from pokertrainer.gui.main_window import MainWindow
from pokertrainer.gui.theme import STYLE
from pokertrainer.gui.widgets import ASSETS


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Poker Trainer")
    app.setOrganizationName("pokertrainer")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setWindowIcon(QIcon(str(ASSETS / "cards" / "As.png")))
    rank_table()  # pré-carrega a tabela do avaliador
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
