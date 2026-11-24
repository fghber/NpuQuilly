"""Diff-preview popup: Original -> Result, Accept / Copy / Dismiss."""
from typing import Callable


def show_request(parent=None):
    """Choose a writing action or enter a custom instruction.

    Returns (action, instruction) or None on cancel. Direct hotkeys skip this
    dialog entirely — that is the difference between popup and direct keys.
    """
    from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                                   QPushButton, QVBoxLayout)
    from ui.styles import DARK
    dlg = QDialog(parent)
    dlg.setWindowTitle("NpuQuilly — choose action")
    dlg.setStyleSheet(DARK)
    dlg.resize(420, 170)
    lay = QVBoxLayout(dlg)
    lay.addWidget(QLabel("Choose an action for the selected text:"))
    row = QHBoxLayout()
    b_g = QPushButton("&Grammar check")
    b_r = QPushButton("&Rewrite")
    b_s = QPushButton("&Summarize")
    b_c = QPushButton("&Cancel")
    for button in (b_g, b_r, b_s, b_c):
        button.setAutoDefault(False)
        row.addWidget(button)
    lay.addLayout(row)
    lay.addWidget(QLabel("Or type a custom instruction (Enter to run):"))
    edit = QLineEdit()
    edit.setPlaceholderText("type instruction, press Enter (buttons ignore this field)")
    edit.setFocus()
    lay.addWidget(edit)
    choice: dict = {}

    def pick(action: str, instruction: str = ""):
        choice["v"] = (action, instruction)
        dlg.accept()

    b_g.clicked.connect(lambda: pick("grammar_check"))
    b_r.clicked.connect(lambda: pick("rewrite"))
    b_s.clicked.connect(lambda: pick("summarize"))
    b_c.clicked.connect(dlg.reject)
    edit.returnPressed.connect(
        lambda: pick("custom", edit.text().strip()) if edit.text().strip() else None)
    dlg.exec()
    return choice.get("v")


def show_result(original: str, result: str, latency_s: float,
                on_accept: Callable | None, parent=None, *, notice: str = ""):
    from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTextEdit, QHBoxLayout, QPushButton
    from ui.styles import DARK
    dlg = QDialog(parent)
    dlg.setWindowTitle(f"NpuQuilly ({latency_s:.1f}s)")
    dlg.setStyleSheet(DARK)
    dlg.resize(560, 420)
    lay = QVBoxLayout(dlg)
    if notice:
        label = QLabel(notice)
        label.setWordWrap(True)
        lay.addWidget(label)
    lay.addWidget(QLabel("Original:"))
    o = QTextEdit(readOnly=True)
    o.setPlainText(original[:4000])
    o.setMaximumHeight(120)
    lay.addWidget(o)
    lay.addWidget(QLabel("Result:"))
    r = QTextEdit(readOnly=True)
    r.setPlainText(result)
    lay.addWidget(r)
    row = QHBoxLayout()
    b_cp = QPushButton("Copy")
    b_no = QPushButton("Dismiss")
    if on_accept is not None:
        b_ok = QPushButton("Accept (paste)")
        b_ok.clicked.connect(dlg.accept)
        row.addWidget(b_ok)
    row.addWidget(b_cp)
    row.addWidget(b_no)
    lay.addLayout(row)

    b_cp.clicked.connect(lambda: __import__("pyperclip").copy(result))
    b_no.clicked.connect(dlg.reject)
    # Paste only after the dialog has closed and released keyboard focus.
    if dlg.exec() == QDialog.Accepted and on_accept is not None:
        on_accept(result)
