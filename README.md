# Clipboard AI · escritorio 0.6.0

Dock de portapapeles y archivos para Windows, Android, HarmonyOS, macOS y Linux.
La computadora elegida como **cerebro** sincroniza dispositivos y ejecuta la
IA local. El proyecto se ha creado con programación asistida por IA
(«vibe coding»). Consulta [estado de plataformas, compilación y publicación](docs/PUBLICATION.md).

En Windows, la interfaz ofrece **Paper Light** y **Paper Night**, selección de
español o inglés, tres niveles de corrección de texto y la acción Imagen → Texto.
Las preferencias de apariencia se guardan en el equipo.

## Descargas y primeros pasos

- Windows: compila el ejecutable y el instalador con `scripts/Build-Windows.ps1`.
- Android 14 y HarmonyOS 4.3: compila el APK desde `android/` según las instrucciones de este README.
- macOS: consulta [docs/macOS.md](docs/macOS.md). En Linux usa el CLI de `desktop/`.
- Abre el dock, vincula los dispositivos por QR y elige el cerebro donde corre el modelo local.

Los archivos personales y las claves de vinculación permanecen en la carpeta
de datos de cada instalación. No publiques QR ni configuraciones locales.

**macOS (Apple Silicon):** esta etapa añade un dock de escritorio que puede conectarse a otro cerebro o funcionar como cerebro con `--brain`. Consulta [instalación, vinculación y pruebas en Mac](docs/macOS.md). La integración y el protocolo se probaron localmente; los permisos y atajos globales requieren una prueba física en macOS.

Los clientes Android y HarmonyOS actuales se compilan con versión 0.3.9. Varios teléfonos o tabletas pueden vincularse con el mismo cerebro. Los textos, imágenes y archivos se distribuyen con confirmación por destinatario; las imágenes recibidas y los textos compartidos se procesan en el cerebro cuando está activa su acción de IA. Los clientes móviles ofrecen una vista compacta, acciones y un dock que separa Textos, Imágenes con miniaturas y Archivos. Para generar las APK actuales, usa `scripts/build_android.ps1`.

Dock de texto y archivos entre Windows y Android, con ventana y modo de terminal opcional en el PC y una aplicación nativa en el teléfono. Primera pareja: Windows y OnePlus LE2115 con OxygenOS 14.0.

## Prueba de esta etapa en el OnePlus

1. En el móvil instala `dist/ClipboardAI-0.3.3-debug.apk` encima de la versión anterior y usa **Ajustes → Conectar**. No necesitas repetir la vinculación ni actualizar el programa Windows para esta interfaz.
2. Abre **Acciones** en Android, activa **Imagen → Markdown** y, si quieres, **Detectar capturas nuevas del teléfono**. Para la detección automática, concede acceso a **todas las imágenes**. Si prefieres no concederlo, usa **+ Añadir → Imágenes** o **Compartir → Clipboard AI** desde la galería. Puedes seleccionar hasta 20 imágenes en un lote.
3. Comparte varias imágenes desde la galería con **Clipboard AI**. Se incorporan al dock al elegir la app, sin pulsar Enviar otra vez. Revisa **Abrir dock → Imágenes**: cada una tiene miniatura, estado y opciones. El cerebro procesa las imágenes recibidas cuando está activa la acción y devuelve los resultados en **Textos**. Para un lote, cada imagen genera su propio resultado; el último resultado recibido queda en el portapapeles si no has copiado algo más reciente.
4. Activa **Ortografía** o **Gramática** y envía un texto con **Enviar portapapeles**, **Compartir → Clipboard AI** o la acción sobre texto seleccionado. El cerebro usa el mismo modelo y devuelve la corrección. Los prompts se editan en **Acciones → Prompts de las acciones** y se comparten con Windows.
5. Para probar dos móviles o tabletas, vincula el segundo desde **Vincular teléfono** en Windows. La lista de dispositivos mostrará quién está conectado; las entradas nuevas se entregan y confirman por separado.

### Enviar el portapapeles Android desde cualquier aplicación

Abre **Acciones → Añadir botón rápido · Enviar portapapeles**. Acepta añadir **Enviar al dock** a Ajustes rápidos. Si OxygenOS no presenta la invitación, desliza dos veces desde arriba, pulsa **Editar** y arrastra **Enviar al dock** a tus botones visibles. Después copia texto o una imagen en otra aplicación, abre Ajustes rápidos y toca **Enviar al dock**. Si el móvil está bloqueado, Android pedirá desbloquearlo. Aparece una ventana breve con el resultado; el contenido queda guardado para enviarse al cerebro incluso si la conexión está temporalmente caída. El botón no lee el portapapeles continuamente: cada toque es un envío explícito. Las imágenes o archivos copiados como URI se guardan en la bandeja; elementos que una aplicación no coloque realmente en el portapapeles deben enviarse con **Compartir → Clipboard AI**.

Para usar datos móviles, instala [Tailscale](https://tailscale.com/download) en el teléfono y en el cerebro, inicia ambos en la misma red privada y escribe la dirección privada del cerebro en **Ajustes → Dirección del cerebro**. La app continúa verificando el certificado TLS ya vinculado. La computadora debe estar encendida y escuchando. Si Android pierde la conexión, sus envíos permanecen pendientes. Windows es el cerebro probado con el teléfono; el nuevo modo cerebro de macOS requiere pruebas físicas según [la guía de Mac](docs/macOS.md).

## IA local: primera prueba

1. Activa **Local API** en Bionic, con inicio automático del servidor. En este equipo se detectó `http://127.0.0.1:1235` y el modelo `qwen/qwen3.5-9b`, variante Q4_K_M. La dirección se detecta desde la configuración publicada por Bionic/LM Studio y puede cambiarse en **Ajustes → IA local**.
2. Abre Clipboard AI y espera **IA lista**. Consulta modelos disponibles, reutiliza el seleccionado si ya está cargado o solicita su carga; después envía una imagen sintética de calentamiento. No usa tu portapapeles para preparar el modelo. La carga preserva los ajustes guardados de GPU, caché y microbatch, con contexto inicial 2048, batch 512 y Flash Attention. Las pruebas detectaron microbatch 128 y concurrencia 1 en tu configuración.
3. Abre **Acciones** y activa **Imagen → Markdown**, **Texto → Ortografía** o **Texto → Gramática**. Selecciona el contenido y usa **Copiar y enviar** (Ctrl+Alt+C por defecto). También puedes seleccionar un archivo de imagen en el Explorador y usar ese atajo: se añade al dock y se procesa si está activo Imagen → Markdown. Para IA desde el Explorador, envía una imagen a la vez. Ctrl+C de texto no inicia peticiones al LLM. Las capturas que llegan como imagen al portapapeles sí se procesan automáticamente cuando está activo Imagen → Markdown. Ortografía y Gramática son mutuamente excluyentes; el modo de imagen es independiente. Para una captura ya guardada en Imágenes, usa **Procesar selección**.
4. Los resultados propios y los textos recibidos/copias hechas desde el dock no disparan otro procesamiento. Cada petición tiene instrucciones independientes y sin historial. Los prompts se editan en **Configurar IA**; el contrato de salida con `<<<CLIPBOARD_START>>>` / `<<<CLIPBOARD_END>>>` se añade automáticamente. Solo el contenido validado se copia; errores, respuesta truncada, vacía o sin un par único no cambian el portapapeles.
5. Si copias otra cosa durante la espera, el resultado anterior queda en **Textos**, sin sobrescribir lo nuevo. Hay una tarea activa y una entrada pendiente: una entrada nueva sustituye la pendiente. **Cancelar tarea** invalida el trabajo activo y vacía la pendiente. La cancelación cierra la petición de generación cuando es posible; una carga de modelo ya iniciada se comparte para evitar duplicarla.
6. El texto de entrada y el resultado corregido se publican una sola vez. Si el portapapeles cambia durante el procesamiento, el resultado se conserva en Textos sin sobrescribir esa copia más reciente. Los envíos manuales siguen disponibles.
7. **Ver entrada** permite revisar el texto o la imagen original asociado al resultado. Se retienen hasta 20 entradas originales y 64 MiB de imágenes en total, separadas de la cuota de archivos; resultados anteriores pueden permanecer sin su entrada original. Borrar un resultado borra su entrada asociada. **Procesar selección** usa el texto o imagen del historial con el modo correspondiente activo.
8. **Configurar IA → Probar conexión / buscar modelos** consulta la dirección escrita. **Guardar** aplica dirección/modelo/prompts; **Preparar** usa lo ya guardado. Si la API requiere autenticación, define `CLIPBOARD_AI_API_TOKEN` antes de abrir el programa; no se guarda el token en ai.json. Ese archivo, junto a desktop.ini, contiene preferencias y prompts locales.

La interfaz y la red funcionan mientras el modelo carga o procesa. La lectura de imágenes se hace en Qt y tiene un límite de 24 megapíxeles y 8 MiB PNG; recorta capturas grandes. Las entradas/salidas deben caber en el contexto del modelo: la API puede rechazar documentos largos y la salida tiene inicialmente un límite de 1024 tokens. No se amplía el contexto automáticamente porque afecta a la VRAM. OCR y corrección requieren revisión para comprobar fidelidad en documentos científicos.

Las fórmulas de OCR se normalizan a bloques `$$` + salto de línea + expresión + salto de línea + `$$`. El resto del Markdown conserva su formato. Esta instrucción se añade por petición incluso con prompts personalizados; no es necesario restaurarlos. Los bloques de código y precios como `$5 and $10` se preservan. Las escrituras propias llevan una marca MIME privada y se ignoran sus avisos tardíos durante un intervalo breve. Una copia nueva del usuario, incluso con el mismo texto, puede volver a procesarse.

En Windows se consulta el contador de cambios cada 200 ms y se reintenta brevemente la lectura de datos tardíos. Una captura que Recortes coloque en el portapapeles se guarda localmente en Imágenes. Si está activo Imagen → Markdown, la captura se procesa automáticamente; también puedes usar Procesar selección. Los píxeles tienen prioridad sobre una ruta asociada y se aceptan datos PNG aunque Qt no anuncie hasImage. Las rutas copiadas desde el Explorador se incorporan como archivos originales al usar Copiar y enviar.

**Gramática usa thinking**, con un presupuesto por petición de hasta 512 tokens o la mitad del límite de salida. Así se anula para esa petición un presupuesto cero guardado en Bionic. OCR, Ortografía y calentamiento usan razonamiento desactivado. Los tokens de thinking consumen parte del límite de salida y nunca se copian al portapapeles. En una prueba corta Gramática tardó unos 24 s con thinking; aumenta el límite de salida si una entrada larga termina truncada, sin ampliar automáticamente el contexto ni la VRAM.

Si la API no responde, se intenta iniciar la instalación local publicada por Bionic/LM Studio en segundo plano. Es necesario haber activado el inicio automático de Local API una vez. No se cierran aplicaciones existentes. **Liberar modelo** solo descarga una instancia que este cliente haya cargado; si ya estaba abierta, se libera desde Bionic. Se ha probado la carga automática desde modelo descargado; no se ha cerrado Bionic durante esta entrega para comprobar el arranque en frío de su aplicación.

## Usar el dock visual

1. Cierra la ventana anterior con **Salir** (o la terminal con `quit`). Abre **Iniciar-Windows.cmd**: aparece un dock compacto con conexión y nombres de dispositivos, Vincular teléfono/Ajustes/Salir, la zona para arrastrar y **Enviar portapapeles como texto**. Las dependencias gráficas ya están preparadas en este ordenador.
2. Si el teléfono ya estaba vinculado, pulsa **Conectar** en Android cuando sea necesario. No vuelvas a vincularlo. El estado del dock mostrará **Teléfono conectado**.
3. Selecciona texto o una imagen en cualquier aplicación de Windows y pulsa **Ctrl+Alt+C**: se copia, se envía y se procesa con la acción de IA activada. **Ctrl+C** de texto solo copia localmente, sin activar IA. Las capturas del portapapeles se guardan en Imágenes y se procesan automáticamente si está activo Imagen → Markdown. Para acceder al historial y las demás acciones, pulsa **Expandir**. **Contraer** recupera el dock pequeño; al volver a iniciar siempre abre en compacto. Cada vista conserva su tamaño y posición por separado.
4. Para enviar archivos, usa **Añadir archivos**, arrástralos a la zona indicada o cópialos a **Carpeta Entrada**. Se conservan los originales. El historial muestra estado y progreso.
5. Selecciona un texto para leerlo completo y pulsar **Copiar**. Los archivos recibidos entregados permiten **Abrir**, **Ubicación** y **Guardar copia**. También puedes arrastrar imágenes y archivos del historial a una carpeta o documento; el dock prepara una copia temporal con el nombre original y conserva su archivo interno.
6. En la vista expandida, el historial tiene las secciones **Textos**, **Imágenes** y **Otros archivos**, con sus cantidades. Imágenes muestra miniaturas y una vista previa al seleccionar una imagen; PDF y documentos permanecen en Otros archivos. La búsqueda se aplica a la sección seleccionada. Se muestran hasta 1000 textos y los 100 registros de archivos más recientes; **Limpiar archivos** considera todas las copias entregadas.
   Puedes arrastrar los separadores entre historial, detalles y acciones, y entre el historial y el cuadro para escribir. El dock recuerda esas proporciones al contraerlo y al volverlo a abrir.
7. El atajo **Ctrl+Alt+C** comparte la nueva selección copiada. El botón **Enviar portapapeles como texto** permite enviar el contenido que ya estaba copiado. Por defecto, los textos e imágenes recibidos se copian al portapapeles de Windows: la última recepción queda lista para pegar. **Copiar textos e imágenes recibidos** permite desactivar esa copia automática. Los resultados de IA se distribuyen según la configuración de la acción.
8. La **X** oculta la ventana cuando hay bandeja y la conexión continúa. Usa el icono junto al reloj para recuperarla. **Pausar conexión** cierra el enlace y deja de escuchar; **Reanudar conexión** permite al teléfono reconectar. **Salir** cierra completamente después de conservar las copias que ya se estaban preparando.

Atajos globales de Windows: **Ctrl+Alt+D** muestra u oculta el dock; **Ctrl+Alt+C** copia la selección de la ventana activa y envía esa nueva copia; **Ctrl+Alt+O** activa o desactiva Ortografía; **Ctrl+Alt+I** activa o desactiva Imagen → Markdown; **Ctrl+Alt+G** activa o desactiva Gramática. Funcionan aunque otra ventana tenga el foco y las letras mayúsculas o minúsculas son equivalentes. **Ctrl+C** conserva su función normal sin enviar el contenido original. Dentro de la ventana, **Ctrl+F** expande y enfoca la búsqueda; **Esc** oculta o minimiza. Puedes cambiar o desactivar los cinco atajos en **Ajustes**. Si la aplicación activa no copia la selección, el portapapeles anterior no se envía. Abrir de nuevo el lanzador recupera la ventana existente.

En **Ajustes** también puedes activar avisos de envíos y recepciones, desvincular el teléfono y elegir **Iniciar con Windows**, desactivado de forma inicial. Los avisos consecutivos se agrupan en una notificación con el número de textos, imágenes y archivos añadidos al dock o recibidos. Si activas el inicio con Windows, se abre el dock visible. Esa opción crea únicamente una entrada de inicio para tu usuario y puede desactivarse desde el mismo lugar. Si mueves el proyecto o cambias el intérprete, vuelve a guardar esa opción para actualizar su ruta.

Para una vinculación nueva, pulsa **Vincular teléfono**, elige la IP de la red compartida y pulsa **Generar QR**. El diálogo permite copiar el bloque completo para vincular sin cámara. El código caduca en cinco minutos y se invalida al cerrar el diálogo o pausar la conexión.

La terminal sigue disponible con **Iniciar-Terminal.cmd** o `./Iniciar-Windows.ps1 -Terminal`. La ventana y la terminal usan los mismos datos y se ejecutan alternativamente. Los apartados siguientes conservan las instrucciones del modo terminal.

## Estado actual

Implementados: vinculación mediante QR o pegado, conexión cifrada, texto y archivos en ambos sentidos, historial persistente, pendientes, confirmaciones y deduplicación, ventana de escritorio, búsqueda, bandeja, atajos Windows y ajustes. La terminal inicia los modos automáticos desactivados; la ventana conserva tus preferencias. Los archivos se incorporan como copias; los originales se conservan.

En Android, usa **Ajustes → Conectar** para mantener el enlace con la pantalla apagada. **Ajustes → Pausar conexión** o la notificación detienen el enlace y los reintentos. La vista compacta ofrece **Enviar portapapeles** y **+ Añadir** para imágenes, archivos o texto. **Compartir → Clipboard AI** incorpora directamente el contenido, incluso varias imágenes, y lo deja pendiente si no hay conexión. Las capturas nuevas se incorporan automáticamente cuando activas su detección y concedes acceso completo a imágenes. Los textos recibidos en directo se copian al portapapeles; los pendientes recuperados al reconectar permanecen en el historial. Android no permite leer automáticamente el portapapeles de otras apps en segundo plano.

El usuario confirmó el funcionamiento de versiones anteriores con su OnePlus LE2115 (OxygenOS 14.0). La versión 0.3.3 pasó compilación, pruebas automatizadas y lint localmente; aún necesita prueba física de la cabecera corregida, el selector múltiple, Compartir, miniaturas y permisos en ese móvil. Voz, escritura mediante teclado y cambio dinámico de cerebro desde la interfaz quedan para próximas etapas. El nuevo cliente y cerebro de Mac requieren validación nativa; Linux también requiere validación propia.

## Probar en este ordenador y el teléfono

1. Conecta ambos a la misma red. El PC puede estar conectado por cable al mismo router. Una red de invitados, una VPN o el aislamiento entre clientes pueden impedir la conexión.
2. Instala en el teléfono `dist/ClipboardAI-0.3.3-debug.apk`. Android puede pedirte autorizar temporalmente la instalación desde la aplicación con la que abras el APK. Es una APK de desarrollo para pruebas personales.
3. Para estas pruebas por comandos, abre **Iniciar-Terminal.cmd**. Mantén esa terminal abierta.
4. Escribe `pair`. Se abrirá una página local con un QR válido durante cinco minutos.
5. En Android, pulsa **Ajustes → Vincular ordenador → Escanear QR** y permite el acceso a la cámara. También puedes pegar el bloque de vinculación que aparece en la terminal.
6. Cuando indique **Vinculado**, pulsa **Ajustes → Conectar**. Ambos equipos deben mostrar la conexión. Permite las notificaciones para ver el estado y poder pausarlo desde ellas; si las rechazas, el servicio puede seguir funcionando y puedes pausarlo dentro de la app.
7. En Windows, escribe `send Hola desde Windows`. El teléfono debe mostrar el texto y permitir copiarlo.
8. En el teléfono pulsa **+ Añadir → Escribir texto**, escribe algo y toca **Enviar texto**. En la terminal usa `list` y después `copy ID`, donde ID son los ocho caracteres que aparecen en la lista. Pega el texto en un editor.

Para vincular sin cámara, **Ajustes → Vincular ordenador** ofrece dos alternativas:

- **Pegar bloque completo:** copia todo el objeto que aparece bajo el QR, desde `{` hasta `}`. No basta con el valor de `code`.
- **Introducir datos:** completa dirección IP, puerto, huella de seguridad y código temporal. La nueva página del QR los muestra en campos separados. El puerto predeterminado es 45821.

Si faltan datos, el formulario permanece abierto y explica qué completar. El código por sí solo no contiene la dirección del ordenador ni permite comprobar su identidad.

Para enviar directamente lo que has copiado en Windows, usa `clip`. Para activar la automatización:

```text
auto on
receive on
```

`auto on` envía cambios de texto mientras el teléfono está conectado. `receive on` copia al portapapeles de Windows los textos nuevos que lleguen en una sesión activa. Los mensajes antiguos recuperados tras una desconexión solo se guardan en el dock. Usa `auto off` y `receive off` para desactivar estos modos, y `quit` para salir.

## Enviar y recibir archivos

1. En Windows escribe `folder`: abre Entrada y muestra las rutas de Entrada y Recibidos. Por defecto están dentro de `%LOCALAPPDATA%\ClipboardAI\Dock`.
2. Copia un PDF o una imagen a Entrada. Tras unos segundos se crea una copia interna estable y se envía al teléfono conectado. La carpeta no es recursiva; subcarpetas y enlaces no se incorporan. Extensiones temporales `.part`, `.tmp` y `.crdownload` se ignoran.
3. En Android aparecerá el archivo con progreso. Solo cuando indique **Entregado** estarán disponibles **Abrir**, **Guardar** y **Compartir**. Guardar permite elegir una copia externa; no requiere acceso general al almacenamiento.
4. Desde Android pulsa **+ Añadir → Archivos**, selecciona uno o varios documentos y espera a que se preparen. También puedes usar **Compartir → Clipboard AI** desde otra app; el contenido se incorpora directamente. Si estás sin conexión queda pendiente.
5. En Windows usa `files` para ver progreso, errores y la ruta completa de los entregados. Los recibidos están organizados en Recibidos/identificador/nombre, por lo que dos archivos con el mismo nombre no se sobrescriben.

Alternativa para envío directo: `file "C:\ruta con espacios\documento.pdf"`.

El archivo no se abre automáticamente ni cambia el portapapeles. El original queda intacto; la copia de envío conserva el contenido que tenía al incorporarlo. Cambiar un archivo de Entrada vuelve a incorporarlo como un envío nuevo; reiniciar el programa sin cambios no lo reenvía.

**Límites:** 100 MiB por archivo, 1 GiB de copias administradas/reservadas por dispositivo y 100 transferencias pendientes. Una transferencia por dirección, con fragmentos de 64 KiB. Los originales de Entrada y las copias exportadas quedan fuera de la cuota administrada y de la limpieza.

Al cortar la red se conserva el progreso confirmado. Al reconectar se reanuda y se verifica tamaño y SHA-256 antes de marcar Entregado. Los mensajes de texto pueden circular durante la transferencia. Si hay un error de integridad, cancela y vuelve a incorporar el original. Los errores de archivos aparecen en su tarjeta o en `files` y no deben detener el intercambio de texto.

**Cancelación y limpieza:** `cancel ID` cancela un archivo pendiente y comunica la cancelación al conectar; no borra una copia que ya terminó de llegar al otro equipo. `deletefile ID` borra la copia local entregada o un registro cancelado. `clearfiles` muestra cuántas copias y bytes liberaría; `clearfiles confirm` realiza esa limpieza. Android ofrece Cancelar/Borrar del dock y **Limpiar archivos entregados**, con confirmación de cantidad y espacio. El borrado local no se propaga, y se conservan recibos para impedir que un reintento recree un archivo borrado. No hay caducidad automática.

Si un dispositivo aún usa 0.1.x, el texto básico continúa funcionando; la distribución entre varios dispositivos y los ajustes compartidos requieren Android 0.3.0. Actualizar una instalación ya vinculada no exige volver a vincularla.

## Probar con el teléfono bloqueado

1. Instala 0.3.3 encima de la versión anterior y pulsa **Ajustes → Conectar**. No vuelvas a vincular si ya funciona.
2. Bloquea el teléfono. En Windows escribe `send Prueba con el móvil bloqueado`.
3. Sin desbloquear el móvil, usa `list` en Windows: el texto debe pasar de pendiente a entregado. Así compruebas la recepción antes de abrir la app.
4. Desbloquea, abre la app y verifica el texto en el dock. No deberías necesitar pulsar Conectar otra vez.
5. Repite después de 10–15 minutos en reposo y prueba **Pausar** desde la notificación. Debe desconectarse y no reconectar hasta que pulses Conectar.

Para la recepción continua durante reposo prolongado, abre **Ajustes → Conexión con pantalla apagada → Ajustes de batería** y permite a Clipboard AI funcionar sin optimización. En OnePlus comprueba también la opción de permitir actividad en segundo plano; los nombres pueden variar. Android puede suspender la red en Doze incluso con un servicio activo. La exclusión de optimización se elige en los ajustes del sistema, no se cambia automáticamente. [Restricciones de Doze](https://developer.android.com/training/monitoring-device-state/doze-standby).

La sesión mantiene la CPU disponible para responder a la conexión mientras está activa, sin encender la pantalla; esto aumenta el consumo de batería. **Pausar** libera ese recurso. Si se pierde la Wi-Fi, reintenta con espera progresiva y conserva los pendientes. No se inicia automáticamente al reiniciar el teléfono ni después de Forzar detención; abre la app y pulsa Conectar. El sistema puede recuperar un servicio interrumpido, pero no se garantiza continuidad si el fabricante lo detiene.

## Si no conecta

- Comprueba la IP que aparece en la página del QR. Debe ser la del adaptador conectado a la red del teléfono. No uses `127.0.0.1`, que representa el propio dispositivo.
- Para elegirla explícitamente en el modo terminal, ejecuta `./Iniciar-Windows.ps1 -Terminal -Address 192.168.1.10`, sustituyendo la IP. Después genera un nuevo QR con `pair`. La ventana permite elegir la IP directamente en Vincular teléfono.
- Si Windows solicita acceso de red para Python, permite la conexión en tu red privada. Si sigue bloqueado, revisa la regla del firewall para ese programa y el puerto TCP 45821. No hace falta abrir puertos del router.
- Caducado el código, escribe `pair` de nuevo. Generar un nuevo código invalida el anterior.
- Si el teléfono ya está vinculado pero perdió sus datos, usa `peers` y `revoke UUID` en Windows antes de volver a vincularlo.
- Si cambia la IP del cerebro, usa **Dirección del cerebro** en Android para guardar la nueva IP o el nombre privado. La huella TLS vinculada se sigue verificando y no hace falta repetir la vinculación.
- Bloquear o salir de la pantalla de Android no pausa una sesión iniciada con **Conectar**. Si el sistema la detiene o fuerzas el cierre, vuelve a abrir la app y pulsa **Conectar**. Los textos enviados explícitamente sin conexión permanecen pendientes.

## Acciones de terminal

| Acción | Resultado |
| --- | --- |
| `pair` | Genera QR y datos privados de vinculación. |
| `send TEXTO` | Guarda y envía texto escrito. |
| `clip` | Guarda y envía el texto del portapapeles. |
| `file "RUTA"` | Prepara una copia del archivo y la envía. |
| `files` | Archivos, dirección, estado, porcentaje, errores y rutas. |
| `folder` | Abre Entrada y muestra Entrada/Recibidos. |
| `cancel ID` | Cancela una transferencia pendiente. |
| `deletefile ID` | Borra una copia de archivo local. |
| `clearfiles` / `clearfiles confirm` | Previsualiza / realiza limpieza de archivos entregados. |
| `list` | Lista los últimos 20 elementos sin imprimir su contenido. |
| `show ID` | Muestra el texto completo. |
| `copy ID` | Copia el texto al portapapeles. |
| `delete ID` | Borra localmente un elemento entregado. |
| `auto on/off` | Activa o pausa el envío automático. |
| `receive on/off` | Activa o pausa el copiado de nuevos textos remotos. |
| `peers` / `revoke UUID` | Consulta o revoca el teléfono vinculado. |
| `status` / `help` / `quit` | Estado, ayuda y salida. |

Conserva hasta 500 elementos entregados y 500 pendientes. La pantalla Android muestra los últimos 50. El texto admite hasta 256 KiB UTF-8; los espacios y saltos de línea se conservan. El envío escrito en la terminal ocupa una línea; usa el portapapeles para enviar párrafos con varias líneas.

## Datos locales

- Windows: `%LOCALAPPDATA%\ClipboardAI` (historial SQLite, identidad TLS y QR temporal).
- Android: almacenamiento privado, excluido de copias de seguridad.
- Los registros habituales muestran estados e identificadores. `show` muestra el contenido por petición del usuario.
- Los elementos borrados no se eliminan de otros equipos. Se guardan recibos con hashes, sin texto, para que los reintentos no los hagan reaparecer.
- El cerebro admite varios teléfonos o tabletas vinculados. A uno recién vinculado le entrega los pendientes y una selección reciente del historial. Cada destinatario confirma sus propios textos y archivos.

## Instalación de desarrollo

Se requiere Python 3.11 o posterior. En este ordenador el lanzador también detecta el Python incluido con Codex y las dependencias locales de `.deps`.

En un entorno Python propio:

```text
python -m pip install -e "./desktop[gui]"
clipboard-ai-dock
```

Alternativas desde el repositorio: `python scripts/run_gui.py` para la ventana y `python scripts/run_desktop.py` para la terminal. El modo de terminal puede instalarse sin los componentes gráficos con `python -m pip install -e ./desktop`.

En Linux, crea un entorno Python 3.11 o posterior (`python3 -m venv .venv-linux`), instala `"./desktop[gui]"` con el Python de ese entorno y ejecuta `sh Iniciar-Linux.sh`. El lanzador busca primero `.venv-linux` y después `.venv`; ignora las dependencias binarias Windows de `.deps` aunque compartas el proyecto por Seafile. La ventana usa el portapapeles de Qt. En Wayland la disponibilidad de su contenido puede depender del foco y del compositor; debe verificarse en tu escritorio. La terminal conserva el adaptador `wl-clipboard`/`xclip`.

Los atajos de esta entrega son globales en Windows. En Linux funcionan dentro de la ventana; puedes asignar `python /ruta/al/proyecto/scripts/run_gui.py --show` y `--send-clipboard` como acciones globales desde los ajustes del escritorio, usando el intérprete del entorno correspondiente. La bandeja depende del escritorio y sus extensiones. Si no existe, **Esc** minimiza y la X ofrece salir. Linux y estos accesos quedan pendientes de prueba física.

## Compilar Android

Proyecto Kotlin nativo, API mínima 26; compilación API 35 extensión 15. Toolchain fijado: Java 17, Gradle 8.11.1, Android Gradle Plugin 8.9.2 y Kotlin 2.1.20. Se puede abrir la carpeta `android` en Android Studio.

Para preparar un entorno portable en Windows, con acceso a Internet:

```text
python scripts/prepare_android.py
```

Descarga herramientas de distribuidores oficiales y verifica sus checksums; todo queda en `.tools`, sin modificar el registro ni el PATH del sistema. El script de preparación está pensado para Windows x64.

Después, en PowerShell:

```powershell
./scripts/build_android.ps1 -Check
```

Genera la APK de prueba en `dist`. El script crea una clave de firma de desarrollo local. Conserva esa clave para poder actualizar la APK sin reinstalarla y perder los datos de la aplicación. Para una distribución pública habría que preparar una firma de publicación propia.

## Verificación

```powershell
./scripts/test_desktop.ps1
python scripts/verify_gui.py
./scripts/build_android.ps1 -Check
```

Las pruebas de escritorio requieren `pytest==8.4.2`; las de ventana requieren también el extra `gui`. `scripts/verify_gui.py` abre brevemente una ventana de prueba en Windows y verifica atajos, conflictos, segunda apertura y salida completa, con datos temporales y un portapapeles simulado. No activa el inicio con Windows ni cambia tu vinculación.

La prueba adicional `python scripts/verify_interop.py` inicia un servidor TLS temporal y ejecuta el código de red Kotlin contra él: comprueba vinculación, verificación del certificado, texto Unicode y confirmaciones de duplicados. No requiere teléfono ni modifica el portapapeles real.

## Documentación

- [Plan y etapas](docs/PLAN.md).
- [Contrato del protocolo implementado](docs/protocol.md).
- [Estado de verificación](docs/VERIFICATION.md).
