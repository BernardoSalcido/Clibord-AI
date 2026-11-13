import argparse
import asyncio
import contextlib
import json
import os
from pathlib import Path
import html
import socket
import sys
import webbrowser

import qrcode
import qrcode.image.svg

from .clipboard import Clipboard
from .protocol import ProtocolError
from .security import tls_identity
from .server import DockServer
from .store import Store
from .files import FileDock

HELP = """Acciones:
  pair                   Mostrar datos de vinculación (caducan en 5 minutos).
  send TEXTO             Enviar texto escrito, conservando espacios tras 'send '.
  clip                   Enviar el texto actual del portapapeles.
  file "RUTA"            Incorporar un archivo y enviarlo.
  files                  Mostrar archivos, progreso y errores.
  folder                 Abrir Entrada y mostrar las carpetas del dock.
  cancel ID              Cancelar una transferencia de archivo.
  deletefile ID          Borrar una copia local del dock.
  clearfiles             Mostrar cuánto espacio liberaría la limpieza.
  clearfiles confirm     Borrar las copias locales entregadas.
  list                   Ver los últimos 20 elementos, sin mostrar su contenido.
  show ID                Mostrar el texto de un elemento.
  copy ID                Copiar un elemento al portapapeles.
  delete ID              Borrar localmente un elemento entregado.
  auto on|off            Activar/desactivar envío automático mientras hay conexión.
  receive on|off         Activar/desactivar copiado de nuevos mensajes recibidos.
  peers                  Mostrar dispositivo vinculado.
  revoke ID              Revocar dispositivo (UUID completo).
  status                 Mostrar estado.
  help                   Mostrar estas acciones.
  quit                   Salir.
"""


def data_directory():
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ClipboardAI"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ClipboardAI"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "clipboard-ai"


def local_addresses():
    values = {"127.0.0.1"}
    with contextlib.suppress(OSError):
        values.update(info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    return sorted(values)


def pairing_payload(server, fingerprint, address, port):
    return json.dumps(dict(v=1, host=address, port=port, fingerprint=fingerprint,
                           code=server.pairing.open()), separators=(",", ":"))


async def run(args):
    from .instance import InstanceLock
    directory = (args.data_dir or data_directory()).expanduser().resolve()
    with InstanceLock(directory):
        await _run(args)


async def _run(args):
    directory = (args.data_dir or data_directory()).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    store = Store(directory / "dock.sqlite3")
    context, fingerprint = tls_identity(directory)
    try:
        clipboard = Clipboard()
    except (OSError, RuntimeError) as exc:
        clipboard = None
        print(f"Portapapeles no disponible: {exc}. Puedes intercambiar texto con 'send'.")
    files = FileDock(directory / "Dock", store.device)
    server = DockServer(store, clipboard, files=files)
    try:
        async with server.listen(args.bind, args.port, context):
            watcher = asyncio.create_task(server.watch())
            file_watcher = asyncio.create_task(server.watch_files())
            print(f"Clipboard AI 0.3 — puerto {args.port}")
            print(f"Entrada de archivos: {files.inbox}")
            print(f"Archivos recibidos: {files.received}")
            print("Direcciones locales:", ", ".join(local_addresses()))
            print("En el móvil, usa la dirección de la red compartida, no 127.0.0.1.")
            print("Escribe 'pair' para vincular el teléfono; 'help' muestra las acciones.")
            queue = asyncio.Queue()
            loop = asyncio.get_running_loop()
            # A daemon reader lets quit/Ctrl+C finish without a blocked executor thread.
            import threading
            def reader():
                for line in sys.stdin:
                    with contextlib.suppress(RuntimeError):
                        loop.call_soon_threadsafe(queue.put_nowait, line.rstrip("\r\n"))
                with contextlib.suppress(RuntimeError):
                    loop.call_soon_threadsafe(queue.put_nowait, "quit")
            threading.Thread(target=reader, daemon=True).start()
            try:
                while True:
                    line = await queue.get()
                    command, _, value = line.partition(" ")
                    try:
                        if command == "quit":
                            break
                        if command in ("help", ""):
                            print(HELP)
                        elif command == "pair":
                            address = args.advertise or next((a for a in local_addresses() if a != "127.0.0.1"), "127.0.0.1")
                            payload = pairing_payload(server, fingerprint, address, args.port)
                            print("Comprueba la dirección y pega este bloque en Android:")
                            print(payload)
                            print("Estos datos autorizan la vinculación. No los compartas fuera de tus dispositivos.")
                            qr = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage)
                            page = directory / "pairing.html"
                            data = json.loads(payload)
                            manual_fields = "".join(
                                "<label>" + label + "<input readonly onclick='this.select()' value=\""
                                + html.escape(str(data[key]), quote=True) + "\"></label>"
                                for key, label in (("host", "Dirección IP del ordenador"), ("port", "Puerto"),
                                                   ("fingerprint", "Huella de seguridad"), ("code", "Código temporal")))
                            page.write_text("<!doctype html><html lang='es'><meta charset='utf-8'>"
                                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                                "<title>Vincular Clipboard AI</title><style>body{font:18px system-ui;"
                                "max-width:650px;margin:40px auto;padding:20px;text-align:center;background:#f6f8fb}"
                                "svg{width:min(100%,480px);height:auto;background:white}"
                                "label{display:block;text-align:left;margin:16px 0;font-weight:600}"
                                "input,textarea{display:block;box-sizing:border-box;width:100%;padding:12px;"
                                "margin-top:6px;font:15px monospace;border:1px solid #bbc8d5;border-radius:6px}</style>"
                                "<h1>Vincular tu teléfono</h1><p>En Clipboard AI pulsa Vincular → Escanear QR.</p>"
                                + qr.to_string(encoding="unicode") + "<p>Caduca en 5 minutos.</p><p>Red: "
                                + html.escape(address) + ":" + str(args.port) + "</p>"
                                "<p>Comprueba que esta dirección corresponde a la red de tu teléfono.</p>"
                                "<h2>Vincular sin cámara</h2><p>En el teléfono pulsa Vincular → Introducir datos y completa estos cuatro campos.</p>"
                                + manual_fields + "<h2>Pegar el bloque completo</h2>"
                                "<p>La opción Pegar bloque completo necesita todo el contenido siguiente, desde { hasta }. El código temporal por sí solo no basta.</p>"
                                "<textarea readonly rows='7' onclick='this.select()'>" + html.escape(payload)
                                + "</textarea></html>", encoding="utf-8")
                            print(f"QR de vinculación: {page}")
                            webbrowser.open(page.as_uri())
                        elif command == "send":
                            await server.publish(value)
                        elif command == "clip":
                            if not clipboard:
                                raise ProtocolError("Portapapeles no disponible")
                            await server.publish(clipboard.read())
                        elif command == "file":
                            path = Path(value.strip().strip('"')).expanduser()
                            await server.add_file(path)
                        elif command == "files":
                            for row in files.history():
                                item = row["item"]
                                percent = 100 if row["state"] == "delivered" else int(row["offset"] * 100 / max(1, item["size"]))
                                state = dict(pending="pendiente", sending="enviando", receiving="recibiendo", delivered="entregado", cancelled="cancelado", error="error").get(row["state"], row["state"])
                                direction = "PC → móvil" if row["direction"] == "out" else "móvil → PC"
                                print(f"{item['id'][:8]} {direction} {state} {percent}% {item['size']} bytes · {item['name']}")
                                if row["error"]: print("  " + row["error"])
                                if row["state"] == "delivered": print("  " + row["path"])
                            if server.sessions and not server.file_peers:
                                print("El teléfono conectado necesita la APK 0.2 para transferir archivos.")
                        elif command == "folder":
                            print(f"Entrada: {files.inbox}\nRecibidos: {files.received}")
                            if sys.platform == "win32": os.startfile(files.inbox)
                            else: webbrowser.open(files.inbox.as_uri())
                        elif command == "clearfiles":
                            count, size = files.delivered_usage()
                            if value == "confirm":
                                files.clear_delivered()
                                print(f"Borradas {count} copias locales ({size} bytes).")
                            else:
                                print(f"Se liberarían {size} bytes de {count} copias entregadas. Usa clearfiles confirm para borrarlas.")
                        elif command in ("cancel", "deletefile"):
                            (files.cancel if command == "cancel" else files.delete)(value.strip())
                            for ws in list(server.file_peers):
                                await server.offer_files(ws)
                        elif command == "list":
                            for item in store.history():
                                state = "entregado" if item["delivered"] else "pendiente"
                                print(f"{item['id'][:8]}  {state:10}  {len(item['text'])} caracteres  {item['created']}")
                        elif command in ("show", "copy", "delete"):
                            if command == "delete":
                                store.delete(value.strip())
                            else:
                                item = store.get(value.strip())
                                if command == "show":
                                    print(item["text"])
                                elif clipboard:
                                    clipboard.write(item["text"])
                                    print("Copiado.")
                                else:
                                    raise ProtocolError("Portapapeles no disponible")
                        elif command in ("auto", "receive") and value in ("on", "off"):
                            if not clipboard:
                                raise ProtocolError("Portapapeles no disponible")
                            if command == "auto":
                                clipboard._last = clipboard.revision()
                            setattr(server, "auto_send" if command == "auto" else "auto_receive", value == "on")
                            print(f"{command}: {value}")
                        elif command == "peers":
                            print(json.dumps(store.peers(), ensure_ascii=False, indent=2))
                        elif command == "revoke":
                            print("Revocado." if await server.revoke(value.strip()) else "No encontrado.")
                        elif command == "status":
                            print(f"Conectados: {len(server.sessions)}; pendientes: {store.pending_count()}; "
                                  f"envío automático: {server.auto_send}; copiado recibido: {server.auto_receive}")
                            pending_files = files.db.execute("SELECT COUNT(*) FROM files WHERE state IN ('pending','sending','receiving')").fetchone()[0]
                            print(f"Archivos pendientes: {pending_files}; espacio del dock: {files.used()} bytes (máximo 1 GiB).")
                        else:
                            print("Acción desconocida. Escribe help.")
                    except (ProtocolError, OSError, ValueError, RuntimeError) as exc:
                        print(f"No se pudo completar: {exc}")
            finally:
                watcher.cancel()
                file_watcher.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watcher
                with contextlib.suppress(asyncio.CancelledError):
                    await file_watcher
    finally:
        store.close()
        files.close()


def main():
    parser = argparse.ArgumentParser(description="Dock local de texto para Windows/Android")
    parser.add_argument("--bind", default="0.0.0.0", help="Dirección donde escuchar")
    parser.add_argument("--port", type=int, default=45821)
    parser.add_argument("--advertise", help="IP local que se incluirá en la vinculación")
    parser.add_argument("--data-dir", type=Path, help="Carpeta local de datos (opcional)")
    args = parser.parse_args()
    try:
        # Avoid Proactor TLS shutdown hangs after an Android socket is cancelled on Windows.
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop if os.name == "nt" else None) as runner:
            runner.run(run(args))
    except KeyboardInterrupt:
        print("\nCerrado.")
    except OSError as exc:
        parser.exit(1, f"No se pudo iniciar: {exc}\n")


if __name__ == "__main__":
    main()
