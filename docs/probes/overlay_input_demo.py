"""Live manual acceptance fixture using production input routing; no audio/network.

Run with venv/Scripts/python.exe docs/probes/overlay_input_demo.py.
The separate background must keep its button/scroll counters unchanged while
using the overlay. The checkbox turns the experimental production mode on/off.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PyQt6 import QtCore, QtWidgets
from overlay import CodeAnswerOverlay
from overlay_cursor import install_cursor_mirroring

app = QtWidgets.QApplication(sys.argv)
background = QtWidgets.QWidget()
background.setWindowTitle('AI-Live cursor mode test')
background.setGeometry(100, 100, 1050, 740)
layout = QtWidgets.QVBoxLayout(background)
status = QtWidgets.QLabel('Underlying clicks: 0 | Overlay clicks: 0')
layout.addWidget(status)
toggle = QtWidgets.QCheckBox('Underlying cursor (experimental)')
layout.addWidget(toggle)
under = QtWidgets.QPushButton('Underlying app button — hand cursor')
under.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
under.setMinimumHeight(320)
layout.addWidget(under)
text = QtWidgets.QTextEdit('\n'.join(f'Underlying editor line {i}' for i in range(100)))
text.setPlainText('\n'.join(f'Underlying editor line {i}' for i in range(100)))
layout.addWidget(text)
counts = [0, 0]
def count(index):
    counts[index] += 1
    status.setText(f'Underlying clicks: {counts[0]} | Overlay clicks: {counts[1]}')
    print(status.text(), flush=True)
under.clicked.connect(lambda: count(0))
text.verticalScrollBar().valueChanged.connect(lambda n: print(f'UNDERLYING SCROLL {n}', flush=True))
background.show()

class TestOverlay(CodeAnswerOverlay):
    def showEvent(self, event):
        # Test fixture deliberately remains visible in automation screenshots.
        # Production capture protection is not modified.
        QtWidgets.QWidget.showEvent(self, event)

overlay = TestOverlay()
overlay.title_label.setText('Production overlay — drag this header / resize edges')
overlay.setGeometry(290, 300, 630, 470)
overlay.answer_text.setPlainText('\n'.join(f'Overlay selection/scroll test line {i}' for i in range(100)))
button = QtWidgets.QPushButton('Overlay test button')
button.setMinimumHeight(45)
button.clicked.connect(lambda: count(1))
overlay.panel.layout().insertWidget(1, button)
overlay.answer_text.selectionChanged.connect(lambda: print('OVERLAY SELECTION ' + str(len(overlay.answer_text.textCursor().selectedText())), flush=True))
overlay.answer_text.verticalScrollBar().valueChanged.connect(lambda n: print(f'OVERLAY SCROLL {n}', flush=True))
overlay.show()
mode = install_cursor_mirroring(app)
toggle.toggled.connect(mode.set_enabled)
toggle.setChecked(True)
print(f'PRODUCTION MODE: {mode.enabled}', flush=True)
app.aboutToQuit.connect(mode.close)
QtCore.QTimer.singleShot(600000, app.quit)
sys.exit(app.exec())
