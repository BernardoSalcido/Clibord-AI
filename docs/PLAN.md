# Plan de Clipboard AI

Actualizado: 2026-10-16. Estado: el usuario confirmó las pruebas de funcionamiento de 0.2.0 Windows–OnePlus LE2115. La versión de escritorio 0.3.0 añade ventana, búsqueda, bandeja, arrastrar archivos, atajos Windows y ajustes sobre los datos y el protocolo existentes; Android conserva 0.2.0. Pendientes la prueba de uso diario de la ventana, Linux y la medición de batería/reposo prolongado. Este documento conserva el plan general. README.md y protocol.md describen el comportamiento actual.

Siguientes entregas, en orden:

1. Validar conexión con pantalla bloqueada, pausa, reconexión y consumo de batería.
2. Incorporar archivos al dock: enviar/recibir, progreso, integridad, límites y limpieza temporal.
3. Facilitar el uso diario: ventana de escritorio, bandeja y atajos; probar Linux.
4. IA local: imagen a texto y corrección exclusivamente ortográfica, conservando el original.
5. Integrar el código existente de voz a portapapeles y portapapeles a teclado.
6. Ampliar la vinculación y sincronización a una tableta y otros dispositivos.

## 1. Objetivo y decisiones de partida

Construir una aplicación personal que conecte un dock de contenido con el portapapeles de cada dispositivo y permita ejecutar acciones de IA local sobre ese contenido.

Decisiones expresadas en la conversación:

- Plataformas finales: Windows, Linux y Android.
- Primera pareja de prueba: ordenador Windows y teléfono Android.
- Teléfono indicado por el usuario: OnePlus LE2115 con OxygenOS 14.0.
- El programa de escritorio puede funcionar desde la terminal.
- Android tendrá un paquete instalable APK.
- Construcción progresiva; primero comunicación y portapapeles, después archivos e IA.
- La corrección solicitada es únicamente ortográfica, sin modificar sintaxis, estilo ni significado.
- Existen herramientas anteriores de voz a portapapeles y portapapeles a teclado; el usuario aportará su código posteriormente.
- No se requiere Flutter ni una interfaz gráfica compartida.

Supuestos de trabajo revisables:

- Ambos equipos están en una misma red que permite conexiones entre ellos.
- La aplicación Android permanece abierta durante la primera prueba.
- No se necesita nube, cuenta externa, acceso por Internet ni root para el primer prototipo.
- Python para escritorio y Kotlin nativo para Android ya se validaron con un intercambio real.

## 2. Tres conceptos diferentes

| Concepto | Función |
| --- | --- |
| Dock | Colección local de elementos enviados y recibidos: primero texto, después imágenes y archivos. |
| Portapapeles activo | Contenido que el sistema permite pegar en ese momento. No equivale al historial del dock. |
| Acción | Operación sobre un elemento: copiar, compartir, extraer texto, corregir, transcribir o escribir. |

En escritorio, el dock contará posteriormente con una carpeta para los archivos y una ventana opcional. El texto y los metadatos se guardarán en una base local. En Android se usarán almacenamiento propio y opciones de importar/exportar mediante el sistema.

Agregar un archivo al dock no cambia por sí solo el portapapeles activo. Recibir historial atrasado tampoco lo cambia.

## 3. Alcance de la versión 0.1

Incluye:

- Programa de terminal para Windows.
- Aplicación Android con estado de conexión, lista de textos y acciones de enviar/copiar.
- Vinculación explícita de un teléfono con un ordenador.
- Envío bidireccional de texto plano Unicode.
- Historial local persistente y estado pendiente/entregado.
- Reconexión, confirmación de recepción y eliminación de duplicados.
- Envío manual desde el portapapeles; después, modo automático activable en Windows.
- Errores comprensibles cuando no hay conexión o permisos.

Quedan para versiones posteriores: archivos, imágenes, IA, ventana de escritorio, atajos globales, inicio automático, operación Android en segundo plano, teclado Android propio, varios dispositivos e Internet.

## 4. Arquitectura de la primera versión

```text
Windows: programa Python                    Android: aplicación Kotlin
  Terminal                                    Pantalla del dock
  Dock local + cola pendiente                  Dock local + cola pendiente
  Adaptador de portapapeles                    Acciones enviar / copiar
  Servicio de conexión  <--- canal cifrado ---> Cliente de conexión
```

Para reducir el alcance, Windows acepta la conexión y Android la inicia. El PC debe estar encendido y el programa ejecutándose para intercambiar contenido en esta versión. El historial ya descargado sigue disponible sin conexión.

Esta topología es temporal. No constituye todavía una red independiente entre todos los dispositivos. La conexión directa entre pares se evaluará al incorporar un tercer equipo y el segundo plano en Android.

Componentes previstos:

| Componente | Propuesta |
| --- | --- |
| Escritorio | Python, con núcleo independiente del sistema y adaptador Windows. |
| Android | Kotlin, una actividad sencilla e integración con el portapapeles y Compartir. |
| Transporte | WebSocket sobre TLS, mensajes JSON con versión de protocolo. |
| Persistencia | SQLite en escritorio y SQLiteOpenHelper nativo en Android; se simplificó la propuesta inicial de Room para el prototipo. |
| Identidad | Identificador persistente por instalación y credencial por dispositivo vinculado. |
| Linux posterior | Reutilizar el núcleo Python e implementar el adaptador del escritorio objetivo. |

Las bibliotecas concretas y sus versiones se fijarán durante la preparación del entorno. Se usarán implementaciones mantenidas de TLS y del transporte, sin crear criptografía propia.

## 5. Flujos de uso

### Primera vinculación

1. El usuario ejecuta el programa en Windows y solicita vincular un dispositivo.
2. Windows muestra la dirección local y datos de vinculación de un solo uso.
3. Android recibe esos datos mediante QR o introducción manual.
4. Se verifica la identidad del servidor: huella del certificado transferida por QR o comparada manualmente antes de enviar credenciales.
5. Windows confirma la incorporación del teléfono y se guarda una credencial propia para esa vinculación.

El código de vinculación caduca y tiene límite de intentos. El certificado queda fijado para conexiones posteriores; un cambio de identidad requiere volver a vincular. Se podrá revocar el teléfono desde Windows. No se deshabilitará globalmente la verificación TLS.

La preparación del entorno comprobará la conectividad y si Windows necesita una regla de firewall limitada a la aplicación y a redes privadas. No se abrirán puertos del router.

### Windows a Android

1. El usuario copia texto en cualquier aplicación de Windows.
2. En modo manual, ejecuta la acción de enviar portapapeles; en modo automático, se detecta el cambio.
3. El elemento se guarda localmente y se transmite al teléfono.
4. Android lo guarda y confirma su recepción.
5. El usuario pulsa Copiar en Android y pega donde necesite.

### Android a Windows

1. El usuario pega o escribe texto dentro de la aplicación y pulsa Enviar.
2. También podrá usar Compartir desde aplicaciones que admitan compartir texto.
3. Windows guarda el elemento recibido.
4. Se copia mediante una acción de terminal o, si se ha activado ese modo, se aplica automáticamente al portapapeles.

### Sin conexión

- Los envíos explícitos quedan pendientes y visibles en el dock.
- Al volver a conectar, se reintentan y se confirma su recepción persistida.
- Recuperar contenido pendiente actualiza el historial, sin sustituir automáticamente el portapapeles actual.
- El modo automático de Windows solo publicará mientras esté conectado en la versión inicial; no se archivará toda la actividad desconectada silenciosamente.

## 6. Reglas de sincronización

- Cada elemento tiene un UUID, origen, secuencia creciente de origen, tipo, fecha informativa y contenido.
- El protocolo diferencia saludo, creación de elemento, confirmación, error y recuperación de pendientes.
- Un receptor confirma después de persistir el elemento. Si ya existe, confirma otra vez sin duplicarlo.
- Los envíos usan reintentos con espera creciente. Perder una confirmación no crea una segunda entrada.
- La fecha del equipo no decide qué texto gana: los relojes pueden diferir.
- La recuperación inicial termina con una señal explícita de sincronización completa. Solo eventos nuevos de la sesión activa pueden activar el copiado automático.
- Las escrituras propias al portapapeles se identifican en el adaptador para no capturarlas como nuevos envíos. La supresión es limitada al cambio esperado, no permanente por contenido.
- Copiar voluntariamente el mismo texto más tarde sigue siendo una acción válida.
- Si hay cambios simultáneos se conservan ambos en el historial. No se promete un portapapeles global único en la versión 0.1; el orden local de eventos determina el activo de cada equipo.
- Propuesta inicial: máximo 256 KiB de texto UTF-8 por elemento, sin truncamiento silencioso. Mensajes mayores se rechazan con explicación; archivos tendrán su propio mecanismo.
- El historial tendrá borrado manual y un límite configurable, propuesto en 500 elementos entregados. Los pendientes no se eliminan sin avisar; al alcanzar su límite se detienen nuevos envíos y se explica la causa.
- Los registros de diagnóstico muestran identificadores y estados, sin volcar textos completos ni credenciales.

## 7. Organización prevista del código

```text
Clipboard_AI/
  README.md
  docs/
    PLAN.md
    protocol.md          # Se escribirá al iniciar la implementación.
  desktop/
    src/clipboard_ai/
      core/              # Elementos, persistencia y cola.
      transport/         # Conexión, vinculación y mensajes.
      platforms/         # Windows; Linux posteriormente.
      cli/               # Acciones de terminal.
    tests/
  android/
    app/                 # Cliente nativo y almacenamiento local.
  protocol/
    fixtures/            # Ejemplos compartidos para verificar interoperabilidad.
```

La implementación inicial usa módulos Python pequeños en desktop/src/clipboard_ai y clases Kotlin en android/app/src/main/java/org/clipboardai/app. La subdivisión en más carpetas se hará cuando crezcan los módulos. Los datos de uso y las credenciales van en las ubicaciones de datos de aplicación de cada sistema, fuera del código fuente y de la carpeta compartida del proyecto.

## 8. Etapas y criterios para avanzar

| Etapa | Entrega | Criterio de aceptación |
| --- | --- | --- |
| A. Preparación | Revisar Python, JDK, SDK Android y teléfono; fijar dependencias y contrato mínimo. | Podemos ejecutar el programa base y compilar/instalar una APK de prueba. |
| B. Conexión | Servicio Windows y cliente Android, vinculación y texto escrito manualmente. | Texto Unicode viaja en ambos sentidos entre los dispositivos reales; una conexión no vinculada se rechaza. |
| C. Dock persistente | Historial, confirmaciones, cola y recuperación. | Reiniciar ambos conserva los elementos; perder una confirmación y reconectar no duplica el envío. |
| D. Portapapeles | Enviar/copiar manualmente y modo automático Windows. | Copiar en Windows llega al dock Android; enviar desde Android puede pegarse en Windows; no hay bucles. |
| E. Entrega 0.1 | Instrucciones breves, programa de escritorio y APK de pruebas. | El usuario repite los flujos sin herramientas de desarrollo abiertas. |
| F. Ampliación | Adaptador Linux en el escritorio elegido y evaluación del segundo plano Android. | Se documentan y prueban las capacidades reales antes de prometer automatización continua. |
| G. Archivos | Imágenes, archivos, carpeta de entrada y selección/Compartir en Android. | Transferencias verificadas por tamaño y hash; archivos incompletos no aparecen como terminados. |
| H. IA | Extracción de texto y corrección ortográfica en el ordenador. | Original recuperable y resultado asociado al elemento correcto, incluso si el usuario copia otra cosa mientras espera. |
| I. Herramientas existentes | Integrar voz a portapapeles y portapapeles a teclado. | Se reutiliza el código aportado después de comprobar sus dependencias y comportamiento. |
| J. Experiencia completa | Ventana del dock, atajos, arranque automático y varios dispositivos. | Flujos coherentes con las capacidades de cada sistema. |

No se estiman fechas hasta comprobar el entorno Android y completar el primer intercambio real.

## 9. Pruebas necesarias para la primera entrega

Pruebas automatizadas centradas en el comportamiento:

- Texto con acentos, emoji, saltos de línea, espacios iniciales/finales y caracteres no latinos se conserva exactamente.
- Recepción duplicada y pérdida de confirmación producen una sola entrada persistida.
- Reconexión y reinicio recuperan pendientes sin sobrescribir el portapapeles activo.
- Escritura remota al portapapeles no genera un envío de retorno.
- Los ejemplos de protocolo se interpretan igual en Python y Kotlin.
- Mensajes malformados, tipos desconocidos, exceso de tamaño y credenciales inválidas se rechazan sin cerrar inesperadamente la aplicación.

Pruebas reales en Windows y el teléfono:

- Vincular, enviar en ambos sentidos y pegar en otra aplicación.
- Desactivar y reactivar Wi-Fi; detener y reiniciar Windows; comprobar estados y recuperación.
- Copiar textos rápidamente y enviar desde ambos equipos casi al mismo tiempo; no perder elementos del historial.
- Pausar y reactivar el envío automático.
- Comprobar el comportamiento al salir de Android y volver: la versión inicial no promete continuidad en segundo plano.
- Revocar un dispositivo e intentar reconectar.

Compilar correctamente no equivale a verificar funcionamiento en el teléfono. El cierre de la versión 0.1 requiere la prueba física con el usuario.

## 10. Reglas para las ampliaciones

Archivos: incorporar como copias, conservar el original, mostrar progreso y validar integridad. Un nombre recibido no puede seleccionar rutas fuera del dock. Decidir límites y caducidad antes de habilitar descargas automáticas de archivos grandes. El borrado local no se propagará a otros equipos sin una política explícita.

IA: servicio opcional ejecutado en el ordenador. El intercambio normal funciona sin el modelo. Conservar entrada y salida relacionadas; nunca procesar repetidamente el resultado por confundirlo con una nueva entrada. Si cambia el portapapeles durante el procesamiento, guardar la salida en el dock y ofrecer copiarla.

Imagen a texto: evaluar OCR y modelos con visión con capturas reales; transcribir el texto, sin resumirlo ni completarlo. El modo automático para capturas será opcional y posterior al modo manual.

Corrección: ortografía solamente. Usar ejemplos con términos científicos, citas, fórmulas y sintaxis deliberadamente imperfecta para detectar reescrituras indebidas. Una instrucción al modelo no garantiza fidelidad; ofrecer diferencias y recuperar el original.

Voz: revisar primero la herramienta existente; la transcripción produce un elemento normal del dock, reutilizando el mecanismo de sincronización.

Teclado: revisar la herramienta existente y probar aplicación destino, foco, distribución, Unicode y cancelación. La escritura se inicia explícitamente; recibir un elemento remoto nunca debe escribirlo automáticamente en la ventana activa.

## 11. Restricciones verificadas y asuntos pendientes

Android 10 o posterior restringe la lectura del portapapeles a la aplicación con foco o al teclado predeterminado. Un servicio en segundo plano no elimina esa restricción. Por eso el primer diseño usa acciones dentro de la aplicación y Compartir. [Documentación oficial](https://developer.android.com/about/versions/10/privacy/changes#clipboard-data).

Android 0.1.2 usa un servicio en primer plano de tipo `connectedDevice`, iniciado mediante Conectar, con notificación y pausa explícita. Mantiene la conexión al salir de la Activity y libera el bloqueo parcial de CPU al pausar o finalizar. El servicio no evita por sí solo las restricciones de Doze: la app incluye acceso a los ajustes de batería. Pendiente medir continuidad y consumo en el teléfono real. [Tipos de servicio](https://developer.android.com/develop/background-work/services/fgs/service-types), [Doze](https://developer.android.com/training/monitoring-device-state/doze-standby).

Antes de fijar permisos y SDK objetivo, comprobar los requisitos de acceso a red local correspondientes a las versiones de Android usadas. [Permiso de red local](https://developer.android.com/privacy-and-security/local-network-permission).

El almacenamiento Android se diseñará con las ubicaciones y mecanismos de acceso de la plataforma. [Almacenamiento propio de la aplicación](https://developer.android.com/training/data-storage/app-specific).

Pendiente de información del usuario, sin bloquear este plan:

- Ajustes de batería del OnePlus y resultado de la prueba prolongada con la pantalla bloqueada.
- Distribución Linux, escritorio y tipo de sesión para la etapa posterior.
- Código existente de voz y teclado, cuando corresponda integrarlo.

Siguiente tarea concreta: probar el dock 0.3.0 en Windows con el Android 0.2.0 ya vinculado, cerrar la ventana a la bandeja, enviar con atajos y repetir texto/archivos. Después validar el escritorio Linux concreto y avanzar a IA local.

## Entrega de escritorio 0.3.0

- Python con PySide6 Essentials 6.12.0; la terminal continúa disponible sin el extra gráfico.
- Motor asyncio y ambas bases SQLite en un único hilo dedicado; interfaz Qt en el hilo principal, con un puente de portapapeles que evita acceder a QClipboard desde el hilo de red.
- Historial combinado, búsqueda, filtros, lectura/copia de texto, envío manual y automático, importación por selector o arrastrar, progreso, cancelación, apertura de recibidos, exportación y limpieza.
- Bandeja con Abrir, Enviar portapapeles, Añadir archivos, Pausar/Reanudar y Salir. Sin bandeja la ventana permite minimizar y confirma la salida.
- Una instancia por carpeta de datos: bloqueo del sistema compartido con la terminal y canal local restringido al usuario para recuperar la ventana. No hay comandos remotos de teclado ni de ejecución arbitraria.
- Preferencias locales en desktop.ini: geometría, automatización, avisos y atajos. Inicio con Windows opcional para el usuario actual, desactivado inicialmente.
- Ctrl+Alt+D y Ctrl+Alt+S globales en Windows, configurables y con detección de conflictos. Linux usa atajos de ventana y permite integrar --show/--send-clipboard con las acciones del escritorio.
- Cierre cooperativo: una copia ya aceptada termina de incorporarse antes de cerrar SQLite; los pendientes se conservan para reanudar.
- La red sigue siendo una pareja PC–teléfono. El protocolo, los límites de archivos y la APK permanecen compatibles.

## Etapa de IA local 0.4.0 · 2026-10-20

Esta entrega sustituye la propuesta anterior de empezar por acciones manuales: el usuario decidió modos automáticos persistentes. Imagen → Markdown es independiente; Ortografía y Gramática son mutuamente excluyentes. Se activan al cambiar el portapapeles externo; resultados propios y textos recibidos quedan excluidos. Una tarea activa y la entrada pendiente más reciente, con cancelación y protección por revisión del portapapeles.

Cliente HTTP asíncrono nativo `/api/v1/models`, `/api/v1/models/load`, `/api/v1/chat` con SSE, sin conversación almacenada ni herramientas. Prompts por acción en ai.json; el programa añade el contrato de delimitadores y solo copia una respuesta final válida. Qwen3.5-9B Q4_K_M se detectó en la API de Bionic en 127.0.0.1:1235. Carga y calentamiento al iniciar, reutilización de instancia existente, arranque del servicio mediante instalación publicada y Local API previamente configurada para inicio automático.

El resultado se guarda localmente antes de copiarlo. Solo se publica automáticamente cuando se copió y el envío automático está activo. El historial conserva hasta 20 originales, con 64 MiB máximos de imágenes originales. Acciones a la derecha y Detalles hacia abajo; Detalles sustituye el área de arrastre. Voz y teclado permanecen como opciones pendientes.

Validación: pruebas automáticas de escritorio, prueba nativa de paneles/atajos/bandeja y dos comprobadores explícitos con Qwen real y datos sintéticos. Uso diario con el teléfono físico, arranque con Bionic completamente cerrado y Linux quedan por comprobar. No se cerró la aplicación del usuario para probar un arranque en frío.
