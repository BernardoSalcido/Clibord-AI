import base64
import hashlib
import json
import uuid

import pytest

from clipboard_ai.files import FileDock, CHUNK, MAX_FILE, metadata
from clipboard_ai.protocol import ProtocolError


def transfer(a, b, item):
    reply = b.handle(dict(type="file_offer", file=item), a.device)
    while reply and reply["type"] != "file_done":
        chunk = a.handle(reply, b.device)
        reply = b.handle(chunk, a.device)
    a.handle(reply, b.device)


@pytest.fixture
def docks(tmp_path):
    a = FileDock(tmp_path / "a", str(uuid.uuid4()))
    b = FileDock(tmp_path / "b", str(uuid.uuid4()))
    yield a, b
    a.close(); b.close()


@pytest.mark.parametrize("content", [b"", bytes(range(256)) * 800, "Árbol ñ 🧪\n".encode()], ids=["empty", "binary", "unicode"])
def test_exact_transfer_and_deleted_receipt(docks, tmp_path, content):
    a, b = docks
    source = tmp_path / "Prueba á.bin"; source.write_bytes(content)
    item = a.add(source)
    source.write_bytes(b"original changed")
    transfer(a, b, item)
    assert a.get(item["id"])["state"] == "delivered"
    row = b.get(item["id"])
    from pathlib import Path
    assert Path(row["path"]).read_bytes() == content
    b.delete(item["id"])
    assert not Path(row["path"]).exists()
    assert b.accept(item, a.device)["type"] == "file_done"
    assert b.history() == []
    assert source.read_bytes() == b"original changed"


def test_clipboard_capture_is_durable_image_and_queued_for_transfer(docks):
    from pathlib import Path
    a, b = docks
    picture = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==")
    item = a.save_capture(picture)
    row = a.get(item["id"])
    assert item["mime"] == "image/png"
    assert (row["direction"], row["state"]) == ("out", "pending")
    assert Path(row["path"]).read_bytes() == picture
    assert a.offers()[0]["file"]["id"] == item["id"]
    root, device = a.root, a.device
    a.close(); a.__init__(root, device)
    assert a.history()[0]["id"] == item["id"]
    transfer(a, b, item)
    assert Path(b.get(item["id"])["path"]).read_bytes() == picture
    a.delete(item["id"])
    assert a.history() == [] and not Path(row["path"]).exists()


def test_brain_relays_received_image_to_another_device(tmp_path):
    from pathlib import Path
    brain = FileDock(tmp_path / "brain", str(uuid.uuid4()))
    phone = FileDock(tmp_path / "phone", str(uuid.uuid4()))
    tablet = FileDock(tmp_path / "tablet", str(uuid.uuid4()))
    picture = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==")
    source = tmp_path / "captura.png"; source.write_bytes(picture)
    try:
        item = phone.add(source)
        transfer(phone, brain, item)
        brain.subscribe_peer(tablet.device, relay=True)
        assert brain.offers(tablet.device)[0]["file"]["origin"] == phone.device
        reply = tablet.handle(brain.offers(tablet.device)[0], brain.device, relayed=True)
        while reply["type"] != "file_done":
            reply = tablet.handle(brain.handle(reply, tablet.device), brain.device, relayed=True)
        brain.handle(reply, tablet.device)
        assert brain.offers(tablet.device) == []
        assert Path(tablet.get(item["id"])["path"]).read_bytes() == picture
    finally:
        brain.close(); phone.close(); tablet.close()


def test_restart_resume_replays_only_committed_bytes(docks, tmp_path):
    a, b = docks
    source = tmp_path / "resume.bin"; source.write_bytes(b"abc" * CHUNK)
    item = a.add(source)
    accept = b.accept(item, a.device)
    chunk = a.send_chunk(accept)
    progress = b.chunk(chunk, a.device)
    assert progress["offset"] == CHUNK
    assert b.chunk(chunk, a.device) == progress
    from pathlib import Path
    part = Path(b.get(item["id"])["path"])
    with part.open("ab") as stream: stream.write(b"uncommitted")
    root, device = b.root, b.device
    b.close(); b.__init__(root, device)
    assert b.accept(item, a.device)["offset"] == CHUNK
    assert part.stat().st_size == CHUNK
    transfer(a, b, item)
    assert Path(b.get(item["id"])["path"]).read_bytes() == source.read_bytes()


def test_integrity_failure_cancel_and_cancel_before_offer(docks, tmp_path):
    a, b = docks
    source = tmp_path / "test.bin"; source.write_bytes(b"hello")
    item = a.add(source)
    accept = b.accept(item, a.device)
    chunk = a.send_chunk(accept); chunk["data"] = base64.b64encode(b"other").decode()
    with pytest.raises(ProtocolError, match="huella"): b.chunk(chunk, a.device)
    a.cancel(item["id"])
    ack = b.handle(a.notices()[0], a.device)
    a.handle(ack, b.device)
    assert not a.notices()
    assert b.get(item["id"])["state"] == "cancelled"
    item2 = a.add(source); a.cancel(item2["id"])
    ack = b.handle(a.notices()[0], a.device); a.handle(ack, b.device)
    assert b.accept(item2, a.device)["type"] == "file_cancel"


@pytest.mark.parametrize("name", ["../bad", "C:\\bad", "CON.txt", "nul", "a/b", "test.", "bad\nname"])
def test_unsafe_name_and_bounds(docks, name):
    a, _ = docks
    raw = dict(id=str(uuid.uuid4()), origin=a.device, created="", name=name, size=1, sha256="0"*64, mime="")
    with pytest.raises(ProtocolError): metadata(raw, a.device)


def test_quota_wrong_origin_offset_and_duplicate_collision(docks, tmp_path, monkeypatch):
    a, b = docks
    source = tmp_path / "a.bin"; source.write_bytes(b"a" * (CHUNK + 2))
    item = a.add(source)
    monkeypatch.setattr("clipboard_ai.files.QUOTA", 1)
    with pytest.raises(ProtocolError, match="lleno"): b.accept(item, a.device)
    monkeypatch.setattr("clipboard_ai.files.QUOTA", 1024**3)
    with pytest.raises(ProtocolError, match="Origen"): b.accept(item, str(uuid.uuid4()))
    accept = b.accept(item, a.device)
    chunk = a.send_chunk(accept)
    bad = dict(chunk, offset=True)
    with pytest.raises(ProtocolError): b.chunk(bad, a.device)
    b.chunk(chunk, a.device)
    bad = dict(chunk, data=base64.b64encode(b"b" * CHUNK).decode())
    with pytest.raises(ProtocolError, match="duplicado"): b.chunk(bad, a.device)
    with pytest.raises(ProtocolError, match="reutilizado"): b.accept(dict(item, name="other.bin"), a.device)
    with pytest.raises(ProtocolError): metadata(dict(item, size=MAX_FILE+1), a.device)
    assert b.handle(dict(type="file_error", id=str(uuid.uuid4())), a.device) is None


def test_two_equal_names_are_distinct(docks, tmp_path):
    a, b = docks
    source = tmp_path / "same.pdf"; source.write_bytes(b"one")
    first = a.add(source); transfer(a, b, first)
    source.write_bytes(b"two")
    second = a.add(source); transfer(a, b, second)
    assert b.get(first["id"])["path"] != b.get(second["id"])["path"]


def test_watched_folder_queues_once_and_survives_restart(tmp_path):
    import asyncio
    from clipboard_ai.server import DockServer
    from clipboard_ai.store import Store
    async def scenario():
        store = Store(tmp_path / "text.db")
        files = FileDock(tmp_path / "Dock", store.device)
        server = DockServer(store, files=files, notify=lambda _: None)
        path = files.inbox / "document.pdf"; path.write_bytes(b"first")
        task = asyncio.create_task(server.watch_files())
        async def wait_count(count):
            for _ in range(60):
                if len(files.history()) == count: return
                await asyncio.sleep(.1)
            pytest.fail("La carpeta no incorporó el archivo")
        try:
            await wait_count(1)
            await asyncio.sleep(1.2)
            assert len(files.history()) == 1
            path.write_bytes(b"second-version")
            await wait_count(2)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            task = asyncio.create_task(server.watch_files())
            await asyncio.sleep(2.2)
            assert len(files.history()) == 2
            assert files.delivered_usage() == (0, 0)
            assert path.read_bytes() == b"second-version"
        finally:
            task.cancel(); await asyncio.gather(task, return_exceptions=True)
            files.close(); store.close()
    asyncio.run(asyncio.wait_for(scenario(), 16))


def test_cleanup_usage_and_cancelled_hidden_receipt(docks, tmp_path):
    a, b = docks
    source = tmp_path / "source.bin"; source.write_bytes(b"test")
    item = a.add(source); transfer(a, b, item)
    assert a.delivered_usage() == b.delivered_usage() == (1, 4)
    a.clear_delivered(); b.clear_delivered()
    assert a.used() == b.used() == 0
    item2 = a.add(source); a.cancel(item2["id"]); a.delete(item2["id"])
    assert not a.history()
    assert a.notices()[0]["id"] == item2["id"]
    assert source.read_bytes() == b"test"


def test_tls_negotiation_old_client_and_file_error_preserve_text(tmp_path):
    import asyncio
    import ssl
    from websockets.asyncio.client import connect
    from clipboard_ai.security import tls_identity
    from clipboard_ai.server import DockServer
    from clipboard_ai.store import Store
    from clipboard_ai.protocol import encode, decode
    async def scenario():
        store = Store(tmp_path / "text.db")
        files = FileDock(tmp_path / "Dock", store.device)
        server = DockServer(store, files=files, notify=lambda _: None)
        peer = str(uuid.uuid4()); token = store.pair(peer, "test")
        context, _ = tls_identity(tmp_path)
        trusted = ssl.create_default_context(cafile=str(tmp_path / "server.pem")); trusted.check_hostname = False
        source = tmp_path / "queued.pdf"; source.write_bytes(b"pending")
        files.add(source)
        try:
            async with server.listen("127.0.0.1", 0, context) as listener:
                url = f"wss://127.0.0.1:{listener.sockets[0].getsockname()[1]}"
                async with connect(url, ssl=trusted, proxy=None) as ws:
                    await ws.send(encode("hello", device=peer, token=token))
                    assert "files-v1" in decode(await ws.recv())["capabilities"]
                    assert decode(await ws.recv())["type"] == "ready"
                    await ws.send(encode("ready"))
                    await ws.send(encode("item", item=dict(id=str(uuid.uuid4()), origin=peer, seq=1, created="now", text="old client")))
                    assert decode(await ws.recv())["type"] == "ack"
                    assert not server.file_peers
                async with connect(url, ssl=trusted, proxy=None) as ws:
                    await ws.send(encode("hello", device=peer, token=token, capabilities=["files-v1"]))
                    assert decode(await ws.recv())["type"] == "welcome"
                    assert decode(await ws.recv())["type"] == "ready"
                    await ws.send(encode("ready"))
                    assert decode(await ws.recv())["type"] == "file_offer"
                    bad = dict(id=str(uuid.uuid4()), origin=peer, created="", name="../bad", size=0,
                               sha256=hashlib.sha256(b"").hexdigest(), mime="application/octet-stream")
                    await ws.send(encode("file_offer", file=bad))
                    assert decode(await ws.recv())["type"] == "file_error"
                    await ws.send(encode("item", item=dict(id=str(uuid.uuid4()), origin=peer, seq=2, created="now", text="after error")))
                    assert decode(await ws.recv())["type"] == "ack"
                    assert len(store.history()) == 2
        finally: files.close(); store.close()
    asyncio.run(asyncio.wait_for(scenario(), 15))
