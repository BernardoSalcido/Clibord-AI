# Publicación y compilación de Clipboard AI

Clipboard AI es un proyecto desarrollado mediante programación asistida por IA
(«vibe coding»). Las funciones que aparecen aquí se han probado por partes; revisa
el resultado generado y los permisos antes de usarlo con datos sensibles.

## Plataformas

| Plataforma | Estado | Forma de ejecución |
| --- | --- | --- |
| Windows | Dock, cerebro y cliente | Ejecutable portable o instalador Inno Setup |
| Android 14 | Cliente | APK Android |
| HarmonyOS 4.3 | Cliente | APK Harmony de este repositorio |
| macOS Apple Silicon | Cliente o cerebro | Código Python; requiere prueba física de permisos y atajos |
| Linux | CLI/cerebro | Código Python; la GUI requiere validación de escritorio |

El cerebro ejecuta la red y las peticiones al modelo local. Cada dispositivo
vinculado conserva una copia de los elementos recibidos. La vinculación usa un
código temporal y comprobación de huella TLS. El QR y el bloque de vinculación
conceden acceso: compártelos solo con tus dispositivos.

## Windows: compilar

Requiere Windows, Python 3.11 o posterior y acceso a PyPI para descargar las
dependencias. En PowerShell, desde la raíz del proyecto:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Build-Windows.ps1
```

El script genera `dist/windows/ClipboardAI/ClipboardAI.exe`, que se ejecuta
sin instalar Python. Si Inno Setup 6 está disponible, también genera
`dist/windows/ClipboardAI-0.6.0-Setup.exe`. La compilación de PyInstaller es
específica de Windows: compílala en Windows. El instalador no borra los datos
de vinculación en `%LOCALAPPDATA%\ClipboardAI` al desinstalar.

Para probar sin crear instalador:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Build-Windows.ps1 -SkipInstaller
```

Antes de distribuir, inicia el ejecutable portable con un directorio de datos
temporal, comprueba que abra la ventana, que guarde apariencia, que se vincule
con un dispositivo y que el modelo local responda. Luego instala el paquete
y repite la prueba en una cuenta Windows distinta. El archivo publicado debe
acompañarse de su SHA-256 y de las licencias de dependencias incluidas.

## Datos que no se publican

No subas `%LOCALAPPDATA%\ClipboardAI`, `ai.json`, `desktop.ini`, bases de datos,
certificados, claves privadas, bloques QR ni `android/local.properties` o
`debug.keystore`. La carpeta `dist/` se excluye de Git; distribuye binarios
mediante una Release después de probarlos. Ejecuta `git status --short` y
revisa cada archivo agregado antes del primer push público.

## Publicación

El código se distribuye bajo MIT. Crea un repositorio público en GitHub,
sube el árbol auditado y publica una Release con instalador, APKs y sumas
SHA-256. Los binarios de Qt/PySide6 tienen licencias propias; incluye sus
avisos correspondientes en la Release.
