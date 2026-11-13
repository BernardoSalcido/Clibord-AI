"""Clipboard AI desktop dock, with a Qt main thread and one network worker."""
import argparse
import ctypes
import hashlib
import os
from pathlib import Path
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import qrcode
import qrcode.image.svg
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QMimeData, QPoint, QRectF, QSize, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QDrag, QFont, QGuiApplication, QIcon, QImage, QImageReader, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel, QKeySequenceEdit, QLineEdit,
    QAbstractItemView, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSpinBox, QSplitter, QSystemTrayIcon, QTabBar, QTabWidget, QVBoxLayout, QWidget)

from .cli import data_directory, local_addresses
from .desktop_platform import (WindowsHotkeys, copy_focused_selection, is_copy_hotkey,
    migrate_hidden_startup, parse_hotkey, set_startup, shortcut_released, startup_enabled)
from .gui_backend import Backend, QtClipboard
from .instance import InstanceLock
from .ai import AIConfig, AIError, PROMPTS
from .appearance import LABELS, PAPER, stylesheet


def warmup_image():
    image = QImage(160, 70, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image); painter.setPen(QColor("black")); painter.setFont(QFont("Arial", 22))
    painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, "OK"); painter.end()
    data = QByteArray(); buffer = QBuffer(data); buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


class AISettingsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("IA local · Bionic / LM Studio"); self.resize(640, 650)
        layout = QVBoxLayout(self); form = QFormLayout()
        config = window.ai_config
        self.endpoint = QLineEdit(config.endpoint)
        self.model = QComboBox(); self.model.setEditable(True); self.model.addItem(config.model)
        form.addRow("API local", self.endpoint); form.addRow("Modelo", self.model)
        layout.addLayout(form)
        self.preload = QCheckBox("Cargar y preparar el modelo al iniciar"); self.preload.setChecked(config.preload)
        self.autostart = QCheckBox("Iniciar el servicio local si no responde"); self.autostart.setChecked(config.autostart)
        layout.addWidget(self.preload); layout.addWidget(self.autostart)
        row = QHBoxLayout()
        row.addWidget(button("Probar conexión / buscar modelos", self.probe))
        row.addWidget(button("Preparar", lambda: window.backend.request("ai_prepare")))
        row.addWidget(button("Liberar modelo", lambda: window.backend.request("ai_release")))
        layout.addLayout(row)
        limits = QFormLayout()
        self.context = QSpinBox(); self.context.setRange(512, 32768); self.context.setValue(config.context)
        self.output = QSpinBox(); self.output.setRange(64, 32768); self.output.setValue(config.max_output)
        self.image_max_edge = QComboBox()
        for label, edge in (("Original (sin reducción)", 0), ("2048 px", 2048), ("1600 px", 1600),
                            ("1280 px · recomendado", 1280), ("1024 px", 1024), ("768 px", 768)):
            self.image_max_edge.addItem(label, edge)
        self.image_max_edge.setCurrentIndex(self.image_max_edge.findData(config.image_max_edge))
        limits.addRow("Contexto al cargar", self.context); limits.addRow("Límite de salida (incluye thinking)", self.output)
        limits.addRow("Lado máximo de captura para IA", self.image_max_edge)
        layout.addLayout(limits)
        tabs = QTabWidget(); self.editors = {}
        for key, label in (("image", "Imagen → Markdown"), ("spelling", "Ortografía"), ("grammar", "Gramática")):
            editor = QPlainTextEdit(config.prompts[key]); self.editors[key] = editor; tabs.addTab(editor, label)
        layout.addWidget(tabs, 1)
        layout.addWidget(button("Restaurar prompts", self.restore_prompts))
        hint = QLabel("Los prompts se envían con cada petición. El programa añade los delimitadores automáticamente.\n"
                      "Cada acción usa una petición independiente y no acumula conversación. La imagen original se conserva en el dock.\n"
                      "Si la API requiere un token: define CLIPBOARD_AI_API_TOKEN antes de abrir el dock.\n"
                      "Guardar aplica la dirección y el modelo; Preparar usa la configuración ya guardada.")
        hint.setWordWrap(True); layout.addWidget(hint)
        self.message = QLabel(); self.message.setWordWrap(True); self.message.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.message)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        window.backend.completed.connect(self.completed)

    def restore_prompts(self):
        for key, editor in self.editors.items(): editor.setPlainText(PROMPTS[key])

    def probe(self):
        self.message.setText("Comprobando API…")
        self.window.backend.request("ai_probe", self.endpoint.text().strip())

    def completed(self, action, value):
        if action != "ai_probe" or not self.isVisible(): return
        if value.get("error"):
            self.message.setText(value["error"]); return
        selected = self.model.currentText(); self.model.clear()
        self.model.addItems([model["key"] for model in value["models"] if model.get("type") == "llm" and model.get("capabilities", {}).get("vision")])
        self.model.setCurrentText(selected)
        self.message.setText("API conectada. Selecciona el modelo y guarda.")

    def save(self):
        from dataclasses import replace
        try:
            config = replace(self.window.ai_config, endpoint=self.endpoint.text().strip(), model=self.model.currentText().strip(),
                preload=self.preload.isChecked(), autostart=self.autostart.isChecked(), context=self.context.value(),
                max_output=self.output.value(), image_max_edge=self.image_max_edge.currentData(),
                prompts={key: editor.toPlainText() for key, editor in self.editors.items()})
            config.save(self.window.args.data_dir)
            self.window.ai_config = config
            self.window.backend.request("ai_config", config)
            self.accept()
        except (AIError, OSError) as exc:
            self.message.setText(str(exc))

STATES = dict(pending="Pendiente", sending="Enviando", receiving="Recibiendo",
              delivered="Entregado", cancelled="Cancelado", error="Error")


class CursorActivity(QWidget):
    """A non-interactive AI status badge that follows the system pointer."""

    LABELS = {"working": "Procesando…", "copied": "Copiado", "saved": "No copiado", "error": "Error"}
    COLORS = {"working": "#287ea8", "copied": "#16835b", "saved": "#aa6a16", "error": "#bd3c42"}

    def __init__(self):
        flags = (Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint |
                 Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput)
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(150, 42)
        self.state = "idle"
        self.angle = 0
        self.tick = QTimer(self)
        self.tick.setInterval(80)
        self.tick.timeout.connect(self._tick)
        self.dismiss = QTimer(self)
        self.dismiss.setSingleShot(True)
        self.dismiss.setInterval(2000)
        self.dismiss.timeout.connect(lambda: self.set_state("idle"))

    def set_state(self, state):
        if state == "idle":
            self.state = state
            self.tick.stop(); self.dismiss.stop(); self.hide()
            return
        if state not in self.LABELS:
            raise ValueError("Estado visual de IA desconocido")
        self.state = state
        self.dismiss.stop()
        self._position_near_cursor()
        self.update()
        self.show()
        self.tick.start()
        if state != "working":
            self.dismiss.start()

    def _tick(self):
        self._position_near_cursor()
        if self.state == "working":
            self.angle = (self.angle + 24) % 360
            self.update()

    def _position_near_cursor(self):
        cursor = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        target = cursor + QPoint(18, 22)
        if target.x() + self.width() > area.right():
            target.setX(cursor.x() - self.width() - 14)
        if target.y() + self.height() > area.bottom():
            target.setY(cursor.y() - self.height() - 14)
        target.setX(max(area.left(), min(target.x(), area.right() - self.width() + 1)))
        target.setY(max(area.top(), min(target.y(), area.bottom() - self.height() + 1)))
        self.move(target)

    def paintEvent(self, event):
        if self.state == "idle":
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#cbd8e2"), 1))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 12, 12)
        color = QColor(self.COLORS[self.state])
        painter.setPen(QPen(color, 3))
        if self.state == "working":
            painter.drawArc(QRectF(13, 13, 16, 16), self.angle * 16, 270 * 16)
        else:
            painter.setPen(color)
            painter.setFont(QFont("Segoe UI", 17, QFont.Weight.Bold))
            glyph = "✓" if self.state == "copied" else "!" if self.state == "saved" else "×"
            painter.drawText(QRectF(10, 3, 24, 35), Qt.AlignmentFlag.AlignCenter, glyph)
        painter.setPen(QColor("#172d3e"))
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        painter.drawText(QRectF(38, 4, 107, 34), Qt.AlignmentFlag.AlignVCenter, self.LABELS[self.state])
        painter.end()

STYLE = """
QMainWindow, QDialog { background: #f4f7fa; }
QWidget { color: #172d3e; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
QFrame#card { background: white; border: 1px solid #dce5ec; border-radius: 10px; }
QLabel#title { font-size: 26px; font-weight: 700; }
QLabel#muted { color: #52697b; }
QLabel#message { background: #e1edf3; padding: 9px; border-radius: 6px; }
QPushButton { background: white; border: 1px solid #cbd8e2; padding: 8px 12px; border-radius: 6px; }
QPushButton:hover { background: #eaf3f5; border-color: #32908d; }
QPushButton:disabled { color: #8998a4; background: #edf1f4; }
QPushButton#primary { background: #177d78; color: white; border-color: #177d78; font-weight: 600; }
QPushButton#primary:hover { background: #116660; }
QLineEdit, QPlainTextEdit, QComboBox, QKeySequenceEdit { background: white; border: 1px solid #cbd8e2;
 border-radius: 6px; padding: 7px; selection-background-color: #c4e7e3; selection-color: #172d3e; }
QListWidget { background: white; border: 1px solid #dce5ec; border-radius: 8px; padding: 5px; }
QListWidget::item { padding: 11px 8px; border-bottom: 1px solid #edf1f4; }
QListWidget::item:selected { background: #dff1ee; color: #123d3a; border-radius: 5px; }
QListWidget::item:hover:!selected { background: #f2f7f8; }
QProgressBar { border: 1px solid #dce5ec; border-radius: 5px; background: #edf1f4; text-align: center; }
QProgressBar::chunk { background: #7bbeb5; }
QCheckBox::indicator { width: 14px; height: 14px; background: white; border: 1px solid #9ab0bf; border-radius: 3px; }
QCheckBox::indicator:checked { background: #177d78; border: 2px solid #177d78; }
QCheckBox::indicator:disabled { background: #e4eaf0; border-color: #cbd8e2; }
QSplitter::handle { background: #dce8ec; }
QSplitter::handle:hover { background: #7bbeb5; }
QTabBar::tab { background: #e8eef3; padding: 9px 20px; margin-right: 4px; border-radius: 6px; }
QTabBar::tab:selected { background: #177d78; color: white; }
"""


def size_text(value):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{value} B"
        value /= 1024


def history_section(entry):
    if entry["kind"] == "text":
        return 0
    return 1 if entry["row"]["item"]["mime"].lower().startswith("image/") else 2


def dock_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#177d78")); painter.drawRoundedRect(2, 2, 60, 60, 14, 14)
    painter.setBrush(QColor("#ffffff")); painter.drawRoundedRect(17, 17, 30, 35, 4, 4)
    painter.setBrush(QColor("#a9d8d1")); painter.drawRoundedRect(24, 12, 16, 10, 3, 3)
    painter.setBrush(QColor("#177d78")); painter.drawRoundedRect(23, 30, 18, 3, 1, 1)
    painter.drawRoundedRect(23, 38, 13, 3, 1, 1)
    painter.end()
    return QIcon(pixmap)


def button(text, callback, primary=False):
    item = QPushButton(text)
    item.setMinimumHeight(34)
    if primary:
        item.setObjectName("primary")
    item.clicked.connect(callback)
    return item


class DropZone(QFrame):
    files_dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        self.label = QLabel("Arrastra archivos aquí para enviarlos")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)
        self.help_label = QLabel("Se enviará una copia · Hasta 100 MiB por archivo")
        self.help_label.setObjectName("muted")
        self.help_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.help_label)

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if urls and all(url.isLocalFile() for url in urls):
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls and all(url.isLocalFile() for url in urls):
            self.files_dropped.emit([url.toLocalFile() for url in urls])
            # Copy only: a move from Explorer must never remove the source.
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()


class HistoryList(QListWidget):
    """Send file URLs to other applications while keeping dock originals intact."""

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def startDrag(self, supported_actions):
        entries = [item.data(Qt.ItemDataRole.UserRole) for item in self.selectedItems()]
        try:
            paths = self.window.prepare_drag_files(entries)
        except (OSError, ValueError) as exc:
            self.window.show_error("No se pudieron preparar los archivos para arrastrar: " + str(exc))
            return
        if not paths:
            return
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
        file_entries = [entry for entry in entries if entry and entry["kind"] == "file"]
        if len(paths) == 1 and file_entries[0]["row"]["item"]["mime"].lower().startswith("image/"):
            reader = QImageReader(str(paths[0]))
            size = reader.size()
            if size.isValid() and size.width() * size.height() <= 24_000_000:
                image = reader.read()
                if not image.isNull():
                    data.setImageData(image)
        drag = QDrag(self)
        drag.setMimeData(data)
        drag.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)


class PairDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Vincular teléfono")
        self.resize(510, 680)
        layout = QVBoxLayout(self)
        text = QLabel("Elige la dirección de la red compartida con tu teléfono.\nEn Android pulsa Vincular → Escanear QR.")
        text.setWordWrap(True); layout.addWidget(text)
        row = QHBoxLayout()
        self.address = QComboBox(); self.address.setEditable(True)
        addresses = [a for a in local_addresses() if a != "127.0.0.1"]
        self.address.addItems(addresses)
        if window.args.advertise:
            self.address.setCurrentText(window.args.advertise)
        row.addWidget(self.address, 1)
        row.addWidget(button("Generar QR", self.generate, True)); layout.addLayout(row)
        self.svg = QSvgWidget(); self.svg.setMinimumSize(280, 280); layout.addWidget(self.svg, 1)
        self.remaining = QLabel("Genera un código para vincular. Caducará en cinco minutos.")
        self.remaining.setWordWrap(True); layout.addWidget(self.remaining)
        hint = QLabel("Sin cámara: en Android usa Pegar bloque completo, incluyendo las llaves { }.")
        hint.setWordWrap(True); layout.addWidget(hint)
        self.payload = QPlainTextEdit(); self.payload.setReadOnly(True); self.payload.setMaximumHeight(115)
        layout.addWidget(self.payload)
        layout.addWidget(button("Copiar bloque completo", lambda: self.window.clipboard_bridge.write_ui(self.payload.toPlainText())))
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.close); layout.addWidget(close)
        self.seconds = 0
        self.timer = QTimer(self); self.timer.timeout.connect(self.tick)
        self.finished.connect(self.closed)

    def generate(self):
        self.window.backend.request("pair", self.address.currentText())

    def show_payload(self, payload):
        self.payload.setPlainText(payload)
        qr = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage)
        self.svg.load(QByteArray(qr.to_string()))
        self.svg.show()
        self.seconds = 300; self.tick(); self.timer.start(1000)

    def tick(self):
        self.remaining.setText(f"Código temporal: {self.seconds // 60}:{self.seconds % 60:02d} restantes. Solo para tus dispositivos.")
        if self.seconds <= 0:
            self.timer.stop(); self.svg.hide(); self.payload.clear()
            self.remaining.setText("Código caducado. Pulsa Generar QR para obtener otro.")
        self.seconds -= 1

    def closed(self, result):
        self.timer.stop(); self.payload.clear(); self.svg.hide()
        if self.window.backend.accepting:
            self.window.backend.request("close_pair")


class DockWindow(QMainWindow):
    preview_ready = Signal(object, object)

    def __init__(self, args, settings, backend=None, clipboard=None):
        super().__init__()
        self.args, self.settings = args, settings
        self.language = settings.value("appearance/language", "es")
        if self.language not in LABELS: self.language = "es"
        self.theme = settings.value("appearance/theme", "light")
        if self.theme not in PAPER: self.theme = "light"
        QApplication.instance().setStyleSheet(stylesheet(self.theme))
        self.setWindowTitle("Clipboard AI · Dock")
        self.setWindowIcon(dock_icon())
        self._expanded = False
        self._actions_expanded = False
        self._layout_transition = False
        self._layout_epoch = 0
        self.resize(660, 350)
        self._quitting = False
        self._stopped = False
        self._copy_send_armed = False
        self._copy_send_revision = None
        self._copy_send_started = 0.0
        self._copy_send_binding = ""
        self._copy_send_id = 0
        self.state = None
        self.entries = []
        self._displayed = None
        self._preview_cache = {}
        self._preview_pending = set()
        self._preview_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="clipboard-preview")
        self.preview_ready.connect(self._preview_loaded)
        self._clean_drag_exports()
        self.pair_dialog = None
        self.ai_dialog = None
        try:
            self.ai_config = AIConfig.load(args.data_dir)
        except (ValueError, OSError, TypeError):
            self.ai_config = AIConfig(preload=False, autostart=False)
        self.clipboard_bridge = clipboard or QtClipboard(QApplication.clipboard())
        self.clipboard_bridge.capture_image = True
        self.clipboard_bridge.capture_text = True
        self.backend = backend or Backend(args, self.clipboard_bridge,
            True,
            settings.value("automatic/receive_media", True, type=bool), self.ai_config, warmup_image())
        self.cursor_activity = CursorActivity()
        self.backend.snapshot.connect(self.update_state)
        self.backend.completed.connect(self.result)
        self.backend.error.connect(self.show_error)
        self.backend.notice.connect(self.show_notice)
        self.backend.stopped.connect(self.backend_stopped)
        if hasattr(self.backend, "ai_state"):
            self.backend.ai_state.connect(self.update_ai_status)
        if hasattr(self.backend, "ai_activity"):
            self.backend.ai_activity.connect(self.cursor_activity.set_state)
        if hasattr(self.clipboard_bridge, "external_changed"):
            self.clipboard_bridge.external_changed.connect(self.external_clipboard_changed)
            self.clipboard_bridge.capture_error.connect(self.show_error)
        self.build()
        self.apply_language()
        self.set_expanded(False, initial=True)
        self.make_tray()
        self.hotkey_callbacks = dict(show=self.toggle_window, send=self.copy_and_send,
            spelling=lambda: self.toggle_ai_mode(self.spelling_mode),
            image=lambda: self.toggle_ai_mode(self.image_mode),
            grammar=lambda: self.toggle_ai_mode(self.grammar_mode))
        if sys.platform == "darwin":
            from .macos_platform import MacHotkeys
            self.hotkeys = MacHotkeys(self.hotkey_callbacks)
        else:
            self.hotkeys = WindowsHotkeys(self.hotkey_callbacks)
            QApplication.instance().installNativeEventFilter(self.hotkeys)
        self.local_shortcuts = []
        errors = self.configure_hotkeys(self.bindings())
        if errors:
            self.show_error("Atajos: " + "; ".join(errors) + ". Puedes cambiarlos en Ajustes.")
        self.search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self.search_shortcut.activated.connect(self.focus_search)
        self.escape_shortcut = QShortcut(QKeySequence("Esc"), self)
        self.escape_shortcut.activated.connect(self.hide_if_tray)
        self.notification_counts = dict(sent_text=0, sent_image=0, sent_file=0,
                                        received_text=0, received_image=0, received_file=0)
        self.notification_timer = QTimer(self)
        self.notification_timer.setSingleShot(True)
        self.notification_timer.setInterval(1400)
        self.notification_timer.timeout.connect(self.flush_notifications)
        self.set_controls(False)

    def build(self):
        center = QWidget(); self.setCentralWidget(center)
        root = QVBoxLayout(center); root.setContentsMargins(22, 18, 22, 16); root.setSpacing(12)
        header = QHBoxLayout()
        brand = QVBoxLayout(); title = QLabel("Clipboard AI"); title.setObjectName("title")
        brand.addWidget(title); self.subtitle = QLabel("Tu dock de texto y archivos"); self.subtitle.setObjectName("muted")
        brand.addWidget(self.subtitle); header.addLayout(brand); header.addStretch()
        self.pair_button = button("Vincular teléfono", self.show_pair)
        header.addWidget(self.pair_button)
        self.settings_button = button("Ajustes", self.show_settings)
        header.addWidget(self.settings_button); root.addLayout(header)
        self.connection = QLabel("Iniciando conexión…"); self.connection.setObjectName("message")
        self.connection.setTextFormat(Qt.TextFormat.PlainText)
        self.connection.setWordWrap(True)
        root.addWidget(self.connection)
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setHandleWidth(8)
        self.content_splitter.setChildrenCollapsible(False)
        self.main_panel = QWidget(); self.main_layout = QVBoxLayout(self.main_panel)
        self.main_layout.setContentsMargins(0, 0, 0, 0); self.main_layout.setSpacing(10)
        root.addWidget(self.content_splitter, 1); self.content_splitter.addWidget(self.main_panel)
        self.dropzone = DropZone(); self.dropzone.files_dropped.connect(self.add_files)
        self.main_layout.addWidget(self.dropzone, 1)
        basic = QHBoxLayout()
        self.clip_button = button("Enviar portapapeles como texto", self.send_clipboard, True)
        self.expand_button = button("Expandir", lambda: self.set_expanded(not self._expanded))
        self.actions_button = button("Acciones ▸", self.toggle_actions)
        basic.addWidget(self.clip_button, 1); basic.addWidget(self.expand_button); basic.addWidget(self.actions_button)
        self.main_layout.addLayout(basic)
        self.advanced = QWidget()
        expanded_layout = QVBoxLayout(self.advanced)
        expanded_layout.setContentsMargins(0, 0, 0, 0); expanded_layout.setSpacing(10)
        self.main_layout.addWidget(self.advanced, 1)
        self.actions_panel = QFrame(); self.actions_panel.setObjectName("card")
        self.actions_panel.setMinimumWidth(205)
        side_layout = QVBoxLayout(self.actions_panel); side_layout.setContentsMargins(2, 2, 2, 2)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        action_widget = QWidget(); action_layout = QVBoxLayout(action_widget)
        action_widget.setObjectName("actionsContent"); action_widget.setMinimumHeight(345)
        scroll.setWidget(action_widget); side_layout.addWidget(scroll)
        self.actions_heading = QLabel("Acciones automáticas")
        action_layout.addWidget(self.actions_heading)
        self.image_mode = QCheckBox("Imagen → Markdown")
        self.spelling_mode = QCheckBox("Texto → Ortografía")
        self.grammar_mode = QCheckBox("Gramática · thinking")
        self.image_mode.setChecked(self.ai_config.image)
        self.spelling_mode.setChecked(self.ai_config.text_mode == "spelling")
        self.grammar_mode.setChecked(self.ai_config.text_mode == "grammar")
        for mode in (self.image_mode, self.spelling_mode, self.grammar_mode):
            action_layout.addWidget(mode)
            mode.toggled.connect(lambda checked, control=mode: self.ai_modes_changed(control, checked))
        self.correction_heading = QLabel("Corrección de texto")
        action_layout.addWidget(self.correction_heading)
        self.correction_level = QComboBox()
        for label, mode in zip(LABELS[self.language]["levels"], ("none", "spelling", "grammar")):
            self.correction_level.addItem(label, mode)
        self.correction_level.setCurrentIndex(self.correction_level.findData(self.ai_config.text_mode))
        self.correction_level.currentIndexChanged.connect(self.correction_changed)
        action_layout.addWidget(self.correction_level)
        self.spelling_mode.hide(); self.grammar_mode.hide()
        self.mode_hint = QLabel("Procesan lo nuevo que copies.\nEl resultado queda listo para pegar.")
        self.mode_hint.setWordWrap(True); self.mode_hint.setObjectName("muted"); action_layout.addWidget(self.mode_hint)
        action_layout.addStretch()
        self.process_button = button("Procesar selección", self.process_selected)
        action_layout.addWidget(self.process_button)
        self.configure_button = button("Configurar IA", self.show_ai_settings)
        side_layout.addWidget(self.configure_button)
        self.cancel_button = button("Cancelar tarea", lambda: self.backend.request("ai_cancel"))
        side_layout.addWidget(self.cancel_button)
        self.content_splitter.addWidget(self.actions_panel)
        self.content_splitter.setSizes([760, 245])
        self.content_splitter.splitterMoved.connect(self.save_panel_sizes)
        self.actions_panel.hide()
        self.ai_status = QLabel("IA: preparando…" if self.ai_config.preload else "IA: carga bajo demanda")
        self.ai_status.setWordWrap(True); self.ai_status.setObjectName("muted")
        self.ai_status.setTextFormat(Qt.TextFormat.PlainText); root.addWidget(self.ai_status)
        toolbar = QHBoxLayout()
        self.file_button = button("Añadir archivos", self.choose_files)
        self.inbox_button = button("Carpeta Entrada", lambda: self.open_folder("inbox"))
        self.received_button = button("Recibidos", lambda: self.open_folder("received"))
        self.pause_button = button("Pausar conexión", lambda: self.backend.request("pause"))
        for item in (self.file_button, self.inbox_button, self.received_button, self.pause_button):
            toolbar.addWidget(item)
        expanded_layout.addLayout(toolbar)
        automatic = QHBoxLayout()
        self.auto_receive = QCheckBox("Copiar textos e imágenes recibidos")
        self.automatic_hint = QLabel("Ctrl+C copia normalmente. Usa Ctrl+Alt+C para copiar la selección y enviarla a tus dispositivos.")
        self.automatic_hint.setWordWrap(True)
        automatic.addWidget(self.automatic_hint, 1)
        self.auto_receive.toggled.connect(self.automatic_changed); automatic.addWidget(self.auto_receive)
        automatic.addStretch(); expanded_layout.addLayout(automatic)
        search_row = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText("Buscar texto o nombre de archivo…")
        self.search.setClearButtonEnabled(True); self.search.textChanged.connect(self.render_history)
        self.sections = QTabBar()
        for label in ("Textos", "Imágenes", "Otros archivos"):
            self.sections.addTab(label)
        self.sections.currentChanged.connect(self.render_history)
        search_row.addWidget(self.search, 1)
        self.clear_text_button = button("Limpiar textos", self.clear_texts)
        search_row.addWidget(self.clear_text_button)
        self.clear_button = button("Limpiar archivos", self.clear_files); search_row.addWidget(self.clear_button)
        expanded_layout.addLayout(search_row)
        expanded_layout.addWidget(self.sections)
        self.history_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.history_splitter.setHandleWidth(8)
        self.history_splitter.setChildrenCollapsible(False)
        self.history = HistoryList(self); self.history.currentItemChanged.connect(self.show_selection)
        self.history.setIconSize(QSize(52, 52))
        self.history.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.history.setMinimumWidth(210); self.history_splitter.addWidget(self.history)
        detail = QFrame(); detail.setObjectName("card"); detail_layout = QVBoxLayout(detail)
        detail.setMinimumWidth(285)
        self.detail_title = QLabel("Tu dock está listo"); self.detail_title.setWordWrap(True)
        self.detail_title.setStyleSheet("font-size: 17px; font-weight: 600;")
        self.detail_meta = QLabel("Selecciona un elemento para ver su contenido y acciones.")
        self.detail_meta.setObjectName("muted"); self.detail_meta.setWordWrap(True)
        self.detail_body = QPlainTextEdit(); self.detail_body.setReadOnly(True); self.detail_body.setAcceptDrops(False)
        self.detail_body.setPlaceholderText("Los textos y archivos aparecerán aquí cuando los compartas.")
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(180)
        self.preview_label.setMaximumHeight(320)
        self.preview_label.setObjectName("preview")
        self.preview_label.hide()
        self.progress = QProgressBar(); self.progress.hide()
        detail_layout.addWidget(self.detail_title); detail_layout.addWidget(self.detail_meta)
        detail_layout.addWidget(self.preview_label); detail_layout.addWidget(self.detail_body, 1); detail_layout.addWidget(self.progress)
        actions = QHBoxLayout()
        self.copy_button = button("Copiar", self.copy_selected)
        self.open_button = button("Abrir", lambda: self.file_action("open"))
        self.location_button = button("Ubicación", lambda: self.file_action("folder"))
        self.save_button = button("Guardar copia", lambda: self.file_action("save"))
        self.delete_button = button("Eliminar", self.delete_selected)
        self.original_button = button("Ver entrada", lambda: self.backend.request("ai_original", self.selected()["id"]) if self.selected() else None)
        self.original_button.hide(); detail_layout.addWidget(self.original_button)
        for item in (self.copy_button, self.open_button, self.location_button, self.save_button, self.delete_button):
            item.hide(); actions.addWidget(item)
        detail_layout.addLayout(actions); self.history_splitter.addWidget(detail)
        self.history_splitter.setSizes([390, 570])
        self.history_splitter.splitterMoved.connect(self.save_panel_sizes)
        composer = QHBoxLayout()
        self.draft = QPlainTextEdit(); self.draft.setPlaceholderText("Escribe o pega un texto para enviarlo…")
        self.draft.setMinimumHeight(55); self.draft.setAcceptDrops(False)
        composer.addWidget(self.draft, 1)
        self.send_button = button("Enviar texto", self.send_text, True); composer.addWidget(self.send_button)
        composer_widget = QWidget(); composer_widget.setLayout(composer)
        composer_widget.setMinimumHeight(70)
        self.vertical_splitter = QSplitter(Qt.Orientation.Vertical)
        self.vertical_splitter.setHandleWidth(8)
        self.vertical_splitter.setChildrenCollapsible(False)
        self.vertical_splitter.addWidget(self.history_splitter)
        self.vertical_splitter.addWidget(composer_widget)
        self.vertical_splitter.setSizes([430, 100])
        self.vertical_splitter.splitterMoved.connect(self.save_panel_sizes)
        expanded_layout.addWidget(self.vertical_splitter, 1)
        self.usage = QLabel("Preparando historial…"); self.usage.setObjectName("muted"); expanded_layout.addWidget(self.usage)
        self.message = QLabel("Los envíos sin conexión se guardan como pendientes.")
        self.message.setWordWrap(True); self.message.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.message)
        self.feedback_timer = QTimer(self); self.feedback_timer.setSingleShot(True)
        self.feedback_timer.timeout.connect(lambda: self.message.setVisible(self._expanded))

    def apply_language(self):
        """Refresh visible navigation without touching transport or AI modes."""
        t = LABELS[self.language]
        for widget, key in ((self.subtitle, "subtitle"), (self.settings_button, "settings"),
                            (self.pair_button, "pair"), (self.clip_button, "send_clip"),
                            (self.actions_heading, "automatic"), (self.image_mode, "image"),
                            (self.spelling_mode, "spelling"), (self.grammar_mode, "grammar"),
                            (self.process_button, "process"), (self.configure_button, "configure"),
                            (self.cancel_button, "cancel"), (self.file_button, "add"),
                            (self.inbox_button, "inbox"), (self.received_button, "received"),
                            (self.auto_receive, "receive"), (self.clear_text_button, "clear_text"),
                            (self.clear_button, "clear_files"), (self.copy_button, "copy"),
                            (self.open_button, "open"), (self.location_button, "location"),
                            (self.save_button, "save"), (self.delete_button, "delete"),
                            (self.send_button, "send_text")):
            widget.setText(t[key])
        self.expand_button.setText(t["collapse" if self._expanded else "expand"])
        self.actions_button.setText(t["actions"] + (" ◂" if self._actions_expanded else " ▸"))
        self.search.setPlaceholderText(t["search"])
        self.dropzone.label.setText(t["drop"])
        self.dropzone.help_label.setText(t["drop_hint"])
        self.mode_hint.setText(t["mode_hint"])
        self.automatic_hint.setText(t["copy_hint"])
        self.draft.setPlaceholderText(t["draft"])
        self.detail_body.setPlaceholderText(t["detail_hint"])
        self.correction_heading.setText(t["correction"])
        for index, label in enumerate(t["levels"]): self.correction_level.setItemText(index, label)
        if not self.selected():
            self.detail_title.setText(t["ready"])
            self.detail_meta.setText(t["select"])
        for index, label in enumerate(t["tabs"]):
            count = sum(history_section(entry) == index for entry in self.entries)
            self.sections.setTabText(index, f"{label} ({count})")

    def save_window_geometry(self):
        mode = ("expanded" if self._expanded else "compact") + ("_actions" if self._actions_expanded else "")
        self.settings.setValue(f"window/{mode}_geometry", self.saveGeometry())
        self.save_panel_sizes()

    def save_panel_sizes(self, *unused):
        if self._layout_transition:
            return
        if self._expanded:
            self.settings.setValue("window/history_detail_sizes", self.history_splitter.saveState())
            self.settings.setValue("window/history_composer_sizes", self.vertical_splitter.saveState())
        if self._actions_expanded:
            self.settings.setValue("window/main_actions_sizes", self.content_splitter.saveState())

    def restore_panel_sizes(self):
        try:
            if self._expanded:
                for key, splitter in (("window/history_detail_sizes", self.history_splitter),
                                      ("window/history_composer_sizes", self.vertical_splitter)):
                    state = self.settings.value(key)
                    if state:
                        splitter.restoreState(state)
            if self._actions_expanded:
                state = self.settings.value("window/main_actions_sizes")
                if state:
                    self.content_splitter.restoreState(state)
        finally:
            self._layout_transition = False

    def _restore_panel_sizes_if_current(self, epoch):
        if epoch == self._layout_epoch:
            self.restore_panel_sizes()

    def set_expanded(self, expanded, initial=False):
        if not initial and expanded == self._expanded:
            return
        if not initial:
            self.save_window_geometry()
        self._layout_transition = True
        self._layout_epoch += 1
        self._expanded = expanded
        self.advanced.setVisible(expanded); self.subtitle.setVisible(expanded)
        self.expand_button.setText(LABELS[self.language]["collapse" if expanded else "expand"])
        self.message.setVisible(expanded)
        self.dropzone.setVisible(not expanded)
        self.dropzone.setMinimumHeight(125)
        self.setMinimumSize((760 if expanded else 680) + (260 if self._actions_expanded else 0), 600 if expanded else 350)
        mode = ("expanded" if expanded else "compact") + ("_actions" if self._actions_expanded else "")
        geometry = self.settings.value(f"window/{mode}_geometry")
        if expanded and not geometry:
            geometry = self.settings.value("window/geometry")
        self.centralWidget().layout().activate()
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.resize((1040 if expanded else 700) + (260 if self._actions_expanded else 0), 780 if expanded else 410)
        QTimer.singleShot(0, lambda epoch=self._layout_epoch: self._restore_panel_sizes_if_current(epoch))
        if self.isVisible():
            self.place_on_cursor_screen()

    def toggle_actions(self):
        self.save_window_geometry()
        self._actions_expanded = not self._actions_expanded
        self.actions_panel.setVisible(self._actions_expanded)
        self.actions_button.setText(LABELS[self.language]["actions"] + (" ◂" if self._actions_expanded else " ▸"))
        self.set_expanded(self._expanded, initial=True)

    def update_ai_status(self, text):
        self.ai_status.setText("IA: " + text)

    def ai_modes_changed(self, control, checked):
        from dataclasses import replace
        if checked and control in (self.spelling_mode, self.grammar_mode):
            other = self.grammar_mode if control is self.spelling_mode else self.spelling_mode
            other.blockSignals(True); other.setChecked(False); other.blockSignals(False)
        mode = "spelling" if self.spelling_mode.isChecked() else "grammar" if self.grammar_mode.isChecked() else "none"
        if self.correction_level.currentData() != mode:
            self.correction_level.blockSignals(True)
            self.correction_level.setCurrentIndex(self.correction_level.findData(mode))
            self.correction_level.blockSignals(False)
        config = replace(self.ai_config, image=self.image_mode.isChecked(), text_mode=mode)
        try:
            config.save(self.args.data_dir)
            self.ai_config = config
            self.clipboard_bridge.capture_image = True
            self.clipboard_bridge.capture_text = True
            if hasattr(self.clipboard_bridge, "rearm"):
                self.clipboard_bridge.rearm()
            self.backend.request("ai_config", config)
        except (OSError, AIError) as exc:
            self.show_error(str(exc))

    def correction_changed(self):
        mode = self.correction_level.currentData()
        if mode == "none":
            if self.spelling_mode.isChecked(): self.spelling_mode.setChecked(False)
            elif self.grammar_mode.isChecked(): self.grammar_mode.setChecked(False)
        elif mode == "spelling":
            self.spelling_mode.setChecked(True)
        elif mode == "grammar":
            self.grammar_mode.setChecked(True)

    def toggle_ai_mode(self, control):
        if not self._quitting and control.isEnabled():
            control.setChecked(not control.isChecked())

    def external_clipboard_changed(self, source):
        if not self.backend.accepting:
            return
        explicit = (self._copy_send_revision is not None and
                    source.get("revision", -1) > self._copy_send_revision)
        if explicit:
            self._copy_send_revision = None
            self._copy_send_armed = False
        if source.get("files"):
            if not explicit:
                return
            paths = source["files"]
            self.add_files(paths)
            if self.ai_config.image:
                if len(paths) != 1:
                    self.show_notice("Archivos enviados. Para Imagen → Markdown, copia y envía una imagen a la vez.")
                    return
                reader = QImageReader(paths[0])
                if not reader.canRead():
                    return
                size = reader.size()
                if size.width() * size.height() > 24_000_000:
                    self.show_error("Imagen enviada, pero supera 24 megapíxeles para IA.")
                    return
                picture = reader.read()
                if picture.isNull():
                    self.show_error("Imagen enviada, pero no se pudo leer para IA.")
                    return
                data = QByteArray(); buffer = QBuffer(data); buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                picture.save(buffer, "PNG")
                if len(data) > 8 * 1024 * 1024:
                    self.show_error("Imagen enviada, pero supera 8 MiB PNG para IA.")
                    return
                self.backend.request("ai_submit", dict(revision=source["revision"], text="", image=bytes(data)))
            return
        if source.get("image"):
            self.backend.request("capture_image" if explicit else "capture_image_local", source["image"])
            # Screenshot pixels arrive without the copy-and-send shortcut.
            if self.ai_config.image:
                self.backend.request("ai_submit", source)
        elif source.get("text"):
            if explicit:
                self.backend.request("clipboard_text", source["text"])
            if explicit and self.ai_config.text_mode != "none":
                self.backend.request("ai_submit", source)
        elif explicit:
            self.show_notice("La selección no contenía texto ni imagen; no se envió nada.")

    def copy_and_send(self):
        """Copy from the foreground app, then publish only its new clipboard revision."""
        if sys.platform not in ("win32", "darwin"):
            self.send_clipboard()
            return
        if not self.backend.accepting or self._copy_send_armed:
            return
        self._copy_send_armed = True
        self._copy_send_started = time.monotonic()
        self._copy_send_binding = self.bindings()["send"]
        self._copy_send_id += 1
        self._wait_for_copy_shortcut_release()

    def _wait_for_copy_shortcut_release(self):
        if not self._copy_send_armed or self._quitting:
            return
        if time.monotonic() - self._copy_send_started > 2:
            self._copy_send_armed = False
            if hasattr(self.clipboard_bridge, "cancel_explicit_copy"):
                self.clipboard_bridge.cancel_explicit_copy()
            self.show_notice("Suelta el atajo para copiar y enviar la selección.")
            return
        released = (self.hotkeys.released(self._copy_send_binding) if sys.platform == "darwin"
                    else shortcut_released(self._copy_send_binding))
        if not released:
            QTimer.singleShot(25, self._wait_for_copy_shortcut_release)
            return
        self._copy_send_revision = self.clipboard_bridge.revision()
        if hasattr(self.clipboard_bridge, "prepare_explicit_copy"):
            self.clipboard_bridge.prepare_explicit_copy()
        copied = (self.hotkeys_copy_selection() if sys.platform == "darwin" else copy_focused_selection())
        if not copied:
            self._copy_send_revision = None
            self._copy_send_armed = False
            if hasattr(self.clipboard_bridge, "cancel_explicit_copy"):
                self.clipboard_bridge.cancel_explicit_copy()
            self.show_error("No se pudo copiar la selección de la aplicación activa. Comprueba el permiso de Accesibilidad.")
            return
        token = self._copy_send_id
        QTimer.singleShot(2500, lambda: self._copy_send_timed_out(token))

    def _copy_send_timed_out(self, token):
        if self._copy_send_armed and self._copy_send_id == token:
            self._copy_send_revision = None
            self._copy_send_armed = False
            if hasattr(self.clipboard_bridge, "cancel_explicit_copy"):
                self.clipboard_bridge.cancel_explicit_copy()
            self.show_notice("La aplicación no copió la selección; no se envió el portapapeles anterior.")

    @staticmethod
    def hotkeys_copy_selection():
        from .macos_platform import copy_focused_selection
        return copy_focused_selection()

    def show_ai_settings(self):
        if not self.ai_dialog:
            self.ai_dialog = AISettingsDialog(self)
            self.ai_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            self.ai_dialog.finished.connect(lambda: setattr(self, "ai_dialog", None))
        self.ai_dialog.show(); self.ai_dialog.raise_()

    def focus_search(self):
        self.set_expanded(True)
        self.search.setFocus()

    def set_controls(self, enabled):
        for item in (self.clip_button, self.file_button, self.inbox_button, self.received_button, self.pause_button,
                      self.pair_button, self.auto_receive, self.clear_button, self.clear_text_button,
                      self.send_button, self.dropzone,
                     self.image_mode, self.spelling_mode, self.grammar_mode):
            item.setEnabled(enabled)

    def make_tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip("Clipboard AI · Iniciando")
        menu = QMenu(self)
        for label, callback in (("Abrir dock", self.show_window), ("Enviar portapapeles", self.send_clipboard),
                                ("Añadir archivos", self.choose_files)):
            menu.addAction(label, callback)
        self.tray_pause = menu.addAction("Pausar conexión", lambda: self.backend.request("pause"))
        menu.addSeparator(); menu.addAction("Salir", self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_window() if reason in (
            QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def bindings(self):
        modifier = "Meta" if sys.platform == "darwin" else "Ctrl"
        defaults = dict(show=f"{modifier}+Alt+D", send=f"{modifier}+Alt+C", spelling=f"{modifier}+Alt+O",
                        image=f"{modifier}+Alt+I", grammar=f"{modifier}+Alt+G")
        bindings = {name: self.settings.value("keys/" + name, default) for name, default in defaults.items()}
        # Upgrade the old shipping default once; subsequent user edits remain editable.
        if not self.settings.value("keys/copy_send_default_migrated", False, type=bool):
            try:
                legacy_send = parse_hotkey(bindings["send"]) == parse_hotkey("Ctrl+Alt+S")
            except ValueError:
                legacy_send = False
            if legacy_send:
                bindings["send"] = defaults["send"]
                self.settings.setValue("keys/send", defaults["send"])
            self.settings.setValue("keys/copy_send_default_migrated", True)
        for name, value in bindings.items():
            if is_copy_hotkey(value):
                bindings[name] = defaults[name]
                self.settings.setValue("keys/" + name, defaults[name])
        self.settings.sync()
        return bindings

    def configure_hotkeys(self, bindings):
        if any(is_copy_hotkey(value) for value in bindings.values() if value):
            return ["Ctrl+C está reservado para copiar; elige otro atajo"]
        assigned = {}
        for name, text in bindings.items():
            if text:
                try:
                    key = parse_hotkey(text)
                except ValueError as exc:
                    return [str(exc)]
                if key in assigned:
                    return [f"{text} ya está asignado a {assigned[key]}"]
                assigned[key] = name
        for shortcut in self.local_shortcuts:
            shortcut.setEnabled(False); shortcut.deleteLater()
        self.local_shortcuts.clear()
        errors = self.hotkeys.configure(bindings)
        if sys.platform not in ("win32", "darwin"):
            for action, text in bindings.items():
                if text:
                    shortcut = QShortcut(QKeySequence(text), self)
                    shortcut.activated.connect(self.hotkey_callbacks[action])
                    self.local_shortcuts.append(shortcut)
        return errors

    def update_state(self, state):
        if self._quitting:
            return
        previous = self.state
        self.state = state
        shared = state.get("shared_settings", {}).get("values", {})
        if shared and (self.ai_config.image != shared["image"] or
                       self.ai_config.text_mode != shared["text_mode"] or
                       self.ai_config.prompts != shared.get("prompts", self.ai_config.prompts)):
            from dataclasses import replace
            self.ai_config = replace(self.ai_config, image=shared["image"],
                                     text_mode=shared["text_mode"],
                                     prompts=shared.get("prompts", self.ai_config.prompts))
            for control, checked in ((self.image_mode, self.ai_config.image),
                                     (self.spelling_mode, self.ai_config.text_mode == "spelling"),
                                     (self.grammar_mode, self.ai_config.text_mode == "grammar")):
                control.blockSignals(True); control.setChecked(checked); control.blockSignals(False)
            self.correction_level.blockSignals(True)
            self.correction_level.setCurrentIndex(self.correction_level.findData(self.ai_config.text_mode))
            self.correction_level.blockSignals(False)
        self.set_controls(True)
        t = LABELS[self.language]
        status = t["paused"] if state["paused"] else t["connected"] if state["connected"] else t["waiting"]
        connected = state.get("connected_peers", [peer["id"] for peer in state["peers"]] if state["connected"] else [])
        names = [peer["name"] + " · " + t["online" if peer["id"] in connected else "offline"] for peer in state["peers"]]
        self.connection.setText(f"● {status}\n" + ("\n".join(names) if names else t["unpaired"]))
        self.tray.setToolTip(f"Clipboard AI · {status}")
        pause_text = LABELS[self.language]["resume" if state["paused"] else "pause"]
        self.pause_button.setText(pause_text); self.tray_pause.setText(pause_text)
        self.auto_receive.blockSignals(True); self.auto_receive.setChecked(state["auto_receive"]); self.auto_receive.blockSignals(False)
        self.usage.setText(f"{t['pending']}: {state['pending_text']} {t['texts']} · {state['pending_files']} {t['files']}    |    Dock: {size_text(state['used'])} / 1 GiB")
        entries = []
        for row in state["texts"]:
            entries.append(dict(kind="text", id=row["id"], row=row, created=row["created"]))
        for row in state["files"]:
            entries.append(dict(kind="file", id=row["id"], row=row, created=row["item"]["created"]))
        entries.sort(key=lambda item: item["created"], reverse=True)
        for index, label in enumerate(LABELS[self.language]["tabs"]):
            count = sum(history_section(entry) == index for entry in entries)
            self.sections.setTabText(index, f"{label} ({count})")
        if entries != self.entries:
            self.entries = entries; self.render_history()
        if previous:
            old_texts = {row["id"] for row in previous["texts"]}
            old_files = {row["id"]: row["state"] for row in previous["files"]}
            for row in state["texts"]:
                if row["id"] not in old_texts:
                    self.queue_notification("sent_text" if row["origin"] == state["device"] else "received_text")
            for row in state["files"]:
                is_image = row["item"]["mime"].lower().startswith("image/")
                if row["id"] not in old_files and row["direction"] == "out":
                    self.queue_notification("sent_image" if is_image else "sent_file")
                elif row["direction"] == "in" and row["state"] == "delivered" and old_files.get(row["id"]) != "delivered":
                    self.queue_notification("received_image" if is_image else "received_file")

    def queue_notification(self, kind):
        if not self.settings.value("notifications", True, type=bool) or not self.tray.isVisible():
            return
        self.notification_counts[kind] += 1
        self.notification_timer.start()

    def flush_notifications(self):
        counts = self.notification_counts.copy()
        for kind in counts:
            self.notification_counts[kind] = 0
        if not self.settings.value("notifications", True, type=bool) or not self.tray.isVisible():
            return
        sent = counts["sent_text"] + counts["sent_image"] + counts["sent_file"]
        received = counts["received_text"] + counts["received_image"] + counts["received_file"]
        if not sent and not received:
            return
        parts = []
        if sent:
            details = self._notification_details(counts, "sent")
            parts.append(f"Enviados al dock: {sent} ({details})")
        if received:
            details = self._notification_details(counts, "received")
            parts.append(f"Recibidos: {received} ({details})")
        self.tray.showMessage("Clipboard AI", " · ".join(parts), QSystemTrayIcon.MessageIcon.Information, 3500)

    @staticmethod
    def _notification_details(counts, prefix):
        labels = (("text", "texto", "textos"), ("image", "imagen", "imágenes"),
                  ("file", "archivo", "archivos"))
        return ", ".join(f"{count} {singular if count == 1 else plural}"
            for suffix, singular, plural in labels
            if (count := counts.get(f"{prefix}_{suffix}", 0)))

    def selected(self):
        item = self.history.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _clean_drag_exports(self):
        root = self.args.data_dir / "drag-export"
        if not root.is_dir():
            return
        cutoff = time.time() - 86400
        for folder in root.iterdir():
            try:
                if (folder.is_dir() and not folder.is_symlink() and len(folder.name) == 32 and
                        all(char in "0123456789abcdef" for char in folder.name) and
                        folder.stat().st_mtime < cutoff):
                    shutil.rmtree(folder)
            except OSError:
                pass  # A document may still hold a previously exported copy open.

    def prepare_drag_files(self, entries):
        files = [entry for entry in entries if entry and entry["kind"] == "file"]
        if not files:
            return []
        for entry in files:
            row = entry["row"]
            if row["state"] not in ("delivered", "pending", "sending") or not Path(row["path"]).is_file():
                raise ValueError("Espera a que termine la recepción del archivo.")
        self._clean_drag_exports()
        folder = self.args.data_dir / "drag-export" / uuid4().hex
        folder.mkdir(parents=True, exist_ok=False)
        paths = []
        try:
            for entry in files:
                row = entry["row"]
                name = Path(row["item"]["name"].replace("\\", "/")).name
                if not name or name in (".", ".."):
                    raise ValueError("Nombre de archivo inválido")
                target = folder / name
                duplicate = 2
                while target.exists():
                    target = folder / f"{Path(name).stem} ({duplicate}){Path(name).suffix}"
                    duplicate += 1
                shutil.copyfile(row["path"], target)
                paths.append(target)
        except BaseException:
            shutil.rmtree(folder)
            raise
        return paths

    def _image_key(self, entry):
        if not entry or history_section(entry) != 1:
            return None
        path = Path(entry["row"]["path"])
        try:
            stat = path.stat()
        except OSError:
            return None
        return (str(path), stat.st_mtime_ns, stat.st_size) if path.is_file() else None

    @staticmethod
    def _read_preview(path):
        reader = QImageReader(path)
        dimensions = reader.size()
        if not dimensions.isValid() or dimensions.width() * dimensions.height() > 100_000_000:
            return QImage()
        reader.setScaledSize(dimensions.scaled(QSize(700, 400), Qt.AspectRatioMode.KeepAspectRatio))
        return reader.read()

    def _request_preview(self, key):
        if key is None or key in self._preview_cache or key in self._preview_pending:
            return
        self._preview_pending.add(key)
        future = self._preview_pool.submit(self._read_preview, key[0])
        def completed(task):
            try:
                image = task.result()
            except Exception:
                image = QImage()
            self.preview_ready.emit(key, image)
        future.add_done_callback(completed)

    def _preview_loaded(self, key, image):
        self._preview_pending.discard(key)
        self._preview_cache[key] = image
        if len(self._preview_cache) > 48:
            del self._preview_cache[next(iter(self._preview_cache))]
        for index in range(self.history.count()):
            item = self.history.item(index)
            if self._image_key(item.data(Qt.ItemDataRole.UserRole)) == key and not image.isNull():
                item.setIcon(QIcon(QPixmap.fromImage(image).scaled(52, 52,
                    Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))
        if self._image_key(self.selected()) == key:
            self._show_preview(key)

    def _show_preview(self, key):
        image = self._preview_cache.get(key)
        self.preview_label.setVisible(True)
        if image is None:
            self.preview_label.setText("Cargando vista previa…")
            self._request_preview(key)
        elif image.isNull():
            self.preview_label.setText("Vista previa no disponible")
        else:
            self.preview_label.setPixmap(QPixmap.fromImage(image).scaled(700, 320,
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def render_history(self, *unused):
        selected = self.selected()
        selected_id = (selected["kind"], selected["id"]) if selected else None
        query = self.search.text().casefold(); mode = self.sections.currentIndex()
        scroll = self.history.verticalScrollBar().value()
        self.history.blockSignals(True); self.history.clear()
        target = None
        for entry in self.entries:
            kind, row = entry["kind"], entry["row"]
            if history_section(entry) != mode:
                continue
            content = row["text"] if kind == "text" else row["item"]["name"]
            if query not in content.casefold():
                continue
            outgoing = row["origin"] == self.state["device"] if kind == "text" else row["direction"] == "out"
            direction = "Local" if kind == "file" and row["direction"] == "local" else "Enviado" if outgoing else "Recibido"
            state = ("Entregado" if row["delivered"] else "Pendiente") if kind == "text" else STATES.get(row["state"], row["state"])
            title = " ".join(content.split())[:85] or "(Texto vacío)"
            prefix = ("Texto", "Imagen", "Archivo")[history_section(entry)]
            progress = ""
            if kind == "file":
                percent = 100 if row["state"] == "delivered" else int(row["offset"] * 100 / max(1, row["item"]["size"]))
                progress = f" · {size_text(row['item']['size'])} · {percent}%"
            item = QListWidgetItem(f"{title}\n{prefix} · {direction} · {state}{progress}")
            if kind == "file" and history_section(entry) == 1:
                key = self._image_key(entry)
                cached = self._preview_cache.get(key)
                if cached is not None and not cached.isNull():
                    item.setIcon(QIcon(QPixmap.fromImage(cached).scaled(52, 52,
                        Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))
                else:
                    self._request_preview(key)
            item.setData(Qt.ItemDataRole.UserRole, entry); self.history.addItem(item)
            if (kind, entry["id"]) == selected_id:
                target = item
        if target:
            self.history.setCurrentItem(target)
        elif self.history.count():
            self.history.setCurrentRow(0)
        self.history.blockSignals(False)
        self.history.verticalScrollBar().setValue(scroll)
        self.show_selection()

    def show_selection(self, *unused):
        self.original_button.hide()
        self.preview_label.hide(); self.preview_label.clear()
        entry = self.selected()
        for item in (self.copy_button, self.open_button, self.location_button, self.save_button, self.delete_button):
            item.hide()
        self.progress.hide()
        if not entry:
            self.detail_title.setText("Sin resultados" if self.search.text() else "Tu dock está listo")
            self.detail_meta.setText("Selecciona un elemento o comparte texto y archivos.")
            self.detail_body.clear(); return
        row, kind = entry["row"], entry["kind"]
        created = entry["created"].replace("T", " ")[:19]
        if kind == "text":
            self.detail_title.setText("Texto enviado" if row["origin"] == self.state["device"] else "Texto recibido")
            if row.get("ai_action"):
                self.detail_title.setText({"image": "Imagen → Markdown", "spelling": "Ortografía", "grammar": "Gramática"}.get(row["ai_action"], "Resultado de IA"))
                self.original_button.show()
            self.detail_meta.setText(f"{created} · {len(row['text'])} caracteres · {'Entregado' if row['delivered'] else 'Pendiente'}")
            body = row["text"]; self.copy_button.show()
            self.delete_button.setText("Cancelar y eliminar" if not row["delivered"] else "Eliminar")
            self.delete_button.show()
        else:
            info = row["item"]; self.detail_title.setText(info["name"])
            image_key = self._image_key(entry)
            if image_key is not None:
                self._show_preview(image_key)
            self.detail_meta.setText(f"{created} · {size_text(info['size'])} · {STATES.get(row['state'], row['state'])}")
            origin = "Captura guardada en este equipo" if row["direction"] == "local" else "PC → teléfono" if row["direction"] == "out" else "Teléfono → PC"
            body = f"{origin}\n\n{info['name']}\n{info['mime']}"
            if row["error"]:
                body += "\n\n" + row["error"]
            if row["state"] == "delivered":
                body += "\n\nUbicación de la copia:\n" + row["path"]
                self.save_button.show(); self.location_button.show()
                self.open_button.setVisible(row["direction"] in ("in", "local") or
                    (row["direction"] == "out" and Path(row["path"]).parent.name == "Capturas"))
            elif row["direction"] == "out" and Path(row["path"]).parent.name == "Capturas" and row["state"] in ("pending", "sending"):
                self.save_button.show(); self.location_button.show(); self.open_button.show()
            if row["state"] in ("pending", "sending", "receiving", "error"):
                self.delete_button.setText("Cancelar"); self.delete_button.show()
            elif row["state"] in ("delivered", "cancelled"):
                self.delete_button.setText("Eliminar"); self.delete_button.show()
            if row["state"] not in ("cancelled", "error"):
                percent = 100 if row["state"] == "delivered" else int(row["offset"] * 100 / max(1, info["size"]))
                self.progress.setValue(percent); self.progress.show()
        if self.detail_body.toPlainText() != body:
            self.detail_body.setPlainText(body)

    def send_clipboard(self):
        self.backend.request("clip")

    def process_selected(self):
        entry = self.selected()
        if not entry:
            self.show_notice("Abre Detalles y selecciona un texto o imagen."); return
        source = dict(revision=self.clipboard_bridge.revision(), text="", image=None, manual=True)
        if entry["kind"] == "text":
            if self.ai_config.text_mode == "none":
                self.show_notice("Activa Ortografía o Gramática para procesar el texto seleccionado."); return
            source["text"] = entry["row"]["text"]
        else:
            if not self.ai_config.image or history_section(entry) != 1:
                self.show_notice("Activa Imagen → Markdown y selecciona una imagen."); return
            row = entry["row"]
            is_capture = row["direction"] == "out" and Path(row["path"]).parent.name == "Capturas"
            if row["state"] != "delivered" and not (is_capture and row["state"] in ("pending", "sending")):
                self.show_notice("Espera a que termine la transferencia."); return
            # Inspect dimensions before decoding a potentially large compressed image.
            from PySide6.QtGui import QImageReader
            reader = QImageReader(row["path"])
            size = reader.size()
            if size.width() * size.height() > 24_000_000:
                self.show_error("Imagen mayor de 24 megapíxeles. Recórtala antes de procesarla."); return
            image = reader.read()
            if image.isNull():
                self.show_error("No se pudo abrir la imagen seleccionada."); return
            data = QByteArray(); buffer = QBuffer(data); buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG"); source["image"] = bytes(data)
            if len(source["image"]) > 8 * 1024 * 1024:
                self.show_error("Imagen mayor de 8 MiB. Recórtala antes de procesarla."); return
        self.backend.request("ai_submit", source)

    def send_text(self):
        text = self.draft.toPlainText()
        if not text:
            self.show_error("Escribe o pega un texto antes de enviarlo."); return
        self.backend.request("send", text)

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Añadir archivos al dock")
        if paths:
            self.add_files(paths)

    def add_files(self, paths):
        if not paths:
            return
        if len(paths) > 100:
            self.show_error("Añade como máximo 100 archivos por selección."); return
        self.show_notice("Preparando copias para enviar…")
        self.backend.request("files", paths)

    def copy_selected(self):
        entry = self.selected()
        if entry and entry["kind"] == "text":
            self.backend.request("copy", entry["id"])

    def file_action(self, mode):
        entry = self.selected()
        if not entry or entry["kind"] != "file":
            return
        destination = None
        if mode == "save":
            destination, _ = QFileDialog.getSaveFileName(self, "Guardar copia", str(Path.home() / entry["row"]["item"]["name"]))
            if not destination:
                return
        self.backend.request("file_path", entry["id"], mode, destination)

    def delete_selected(self):
        entry = self.selected()
        if not entry:
            return
        kind, row = entry["kind"], entry["row"]
        cancel = kind == "file" and row["state"] in ("pending", "sending", "receiving", "error")
        text = ("¿Cancelar esta transferencia?" if cancel else
                "¿Cancelar el envío y eliminar este texto del dock local?" if kind == "text" and not row["delivered"] else
                "¿Eliminar este elemento del dock local?")
        if QMessageBox.question(self, "Clipboard AI", text) != QMessageBox.StandardButton.Yes:
            return
        self.backend.request("delete_text" if kind == "text" else "cancel_file" if cancel else "delete_file", entry["id"])

    def clear_texts(self):
        if not self.state or not self.state["texts"]:
            self.show_notice("No hay textos en el dock."); return
        count = len(self.state["texts"])
        message = (f"¿Eliminar los {count} textos del dock local, incluidos los envíos pendientes?\n"
                   "Los textos que ya llegaron al teléfono permanecerán allí.")
        if QMessageBox.question(self, "Limpiar textos", message) == QMessageBox.StandardButton.Yes:
            self.backend.request("clear_texts")

    def clear_files(self):
        if not self.state:
            return
        count, size = self.state["delivered"]
        if not count:
            self.show_notice("No hay archivos o capturas guardados para limpiar."); return
        text = f"Se eliminarán {count} archivos y capturas del dock ({size_text(size)}).\nLos archivos originales y las copias guardadas fuera del dock se conservan."
        if QMessageBox.question(self, "Limpiar archivos", text) == QMessageBox.StandardButton.Yes:
            self.backend.request("clear")

    def open_folder(self, kind):
        if self.state:
            self.open_path(self.state[kind])

    def open_path(self, path):
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.show_error("No se pudo abrir. Comprueba que existe un programa asociado.")

    def automatic_changed(self):
        self.backend.request("automatic", True, self.auto_receive.isChecked())

    def show_pair(self):
        if self.pair_dialog and self.pair_dialog.isVisible():
            self.pair_dialog.raise_(); self.pair_dialog.activateWindow(); return
        self.pair_dialog = PairDialog(self); self.pair_dialog.show()

    def show_settings(self):
        t = LABELS[self.language]
        dialog = QDialog(self); dialog.setWindowTitle(t["settings_title"]); dialog.resize(560, 560)
        layout = QVBoxLayout(dialog)
        appearance = QFormLayout()
        theme = QComboBox()
        theme.addItem("Paper Light", "light"); theme.addItem("Paper Night", "night")
        theme.setCurrentIndex(theme.findData(self.theme))
        language = QComboBox()
        language.addItem("Español", "es"); language.addItem("English", "en")
        language.setCurrentIndex(language.findData(self.language))
        appearance.addRow(LABELS[self.language]["theme"], theme)
        appearance.addRow(LABELS[self.language]["language"], language)
        layout.addLayout(appearance)
        layout.addWidget(button(t["local_ai"], self.show_ai_settings))
        notifications = QCheckBox(t["notifications"])
        notifications.setChecked(self.settings.value("notifications", True, type=bool)); layout.addWidget(notifications)
        startup = QCheckBox(t["startup"].format(system="macOS" if sys.platform == "darwin" else "Windows"))
        startup.setEnabled(sys.platform in ("win32", "darwin"))
        try:
            startup.setChecked(startup_enabled())
        except OSError as exc:
            self.show_error(str(exc)); startup.setEnabled(False)
        layout.addWidget(startup)
        form = QFormLayout(); bindings = self.bindings(); editors = {}
        for name, label in zip(("send", "show", "spelling", "image", "grammar"), t["hotkeys"]):
            editor = QKeySequenceEdit(QKeySequence(bindings[name])); editor.setMaximumSequenceLength(1)
            editor.setObjectName("hotkey_" + name)
            editors[name] = editor; form.addRow(label, editor)
        layout.addLayout(form)
        hint = QLabel(t["hotkey_hint"])
        if sys.platform == "darwin":
            hint.setText("En Mac, el atajo predeterminado es Control+Opción+C. Funciona fuera del dock cuando concedes Accesibilidad a Clipboard AI o a la terminal que lo inicia. ⌘C conserva la copia normal.")
        elif os.name != "nt":
            hint.setText("En Linux estos atajos funcionan dentro del dock; los atajos globales están disponibles en Windows.")
        hint.setWordWrap(True); layout.addWidget(hint)
        peers = self.state["peers"] if self.state else []
        for peer in peers:
            row = QHBoxLayout(); row.addWidget(QLabel(t["paired"] + ": " + peer["name"]))
            row.addWidget(button(t["unpair"], lambda checked=False, p=peer: self.confirm_revoke(p, dialog)))
            layout.addLayout(row)
        layout.addStretch()
        error = QLabel(); error.setWordWrap(True); error.setStyleSheet("color: #a43d34;"); layout.addWidget(error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons); buttons.rejected.connect(dialog.reject)
        def save():
            requested = {name: editor.keySequence().toString(QKeySequence.SequenceFormat.PortableText) for name, editor in editors.items()}
            try:
                for text in requested.values():
                    if text: parse_hotkey(text)
                errors = self.configure_hotkeys(requested)
                if errors:
                    raise ValueError("; ".join(errors))
                if startup.isEnabled():
                    set_startup(startup.isChecked(), self.launch_arguments())
            except (ValueError, OSError) as exc:
                self.configure_hotkeys(bindings); error.setText(str(exc)); return
            for name, text in requested.items():
                self.settings.setValue("keys/" + name, text)
            self.theme = theme.currentData()
            self.language = language.currentData()
            self.settings.setValue("appearance/theme", self.theme)
            self.settings.setValue("appearance/language", self.language)
            QApplication.instance().setStyleSheet(stylesheet(self.theme))
            self.apply_language()
            self.settings.setValue("notifications", notifications.isChecked()); self.settings.sync()
            dialog.accept()
        buttons.accepted.connect(save); dialog.exec()

    def confirm_revoke(self, peer, dialog):
        if QMessageBox.question(dialog, "Desvincular", f"¿Desvincular {peer['name']}? Tendrás que vincularlo otra vez para conectar.") == QMessageBox.StandardButton.Yes:
            self.backend.request("revoke", peer["id"]); dialog.accept()

    def launch_arguments(self):
        args = ["--data-dir", str(self.args.data_dir), "--bind", self.args.bind, "--port", str(self.args.port)]
        if self.args.advertise:
            args.extend(["--advertise", self.args.advertise])
        if sys.platform == "darwin" and getattr(self.args, "brain", False):
            args.append("--brain")
        return args

    def result(self, action, value):
        if self._quitting:
            return
        if action == "pair":
            if self.pair_dialog and self.pair_dialog.isVisible():
                self.pair_dialog.show_payload(value)
        elif action == "automatic":
            self.settings.setValue("automatic/send", value[0]); self.settings.setValue("automatic/receive_media", value[1]); self.settings.sync()
        elif action == "ai_result":
            self.show_notice("Resultado de IA copiado al portapapeles." if value["written"] else
                             "Resultado de IA guardado en Textos: el portapapeles cambió. Selecciónalo y pulsa Copiar.")
        elif action == "ai_original":
            dialog = QDialog(self); dialog.setWindowTitle("Entrada original de IA"); dialog.resize(680, 520)
            layout = QVBoxLayout(dialog)
            if value["image"]:
                label = QLabel(); pixmap = QPixmap(); pixmap.loadFromData(value["image"], "PNG")
                label.setPixmap(pixmap.scaled(650, 460, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                layout.addWidget(label)
            else:
                editor = QPlainTextEdit(value["text"]); editor.setReadOnly(True); layout.addWidget(editor)
            dialog.exec()
        elif action == "file_path":
            if value["mode"] == "save":
                self.show_notice("Copia guardada en " + value["path"])
            else:
                path = Path(value["path"])
                self.open_path(path.parent if value["mode"] == "folder" else path)
        elif action == "files":
            self.show_notice(f"{value['added']} archivos añadidos al dock.")
            if value["errors"]:
                self.show_error("\n".join(value["errors"]))
        elif action == "send":
            if self.draft.toPlainText() == value["text"]:
                self.draft.clear()
            self.show_notice("Texto guardado para enviar.")
        elif action == "copy":
            self.show_notice("Texto copiado al portapapeles.")
        elif action == "clip":
            self.show_notice("Portapapeles guardado para enviar.")
        elif action == "clear":
            self.show_notice("Archivos y capturas guardados eliminados del dock.")
        elif action == "delete_text":
            self.show_notice("Texto eliminado del dock.")
        elif action == "clear_texts":
            self.show_notice(f"{value} textos eliminados del dock local.")

    def show_notice(self, text):
        if text.startswith("Archivo: consulta files"):
            return
        self.message.setStyleSheet("color: #365a66;"); self.message.setText(text)
        self.message.show()
        if not self._expanded:
            self.feedback_timer.start(5000)

    def show_error(self, text):
        self.message.setStyleSheet("color: #a43d34;"); self.message.setText(text)
        self.feedback_timer.stop(); self.message.show()
        if not self.isVisible() and not self._quitting:
            self.show_window()

    def place_on_cursor_screen(self):
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            frame = self.frameGeometry()
            if not area.contains(frame.center()):
                x = area.x() + max(0, (area.width() - self.width()) // 2)
                y = area.y() + max(0, (area.height() - self.height()) // 2)
            else:
                x, y = self.x(), self.y()
            x = max(area.left(), min(x, area.right() - self.width() + 1))
            y = max(area.top(), min(y, area.bottom() - self.height() + 1))
            self.move(x, y)

    def show_window(self):
        self.showNormal()
        self.place_on_cursor_screen()
        self.raise_(); self.activateWindow()
        if os.name == "nt" and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            ctypes.windll.user32.SetForegroundWindow(int(self.winId()))

    def toggle_window(self):
        if self.isVisible() and not self.isMinimized() and self.isActiveWindow():
            self.hide_if_tray()
        else:
            self.show_window()

    def hide_if_tray(self):
        if self.tray.isVisible() and QSystemTrayIcon.isSystemTrayAvailable():
            self.hide()
        else:
            self.showMinimized()

    def closeEvent(self, event):
        self.save_window_geometry(); self.settings.sync()
        if self._quitting:
            if self._stopped:
                event.accept()
            else:
                event.ignore()
            return
        if self.tray.isVisible() and QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore(); self.hide()
            if not self.settings.value("tray/explained", False, type=bool):
                self.tray.showMessage("Clipboard AI sigue abierto", "La conexión continúa. Abre el dock junto al reloj; usa Salir para cerrarlo.")
                self.settings.setValue("tray/explained", True)
        else:
            event.ignore()
            if QMessageBox.question(self, "Salir de Clipboard AI", "Este escritorio no tiene bandeja disponible. ¿Cerrar la aplicación y su conexión?") == QMessageBox.StandardButton.Yes:
                self.quit_app()

    def quit_app(self):
        if self._quitting:
            return
        self.notification_timer.stop()
        self.flush_notifications()
        self._quitting = True
        self.cursor_activity.set_state("idle")
        self.save_window_geometry(); self.settings.sync()
        self.hotkeys.close(); self.set_controls(False)
        self._preview_pool.shutdown(wait=False, cancel_futures=True)
        self.centralWidget().setEnabled(False)
        self.message.setText("Cerrando y conservando los pendientes…")
        if self._stopped:
            QApplication.instance().quit()
        else:
            self.backend.stop()

    def backend_stopped(self):
        self._stopped = True
        self.cursor_activity.set_state("idle")
        self.set_controls(False)
        if self._quitting:
            self.tray.hide(); QApplication.instance().quit()
        else:
            self.connection.setText("El dock está detenido. Cierra y vuelve a abrir la aplicación.")


def socket_name(directory):
    return "clipboard-ai-" + hashlib.sha256(os.fsencode(os.path.normcase(str(directory)))).hexdigest()[:24]


def activate_existing(name, command):
    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(500):
        return False
    socket.write((command + "\n").encode("ascii")); socket.waitForBytesWritten(500)
    if not socket.waitForReadyRead(1500):
        socket.abort()
        return False
    acknowledged = bytes(socket.readLine(32)).strip() == b"ok"
    socket.disconnectFromServer()
    return acknowledged


class MacCompanionWindow(DockWindow):
    """The same dock UI, with pairing and model work delegated to the brain."""

    def __init__(self, args, settings):
        from .companion import CompanionBackend
        clipboard = QtClipboard(QApplication.clipboard())
        backend = CompanionBackend(args, clipboard,
            settings.value("automatic/receive_media", True, type=bool))
        super().__init__(args, settings, backend=backend, clipboard=clipboard)
        self.apply_language()

    def apply_language(self):
        super().apply_language()
        self.pair_button.setText("Pair brain" if self.language == "en" else "Vincular cerebro")
        self.subtitle.setText("Connected dock · AI runs on the brain" if self.language == "en" else "Dock conectado · el cerebro procesa la IA")

    def show_pair(self):
        if self.backend.credentials:
            self.show_notice("Ya hay un cerebro vinculado. Puedes ver la conexión en Ajustes.")
            return
        payload, accepted = QInputDialog.getMultiLineText(self, "Vincular Mac al cerebro",
            "En el cerebro abre Vincular teléfono. Pega aquí el bloque JSON completo:")
        if accepted and payload.strip():
            self.backend.request("pair", payload.strip())

    def show_ai_settings(self):
        dialog = QDialog(self); dialog.setWindowTitle("Prompts del cerebro"); dialog.resize(640, 620)
        layout = QVBoxLayout(dialog)
        description = QLabel("Estos prompts y modos se sincronizan con el cerebro. La API y el modelo se configuran en el propio cerebro.")
        description.setWordWrap(True); layout.addWidget(description)
        tabs = QTabWidget(); editors = {}
        for key, label in (("image", "Imagen → Markdown"), ("spelling", "Ortografía"), ("grammar", "Gramática")):
            editor = QPlainTextEdit(self.ai_config.prompts[key]); editors[key] = editor
            tabs.addTab(editor, label)
        layout.addWidget(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons); buttons.rejected.connect(dialog.reject)
        def save():
            from dataclasses import replace
            config = replace(self.ai_config, prompts={key: editor.toPlainText() for key, editor in editors.items()})
            try:
                config.save(self.args.data_dir)
            except (OSError, AIError) as exc:
                self.show_error(str(exc)); return
            self.ai_config = config
            self.backend.request("ai_config", config)
            dialog.accept()
        buttons.accepted.connect(save); dialog.exec()

    def update_state(self, state):
        super().update_state(state)
        t = LABELS[self.language]
        status = t["paused"] if state["paused"] else ("Brain connected" if self.language == "en" else "Cerebro conectado") if state["connected"] else ("Waiting for brain" if self.language == "en" else "Esperando al cerebro")
        names = [row["name"] + " · " + t["online" if row.get("connected") else "offline"]
                 for row in state.get("devices", [])]
        self.connection.setText("● " + status + ("\n" + "\n".join(names) if names else ""))
        self.tray.setToolTip("Clipboard AI · " + status)

    def result(self, action, value):
        if action == "pair":
            self.show_notice(value)
        else:
            super().result(action, value)


def serve_activation(name, window):
    server = QLocalServer(window)
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    QLocalServer.removeServer(name)  # Only the holder of the data-directory lock calls this.
    if not server.listen(name):
        raise OSError("No se pudo crear el acceso a la ventana: " + server.errorString())
    def accept():
        while server.hasPendingConnections():
            client = server.nextPendingConnection()
            client.setReadBufferSize(32)
            timer = QTimer(client); timer.setSingleShot(True)
            timer.timeout.connect(client.abort); timer.start(2000)
            def read(c=client):
                if c.canReadLine():
                    command = bytes(c.readLine(32)).strip()
                    if command == b"show":
                        window.show_window()
                    elif command == b"send":
                        window.send_clipboard()
                    c.write(b"ok\n"); c.flush()
                    c.disconnectFromServer()
            client.readyRead.connect(read)
            client.disconnected.connect(client.deleteLater)
            read()
    server.newConnection.connect(accept)
    return server


def main():
    parser = argparse.ArgumentParser(description="Clipboard AI · Dock de escritorio")
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=45821)
    parser.add_argument("--advertise")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--background", action="store_true", help="Iniciar oculto si hay bandeja")
    parser.add_argument("--show", action="store_true", help="Abrir el dock existente")
    parser.add_argument("--send-clipboard", action="store_true", help="Enviar portapapeles usando el dock")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--brain", action="store_true", help="Usar este equipo como cerebro/servidor")
    mode.add_argument("--companion", action="store_true", help="Conectar este equipo a otro cerebro")
    args = parser.parse_args()
    args.data_dir = (args.data_dir or data_directory()).expanduser().resolve()
    app = QApplication([sys.argv[0]])
    app.setApplicationName("Clipboard AI"); app.setOrganizationName("ClipboardAI")
    app.setQuitOnLastWindowClosed(False); app.setStyle("Fusion"); app.setStyleSheet(STYLE)
    name = socket_name(args.data_dir)
    lock = InstanceLock(args.data_dir)
    if not lock.acquire():
        for _ in range(3):
            if activate_existing(name, "send" if args.send_clipboard else "show"):
                return 0
        QMessageBox.warning(None, "Clipboard AI ya está abierto", "Abre el dock desde la bandeja. Si estás usando la terminal anterior, ciérrala primero con quit.")
        return 1
    try:
        settings = QSettings(str(args.data_dir / "desktop.ini"), QSettings.Format.IniFormat)
        companion = args.companion or (sys.platform == "darwin" and not args.brain)
        window = MacCompanionWindow(args, settings) if companion else DockWindow(args, settings)
        server = serve_activation(name, window)
        try:
            migrated_startup = migrate_hidden_startup(window.launch_arguments())
        except OSError:
            migrated_startup = False
        if not args.background or migrated_startup or not QSystemTrayIcon.isSystemTrayAvailable():
            window.show_window()
        window.backend.start()
        if args.send_clipboard:
            def send_when_ready(state):
                window.backend.snapshot.disconnect(send_when_ready)
                window.send_clipboard()
            window.backend.snapshot.connect(send_when_ready)
        result = app.exec()
        window.hotkeys.close(); server.close(); window.tray.hide()
        # Normal exit goes through quit_app. Also stop safely if the OS ends Qt's loop.
        window.backend.stop()
        if window.backend.thread:
            window.backend.thread.join(timeout=10)
        return result
    finally:
        lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
