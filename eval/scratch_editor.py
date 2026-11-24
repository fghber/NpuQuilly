"""Disposable editor for testing NpuQuilly without touching existing documents.

Run with NpuQuilly/.venv/Scripts/python.exe eval/scratch_editor.py.
Select the sample text and press Ctrl+Shift+G, then accept the preview.
"""
import sys

from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QVBoxLayout, QWidget


def main():
    app = QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle("NpuQuilly scratch editor - disposable test text")
    layout = QVBoxLayout(window)
    layout.addWidget(QLabel("Select the sample text, press Ctrl+Shift+G, then accept the correction."))
    editor = QPlainTextEdit()
    editor.setPlainText("I recieved teh mesage yesterday.")
    layout.addWidget(editor)
    window.resize(700, 300)
    window.show()
    editor.setFocus()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
