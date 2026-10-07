"""Design tokens shared by every widget.

The window sits on a Windows 11 acrylic backdrop, so surfaces are mostly
translucent whites over a dark tint rather than solid greys.
"""

from __future__ import annotations

from PySide6.QtGui import QColor

from dshub.core.state import Button


def rgba(r: int, g: int, b: int, a: float = 1.0) -> QColor:
    return QColor(r, g, b, round(a * 255))


# Window / surfaces
WINDOW_TINT = rgba(6, 7, 11, 0.80)  # painted over the acrylic backdrop
DEFAULT_TRANSPARENCY = 0.55  # 0 = solid black glass, 1 = as clear as stays readable
DEFAULT_GLASS_STYLE = "frosted"  # "frosted" (blurred, Windows acrylic) | "clear" (smoked, unblurred)


def window_tint(transparency: float, style: str = DEFAULT_GLASS_STYLE) -> QColor:
    """Black glass tint painted over what's behind the window.

    Frosted: Windows' acrylic already blurs and darkens the desktop, so the tint
    only needs to be light. Clear: the tint is the only thing between the user
    and the desktop, so it starts darker.
    """
    t = max(0.0, min(1.0, transparency))
    # 0 must be truly solid; a gentle curve keeps the default (0.55) where it was.
    curve = t ** 0.6
    if style == "clear":
        return rgba(6, 7, 11, 1.0 - 0.60 * curve)  # 1.00 (solid) .. 0.40
    return rgba(6, 7, 11, 1.0 - 0.94 * curve)  # 1.00 (solid) .. 0.06
WINDOW_TINT_FALLBACK = rgba(14, 14, 18, 0.96)  # when no backdrop is available
SURFACE = rgba(255, 255, 255, 0.035)
SURFACE_HOVER = rgba(255, 255, 255, 0.06)
SURFACE_ACTIVE = rgba(255, 255, 255, 0.09)
HAIRLINE = rgba(255, 255, 255, 0.08)
HAIRLINE_STRONG = rgba(255, 255, 255, 0.14)

# Text
TEXT = rgba(237, 237, 242)
TEXT_DIM = rgba(150, 150, 165)
TEXT_FAINT = rgba(95, 95, 110)

# Accent (PlayStation-ish blue, slightly brighter for dark UI)
# PlayStation blue: #0070D1 for filled controls, a brighter tint for lines/text
ACCENT = rgba(31, 134, 242)
ACCENT_DEEP = rgba(0, 112, 209)
ACCENT_SOFT = rgba(31, 134, 242, 0.20)

# Status
OK = rgba(64, 214, 140)
WARN = rgba(255, 184, 64)
BAD = rgba(255, 86, 104)

# Controller artwork
BODY = rgba(26, 26, 33)  # matte shell
BODY_EDGE = rgba(255, 255, 255, 0.10)  # rim highlight
BODY_SHADE = rgba(0, 0, 0, 0.35)
PART = rgba(38, 38, 47)  # sticks, buttons at rest
PART_EDGE = rgba(255, 255, 255, 0.07)
GLOW = rgba(235, 240, 255)  # generic pressed glow
GLYPH_REST = rgba(255, 255, 255, 0.35)

#: Symbol colours used when a face button lights up.
FACE_COLORS: dict[Button, QColor] = {
    Button.TRIANGLE: rgba(62, 219, 178),
    Button.CIRCLE: rgba(255, 90, 110),
    Button.CROSS: rgba(126, 168, 255),
    Button.SQUARE: rgba(229, 138, 224),
}


def glow_for(button: Button) -> QColor:
    return FACE_COLORS.get(button, ACCENT if button is not Button.PS else GLOW)


# Typography
FONT_FAMILY = "Segoe UI Variable Display"
FONT_FALLBACK = "Segoe UI"
RADIUS = 12
RADIUS_SMALL = 8


def apply(app) -> None:
    """Dark palette + stylesheet for the whole app, so every dialog Qt opens
    (message boxes, input prompts, colour picker, menus) matches the UI."""
    from PySide6.QtGui import QPalette

    app.setStyle("Fusion")
    pal = QPalette()
    base, window = QColor(23, 23, 29), QColor(23, 23, 29)
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        pal.setColor(group, QPalette.ColorRole.Window, window)
        pal.setColor(group, QPalette.ColorRole.WindowText, TEXT)
        pal.setColor(group, QPalette.ColorRole.Base, base.darker(115))
        pal.setColor(group, QPalette.ColorRole.AlternateBase, base)
        pal.setColor(group, QPalette.ColorRole.Text, TEXT)
        pal.setColor(group, QPalette.ColorRole.Button, QColor(38, 38, 47))
        pal.setColor(group, QPalette.ColorRole.ButtonText, TEXT)
        pal.setColor(group, QPalette.ColorRole.ToolTipBase, QColor(28, 28, 36))
        pal.setColor(group, QPalette.ColorRole.ToolTipText, TEXT)
        pal.setColor(group, QPalette.ColorRole.Highlight, ACCENT)
        pal.setColor(group, QPalette.ColorRole.HighlightedText, QColor("white"))
        pal.setColor(group, QPalette.ColorRole.PlaceholderText, TEXT_FAINT)
        pal.setColor(group, QPalette.ColorRole.Link, ACCENT)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, TEXT_FAINT)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, TEXT_FAINT)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, TEXT_FAINT)
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)


STYLESHEET = f"""
* {{
    font-family: "{FONT_FAMILY}", "{FONT_FALLBACK}";
    color: {TEXT.name()};
    outline: none;
}}
QWidget#root {{ background: transparent; }}
QLabel[role="h1"] {{ font-size: 24px; font-weight: 300; }}
QLabel[role="h2"] {{ font-size: 14px; font-weight: 600; }}
QLabel[role="dim"] {{ color: {TEXT_DIM.name()}; font-size: 12px; }}
QLabel[role="faint"] {{ color: {TEXT_FAINT.name()}; font-size: 11px; }}
QLabel[role="section"] {{
    color: {TEXT_DIM.name()}; font-size: 10px; font-weight: 600; letter-spacing: 2px;
}}
QPushButton {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255,255,255,0.15), stop:0.49 rgba(255,255,255,0.06),
        stop:0.5 rgba(255,255,255,0.025), stop:1 rgba(255,255,255,0.045));
    border: 1px solid rgba(0,0,0,0.55);
    border-top-color: rgba(255,255,255,0.20);
    border-radius: {RADIUS_SMALL}px;
    padding: 7px 16px;
    font-size: 13px;
}}
QPushButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255,255,255,0.22), stop:0.49 rgba(255,255,255,0.10),
        stop:0.5 rgba(255,255,255,0.05), stop:1 rgba(120,170,255,0.10));
}}
QPushButton:pressed {{ background: rgba(0,0,0,0.30); border-top-color: rgba(0,0,0,0.6); }}
QPushButton:disabled {{ color: {TEXT_FAINT.name()}; background: rgba(255,255,255,0.03); }}
QPushButton[kind="primary"] {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #4aa6ff, stop:0.49 #1a7be8, stop:0.5 #0a63cf, stop:1 #0b6fe0);
    border: 1px solid #03306e; border-top-color: #8cc8ff;
    color: white; font-weight: 600;
}}
QPushButton[kind="primary"]:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #6bb7ff, stop:0.49 #2a8af2, stop:0.5 #1270dc, stop:1 #1680f0);
}}
QPushButton[kind="primary"]:pressed {{ background: #0a58b8; }}
QPushButton[kind="ghost"] {{ background: transparent; border: none; color: {TEXT_DIM.name()}; }}
QPushButton[kind="ghost"]:hover {{ background: rgba(255,255,255,0.06); color: {TEXT.name()}; }}
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(0,0,0,0.42), stop:1 rgba(0,0,0,0.22));
    border: 1px solid rgba(0,0,0,0.6);
    border-bottom-color: rgba(255,255,255,0.10);
    border-radius: {RADIUS_SMALL}px;
    padding: 6px 10px;
    font-size: 13px;
    selection-background-color: {ACCENT_DEEP.name()};
}}
QComboBox:hover, QLineEdit:hover {{ border-color: rgba(31,134,242,0.45); }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: #121218; border: 1px solid rgba(255,255,255,0.10);
    border-radius: 6px; padding: 4px; selection-background-color: rgba(0,112,209,0.55);
}}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.12); border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,0.22); }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none; height: 0;
}}
QSlider::groove:horizontal {{
    height: 4px; border-radius: 2px;
    background: rgba(0,0,0,0.55); border-bottom: 1px solid rgba(255,255,255,0.08);
}}
QSlider::sub-page:horizontal {{
    border-radius: 2px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #5bb0ff, stop:1 {ACCENT_DEEP.name()});
}}
QSlider::handle:horizontal {{
    width: 14px; height: 14px; margin: -6px 0; border-radius: 7px;
    background: qradialgradient(cx:0.4, cy:0.3, radius:0.8, fx:0.35, fy:0.25,
        stop:0 #ffffff, stop:0.6 #c9ccd6, stop:1 #6e7280);
    border: 1px solid rgba(0,0,0,0.6);
}}
QCheckBox {{ font-size: 13px; spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid rgba(255,255,255,0.22); background: rgba(255,255,255,0.04);
}}
QCheckBox::indicator:checked {{ background: {ACCENT.name()}; border-color: {ACCENT.name()}; }}
QToolTip {{
    background: #1c1c24; color: {TEXT.name()}; border: 1px solid rgba(255,255,255,0.12);
    border-radius: 6px; padding: 6px 8px;
}}
QMenu {{
    background: #1a1a21; border: 1px solid rgba(255,255,255,0.10); border-radius: 8px; padding: 4px;
}}
QDialog, QMessageBox, QInputDialog, QColorDialog {{ background: #17171d; }}
QMessageBox QLabel, QInputDialog QLabel, QColorDialog QLabel {{ color: {TEXT.name()}; font-size: 13px; }}
QDialog QPushButton {{ min-width: 72px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: rgba(255,255,255,0.08); }}
"""
