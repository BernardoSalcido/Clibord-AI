"""Desktop presentation preferences. No network or AI state lives here."""

PAPER = {
    "light": dict(background="#eee6dd", surface="#e6dbd1", muted_surface="#dcd3cb",
                  text="#575279", muted="#6b6875", border="#d1c9c2", accent="#286983",
                  accent_hover="#1f5369", accent_text="#ffffff", selection="#dcd3cb"),
    "night": dict(background="#303446", surface="#292c3c", muted_surface="#414559",
                  text="#c6ceef", muted="#b5b7c8", border="#51566c", accent="#11b7c5",
                  accent_hover="#7edede", accent_text="#292c3c", selection="#51566c"),
}

LABELS = {
    "es": {
        "subtitle": "Tu dock de texto y archivos", "settings": "Ajustes", "pair": "Vincular dispositivo",
        "send_clip": "Enviar portapapeles", "expand": "Expandir", "collapse": "Contraer",
        "actions": "Acciones", "automatic": "Acciones automáticas", "image": "Imagen → Texto",
        "spelling": "Corrección media", "grammar": "Corrección alta · thinking",
        "correction": "Corrección de texto", "levels": ("Sin corrección", "Media · ortografía", "Alta · gramática"),
        "process": "Procesar selección", "configure": "Configurar IA", "cancel": "Cancelar tarea",
        "add": "Añadir archivos", "inbox": "Carpeta Entrada", "received": "Recibidos",
        "pause": "Pausar conexión", "resume": "Reanudar conexión", "receive": "Copiar lo recibido",
        "search": "Buscar texto o archivo…", "clear_text": "Limpiar textos",
        "clear_files": "Limpiar archivos", "tabs": ("Textos", "Imágenes", "Archivos"),
        "copy": "Copiar", "open": "Abrir", "location": "Ubicación", "save": "Guardar copia",
        "delete": "Eliminar", "send_text": "Enviar texto", "language": "Idioma", "theme": "Tema",
        "ready": "Tu dock está listo", "select": "Selecciona un elemento para ver su contenido.",
        "drop": "Arrastra archivos aquí para enviarlos", "drop_hint": "Se enviará una copia · Hasta 100 MiB por archivo",
        "mode_hint": "Procesan lo nuevo que copies. El resultado queda listo para pegar.",
        "copy_hint": "Ctrl+C copia normalmente. Usa Ctrl+Alt+C para copiar y enviar.",
        "draft": "Escribe o pega un texto para enviarlo…",
        "detail_hint": "Los textos y archivos aparecerán aquí cuando los compartas.",
        "waiting": "Esperando al teléfono", "connected": "Dispositivo conectado", "paused": "Conexión pausada",
        "offline": "sin conexión", "online": "conectado", "unpaired": "Sin dispositivo vinculado",
        "pending": "Pendientes", "texts": "textos", "files": "archivos",
        "settings_title": "Ajustes de Clipboard AI", "local_ai": "IA local · conexión, modelo y prompts",
        "notifications": "Avisar de envíos y recepciones (agrupar avisos seguidos)",
        "startup": "Iniciar con {system} y abrir el dock", "hotkeys": ("Copiar y enviar", "Mostrar / ocultar dock", "Alternar corrección media", "Alternar Imagen → Texto", "Alternar corrección alta"),
        "hotkey_hint": "Copiar y enviar copia la selección de la aplicación activa, la comparte y usa la acción de IA seleccionada. Atajo inicial: Ctrl+Alt+C. Ctrl+C conserva la copia normal.",
        "paired": "Vinculado", "unpair": "Desvincular",
    },
    "en": {
        "subtitle": "Your text and file dock", "settings": "Settings", "pair": "Pair device",
        "send_clip": "Send clipboard", "expand": "Expand", "collapse": "Collapse",
        "actions": "Actions", "automatic": "Automatic actions", "image": "Image → Text",
        "spelling": "Medium correction", "grammar": "High correction · thinking",
        "correction": "Text correction", "levels": ("No correction", "Medium · spelling", "High · grammar"),
        "process": "Process selection", "configure": "Configure AI", "cancel": "Cancel task",
        "add": "Add files", "inbox": "Inbox folder", "received": "Received",
        "pause": "Pause connection", "resume": "Resume connection", "receive": "Copy received items",
        "search": "Search text or files…", "clear_text": "Clear texts",
        "clear_files": "Clear files", "tabs": ("Texts", "Images", "Files"),
        "copy": "Copy", "open": "Open", "location": "Location", "save": "Save copy",
        "delete": "Delete", "send_text": "Send text", "language": "Language", "theme": "Theme",
        "ready": "Your dock is ready", "select": "Select an item to see its contents.",
        "drop": "Drop files here to send them", "drop_hint": "A copy will be sent · Up to 100 MiB per file",
        "mode_hint": "New copied content is processed. The result is ready to paste.",
        "copy_hint": "Ctrl+C copies normally. Use Ctrl+Alt+C to copy and send.",
        "draft": "Write or paste text to send…",
        "detail_hint": "Shared texts and files will appear here.",
        "waiting": "Waiting for a device", "connected": "Device connected", "paused": "Connection paused",
        "offline": "offline", "online": "connected", "unpaired": "No paired device",
        "pending": "Pending", "texts": "texts", "files": "files",
        "settings_title": "Clipboard AI settings", "local_ai": "Local AI · connection, model and prompts",
        "notifications": "Notify sends and receipts (group consecutive notices)",
        "startup": "Start with {system} and open the dock", "hotkeys": ("Copy and send", "Show / hide dock", "Toggle medium correction", "Toggle Image → Text", "Toggle high correction"),
        "hotkey_hint": "Copy and send copies the selection in the active app, shares it and uses the selected AI action. Default shortcut: Ctrl+Alt+C. Ctrl+C still copies normally.",
        "paired": "Paired", "unpair": "Unpair",
    },
}

AI_SETTINGS = {
    "es": {
        "title": "IA local · Bionic / LM Studio", "api": "API local", "model": "Modelo",
        "preload": "Cargar y preparar el modelo al iniciar",
        "autostart": "Iniciar el servicio local si no responde",
        "probe": "Probar conexión / buscar modelos", "prepare": "Preparar", "release": "Liberar modelo",
        "context": "Contexto al cargar", "output": "Límite de salida (incluye thinking)",
        "image_edge": "Lado máximo de imagen para IA", "original": "Original (sin reducción)",
        "recommended": "1280 px · recomendado",
        "tabs": ("Imagen → Texto", "Media · Ortografía", "Alta · Gramática"),
        "restore": "Restaurar prompts", "save": "Guardar", "cancel": "Cancelar",
        "checking": "Comprobando API…", "connected": "API conectada. Selecciona el modelo y guarda.",
        "hint": "Los prompts se envían con cada petición; la app añade los delimitadores automáticamente.\n"
                "Cada acción es independiente y no acumula conversación. La imagen original se conserva en el dock.\n"
                "Si la API requiere un token, define CLIPBOARD_AI_API_TOKEN antes de abrir el dock.\n"
                "Guardar aplica la dirección y el modelo; Preparar usa la configuración ya guardada.",
    },
    "en": {
        "title": "Local AI · Bionic / LM Studio", "api": "Local API", "model": "Model",
        "preload": "Load and warm up the model at startup",
        "autostart": "Start the local service if it does not respond",
        "probe": "Test connection / find models", "prepare": "Prepare", "release": "Unload model",
        "context": "Context on load", "output": "Output limit (includes thinking)",
        "image_edge": "Maximum image edge for AI", "original": "Original (no resize)",
        "recommended": "1280 px · recommended",
        "tabs": ("Image → Text", "Medium · Spelling", "High · Grammar"),
        "restore": "Restore prompts", "save": "Save", "cancel": "Cancel",
        "checking": "Checking API…", "connected": "API connected. Select the model and save.",
        "hint": "Prompts are sent with each request; the app adds output markers automatically.\n"
                "Each action is independent and does not build a conversation. The original image stays in the dock.\n"
                "If the API requires a token, set CLIPBOARD_AI_API_TOKEN before opening the dock.\n"
                "Save applies the endpoint and model; Prepare uses the saved configuration.",
    },
}


def stylesheet(theme):
    p = PAPER[theme if theme in PAPER else "light"]
    return """
QMainWindow, QDialog, QScrollArea, QWidget#actionsContent {{ background: {background}; }}
QWidget {{ color: {text}; font-family: 'Segoe UI', sans-serif; font-size: 13px; }}
QFrame#card {{ background: {surface}; border: 1px solid {border}; border-radius: 12px; }}
QLabel#preview {{ background: {muted_surface}; border-radius: 8px; }}
QLabel#title {{ font-size: 24px; font-weight: 700; }}
QLabel#muted {{ color: {muted}; }}
QLabel#message {{ background: {muted_surface}; padding: 10px; border-radius: 8px; }}
QPushButton {{ background: {surface}; border: 1px solid {border}; padding: 8px 12px; border-radius: 8px; }}
QPushButton:hover {{ background: {muted_surface}; }}
QPushButton:disabled {{ color: {muted}; background: {muted_surface}; }}
QPushButton#primary {{ background: {accent}; color: {accent_text}; border-color: {accent}; font-weight: 600; }}
QPushButton#primary:hover {{ background: {accent_hover}; }}
QLineEdit, QPlainTextEdit, QComboBox, QKeySequenceEdit {{ background: {surface}; border: 1px solid {border};
 border-radius: 8px; padding: 7px; selection-background-color: {selection}; selection-color: {text}; }}
QListWidget {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 5px; }}
QListWidget::item {{ padding: 9px 7px; border-bottom: 1px solid {border}; }}
QListWidget::item:selected {{ background: {selection}; color: {text}; border-radius: 5px; }}
QProgressBar {{ border: 1px solid {border}; border-radius: 5px; background: {muted_surface}; text-align: center; }}
QProgressBar::chunk {{ background: {accent}; }}
QCheckBox::indicator {{ width: 15px; height: 15px; background: {surface}; border: 1px solid {border}; border-radius: 4px; }}
QCheckBox::indicator:checked {{ background: {accent}; border: 2px solid {accent}; }}
QSplitter::handle {{ background: {border}; }}
QSplitter::handle:hover {{ background: {accent}; }}
QTabBar::tab {{ background: {muted_surface}; padding: 8px 18px; margin-right: 4px; border-radius: 7px; }}
QTabBar::tab:selected {{ background: {accent}; color: {accent_text}; }}
""".format(**p)
