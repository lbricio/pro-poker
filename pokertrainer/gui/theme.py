"""Folha de estilo do app (tema escuro translúcido)."""

STYLE = """
* { color: #e9eef0; }
QWidget { font-size: 14px; }
QLabel#appTitle { font-size: 22px; font-weight: 800; color: #ffffff; }
QLabel#appSubtitle { color: #9fb3ad; font-size: 12px; }
QLabel#section { color: #7f948e; font-size: 11px; font-weight: 700; letter-spacing: 1.5px; }
QLabel#pageTitle { font-size: 26px; font-weight: 800; color: white; }
QLabel#muted { color: #9fb3ad; }
QLabel#rowLabel { color: #b7c7c2; font-size: 12px; font-weight: 600; letter-spacing: 1px; }
QLabel#bigValue { font-size: 40px; font-weight: 800; color: white; }
QLabel#handName { font-size: 17px; font-weight: 700; color: #f5c542; }
QLabel#statValue { font-size: 20px; font-weight: 800; color: white; }
QLabel#statLabel { font-size: 11px; color: #8ea39d; }
QLabel#banner { font-size: 16px; font-weight: 700; padding: 10px 16px; border-radius: 12px;
                background: rgba(0,0,0,0.35); }

QPushButton {
    background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.10);
    border-radius: 10px; padding: 9px 14px; text-align: left; font-weight: 600;
}
QPushButton:hover { background: rgba(255,255,255,0.14); }
QPushButton:pressed { background: rgba(255,255,255,0.20); }
QPushButton:checked { background: rgba(245,197,66,0.18); border: 1px solid rgba(245,197,66,0.55); color: #ffe7a3; }
QPushButton:disabled { color: rgba(255,255,255,0.35); }
QPushButton#primary {
    background: #f5c542; color: #1b1b1b; border: none; text-align: center; font-size: 16px;
    font-weight: 800; padding: 12px 28px; border-radius: 12px;
}
QPushButton#primary:hover { background: #ffd65e; }
QPushButton#primary:disabled { background: rgba(245,197,66,0.35); color: rgba(0,0,0,0.5); }
QPushButton#mode { padding: 8px 14px; }
QPushButton#fold {
    background: rgba(255,107,107,0.16); border: 1px solid rgba(255,107,107,0.55); color: #ffd0d0;
    text-align: center; font-size: 16px; font-weight: 800; padding: 12px 22px; border-radius: 12px;
}
QPushButton#fold:hover { background: rgba(255,107,107,0.28); }
QPushButton#secondary {
    background: rgba(255,255,255,0.12); border: 1px solid rgba(255,255,255,0.28); color: white;
    text-align: center; font-size: 16px; font-weight: 800; padding: 12px 22px; border-radius: 12px;
}
QPushButton#secondary:hover { background: rgba(255,255,255,0.20); }
QPushButton#secondary:disabled { color: rgba(255,255,255,0.35); }
QPushButton#fold:disabled { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
                            color: rgba(255,255,255,0.28); }
QPushButton#danger {
    background: rgba(255,107,107,0.10); border: 1px solid rgba(255,107,107,0.45); color: #ffc4c4;
    text-align: center; padding: 8px 16px;
}
QPushButton#danger:hover { background: rgba(255,107,107,0.22); }
QPushButton#tileButton {
    background: rgba(12,18,20,0.62); border: 1px solid rgba(255,255,255,0.12); border-radius: 16px;
    text-align: left; padding: 0;
}
QPushButton#tileButton:hover { background: rgba(28,38,40,0.80); border: 1px solid rgba(245,197,66,0.55); }
QPushButton#chip {
    background: rgba(0,0,0,0.30); border: 1px solid rgba(255,255,255,0.14); border-radius: 13px;
    padding: 4px 12px; font-size: 12px; font-weight: 700; color: #c8d6d1; text-align: center;
}
QPushButton#chip:hover { background: rgba(255,255,255,0.12); color: white; }
QPushButton#chip:checked { background: rgba(245,197,66,0.22); border: 1px solid rgba(245,197,66,0.65); color: #ffe7a3; }
QPushButton#chip::menu-indicator { subcontrol-position: right center; subcontrol-origin: padding; right: 6px; }
QMenu { background: #1d2529; border: 1px solid #3a4a44; padding: 4px; }
QMenu::item { padding: 6px 22px 6px 22px; border-radius: 6px; }
QMenu::item:selected { background: #3a4a44; }
QPushButton#nav { background: transparent; border: 1px solid transparent; padding: 6px 12px; }
QPushButton#nav:hover { background: rgba(255,255,255,0.08); }
QPushButton#nav:checked { background: rgba(255,255,255,0.12); border: 1px solid rgba(255,255,255,0.12); color: white; }

QFrame#line { background: rgba(255,255,255,0.10); max-height: 1px; min-height: 1px; border: none; }
QFrame#card { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; }

QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: rgba(255,255,255,0.18); border-radius: 4px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QTabWidget::pane { border: none; }
QTabBar::tab { background: transparent; color: #9fb3ad; padding: 8px 16px; margin-right: 4px;
               border-bottom: 2px solid transparent; font-weight: 700; }
QTabBar::tab:selected { color: white; border-bottom: 2px solid #f5c542; }
QTabBar::tab:hover { color: white; }

QSpinBox, QComboBox {
    background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.14); border-radius: 8px;
    padding: 6px 10px; min-width: 90px;
}
QComboBox QAbstractItemView { background: #1d2529; selection-background-color: #3a4a44; }
QCheckBox { spacing: 10px; }
QSlider::groove:horizontal { height: 6px; background: rgba(255,255,255,0.15); border-radius: 3px; }
QSlider::handle:horizontal { background: #f5c542; width: 16px; margin: -6px 0; border-radius: 8px; }

QTableWidget { background: transparent; gridline-color: rgba(255,255,255,0.08); border: none; }
QHeaderView::section { background: rgba(255,255,255,0.06); color: #b7c7c2; border: none; padding: 6px;
                       font-weight: 700; }
QTableWidget::item { padding: 4px; }
QHeaderView { background: transparent; }
QHeaderView::section:checked { background: rgba(255,255,255,0.06); color: #b7c7c2; }
QTableCornerButton::section { background: transparent; border: none; }
QTableWidget::item:selected { background: rgba(245,197,66,0.20); color: white; }
QToolTip { background: #1d2529; color: white; border: 1px solid #3a4a44; padding: 6px; }
QTextBrowser { background: transparent; border: none; }
"""
