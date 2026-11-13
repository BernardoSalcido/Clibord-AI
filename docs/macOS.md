# Clipboard AI en macOS

El Mac puede funcionar en **dos modos**:

- **Conectado** (predeterminado): Windows/Linux u otro Mac actúa como cerebro. El Mac conserva su propio dock, envía texto y archivos, recibe los elementos del resto de dispositivos y las acciones de IA se procesan en el cerebro.
- **Cerebro** (`--brain`): el Mac abre el servidor TLS, recibe y distribuye los elementos de todos los dispositivos y ejecuta la IA local con LM Studio/Bionic.

No hay que cambiar la aplicación Android ni la instalación Windows. Los dos modos usan el protocolo actual (`hub-v2`, `files-v1`). Una misma instancia ejecuta **un modo a la vez**.
Para cambiar de conectado a cerebro o viceversa, pulsa **Salir** en el dock antes de abrir el otro modo; abrir un segundo lanzador mientras ya existe una instancia solo recupera la ventana actual.

## Instalar en un Mac Apple Silicon

Requisitos: macOS 14 o posterior, Python 3.11 o posterior, acceso al mismo proyecto en el Mac. Para el modo cerebro instala también LM Studio/llmster y descarga allí el modelo multimodal; el modelo de Windows no se transfiere con este proyecto. Tu MacBook Air M5 con 32 GB de memoria tiene margen para un modelo Qwen de esta clase, aunque la velocidad y el consumo deben medirse en el equipo real.

Desde Terminal, en la carpeta del proyecto:

```bash
python3 -m venv .venv-mac
.venv-mac/bin/python -m pip install -e './desktop[gui]'
.venv-mac/bin/python scripts/run_gui.py
```

Después de instalar, también puedes abrirlo con `sh Iniciar-Mac.sh` o `sh Iniciar-Mac.sh --brain`.

El último comando abre el dock en modo conectado. Para usar el Mac como cerebro:

```bash
.venv-mac/bin/python scripts/run_gui.py --brain
```

En ese modo, abre **Ajustes → IA local** para comprobar la dirección de la API, el nombre exacto del modelo y **Cargar y preparar al iniciar**. Clipboard AI intenta iniciar `lms server start` si el servicio no responde. El servidor de LM Studio debe escuchar solo en `127.0.0.1`; los demás dispositivos se conectan al servidor TLS de Clipboard AI, no directamente a LM Studio. Si la detección del puerto falla, introduce la dirección local real en los ajustes. Para probar LM Studio en Terminal: `lms server status` y `lms ls`.

El cerebro del Mac tiene una identidad y un certificado propios. Para que Android pase a ese cerebro, vincúlalo desde **Vincular teléfono** en el dock del Mac; la vinculación anterior con Windows no se copia automáticamente. Esta versión permite elegir el cerebro al arrancar el Mac, pero aún no cambia dinámicamente el cerebro de una sesión en marcha.

## Vincular el Mac a un cerebro existente

1. En el cerebro abre **Vincular teléfono** y elige una dirección alcanzable desde el Mac. En una red diferente puede ser la dirección privada de Tailscale de ese equipo, siempre que ambos estén conectados a esa red privada.
2. En el Mac abre **Vincular cerebro** y pega **todo el bloque JSON**, incluida la huella y el código. No basta con pegar solo el código. El código vence a los cinco minutos.
3. Comprueba que el Mac muestra **Cerebro conectado**. Copia una selección con **Control+Opción+C**: el texto debe aparecer en el dock del cerebro. Envía un texto desde el cerebro y comprueba que aparece en el dock y portapapeles del Mac.
4. Copia una captura al portapapeles del Mac. Se guarda en Imágenes y viaja al cerebro. Si **Imagen → Markdown** está activado, el cerebro procesa la captura y devuelve el texto al portapapeles del Mac.

La huella del certificado TLS se comprueba **antes** de enviar el código o token. Si cambia, la conexión se rechaza. Los textos y archivos pendientes permanecen en el dock local y se reintentan al recuperar la conexión.

## Permisos y atajos

Los atajos globales predeterminados en Mac son **Control+Opción+C** (copiar selección y enviar), **Control+Opción+D** (dock), **Control+Opción+O** (ortografía), **Control+Opción+I** (imagen a Markdown) y **Control+Opción+G** (gramática). Se editan en Ajustes. La tecla Control física se guarda internamente como `Meta` porque Qt llama `Ctrl` a la tecla Comando (`⌘`) en macOS. **⌘C** sigue siendo la copia normal y no lanza IA.

Para que los atajos funcionen cuando otra aplicación está en primer plano, concede **Accesibilidad** en **Ajustes del Sistema → Privacidad y seguridad → Accesibilidad** a Terminal o a la aplicación que ejecute Clipboard AI. Cierra y vuelve a abrir la aplicación después de conceder el permiso. El Mac utiliza `NSPasteboard.changeCount` para detectar cambios del portapapeles en segundo plano.

El interruptor **Iniciar con macOS y abrir el dock** crea un LaunchAgent para el siguiente inicio de sesión con el modo actual. Mantén la ruta de Python y del proyecto disponible en el Mac. La primera ejecución del servidor puede requerir aceptar la conexión entrante en el cortafuegos de macOS.

## Comprobación en el Mac

Antes de dar por validada la migración, ejecutar en el Mac:

```bash
.venv-mac/bin/python -m pytest desktop/tests -q
```

Probar además, con Windows y Android reales: texto en ambas direcciones, captura con y sin IA, archivo grande, reinicio del Mac y reconexión, portapapeles con la pantalla bloqueada, cambios de modos sincronizados, atajos globales con mayúsculas, cambio de monitor y uso del Mac como cerebro. Las pruebas automáticas en Windows verifican el protocolo compartido; **no sustituyen estas pruebas nativas de macOS**.
