# Clipboard AI 0.6.2 — ajustes de IA y paquete Windows

El diálogo de IA local usa el idioma elegido en el dock. Sus acciones aparecen
como **Imagen → Texto**, **Media · Ortografía** y **Alta · Gramática** (o sus
equivalentes en inglés). Los prompts guardados y el procesamiento no cambian.

- Instalador: `dist/windows/ClipboardAI-0.6.2-Setup.exe`
- SHA-256: `78B912048BEECA1D262AC109183268114DBF4A85EEE6A31DFF4994C37783C44C`
- Verificación: 138 pruebas de escritorio pasaron antes del último ajuste de
  etiquetas; después pasaron las 3 pruebas específicas del diálogo y temas.
  El ejecutable arrancó el cerebro con datos temporales. Se revisaron 234
  archivos empaquetados sin detectar archivos de vinculación o datos personales.

El script de compilación interrumpe la creación del instalador si aparecen
certificados personales, claves, ajustes de usuario o bases de datos en el
paquete. El instalador incluye solamente `dist/windows/ClipboardAI/`, no la
carpeta personal `%LOCALAPPDATA%\ClipboardAI`.

Cierra Clipboard AI desde la bandeja antes de instalar esta versión.
