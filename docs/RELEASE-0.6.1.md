# Clipboard AI 0.6.1 — corrección del instalador Windows

La versión 0.6.0 podía abrir la ventana, pero el cerebro no iniciaba porque el
Python usado para compilar requiere un certificado auxiliar al crear
`ssl.SSLContext`. PyInstaller no lo incluía. La compilación 0.6.1 lo incorpora
solo cuando ese Python lo requiere. El dock conserva el certificado TLS y los
datos de vinculación de la instalación anterior.

- Instalador: `dist/windows/ClipboardAI-0.6.1-Setup.exe`
- SHA-256: `6B81C659F3B193A7EDB6B9D835C1700B806E420FCCB98941964A94171DA6E9A5`
- Verificación: 136 pruebas de escritorio; el ejecutable final inició el
  cerebro con datos temporales, creó la base de datos y no generó error de
  arranque.

Cierra Clipboard AI desde su icono de bandeja antes de instalar la actualización.
Después abre el dock y comprueba que el estado de conexión se actualiza.
Si el inicio falla, la traza queda en `startup-error.log` dentro de la carpeta
de datos de Clipboard AI.
