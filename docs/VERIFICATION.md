# Verificación del prototipo 0.1

Fecha: 2026-10-15.

## Alcance de las comprobaciones

- Pruebas Python de persistencia, límites, vinculación, revocación y validación de mensajes.
- Conexiones reales WebSocket/TLS sobre loopback: saludo, intercambio bidireccional, confirmaciones, mensajes repetidos y rechazo de certificados no confiables.
- Pruebas Kotlin del mismo ejemplo Unicode usado por Python y de entradas inválidas.
- Compilación de APK Android y análisis estático mediante Android Lint.
- Prueba adicional de interoperabilidad con el código real Kotlin de TLS/protocolo/transporte conectado al servidor Python.

Resultados finales de esta ejecución:

| Comprobación | Resultado |
| --- | --- |
| Python | 25 pruebas aprobadas. |
| Kotlin: contrato y validación | 2 pruebas aprobadas; las 2 pruebas de integración se omiten cuando no está iniciado su servidor auxiliar. |
| Kotlin contra Python real | 2 pruebas aprobadas: intercambio con TLS fijado y rechazo de huella incorrecta. |
| Android Lint | Sin incidencias. |
| APK debug | Compilada; firma APK v2 verificada con apksigner. |
| Lanzador de terminal | Inicio, envío, listado, estado y cierre comprobados con datos temporales. |

APK: `dist/ClipboardAI-0.1-debug.apk`.

SHA-256: `dabe600acebe1275e9ce19601a115b189bd219261856c4d72acff723fe9b9e40`.

## Actualización Android 0.1.1

El usuario informó de un cierre al abrir el lector QR en un OnePlus con OxygenOS 14.0. El registro del teléfono no estaba disponible. Una prueba Robolectric con API 34 reprodujo un fallo en la misma ruta de apertura: `NoClassDefFoundError: androidx/core/content/ContextCompat`, en `CaptureManager.openCameraWithPermission`. La inspección de las clases DEX confirma que la APK 0.1.0 no incluía esa clase y que la APK 0.1.1 sí la incluye.

Se añadió `androidx.core:core:1.15.0` como dependencia explícita. La prueba de apertura del lector pasa con esta dependencia. Esto verifica el fallo de clases ausentes, no el comportamiento del controlador de cámara físico del OnePlus.

También se eliminó el uso de IntentIntegrator en favor del lanzamiento directo de la actividad interna del lector, se eliminó la orientación horizontal obligatoria, y se añadieron formularios de bloque completo y campos separados. Un código aislado muestra una explicación sin cerrar el formulario. La página de vinculación de Windows presenta los cuatro campos y el bloque completo.

La actualización mantiene el identificador de aplicación y la clave de firma de desarrollo para permitir instalar encima conservando datos. Se verificó que ambas APK tienen el mismo certificado de firma.

Resultados de la actualización:

- 8 pruebas Android aprobadas: contrato (2), datos de vinculación (3), apertura del lector y formularios en un entorno Android 14 (3).
- Análisis estático: 0 errores, 2 advertencias; no se desactivó el control de errores de compilación.
- Página de vinculación Windows generada y comprobada con datos temporales, sin abrir el navegador del usuario ni modificar su portapapeles.
- APK 0.1.1 compilada, identificador `org.clipboardai.app`, versión interna 2 y firma verificada.
- Las 2 pruebas Kotlin/Python también pasan con la actualización: vinculación/intercambio de texto y rechazo de una huella TLS incorrecta.
- Prueba física de cámara en el OnePlus pendiente de repetir con esta actualización.

APK actualizada: `dist/ClipboardAI-0.1.1-debug.apk`.

SHA-256: `0700b1f685b1601a5fcc8c11104732b30940e7183627ee8af8c1973527e725d0`.

Las pruebas usan datos de prueba locales en `.test-data`; no escriben en el portapapeles del usuario ni vinculan un teléfono real.

## Confirmación física del usuario · 2026-10-16

El usuario confirmó que la vinculación y las pruebas de intercambio de texto en ambos sentidos Windows–OnePlus LE2115 funcionaron. Informó de desconexión al bloquear el teléfono; la versión anterior llamaba explícitamente a disconnect en onStop.

## Actualización Android 0.1.2 · 2026-10-16

Se trasladó la propiedad de la conexión y del almacenamiento a DockService. Conectar inicia un servicio en primer plano `connectedDevice`; cerrar la Activity solo retira su enlace y observador. Pausar detiene la sesión, los reintentos, la notificación y el bloqueo parcial de CPU. Se añadió ayuda con acceso a los ajustes de batería y solicitud de notificaciones en Android 13+. Las credenciales y el protocolo no cambiaron.

Verificaciones realizadas:

- Compilación APK y 11 pruebas Android aprobadas (contrato 2, vinculación 3, cámara/formularios 3, ciclo del servicio 3). Las tres pruebas que requieren servidor externo se omiten en esta ejecución estándar.
- Las pruebas del servicio comprueban salida y recreación de la Activity, ausencia de recursos retenidos tras Pausar, falta de credenciales, recuperación de una sesión habilitada y respeto de una pausa tras reinicio del servicio.
- `scripts/verify_interop.py --background`: prueba adicional aprobada contra el servidor Python TLS real. Ejecuta DockService/DockConnection y SQLite en Robolectric API 34; vincula, conecta, destruye la Activity, recibe y confirma un texto nuevo, reabre y pausa. El servidor comprueba la cola vacía, los contenidos exactos y el cierre de la conexión.
- Análisis estático: 0 errores y 4 advertencias (versión de dependencia, orientación heredada del lector y dos textos no extraídos a recursos de traducción).
- APK verificada con apksigner; mismo certificado que 0.1.1. Identificador `org.clipboardai.app`, versionCode 3, versionName 0.1.2.

APK: `dist/ClipboardAI-0.1.2-debug.apk`.

SHA-256: `b3b59a8dac9093a8f1964e88cea3215e8e2e5cd7e0f3b33d27346604256e1ced`.

Estas pruebas simulan el ciclo de vida de Android; no simulan el controlador de energía del OnePlus ni prueban Doze real. El primer intento de compilación aislado no pudo comunicarse con el proceso local de Gradle. La compilación y las pruebas posteriores se ejecutaron con acceso local permitido. No se modificaron el portapapeles ni los datos de la instalación real.

## Pendiente de prueba física

- Instalar 0.1.2 sobre 0.1.1 conservando vinculación e historial.
- Recepción y confirmación mientras el OnePlus está bloqueado; repetir tras 10–15 minutos y durante reposo prolongado con los ajustes de batería apropiados.
- Medir consumo de batería y comprobar la pausa desde la notificación.
- Cambiar temporalmente de red y comprobar recuperación de pendientes.
- Menú Compartir de las aplicaciones Android utilizadas por el usuario.
- Adaptador Linux en la distribución y escritorio elegidos.

No se considera comprobada todavía la continuidad durante reposo prolongado en el teléfono físico. Android 0.1.2 ya no pausa una sesión activa al dejar de estar visible; Doze y las políticas del fabricante siguen requiriendo verificación real.

## Versión 0.2.0 · archivos · 2026-10-16

Se incorporaron copias de envío y recepción, carpeta Entrada automática en Windows, mensajes files-v1 negociados, progreso, recuperación desde posiciones durables, comprobación SHA-256, cancelación y limpieza manual. Android incluye selector, recepción desde Compartir, apertura mediante FileProvider, exportación y compartir con permisos temporales. Se mantienen la vinculación, el historial de texto y el servicio de conexión de 0.1.2.

Resultados:

- **42 pruebas de escritorio aprobadas**. Además de los controles anteriores de texto/TLS: binarios y Unicode, archivos vacíos, copia inmutable, reanudación tras reabrir base de datos, descarte de bytes no confirmados, duplicados, nombres iguales, nombres inseguros, límites, cuota, hash incorrecto, cancelación anterior a la oferta, recibos de borrado y limpieza. La carpeta automática se prueba tras cambios y reinicios. Una prueba TLS comprueba compatibilidad de texto con un cliente sin capacidad de archivos y que rechazar un archivo no interrumpe el texto.
- **16 pruebas Android aprobadas** en la ejecución estándar; cuatro pruebas opcionales requieren servidor externo y se omiten en esa ejecución. Las cinco pruebas nuevas de FileDock cubren recepción/reapertura, copia de envío, comprobación, borrado, nombres, límites y cancelación. Permanecen aprobados los controles de cámara, formularios y servicio.
- **Una prueba adicional de interoperabilidad de archivos aprobada**, ejecutada mediante `scripts/verify_interop.py --files`: DockService/DockConnection Android real en Robolectric API 34 frente al servidor Python TLS local. Se transmiten 460800 bytes Windows→Android y 380123 bytes Android→Windows, se cierra la Activity, se corta expresamente la conexión después de un fragmento recibido y se comprueba una nueva oferta con progreso persistido, integridad exacta, confirmaciones y cola final vacía. También verifica la exportación a un flujo de salida y el intercambio de texto después del corte.
- **Compilación y análisis Android aprobados:** 0 errores y 9 advertencias. Son avisos de versión de dependencia, orientación del lector, cálculo conservador de espacio libre y textos de interfaz no extraídos a recursos de traducción.
- **Lanzador Windows comprobado** con datos temporales: archivo por ruta con espacios, listado, previsualización de limpieza, estado y salida. No se modificó el portapapeles ni la instalación/datos de la sesión real que tenía abierta el usuario.
- **Firma APK verificada:** mismo certificado de desarrollo de las versiones anteriores; paquete `org.clipboardai.app`, versionCode 4, versionName 0.2.0.

El corte de prueba reprodujo un error de Windows Proactor durante el cierre TLS (`WinError 10054`) que dejaba esperando al comprobador. El lanzador de escritorio y el comprobador utilizan ahora un SelectorEventLoop de alcance local mediante asyncio.Runner en Windows. La prueba completa terminó correctamente después del cambio. Solo se detuvo el proceso del comprobador bloqueado; se preservó el proceso de escritorio abierto por el usuario.

Robolectric ejecutado en Windows no puede verificar directamente las rutas de FileProvider: AndroidX compara con separadores `/` y el sistema anfitrión devuelve rutas Windows. Se verificaron la declaración privada del proveedor, sus permisos temporales y su configuración de rutas. La lectura por URI y exportación de la prueba de integración usan flujos de proveedor simulados; los selectores, Abrir/Compartir y Guardar requieren la prueba física. No se modificó el proveedor de producción para eludir esa limitación de pruebas.

APK: `dist/ClipboardAI-0.2.0-debug.apk`.

SHA-256: `fa00d7c0d50f06f4f3bba45a0fbbc835479c1e0a775f524ea752633926ec7316`.

Pendiente en el OnePlus: actualizar sobre la APK anterior, comprobar PDF e imagen en ambos sentidos, Abrir/Guardar/Compartir, cancelación, corte de Wi-Fi y reposo prolongado. Linux sigue pendiente de prueba física. La cuota limita contenido administrado y reservado; los originales en Entrada y las exportaciones no se incluyen ni se limpian automáticamente.

## Versión de escritorio 0.3.0 · dock visual · 2026-10-16

El usuario confirmó que las pruebas de funcionamiento de 0.2.0 funcionaron. Se mantiene la APK Android 0.2.0 y el protocolo TLS/texto/files-v1. Esta entrega añade la ventana Python/PySide6 Essentials 6.12.0, búsqueda y filtros, arrastrar archivos, acciones gráficas, bandeja, pausa/reanudación, ajustes y atajos Windows.

Resultados de esta entrega:

- **53 pruebas de escritorio aprobadas**: las 42 anteriores y 11 comprobaciones gráficas/de integración. Incluyen historial y búsqueda Unicode, progreso y acciones, ocultar sin detener el motor, alternativa sin bandeja, QR y caducidad, arrastrar con operación de copia, segunda apertura entre procesos, bloqueo de instancia, exportación y validación de atajos. El puente Qt se prueba entre hilos con portapapeles simulado y supresión del envío de retorno.
- La prueba del motor gráfico usa un servidor TLS y un cliente reales, una vinculación preexistente y dos bases de archivos. Comprueba una transferencia completa con integridad exacta, texto en ambos sentidos, copia automática mediante el adaptador simulado, pausa/reanudación y conservación de pendientes y credenciales después del cierre.
- Dos comprobaciones adicionales detienen el motor durante la preparación de una copia manual y de otra detectada en Entrada: la copia aceptada se incorpora completa y queda pendiente antes de cerrar SQLite. También se comprueba Salir inmediatamente después de iniciar.
- **Comprobación nativa Windows aprobada**, mediante `scripts/verify_gui.py`: registro real de un atajo, recepción de WM_HOTKEY en el filtro nativo Qt, rechazo de un conflicto, activación de una ventana existente desde otro proceso y salida completa sin dejar el hilo del motor activo. La bandeja estaba disponible. No se generan pulsaciones globales ni se escribe en el portapapeles real.
- La prueba nativa encontró un cierre rechazado por closeEvent aun después de terminar el motor. Se corrigió para aceptar el cierre cuando ya no quedan operaciones y se repitió correctamente.
- Se generó e inspeccionó una captura del widget renderizado con Qt Windows y datos ficticios. El renderizador offscreen de pruebas no tenía las fuentes de Windows; la revisión visual final utilizó el componente nativo, que mostró texto, acentos y controles correctamente.
- Se comprobó el arranque del modo terminal mediante Iniciar-Windows.ps1 con carpeta temporal y puerto dinámico. La aplicación de terminal que tenía abierta el usuario se conservó. Se detuvieron únicamente comprobadores identificados por su PID y línea de ejecución durante el diagnóstico.

Las pruebas usan datos bajo .test-data y un portapapeles simulado; no cambian la vinculación, el historial ni el registro de inicio de la instalación real. El inicio con Windows está implementado como opción explícita; la creación y eliminación de su entrada en una sesión real quedan para la prueba voluntaria del usuario. El registro de hotkeys y su entrega se comprueban de forma nativa; queda comprobar su comodidad y posibles conflictos con los programas habituales.

Pendiente: uso diario del dock con el OnePlus físico, cierre a bandeja durante transferencias reales, selección/apertura mediante las aplicaciones habituales y comprobación del inicio opcional con Windows. Linux requiere una instalación real y conocer escritorio/Wayland/X11; los atajos de Linux son de ventana y se ofrece integración por comandos con los ajustes del escritorio. No se considera Linux verificado ni se promete lectura global del portapapeles en Wayland.

## Versión de escritorio 0.3.1 · vista compacta · 2026-10-16

A petición del usuario, el dock siempre abre en compacto: cabecera con vinculación/ajustes/salir, estado y nombres de dispositivos, zona de arrastre y envío del portapapeles como texto. Expandir muestra las demás acciones y el historial; Contraer vuelve al dock pequeño. Los tamaños y posiciones se guardan por separado. Ctrl+F expande antes de enfocar la búsqueda. Los mensajes breves aparecen temporalmente en compacto y los errores siguen siendo visibles.

El historial expandido se divide en Textos, Imágenes y Otros archivos, con cantidades por sección y búsqueda dentro de la seleccionada. Imágenes se reconoce por su tipo MIME; PDF y documentos se conservan en Otros archivos. El estado utiliza los identificadores de sesiones activas para mostrar cada dispositivo con su estado; el protocolo continúa admitiendo una pareja PC–teléfono.

- **13 pruebas de interfaz/motor aprobadas**, incluidas dos nuevas comprobaciones de modo compacto por defecto, expansión/contracción, reapertura tras una sesión expandida, envío desde el dock pequeño, búsqueda y separación entre texto, PNG y PDF.
- **Prueba nativa Windows aprobada**: captura e inspección de ambas vistas, restauración del tamaño al contraer, hotkey real, conflicto, segunda apertura mediante el lanzador completo y salida ordenada. Se utilizaron datos temporales y portapapeles simulado.
- Se conservan las comprobaciones de TLS, integridad y conservación de pendientes de la entrega anterior; no se modifica Android ni el contrato de red.

## Versión de escritorio 0.4.0 · IA local automática · 2026-10-20

- **76 pruebas aprobadas en 20,30 s**, mediante scripts/test_desktop.ps1. Se incluyen los casos anteriores de transporte/archivos y nuevos casos de delimitadores, preservación Markdown/código/LaTeX, flujo SSE sin razonamiento, autenticación fallida, fin de stream ausente, límite de tokens, carga/calientamiento compartidos tras cancelación, modelo ajeno cargado, historial local y publicación explícita, captura de imagen/texto, protección de revisión y cancelación del portapapeles, modos persistentes/exclusivos y cola que mantiene la entrada pendiente más reciente sin bloquear comandos de red.
- **API real de Bionic**: 127.0.0.1:1235, `qwen/qwen3.5-9b`, Q4_K_M. Estaba descargado; scripts/verify_ai.py --live lo cargó, calentó con imagen sintética y comprobó ortografía, gramática y OCR. Resultados correctos, sin razonamiento generado. En entradas pequeñas preparadas se midieron aproximadamente 1,31 s, 1,34 s y 1,80 s respectivamente. Evidencia: `.test-data/ai-live-a2ef751c36784b34b943b3566bbfce98/result.json`.
- Configuración efectiva observada después de cargar: contexto 2048, batch 512, microbatch 128, paralelo 1, Flash Attention y KV en GPU. NVIDIA RTX 3070 Ti Laptop 8 GiB: 7267 MiB de memoria dedicada usada y 751 MiB libres en esa observación posterior. No es una medición del pico durante todas las entradas ni una comprobación de memoria compartida.
- **Recorrido automático completo con Qwen real**, scripts/verify_ai_dock.py --live: cambio de portapapeles Qt simulado a imagen → petición OCR → texto copiado; nuevo texto → ortografía → texto corregido. Exactamente dos entradas externas y dos resultados, sin bucle por escrituras propias. Evidencia: `.test-data/ai-dock-fba2c86302fb49ef89ba128798492327/result.json`. No se leyó ni escribió el portapapeles real.
- **Ventana nativa Windows**: panel lateral con desplazamiento, configuración/cancelación accesibles en compacto, detalles que sustituyen el área de arrastre, hotkey real y conflicto, activación de instancia existente y cierre ordenado. Capturas revisadas en `.test-data/gui-native-3bda775ce18748e6b4077ab4c0960003/`.

Se activó la API local a petición del usuario y se dejó Qwen cargado para sus pruebas. No se cambiaron vinculaciones, datos ni ajustes de inicio de Windows. La herramienta lms antigua de Bionic no descubría su instancia y, con selección explícita, rechazaba la autenticación: la integración evita copiar claves privadas o modificar esa herramienta y usa REST; el arranque del servicio usa la ruta de instalación publicada y la opción de inicio automático ya guardada.

Pendientes físicos: arranque con Bionic completamente cerrado (no se cerró la aplicación abierta del usuario), memoria compartida/picos con capturas grandes, fidelidad OCR con documentos reales y sincronización de resultados con el OnePlus en uso cotidiano. Linux no está verificado. La automatización de IA corresponde al escritorio visual; Android mantiene las restricciones de su portapapeles.

## Corrección 0.4.1 · fórmulas y notificaciones del portapapeles · 2026-10-20

El usuario confirmó el funcionamiento general, pero observó peticiones infinitas con Ortografía. La protección anterior se limitaba al intervalo síncrono de escritura; se reforzó para notificaciones posteriores mediante marca MIME propia y comparación del texto normalizado, con revisiones estables ante avisos repetidos y variantes LF/CRLF. No se ignora para siempre un texto: un cambio externo distinto vuelve a habilitar su captura posterior. La prueba reproduce notificaciones a 20/170 ms, eliminación de la marca y cambio de formato a 250 ms.

**86 pruebas aprobadas en 21,09 s**: se añadieron nueve casos de fórmulas (`$$`, `$`, `\\[...\\]`, `\\(...\\)`), preservación de Markdown, código y moneda, idempotencia y el caso de notificaciones tardías. El formato se aplica únicamente a OCR y fuerza delimitadores matemáticos en líneas independientes, mediante instrucción por petición y normalización local.

También pasó el comprobador con Qwen real y portapapeles simulado que emite avisos tardíos, repetidos y variantes CRLF: dos entradas externas, dos resultados y ningún bucle. Evidencia: `.test-data/ai-dock-4ebbb04733154a5296d692f1dfc59e92/result.json`. No se cambió el portapapeles real. Queda confirmar la desaparición del síntoma en la sesión física del usuario después de reiniciar Clipboard AI.

## Corrección 0.4.2 · capturas, Ctrl+C y thinking · 2026-10-20

El usuario notificó que Recortes de Windows mediante Fn+F6 no producía Markdown y Ctrl+C no activaba Gramática aunque sí lo hacía Copiar del menú. Se corrigieron tres límites: el filtro rechazaba imágenes acompañadas por URL local; el puente dependía solo de señales Qt y de texto cacheado al notificar; las notificaciones adicionales de una imagen adelantaban la revisión y podían invalidar un OCR todavía válido.

Ahora el adaptador real Windows consulta GetClipboardSequenceNumber cada 200 ms, con reintentos breves de datos tardíos. La lectura final usa datos actuales, prioriza píxeles sobre URL y acepta PNG nativo. Se deduplican capturas por hash PNG; al copiar una respuesta con revisión posterior, solo se permite si los píxeles actuales siguen siendo los mismos. Una imagen diferente se conserva. Las listas de archivos sin imagen siguen excluidas. No se interceptan ni reservan Ctrl+C o Fn+F6.

**90 pruebas aprobadas en 23,28 s**, incluidas detección por contador sin señal Qt, texto renderizado tarde, guardia nativa previa a escribir, imagen+URL, PNG sin hasImage, notificaciones equivalentes y selección de reasoning/budget por acción. El resto de casos de TLS/archivos, bucles, formatos y cancelación sigue pasando.

**Qwen real**: Gramática pide reasoning=on y presupuesto positivo (máximo 512 tokens o mitad del límite de salida), anulando solo por petición el presupuesto cero guardado en Bionic. La prueba produjo 440 tokens de razonamiento y respuesta correcta en 23,86 s; el pensamiento no se copió. Ortografía y OCR produjeron cero tokens de razonamiento. Evidencia: `.test-data/ai-live-6426099dd28f4df18a03de7cfd2c3ed5/result.json`.

El flujo automático con Qwen real y portapapeles simulado pasó también usando únicamente cambios de contador para imagen+URL y Ctrl+C, con avisos tardíos y sin bucle: `.test-data/ai-dock-f0b4f17f6d334a329ac5e2c9a1843095/result.json`. No se leyó/escribió el portapapeles real ni se simularon físicamente las teclas del usuario. Queda comprobar Fn+F6 y Ctrl+C en su aplicación concreta después de reiniciar la versión anterior.

## Corrección 0.4.3 · atajos, historial y copia verificada · 2026-10-21

La configuración real tenía Ctrl+C registrado como atajo global de envío. Al iniciar se cambia ese valor conflictivo a Ctrl+Alt+S; el panel Ajustes rechaza configurarlo de nuevo. El contador nativo permite procesar copias sucesivas del mismo texto y un cambio de modo rearma la captura. Los avisos equivalentes del gestor del portapapeles se distinguen de una nueva copia para que no invaliden una corrección en curso.

Los textos pendientes propios ahora pueden cancelarse y eliminarse. La vista ampliada muestra **Limpiar textos**, que requiere confirmación y borra el historial local, incluidos pendientes; conserva los recibos de deduplicación de envíos entrantes. Una escritura de IA se declara copiada solo después de leer el texto esperado en el portapapeles. Cuando falla, el resultado permanece en el dock y se informa del error.

Una prueba OCR sintética inicial resultó inválida: Qt dibujó cuadrados por falta de fuentes en el entorno de prueba. Tras cargar Arial y verificar visualmente la imagen, Qwen extrajo tres líneas y una fórmula en 2,23 s. Se añadió un corte temprano si la respuesta repite `[ilegible]`, para evitar esperar hasta el límite de tokens y copiar ese resultado. No se modificaron los parámetros del modelo.

**96 pruebas de escritorio aprobadas en 23,88 s.** La primera prueba integral con Qwen detectó una notificación tardía que invalidaba la corrección ortográfica; después de corregirla, OCR y ortografía automática copiaron sus resultados sin bucle: `.test-data/ai-dock-6924af0dfbeb44ecbe947aeaaa63269e/result.json`. La prueba de ventana nativa y atajos también pasó: `.test-data/gui-native-3da13692413544d6acffc40fae39a4d6/`. No se leyó ni modificó el portapapeles físico del usuario. La comprobación con Fn+F6 y Ctrl+C en sus aplicaciones queda pendiente al reiniciar el dock.

## Escritorio 0.4.4 · indicador de IA junto al cursor · 2026-10-21

Se añadió un aviso flotante sin foco ni interacción que sigue el cursor durante el procesamiento automático. Solo muestra **✓ Copiado** cuando la escritura al portapapeles se confirmó; si cambió el portapapeles indica **No copiado**, y un fallo indica **Error**. La cancelación y el cierre del dock lo ocultan. El aviso de finalización desaparece a los dos segundos.

**97 pruebas de escritorio aprobadas en 23,12 s.** La prueba nativa de Windows pasó con capturas de ambos estados visuales: `.test-data/gui-native-0598542b72f04ffda7930584a7008f3e/cursor-working.png` y `cursor-copied.png` en la misma carpeta. Se usaron datos temporales y un portapapeles simulado; falta probar el indicador con el modelo real y el cursor del usuario en sus aplicaciones.

## Escritorio 0.4.5 · OCR por partes cuando se agota el contexto · 2026-10-21

La API de Bionic devolvió una respuesta incompleta para una captura de 1308 × 1287: 1908 tokens de entrada más 140 de salida agotaron exactamente los 2048 de contexto. Faltaba el marcador final y no se creó ningún resultado de imagen en el historial real. El programa ahora identifica la respuesta incompleta, divide la captura cerca de una fila con poco detalle y reintenta cada parte. Solo guarda y copia la transcripción si todas las partes son válidas; mantiene el contexto configurado y limita la subdivisión a tres niveles.

**98 pruebas de escritorio aprobadas en 23,10 s.** Con Bionic real y portapapeles simulado, la captura extensa produjo Markdown completo en dos partes y se copió: `.test-data/ai-dock-b567b7e5913b474891d0fe5374452e7b/result.json`. Una captura de prueba con cinco ecuaciones produjo bloques `$$` en líneas propias y también se copió sin bucle: `.test-data/ai-dock-08f7ce1b58c24dc6b886f2804560c3a4/result.json`. Las pruebas no modificaron el portapapeles físico; queda comprobar la captura concreta del usuario tras reiniciar el dock.

## Escritorio 0.4.6 · aceptación de OCR completo sin marcadores · 2026-10-21

La captura concreta de una ecuación de 325 × 75 píxeles produjo una respuesta LaTeX completa en Bionic con 288 tokens de entrada y 82 de salida, muy por debajo del contexto de 2048, pero sin los marcadores externos exigidos por el dock. La causa de ese fallo era la validación del programa, no el tamaño de la ecuación ni una conversación acumulada. Se acepta Markdown sin marcadores solo en OCR, cuando la respuesta terminó y hay margen de contexto; se preserva el rechazo de marcadores parciales, salida truncada y texto explicativo. Ortografía y gramática siguen exigiendo marcadores. El límite configurable de lado de imagen reduce solo la copia enviada al modelo; la imagen original se conserva. Las peticiones mantienen `store=false` y no reutilizan identificadores de respuesta.

**101 pruebas de escritorio aprobadas en 37,38 s.** Una prueba adicional comprueba que 1600 × 800 llega a la API como 1280 × 640 sin modificar los bytes originales. Con Bionic real y portapapeles simulado, la captura exacta de la ecuación se convirtió a un bloque LaTeX y se escribió correctamente; ortografía también pasó sin bucle: `.test-data/ai-dock-f24e9e42845a4ff197d083cc2abb0a88/result.json`. No se modificó el portapapeles físico; la prueba manual del usuario requiere reiniciar el dock.

## Escritorio 0.4.7 · capturas locales y apertura entre monitores · 2026-10-22

La lectura de imágenes estaba ligada al conmutador de OCR: desactivarlo impedía incluso registrar una captura. Ahora el puente de portapapeles lee imágenes siempre y guarda cada captura en `Dock/Capturas` como entrada local de la pestaña **Imágenes**, sin ofrecerla automáticamente al teléfono. La generación de Markdown continúa dependiendo del conmutador. Las capturas sobreviven a un reinicio y se pueden abrir, guardar fuera del dock o eliminar desde Detalles. La operación **Limpiar archivos** incluye esas capturas y avisa antes de borrarlas.

La ventana restauraba geometrías antiguas de otros monitores y se limitaba a `showNormal()/raise_()/activateWindow()` al abrir. Ahora se comprueba el monitor del cursor al abrir y al cambiar las expansiones, se recoloca la ventana si hace falta y Windows intenta traerla al frente mediante `SetForegroundWindow`.

**105 pruebas de escritorio aprobadas en 25,50 s.** La prueba de integración guardó una captura con OCR desactivado, la mostró en Imágenes y verificó los bytes del PNG; otra prueba comprobó que persiste tras reabrir el almacén y no entra en la cola de transferencias. La prueba nativa de Windows pasó con **tres monitores**: ventana en el monitor del cursor, expansión sin salto a otro monitor, atajo global, bandeja y segunda apertura mediante el lanzador con foco activo, usando datos y portapapeles simulados: `.test-data/gui-native-b72b6900963b4ebd918982dd4601c4e5/`.

## Escritorio 0.4.8 · Ctrl+C comparte texto e imágenes · 2026-10-22

Ctrl+C sigue siendo propiedad del sistema: el dock observa los cambios del portapapeles y publica automáticamente texto e imágenes desde Windows. Se quitó el atajo de «Enviar portapapeles» de la configuración; solo queda el atajo opcional para mostrar el dock. El envío de texto ya no depende del conmutador de IA, de una casilla de envío ni de tener el teléfono conectado en ese instante. Cada copia se almacena como pendiente hasta recibir confirmación. Una captura PNG se guarda en `Dock/Capturas`, aparece en Imágenes y entra en la cola de archivos del protocolo TLS; se puede abrir mientras está pendiente. Si está activado «Imagen → Markdown», su resultado de texto también puede compartirse cuando se copie al portapapeles.

La aplicación Android **no se modificó**. Su protocolo existente recibe los textos y archivos que envía Windows. Android 14 limita la lectura del portapapeles global cuando esta app no tiene el foco, de modo que esta entrega no añade sincronización automática de capturas o textos copiados en segundo plano *desde* Android.

**106 pruebas de escritorio aprobadas en 26,30 s.** La prueba de integración TLS recibió una captura PNG con los mismos bytes y un texto copiado por la conexión existente, usando un receptor Android simulado. La prueba nativa del dock pasó en tres monitores. Con Bionic real y portapapeles Qt simulado, OCR y ortografía terminaron y copiaron el resultado sin bucle: `.test-data/ai-dock-b0137fa0786c429caf412615748d9948/result.json`. No se cambió el portapapeles físico ni se instaló una APK nueva; queda comprobar la recepción en el OnePlus conectado.

## Escritorio 0.5.0 / Android 0.3.0 · cerebro y varios dispositivos · 2026-10-22

El cerebro conserva confirmaciones independientes para cada teléfono o tableta. La prueba TLS conecta dos clientes, envía un texto desde uno y verifica la entrega al otro sin devolvérselo al emisor; otra prueba retransmite una imagen con los bytes originales. El dock Android añade las vistas compacta, Acciones y Detalles, la edición sincronizada de modos y prompts, una bandeja de imágenes/archivos y un observador de capturas nuevas de MediaStore. El observador espera a que termine de guardarse cada imagen y reintenta la importación si todavía no está disponible. Los trabajos remotos de IA quedan registrados en el cerebro y sus resultados se distribuyen como texto.

**110 pruebas de escritorio aprobadas en 36,04 s.** La prueba nativa de la ventana pasó con tres monitores, atajo global, bandeja, expansión y reapertura (`.test-data/gui-native-7944813e69a540378b34a918bf9be369/`). Android: `assembleDebug`, `testDebugUnitTest` y `lintDebug` aprobados tras el cambio del reintento de capturas; APK de desarrollo en `dist/ClipboardAI-0.3.0-debug.apk`. Estas pruebas usan clientes y modelo de IA simulados. Aún no se ha comprobado esta versión en el OnePlus físico, con Bionic en directo, con dos Android reales ni a través de Tailscale. Android sigue sujeto a las restricciones del portapapeles en segundo plano: para enviar texto desde otra aplicación usa Compartir o la acción sobre texto seleccionado.

## Android 0.3.1 · botón «Enviar al dock» · 2026-10-22

Se añadió un TileService a Ajustes rápidos y una Activity breve que solo lee el portapapeles cuando obtiene el foco. En Android 14 abre la Activity mediante `startActivityAndCollapse(PendingIntent)` y, si el teléfono está bloqueado, solicita desbloqueo antes de leer. El contenido de texto entra en la cola persistente existente; las URI de imágenes y archivos se copian a la bandeja antes de cerrar la ventana. En la app, **Acciones → Añadir botón rápido** solicita a Android mostrar el botón. La operación no crea un observador de portapapeles en segundo plano.

`assembleDebug`, `testDebugUnitTest` y `lintDebug` completaron **BUILD SUCCESSFUL**. Las pruebas de selección distinguen texto con saltos de línea, URI de archivo y texto vacío. APK de desarrollo: `dist/ClipboardAI-0.3.1-debug.apk` (versionCode 6, misma firma de desarrollo). La interacción real del botón, acceso al portapapeles y permiso de lectura de URI requieren comprobación en el OnePlus con OxygenOS 14; las pruebas locales no sustituyen esa comprobación.

## Android 0.3.2 · lotes, Compartir directo y dock visual · 2026-10-23

La selección de imágenes usa el selector múltiple de Android 13+ (y `ACTION_OPEN_DOCUMENT` múltiple en versiones anteriores), con un máximo de 20 archivos por lote. `ACTION_SEND_MULTIPLE` y `ACTION_SEND` incorporan las URI al dock inmediatamente después de elegir Clipboard AI en la hoja Compartir, sin segunda confirmación. El botón rápido también incorpora todas las URI copiadas en el portapapeles, hasta 20. Cada archivo se prepara y conserva por separado: un fallo no descarta los que sí se guardaron. Cuando el proveedor no publica MIME, se deduce a partir de la extensión conocida.

La pantalla compacta ofrece Enviar portapapeles, + Añadir, Acciones y Abrir dock; Ajustes agrupa vinculación, conexión, dirección y limpieza. El dock tiene Textos, Imágenes y Archivos con cantidades. Imágenes usa dos columnas, miniaturas decodificadas fuera del hilo de UI y una caché limitada a 8 MiB; las imágenes incompletas no se abren. Las opciones por elemento mantienen Abrir, Guardar copia, Compartir y quitar/cancelar.

`assembleDebug`, `testDebugUnitTest` y `lintDebug` completaron **BUILD SUCCESSFUL**. Una prueba de integración Robolectric comparte dos URI en una sola acción y confirma dos copias pendientes con sus tamaños; otras pruebas cubren selección múltiple, deduplicación y el recorrido de vinculación actualizado. APK de desarrollo: `dist/ClipboardAI-0.3.2-debug.apk` (versionCode 7, misma firma de desarrollo). Falta probar en el OnePlus real la hoja Compartir de la galería, permisos de sus URI, miniaturas y entrega al cerebro.

## Android 0.3.3 · cabecera compacta · 2026-10-23

La cabecera fija su altura a 56 dp y da a Ajustes solo el ancho necesario. Así el título vuelve a ser visible y el estado se sitúa inmediatamente debajo, con una separación de 8 dp. Una prueba de medición de la pantalla de 1080 × 2400 comprueba la altura de la cabecera, la posición de la tarjeta de estado y que ambos controles son visibles. APK de desarrollo: `dist/ClipboardAI-0.3.3-debug.apk` (versionCode 8, misma firma de desarrollo). Falta confirmar el resultado visual en el OnePlus real.

## Escritorio 0.5.1 · lo último recibido se copia en Windows · 2026-10-23

La ventana activa por defecto la copia al portapapeles de textos e imágenes que recibe del móvil. Los textos pendientes que llegan al reconectar también se copian en orden; una retransmisión del mismo identificador no vuelve a copiarse. Las imágenes se copian como píxeles mediante Qt después de completarse y validarse su transferencia, incluso con la acción de IA desactivada. Una oferta duplicada de una imagen ya entregada tampoco sustituye una copia posterior. La marca MIME del dock evita que la escritura se detecte como una copia local y genere un bucle. La opción de Ajustes permite desactivar la copia automática de ambos tipos.

**111 pruebas de escritorio aprobadas en 28,18 s.** Incluyen una transferencia TLS de imagen seguida de texto y oferta duplicada, más una escritura de imagen desde el hilo de red al hilo Qt sin republicación. La prueba nativa de Windows abrió el dock en tres monitores y verificó atajo, bandeja y expansiones con portapapeles simulado. Android no cambió. Falta comprobar una imagen y un texto reales del OnePlus tras reiniciar el dock; las pruebas no tocaron el portapapeles físico.

## Escritorio 0.5.2 · Markdown remoto en el portapapeles e indicador · 2026-10-23

Una imagen recibida del móvil se copia como imagen al portapapeles de Windows y activa la tarea de Imagen → Markdown. Al terminar, el resultado se guarda y se distribuye como antes; además reemplaza la imagen en el portapapeles de Windows si este no cambió durante el procesamiento. Los avisos de formato tardíos de la propia imagen no cuentan como una nueva copia. Si el usuario copia otra cosa entretanto, el Markdown permanece en Textos y el cursor indica «No copiado»; cuando sí se copió, muestra «Copiado». El cursor enseña «Procesando» mientras la tarea remota está pendiente o activa.

**112 pruebas de escritorio aprobadas en 30,70 s.** La integración TLS comprueba tanto la copia del Markdown y los estados del cursor como una copia posterior que debe conservarse. El portapapeles de prueba y el modelo de IA son simulados; falta la prueba final con la imagen real del OnePlus y Bionic en vivo. Android no se modificó.

## Escritorio · paneles ajustables, atajo de envío y avisos agrupados · 2026-10-23

El historial, los detalles, las acciones y el cuadro para escribir se separan mediante tiradores ajustables. Sus proporciones se guardan en `desktop.ini` y se restauran al contraer, expandir y reabrir el dock. La frase de estado ahora puede ocupar varias líneas, de modo que no impide ensanchar Acciones.

El diseño inicial de `Ctrl+Alt+C` solo enviaba el contenido anterior del portapapeles; se corrigió después a copiar primero la selección de la ventana activa y publicar solo la nueva revisión. `Ctrl+C` ordinario ya no publica texto ni capturas originales. Las capturas siguen guardándose localmente en Imágenes y los modos de IA siguen procesando la copia cuando están activos. El atajo se edita en Ajustes sin distinguir mayúsculas/minúsculas. Los avisos de nuevos textos, imágenes y archivos se agrupan durante 1,4 segundos y muestran los recuentos de envíos y recepciones; el primer estado cargado al iniciar no genera avisos antiguos.

**119 pruebas de escritorio aprobadas en 30,70 s.** Una prueba comprueba las proporciones de los tres separadores después de cerrar y reabrir, y otras cubren la edición persistente del atajo y la agrupación de avisos. La prueba nativa de Windows registró cinco atajos sin foco, abrió el dock en tres monitores y verificó su segunda apertura con datos y portapapeles simulados. Falta la comprobación manual de los tamaños y de las notificaciones reales en el escritorio del usuario. Android no se modificó.

## Corrección del atajo Copiar y enviar · 2026-10-23

El atajo editable `Ctrl+Alt+C` espera a que se suelten sus teclas, envía `Ctrl+C` a la aplicación que conserva el foco y comparte únicamente una revisión nueva del portapapeles. Si la aplicación no copia nada, caduca a los 2,5 segundos sin compartir el contenido anterior. Las letras de los atajos se normalizan para aceptar mayúsculas y minúsculas. `Ctrl+C` normal no publica el contenido original: el texto queda local; las capturas se guardan en Imágenes sin ponerse en la cola de red. Las acciones automáticas de IA siguen procesando sus entradas cuando están activadas y sus resultados conservan su comportamiento de distribución.

**123 pruebas de escritorio aprobadas en 30,23 s.** Incluyen repetición de una imagen idéntica, revisión nueva antes de enviar, caducidad sin envío anterior, persistencia de edición del atajo, variante con Mayús y estructura de la secuencia `SendInput` sin tocar el teclado real. La prueba nativa registró los atajos globales y verificó el dock en tres monitores con datos simulados. Falta probar físicamente el gesto `Ctrl+Alt+C` dentro de las aplicaciones concretas del usuario después de reiniciar el dock. Android no se modificó.

## Copia explícita e imágenes del Explorador · 2026-10-23

Ctrl+C ya no activa IA. Copiar y enviar publica la nueva copia y solicita el modo activo. Las listas de rutas del Explorador se reconocen y sus archivos se envían; una imagen seleccionada se decodifica con límites de 24 MP y 8 MiB PNG para IA. Los avisos repetidos de la misma lista sin una nueva copia no adelantan su revisión. Los lotes se envían como archivos; el procesamiento desde el Explorador pide una imagen a la vez.

130 pruebas aprobadas en 30,38 s. Se verificaron ausencia de peticiones con Ctrl+C, envío de imagen por ruta y activación de IA correspondiente con portapapeles simulado. Queda la prueba manual desde el Explorador real tras reiniciar.

## Restauración de IA automática para capturas · 2026-10-23

Se restaura únicamente el procesamiento de imágenes con píxeles en el portapapeles cuando Imagen → Markdown está activo. Ctrl+C de texto sigue sin activar IA; el flujo de archivos desde el Explorador con Copiar y enviar se conserva. Siete pruebas específicas aprobadas: captura con acción apagada/encendida, copia normal de texto, imagen del Explorador y selección explícita por modo. No se probó físicamente Recortes en esta corrección.
