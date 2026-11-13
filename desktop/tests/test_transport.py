import asyncio
import json
import ssl
import uuid

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from clipboard_ai.protocol import decode, encode
from clipboard_ai.security import tls_identity
from clipboard_ai.server import DockServer
from clipboard_ai.store import Store


class FakeClipboard:
    def __init__(self):
        self.writes = []

    def write(self, text):
        self.writes.append(text)


def test_real_tls_pair_send_retry_restart_boundary_and_revocation(tmp_path):
    async def scenario():
        store = Store(tmp_path / "dock.db")
        clipboard = FakeClipboard()
        server = DockServer(store, clipboard, lambda _: None)
        server.auto_receive = True
        context, fingerprint = tls_identity(tmp_path)
        trusted = ssl.create_default_context(cafile=str(tmp_path / "server.pem"))
        trusted.check_hostname = False  # Test trusts this exact local self-signed certificate.
        peer = str(uuid.uuid4())
        async with server.listen("127.0.0.1", 0, context) as listener:
            port = listener.sockets[0].getsockname()[1]
            url = f"wss://127.0.0.1:{port}"
            async with connect(url, ssl=trusted, proxy=None) as ws:
                await ws.send(encode("hello", device=peer, token="incorrecto"))
                assert decode(await ws.recv())["type"] == "error"
            code = server.pairing.open()
            async with connect(url, ssl=trusted, proxy=None) as ws:
                await ws.send(encode("pair", device=peer, code=code, name="OnePlus"))
                paired = decode(await ws.recv())
                assert paired["type"] == "paired"
                token = paired["token"]
            old = store.create("  previo\n🧪 ")
            async with connect(url, ssl=trusted, proxy=None) as ws:
                await ws.send(encode("hello", device=peer, token=token))
                assert decode(await ws.recv())["type"] == "welcome"
                backlog = decode(await ws.recv())
                assert backlog["item"] == old and backlog["live"] is False
                assert decode(await ws.recv())["type"] == "ready"
                await ws.send(encode("ack", id=old["id"]))
                incoming = dict(id=str(uuid.uuid4()), origin=peer, seq=1, created="now", text="móvil á\n ")
                # A fresh incoming item becomes the Windows clipboard even during reconnect.
                await ws.send(encode("item", item=incoming, live=True))
                assert decode(await ws.recv())["type"] == "ack"
                assert clipboard.writes == ["móvil á\n "]
                await ws.send(encode("ready"))
                await ws.send(encode("item", item=incoming, live=True))
                assert decode(await ws.recv())["type"] == "ack"
                assert clipboard.writes == ["móvil á\n "]
                incoming = dict(incoming, id=str(uuid.uuid4()), seq=2, text="nuevo")
                await ws.send(encode("item", item=incoming, live=False))
                assert decode(await ws.recv())["type"] == "ack"
                await asyncio.sleep(0)
                assert clipboard.writes == ["móvil á\n ", "nuevo"]
                item = await server.publish("ordenador → teléfono")
                message = decode(await ws.recv())
                assert message["item"] == item and message["live"] is True
                await ws.send(encode("ack", id=item["id"]))
                await ws.send(encode("unknown"))
                assert decode(await ws.recv())["type"] == "error"
                assert not store.pending()
                assert await server.revoke(peer)
                with pytest.raises(ConnectionClosed):
                    await ws.recv()
            async with connect(url, ssl=trusted, proxy=None) as ws:
                await ws.send(encode("hello", device=peer, token=token))
                assert decode(await ws.recv())["type"] == "error"
        store.close()
    asyncio.run(asyncio.wait_for(scenario(), timeout=25))


def test_wrong_server_certificate_rejected(tmp_path):
    async def scenario():
        store = Store(tmp_path / "dock.db")
        context, _ = tls_identity(tmp_path)
        server = DockServer(store, notify=lambda _: None)
        async with server.listen("127.0.0.1", 0, context) as listener:
            port = listener.sockets[0].getsockname()[1]
            with pytest.raises(ssl.SSLCertVerificationError):
                async with connect(f"wss://127.0.0.1:{port}", ssl=ssl.create_default_context(), proxy=None):
                    pass
        store.close()
    asyncio.run(asyncio.wait_for(scenario(), timeout=25))


def test_watcher_suppresses_own_write_but_allows_same_text_later():
    # Exercise the real Windows adapter logic without touching the user's clipboard.
    from clipboard_ai.clipboard import Clipboard
    clipboard = object.__new__(Clipboard)
    revision = [1]
    clipboard.revision = lambda: revision[0]
    clipboard.read = lambda: "mismo texto"
    clipboard._last = 1
    assert clipboard.changed() is None
    revision[0] += 1
    assert clipboard.changed() == "mismo texto"
    assert clipboard.changed() is None
    # An adapter write records its resulting revision, as write() does.
    revision[0] += 1
    clipboard._last = clipboard.revision()
    assert clipboard.changed() is None
    revision[0] += 1
    assert clipboard.changed() == "mismo texto"


def test_brain_relays_phone_text_to_second_device_without_echo(tmp_path):
    async def scenario():
        async def next_type(ws, kind):
            while True:
                value = decode(await ws.recv())
                if value["type"] == kind:
                    return value
        store = Store(tmp_path / "dock.db")
        brain = DockServer(store, notify=lambda _: None)
        first, second = str(uuid.uuid4()), str(uuid.uuid4())
        tokens = {peer: store.pair(peer, peer) for peer in (first, second)}
        context, _ = tls_identity(tmp_path)
        trusted = ssl.create_default_context(cafile=str(tmp_path / "server.pem")); trusted.check_hostname = False
        try:
            async with brain.listen("127.0.0.1", 0, context) as listener:
                url = f"wss://127.0.0.1:{listener.sockets[0].getsockname()[1]}"
                async with connect(url, ssl=trusted, proxy=None) as a, connect(url, ssl=trusted, proxy=None) as b:
                    for ws, peer in ((a, first), (b, second)):
                        await ws.send(encode("hello", device=peer, token=tokens[peer], capabilities=["hub-v2"]))
                        assert decode(await ws.recv())["type"] == "welcome"
                        assert decode(await ws.recv())["type"] == "ready"
                        await ws.send(encode("ready"))
                    item = dict(id=str(uuid.uuid4()), origin=first, seq=1, created="now", text="Desde móvil")
                    await a.send(encode("item", item=item, live=True))
                    assert (await next_type(a, "ack"))["type"] == "ack"
                    forwarded = await next_type(b, "item")
                    assert forwarded["item"] == item and forwarded["live"] is True
                    await b.send(encode("ack", id=item["id"]))
                    await asyncio.sleep(.05)
                    assert store.pending(peer=second) == []
                    assert store.pending(peer=first) == []
        finally:
            store.close()
    asyncio.run(asyncio.wait_for(scenario(), 15))
