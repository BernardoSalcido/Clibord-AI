# Protocolo de texto v1, archivos files-v1 y extensión hub-v2

Implementado en Python y Kotlin. Transporte: WebSocket con TLS; el cliente verifica la huella SHA-256 del certificado DER del servidor antes de enviar secretos. JSON en mensajes de texto; compresión desactivada en servidor. Puerto propuesto: 45821.

Las secciones v1 describen el contrato original y sus límites históricos. La extensión `hub-v2` al final describe la entrega actual entre varios dispositivos. Los clientes antiguos siguen intercambiando texto y, si anuncian `files-v1`, archivos con el cerebro.

## Vinculación

El usuario transfiere por QR o pegado manual este objeto desde Windows a Android:

```json
{"v":1,"host":"192.168.1.10","port":45821,"fingerprint":"64 caracteres hexadecimales","code":"secreto temporal"}
```

Es información privada de vinculación, válida durante cinco minutos y para un solo uso. Cinco intentos fallidos cierran la ventana de vinculación. Un nuevo `pair` invalida el código anterior. El ordenador admite un teléfono vinculado en esta versión.

Tras verificar TLS, Android envía `pair` con `device` (UUID persistente), `name` (1–80 caracteres) y `code`. Windows responde `paired` con `token` y `server` (UUID persistente) y cierra la conexión. Android persiste la credencial en almacenamiento privado, excluido de copias de seguridad. Si se pierde esta respuesta hay que revocar el vínculo en Windows antes de repetirlo.

## Sesión autenticada

Todos los mensajes incluyen `v: 1` y `type`.

1. Android envía `hello` con `device` y `token`.
2. Windows responde `welcome` con `server`; Android comprueba que coincide con la vinculación.
3. Windows envía un primer lote de hasta ocho pendientes con `live: false` y termina con `ready`.
4. Android envía un primer lote de hasta ocho pendientes con `live: false` y termina con `ready`.
5. Nuevos envíos de una sesión activa usan `live: true`. Los reintentos usan siempre `false`.

El servidor autentica en los primeros 15 segundos. Una nueva sesión del mismo dispositivo cierra la anterior. Revocar un dispositivo elimina su autorización y cierra la sesión vigente.

## Elemento y confirmación

```json
{
  "v": 1,
  "type": "item",
  "live": true,
  "item": {
    "id": "00000000-0000-4000-8000-000000000001",
    "origin": "00000000-0000-4000-8000-000000000002",
    "seq": 1,
    "created": "2026-10-15T12:00:00Z",
    "text": "Texto exacto, sin normalizar espacios ni Unicode"
  }
}
```

- UUID canónico en minúsculas; origen igual a la identidad autenticada del emisor.
- Secuencia entera entre 1 y 2^53−1, creciente para la instalación de origen.
- Fecha textual de hasta 64 caracteres, informativa.
- Texto no vacío, hasta 256 KiB UTF-8. Sin truncamiento ni conversión de saltos de línea.
- Límite del mensaje completo: 6 × 256 KiB + 4096 bytes, permitiendo escapes JSON.

El receptor persiste antes de responder `{"v":1,"type":"ack","id":"UUID"}`. Un duplicado idéntico se confirma sin crear otra entrada ni volver a copiar. Reutilizar ID o secuencia con contenido diferente se rechaza.

Cada cinco segundos se envía un lote de hasta ocho pendientes de la sesión, reintentando los que aún no tienen confirmación. Esto limita la memoria y la cola del transporte. `ready` habilita la fase de eventos nuevos; no significa que ya se haya vaciado toda la cola. Android reconecta con espera de 1, 2, 4… hasta 30 segundos. Los envíos permanecen en disco si se pierde la conexión. Se conservan recibos de deduplicación con hashes después de borrar o recortar el contenido del historial.

Solo un elemento nuevo y marcado `live`, recibido después del `ready` remoto, puede activar el copiado automático de Windows. Android copia únicamente por acción del usuario. No se establece un orden global entre cambios simultáneos.

`error` incluye `message`. Los fallos de autorización cierran la conexión; los mensajes inválidos de una sesión autenticada se rechazan con error. El cliente Android detiene la sesión al recibir un error y lo muestra; el usuario puede volver a conectar tras resolverlo.

## Límites y almacenamiento

500 elementos entregados en historial y hasta 500 pendientes; la pantalla Android presenta los últimos 50. Los límites son fijos en este prototipo. Los pendientes no se borran mediante las acciones de borrado normales. El borrado solo afecta al dispositivo donde se solicita.

El prototipo transfiere elementos nuevos y pendientes, no replica indefinidamente todo el historial a dispositivos recién vinculados. Tras revocar un teléfono y vincular otro, el historial entregado al teléfono anterior no se reenvía; los pendientes del PC sí pueden enviarse al nuevo teléfono.

Los recibos guardan metadatos y hashes sin texto, y todavía no tienen una política de compactación. Se diseñará al ampliar el protocolo.

Datos reales fuera del repositorio: `%LOCALAPPDATA%\ClipboardAI` en Windows y almacenamiento privado de la aplicación en Android. El certificado y la clave de Windows son persistentes. El QR guardado localmente queda inválido al consumirse o caducar el código.

## Ciclo de vida Android desde 0.1.2

`DockService` posee una única conexión y base de datos. La Activity se enlaza mientras está visible y retira sus observadores al detenerse; esto no cierra una sesión iniciada con Conectar. El servicio `connectedDevice` publica una notificación sin contenido del portapapeles y una acción Pausar. Tiene los permisos de servicio, tipo, red, notificaciones y bloqueo parcial de CPU declarados. Las notificaciones se solicitan en Android 13+; denegarlas no impide iniciar el servicio.

Conectar inicia explícitamente el servicio desde la pantalla visible. Pausar detiene reintentos, conexión, notificación y bloqueo de CPU. Errores terminales de identidad, autorización o protocolo también detienen la sesión persistente; una pérdida de red conserva los reintentos. Un reinicio del servicio por el sistema recupera únicamente una sesión que estuviera habilitada. No se usa arranque automático del teléfono. El protocolo de red y las credenciales existentes no cambian.

El bloqueo parcial mantiene la CPU disponible durante la sesión solicitada; no impide Doze ni las restricciones del fabricante. La ayuda abre los ajustes de optimización de batería para que el usuario elija. Mantener el transporte activo no concede lectura del portapapeles Android en segundo plano.

## Extensión de archivos · aplicación 0.2.0

Hello y welcome anuncian `capabilities: ["files-v1"]`. Solo se intercambian mensajes file_* cuando ambos extremos anuncian la capacidad; el formato de vinculación y texto v1 permanece compatible con 0.1.x.

Los mensajes siguen siendo JSON dentro del WebSocket TLS autenticado. Los fragmentos usan Base64 para reutilizar el transporte acotado existente; un bloque binario de 64 KiB ocupa aproximadamente 87 KiB codificado. No se envía el archivo completo en un único mensaje. Hay un fragmento pendiente de confirmación por dirección; se suprime la respuesta duplicada para una misma posición dentro de cada sesión. No se usa la cola de texto para transportar archivos.

| Mensaje | Campos y efecto |
| --- | --- |
| file_offer | `file`: id, origin, created, name, size, sha256, mime. Origin debe coincidir con el dispositivo autenticado. |
| file_accept | id, offset: posición durable donde continuar; autoriza el siguiente fragmento. |
| file_chunk | id, offset, data: Base64 de hasta 65536 bytes. |
| file_done | id: archivo completo persistido, tamaño y SHA-256 verificados. |
| file_cancel | id: cancelar una transferencia no completada; se conserva un recibo. |
| file_cancelled | id: cancelación procesada; elimina el aviso pendiente. |
| file_error | id, message: error de este archivo, sin cerrar la sesión de texto. |

Las ofertas y las cancelaciones pendientes se repiten cada cinco segundos y tras conectar. Una oferta repetida devuelve la posición confirmada; si el receptor ya completó o borró un archivo entregado devuelve file_done. Una cancelación recibida antes de la oferta se guarda para que el archivo no reaparezca al reconectar. Los errores de integridad requieren cancelar y crear un nuevo envío.

Cada fragmento se escribe y sincroniza en disco antes de confirmar su posición en SQLite. Tras reiniciar, se trunca cualquier cola no confirmada y se continúa desde la posición durable. El archivo completo se mueve dentro del mismo almacenamiento y luego se marca entregado; se recupera también la interrupción entre ese movimiento y la confirmación en base de datos. Los parciales permanecen fuera de los archivos disponibles para abrir. Se rechazan posiciones inválidas, fragmentos duplicados con contenido distinto y metadatos cambiados bajo el mismo ID.

Los nombres se validan para ambos sistemas y no determinan rutas internas. Recibidos se organiza por UUID/nombre; las copias de envío por UUID. No hay extracción de archivos comprimidos, ejecución automática ni copia automática al portapapeles.

Límites: 100 MiB por archivo, 1 GiB reservado para copias de envío/recepción y 100 pendientes. Los metadatos/recibos permanecen después del borrado; su compactación queda pendiente. Se limpia manualmente contenido entregado y se preservan originales, exportaciones y archivos pendientes. Restos de preparación sin registro y con más de 24 horas se retiran al arrancar; se conserva el margen para no interferir con una importación que termina mientras Android recrea el servicio.

## Extensión `hub-v2` · escritorio 0.5.0 / Android 0.3.0

El cliente anuncia `hub-v2` junto a `files-v1` en `hello`. El cerebro anuncia ambas capacidades en `welcome`. Un cliente antiguo no recibe mensajes nuevos y conserva los flujos v1 que entiende. La vinculación TLS, los tokens y la huella del certificado permanecen iguales. Ahora se pueden vincular varios dispositivos; una sesión activa por identidad de dispositivo.

Cada texto conserva `id`, `origin` y `seq` originales al pasar por el cerebro. El cerebro valida que una entrada nueva del cliente tenga su propio `origin`, la persiste y crea una confirmación pendiente para cada destinatario distinto del emisor. Solo un cliente `hub-v2` recibe textos con origen de otro cliente. El `ack` del destinatario afecta únicamente a su propia entrega. Los pendientes se reintentan por destinatario y sobreviven al reinicio. Un dispositivo recién vinculado recibe los pendientes y hasta 50 textos recientes. Las entradas recibidas con `live:false` no reemplazan el portapapeles Android al restaurarse.

Los archivos conservan también el origen y los bytes originales. Una vez que el cerebro confirma un archivo recibido, lo ofrece a los demás clientes `hub-v2`, con confirmación y reanudación independientes por destinatario. Los clientes nuevos reciben los archivos de envío pendientes y una selección de hasta 50 archivos recientes. Los originales recibidos permanecen en el dock del cerebro. `file_error` y `file_cancel` de un destinatario no eliminan el original. Se mantienen los límites de tamaño y cuota de `files-v1`.

El cerebro envía `settings` con `revision` y `values` (`image`, `text_mode`, `prompts`) al conectar y tras un cambio confirmado. Android conserva `settings_update` sin conexión, con `base_revision` y `changes`, y lo envía antes de su cola de textos y archivos al reconectar. Un cambio sobre una revisión anterior obtiene `settings_conflict`; Android conserva el cambio para que el usuario lo revise y use **Aplicar ajustes pendientes**. El modelo, la dirección de la API, los permisos y la detección de capturas son propios del equipo.

`devices` anuncia los nombres y estados de los clientes vinculados. `ai_status` anuncia `source_id`, acción y estado `pending`, `running`, `done` o `error` al dispositivo que envió la entrada. El cerebro procesa imágenes recibidas cuando `image` está activo y textos recibidos cuando `text_mode` es `spelling` o `grammar`; guarda un trabajo por entrada para evitar reprocesar reintentos. La respuesta viaja como un `item` de texto normal con el campo opcional `result` (`source_id`, `source_origin`, `action`). Solo el contenido validado por la IA se distribuye. Android copia automáticamente un resultado nuevo en directo a su portapapeles; un resultado recuperado del historial permanece disponible para copiar manualmente.
