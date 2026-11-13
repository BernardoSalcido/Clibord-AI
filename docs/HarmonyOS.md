# Clipboard AI en MatePad Pro Max GEM-W09

La GEM-W09 con HarmonyOS 4.3.0 permite ejecutar la APK Android actual. La variante Harmony usa el mismo protocolo y código de transferencia que la app del teléfono, pero se distribuye como una aplicación independiente (`org.clipboardai.app.harmony`). Esto permite instalar ambas sin borrar la vinculación ni los datos de la app Android existente.

## Compilación

En Windows, `scripts/build_android.ps1 -Check` construye y comprueba las dos variantes:

- `dist/ClipboardAI-Android-0.3.6-debug.apk` para el teléfono Android. Mantiene `org.clipboardai.app` y actualiza la instalación existente.
- `dist/ClipboardAI-Harmony-0.3.6-debug.apk` para la MatePad. Usa `org.clipboardai.app.harmony` y se instala por separado.

## Primera conexión de la variante Harmony

1. Abre Clipboard AI en el ordenador y comprueba que indique que espera dispositivos o está conectado.
2. En el ordenador, genera una vinculación nueva. El código anterior caduca; no sirve un bloque antiguo.
3. En la nueva aplicación MatePad, abre **Ajustes → Vincular ordenador** y escanea el QR o pega el bloque JSON completo.
4. Pulsa **Conectar**. La dirección indicada en el QR debe ser alcanzable desde la tableta. Si la IP del ordenador cambia, usa **Ajustes → Dirección del cerebro** para actualizarla conservando la identidad TLS.

El código `code` aislado no basta para vincular: hacen falta dirección, puerto y huella TLS. Si aparece “El cerebro no acepta conexiones”, comprueba que Clipboard AI esté abierto en el ordenador y escuchando. Si se muestra un error de identidad TLS, vuelve a vincular después de comprobar que se trata del ordenador correcto.

Esta variante es para la GEM-W09 con la capa compatible con APK de HarmonyOS 4.3.0. La compatibilidad con HarmonyOS NEXT u otras versiones necesitará una prueba aparte.

## Recortes y SuperHub

La ruta principal para Take Snippet es **Compartir → Clipboard AI · MatePad**. La aplicación recibe la imagen temporal aunque no se guarde en Galería; la copia entra en Imágenes del dock y, si Imagen → Markdown está activado, el cerebro genera texto y lo devuelve al portapapeles al llegar en vivo.

También puedes abrir Clipboard AI junto a SuperHub y arrastrar imágenes o texto a la ventana de Clipboard AI. El soporte de arrastre depende de que SuperHub entregue una URI o texto accesible a esta APK; hay que comprobarlo en la GEM-W09. Para sacar un texto del dock hacia otras apps, usa **Compartir** en la tarjeta de texto o mantén pulsada la tarjeta para arrastrarla. Que SuperHub acepte ese gesto también requiere una prueba en el equipo real.

## Ventana flotante y apariencia

La app admite ventanas redimensionables. HarmonyOS controla el modo en que se abre desde el icono; para abrirla directamente como ventana flotante, añádela al dock de varias ventanas de Huawei y ábrela desde allí. También se puede usar el control de ventana flotante de la vista de aplicaciones recientes. No hay una opción Android documentada que obligue a HarmonyOS 4.3 a abrir una APK siempre en modo flotante desde cualquier acceso directo.

En **Ajustes y conexión → Apariencia** puedes elegir tema claro u oscuro y uno de cuatro colores principales. Cuando llega un texto y la app actualiza el portapapeles, la MatePad muestra un aviso breve «Portapapeles actualizado»; también queda el estado en la notificación de la conexión.
