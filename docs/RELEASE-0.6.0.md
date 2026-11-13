# Clipboard AI 0.6.0 — Windows

La interfaz de escritorio incorpora Paper Light y Paper Night con los colores
base de los clientes Android/HarmonyOS, selección de español o inglés para la
navegación y los ajustes principales, y un selector de corrección de texto
(ninguna, media, alta). La vista principal elimina controles que aún no tenían
función. Se conservan los atajos globales, la vinculación y el procesamiento de IA.

## Descarga local

- Instalador: `dist/windows/ClipboardAI-0.6.0-Setup.exe`
- Ejecutable portable: `dist/windows/ClipboardAI/ClipboardAI.exe` junto con
  toda su carpeta `_internal`.
- SHA-256 del instalador: `DF47785CFB8F16751122FB0F8FDDBB1F1D3730679E6506BDA05DA0B2977DA177`

## Comprobación

La suite de escritorio completó 136 pruebas. El ejecutable portable arrancó
con datos temporales y el instalador se instaló, ejecutó con `--help` y
desinstaló en una carpeta de prueba. Queda por comprobar en el uso diario la
apariencia en varias resoluciones, el modelo local y la sincronización con
dispositivos reales.

Los diálogos avanzados de IA y algunos mensajes de diagnóstico todavía se
muestran en español al elegir inglés. No se modificó el protocolo de red.
