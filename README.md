# Clipboard AI

Dock de portapapeles, imágenes y archivos entre dispositivos. Un ordenador
actúa como **cerebro**: recibe, almacena y distribuye contenido, y ejecuta las
acciones de IA local. Los teléfonos y tabletas funcionan como clientes. Este
proyecto se ha desarrollado mediante programación asistida por IA («vibe
coding») y sigue en desarrollo.

**English:** Clipboard AI shares text, images and files across paired devices.
One desktop acts as the hub and runs a local vision/language model. Windows,
Android and HarmonyOS have been used on real devices; macOS and Linux still
need native validation. The project was built with AI-assisted coding.

## Estado de plataformas

| Plataforma | Estado actual |
| --- | --- |
| Windows | Dock y cerebro probados; ejecutable e instalador 0.6.2. |
| Android 14 / OxygenOS | Cliente 0.3.9 probado con un OnePlus. |
| HarmonyOS 4.3 | Cliente 0.3.9 probado con una MatePad compatible con APK Android; no implica compatibilidad con HarmonyOS NEXT. |
| macOS Apple Silicon | Código para cliente y cerebro; faltan pruebas en un Mac real. Véase [macOS](docs/macOS.md). |
| Linux | CLI/cerebro y GUI en código; faltan pruebas en un escritorio Linux real. |

Las versiones de escritorio y móvil tienen numeraciones distintas. El soporte
para nuevas versiones de Android, otras tabletas, atajos globales en Linux y
permisos de macOS no está confirmado todavía.

## Funciones

- Dock con listas de textos, imágenes y otros archivos; transferencia a varios
  dispositivos vinculados mediante TLS y confirmación por destinatario.
- Acciones automáticas **Imagen → Texto**, **corrección media** (ortografía)
  y **corrección alta** (gramática con razonamiento). Los prompts se envían con
  cada petición desde Clipboard AI; el modelo no necesita un prompt global.
- Resultados de IA en el dock y, si no hubo una copia más reciente, en el
  portapapeles. Las capturas también se conservan como imágenes.
- Cliente móvil con Compartir → Clipboard AI, selección de varias imágenes,
  botón de Ajustes rápidos y vista compacta. La variante MatePad admite
  compartir recortes desde SuperHub.
- Temas Paper Light/Paper Night e interfaz en español o inglés.

La vinculación por QR configura una dirección del cerebro; **no crea una VPN**.
En redes distintas hace falta una ruta alcanzable y privada, por ejemplo una
VPN configurada por el usuario. El cerebro debe estar encendido y accesible.

## IA local probada

La prueba principal en Windows se hizo con **LM Studio (Bionic)** y su **Local
API**, modelo multimodal `qwen/qwen3.5-9b` Q4_K_M, en una **RTX 4070 Laptop
GPU con 8 GB de VRAM**. No se distribuye el modelo con esta aplicación. Los
ajustes usados y la diferencia entre el contexto de Bionic y el de Clipboard
AI están en [configuración de IA](docs/AI-SETUP.md). La fidelidad de OCR,
especialmente fórmulas, debe revisarse antes de usar el resultado.

## Instalación y desarrollo

### Windows

Desde la raíz del proyecto, con Windows y Python 3.11 o posterior:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Build-Windows.ps1
```

El script genera `dist/windows/ClipboardAI/ClipboardAI.exe` y, con Inno Setup 6,
`dist/windows/ClipboardAI-0.6.2-Setup.exe`. Comprueba el arranque con datos
temporales y rechaza archivos personales en el paquete. Para ejecutar el
código sin compilar: `python -m pip install -e "./desktop[gui]"` y después
`python scripts/run_gui.py`.

### Android y HarmonyOS

Abre `android/` con Android Studio o prepara el entorno local con
`python scripts/prepare_android.py`. En Windows, ejecuta:

```powershell
./scripts/build_android.ps1 -Check
```

Se generan `dist/ClipboardAI-Android-0.3.9-debug.apk` y
`dist/ClipboardAI-Harmony-0.3.9-debug.apk`. Son APK **de depuración** con una
clave local que no se publica. Para distribuir actualizaciones a terceros se
necesita una firma de publicación propia. Consulta [la guía de MatePad](docs/HarmonyOS.md).

### macOS y Linux

El código de ambos está disponible, pero **no hay instaladores validados**.
En macOS, el Mac puede conectarse como cliente o iniciarse con `--brain`; sigue
la [guía de pruebas de macOS](docs/macOS.md). En Linux, crea un entorno Python,
instala `./desktop[gui]` y ejecuta `sh Iniciar-Linux.sh`. Estas rutas requieren
pruebas nativas antes de anunciar compatibilidad completa.

## Vinculación y privacidad

Inicia el cerebro, crea un QR nuevo desde **Vincular dispositivo** y escanéalo
en el cliente. Verifica que la dirección mostrada sea alcanzable desde el
cliente. El código caduca; el QR y su bloque JSON conceden acceso temporal y
no deben compartirse públicamente. El historial, la identidad TLS y las
credenciales se guardan en los datos locales de cada instalación. En Windows
la carpeta es `%LOCALAPPDATA%\ClipboardAI`; no forma parte del repositorio ni
del instalador. Desinstalar el programa no borra esos datos automáticamente.

## Versiones y contribuciones

Git conserva cada **commit** y cada etiqueta de versión. Los cambios en esta
carpeta **no aparecen solos en GitHub**: hay que revisarlos, crear un commit y
enviarlo con `git push`. Así se evita publicar por accidente claves, historial
o cambios sin probar. Una instalación existente tampoco se actualiza sola al
cambiar el código; necesita un nuevo instalador o APK. Véase
[publicación y controles](docs/PUBLICATION.md).

Pruebas de escritorio: `./scripts/test_desktop.ps1`. Pruebas de Android y
HarmonyOS: `./scripts/build_android.ps1 -Check` en el entorno preparado.

## Documentación

- [Configuración de LM Studio/Bionic](docs/AI-SETUP.md)
- [Estado y proceso de publicación](docs/PUBLICATION.md)
- [Protocolo](docs/protocol.md)
- [macOS](docs/macOS.md) y [HarmonyOS](docs/HarmonyOS.md)
- [Licencia MIT](LICENSE)
