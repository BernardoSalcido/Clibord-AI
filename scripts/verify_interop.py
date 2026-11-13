"""Run the actual Kotlin network code against Python; no phone required."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / ".deps"), str(ROOT / "desktop/src")]

from clipboard_ai.security import tls_identity
from clipboard_ai.server import DockServer
from clipboard_ai.store import Store
from clipboard_ai.files import FileDock, CHUNK


async def main():
    background = "--background" in sys.argv
    file_test = "--files" in sys.argv
    directory = ROOT / ".test-data" / ("interop-" + str(uuid.uuid4()))
    directory.mkdir(parents=True)
    store = Store(directory / "dock.db")
    tls, pin = tls_identity(directory)
    files = FileDock(directory / "Dock", store.device) if file_test else None
    server = DockServer(store, notify=lambda _: None, files=files)
    interrupted = False
    resumed = False
    if file_test:
        original_handler = server.file_message
        async def interrupt_transfer(ws, msg, peer):
            nonlocal interrupted, resumed
            if msg["type"] == "file_offer" and interrupted:
                try:
                    if files.get(msg["file"]["id"])["offset"] >= CHUNK:
                        resumed = True
                except ValueError:
                    pass
            await original_handler(ws, msg, peer)
            if msg["type"] == "file_chunk" and not interrupted:
                interrupted = True
                await ws.close(1012, "Corte de red de prueba")
        server.file_message = interrupt_transfer
        download = directory / "Desde Windows ñ.bin"
        download.write_bytes(bytes(range(256)) * 1800)
        download_item = files.add(download)
    text = json.loads((ROOT / "protocol/fixtures/unicode.json").read_text(encoding="utf-8"))["item"]["text"]
    store.create(text)
    config = json.loads((ROOT / ".tools/android-env.json").read_text(encoding="utf-8"))
    env = os.environ.copy()
    env.update(JAVA_HOME=config["java"], ANDROID_HOME=config["sdk"],
               GRADLE_USER_HOME=str(ROOT / ".tools/gradle-home"),
               ANDROID_USER_HOME=str(ROOT / ".tools/android-home"))
    async with server.listen("127.0.0.1", 0, tls) as listener:
        port = listener.sockets[0].getsockname()[1]
        config_file = directory / "connection.json"
        details = dict(url=f"https://127.0.0.1:{port}", fingerprint=pin, code=server.pairing.open(), text=text)
        if file_test: details["downloadHash"] = download_item["sha256"]
        config_file.write_text(json.dumps(details), encoding="utf-8")
        env["CLIPBOARD_AI_FILES_TEST" if file_test else "CLIPBOARD_AI_BACKGROUND_TEST" if background else "CLIPBOARD_AI_INTEROP"] = str(config_file)
        async def send_after_screen_off():
            while not any(item["text"] == "request-after-screen-off" for item in store.history()):
                await asyncio.sleep(0.05)
            await server.publish(text + "\nCon la pantalla apagada")
        sender = asyncio.create_task(send_after_screen_off()) if background else None
        gradle_home = Path(config["gradle"]).parent.parent
        launcher = next((gradle_home / "lib").glob("gradle-gradle-cli-main-*.jar"))
        args = [str(Path(config["java"]) / "bin/java.exe"), "-classpath", str(launcher),
                "org.gradle.launcher.GradleMain", "--no-daemon", "--console=plain", "-p", str(ROOT / "android"),
                "testDebugUnitTest", "--tests", "*FileTransferInteropTest" if file_test else "*BackgroundConnectionTest" if background else "*DesktopInteropTest", "--rerun-tasks"]
        try:
            result = await asyncio.to_thread(subprocess.run, args, env=env, cwd=ROOT, timeout=240)
        finally:
            if sender:
                sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)
        if result.returncode:
            raise RuntimeError("Falló la prueba Kotlin/Python")
        assert store.pending_count() == 0
        history = store.history()
        if file_test:
            assert interrupted and resumed, "Debe reanudar desde progreso persistido tras el corte"
            rows = files.history()
            assert len(rows) == 2 and all(row["state"] == "delivered" for row in rows)
            upload = next(row for row in rows if row["direction"] == "in")
            assert Path(upload["path"]).read_bytes() == bytes(i % 251 for i in range(380_123))
            assert len(history) == 2 and all(item["text"] == text for item in history)
            assert not server.sessions
            print("Archivos Android/Python verificados: ambos sentidos, integridad, corte, reanudación y texto.")
        elif background:
            assert len(history) == 3
            assert {item["text"] for item in history} == {text, "request-after-screen-off", text + "\nCon la pantalla apagada"}
            assert not server.sessions, "Pausar debe cerrar la conexión real"
            print("Servicio Android/Python verificado: recepción y confirmación sin Activity, reapertura y pausa.")
        else:
            assert len(history) == 2 and all(item["text"] == text for item in history)
            print("Interoperabilidad Kotlin/Python verificada: TLS fijado, vinculación, Unicode y duplicados.")
    store.close()
    if files: files.close()


if __name__ == "__main__":
    # Windows Proactor can leave a TLS close waiter unresolved after a forced peer reset.
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop if os.name == "nt" else None) as runner:
        runner.run(main())
