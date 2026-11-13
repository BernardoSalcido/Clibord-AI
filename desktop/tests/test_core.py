import json
from pathlib import Path
import uuid

import pytest

from clipboard_ai.protocol import MAX_TEXT, ProtocolError, decode, validate_item
from clipboard_ai.security import Pairing
from clipboard_ai.store import Store

FIXTURE = Path(__file__).resolve().parents[2] / "protocol/fixtures/unicode.json"


def incoming(text="texto", seq=1, origin=None):
    return dict(id=str(uuid.uuid4()), origin=origin or str(uuid.uuid4()), seq=seq,
                created="2026-10-15T12:00:00Z", text=text)


def test_unicode_fixture_persists_exactly_and_deduplicates(tmp_path):
    msg = decode(FIXTURE.read_text(encoding="utf-8"))
    item = validate_item(msg["item"])
    path = tmp_path / "dock.db"
    store = Store(path)
    assert store.receive(item, item["origin"])
    assert not store.receive(item, item["origin"])
    identity = store.device
    store.close()
    store = Store(path)
    assert store.device == identity
    assert store.history()[0]["text"] == item["text"]
    assert not store.receive(item, item["origin"])
    store.close()


def test_outbox_survives_restart_and_ack_is_idempotent(tmp_path):
    path = tmp_path / "dock.db"
    store = Store(path)
    first = store.create("  mensaje\n ")
    store.close()
    store = Store(path)
    assert store.pending() == [first]
    store.acknowledge(first["id"])
    store.acknowledge(first["id"])
    assert not store.pending()
    second = store.create("otra vez")
    assert second["seq"] == first["seq"] + 1
    store.close()


def test_conflicting_id_and_sequence_rejected(tmp_path):
    store = Store(tmp_path / "dock.db")
    item = incoming()
    store.receive(item, item["origin"])
    for changed in [dict(item, text="distinto"), dict(item, id=str(uuid.uuid4()))]:
        with pytest.raises(ProtocolError):
            store.receive(changed, item["origin"])
    store.close()


def test_history_pruning_and_deletion_do_not_reanimate_retries(tmp_path):
    store = Store(tmp_path / "dock.db")
    first = incoming()
    store.receive(first, first["origin"])
    for seq in range(2, 503):
        store.receive(incoming(seq=seq, origin=first["origin"]), first["origin"])
    assert len(store.history(1000)) == 500
    assert not store.receive(first, first["origin"])
    last = store.history()[0]
    store.delete(last["id"])
    assert not store.receive(Store.wire(last), last["origin"])
    assert len(store.history(1000)) == 499
    store.close()


def test_pending_limit_requires_explicit_deletion(tmp_path):
    store = Store(tmp_path / "dock.db")
    for _ in range(500):
        store.create("pendiente")
    with pytest.raises(ProtocolError, match="500"):
        store.create("otro")
    assert len(store.pending()) == 500
    pending_id = store.pending()[0]["id"]
    store.delete(pending_id)
    assert store.pending_count() == 499
    store.create("otro")
    assert store.pending_count() == 500
    store.close()


def test_clear_texts_removes_duplicates_and_outbox_but_preserves_receipts(tmp_path):
    store = Store(tmp_path / "dock.db")
    original = incoming()
    store.receive(original, original["origin"])
    store.create("repetido")
    store.create("repetido")
    assert store.clear_texts() == 3
    assert store.history() == [] and store.pending_count() == 0
    assert not store.receive(original, original["origin"])
    store.close()


@pytest.mark.parametrize("change", [dict(text=""), dict(text="é" * (MAX_TEXT // 2 + 1)),
    dict(seq=True), dict(seq=0), dict(seq=2**53), dict(id="mal"), dict(created=1),
    dict(text="\ud800"), dict(created="\ud800")])
def test_invalid_items(change):
    with pytest.raises(ProtocolError):
        validate_item(dict(incoming(), **change))


@pytest.mark.parametrize("raw", ['[]', '{"v":true,"type":"ready"}', '{"v":2,"type":"ready"}', '{}', 'not-json', b'bytes'])
def test_bad_envelopes(raw):
    with pytest.raises(ProtocolError):
        decode(raw)


def test_pair_code_one_use_expiry_and_attempt_limit():
    pairing = Pairing()
    code = pairing.open()
    assert pairing.consume(code)
    assert not pairing.consume(code)
    code = pairing.open()
    pairing.deadline = 0
    assert not pairing.consume(code)
    code = pairing.open()
    for _ in range(5):
        assert not pairing.consume("incorrecto")
    assert not pairing.consume(code)


def test_authentication_revocation(tmp_path):
    store = Store(tmp_path / "dock.db")
    peer = str(uuid.uuid4())
    token = store.pair(peer, "OnePlus")
    assert store.authenticate(peer, token)
    assert not store.authenticate(peer, "bad")
    second = str(uuid.uuid4())
    second_token = store.pair(second, "Segundo")
    assert store.authenticate(second, second_token)
    assert store.revoke(peer)
    assert not store.authenticate(peer, token)
    assert store.authenticate(second, second_token)
    store.close()


def test_multi_peer_delivery_survives_restart_and_acks_separately(tmp_path):
    path = tmp_path / "dock.db"
    store = Store(path)
    phone, tablet = str(uuid.uuid4()), str(uuid.uuid4())
    store.pair(phone, "Phone"); store.pair(tablet, "Tablet")
    item = store.create("Copied on Windows")
    assert store.pending(peer=phone) == [item]
    assert store.pending(peer=tablet) == [item]
    store.acknowledge(item["id"], phone)
    assert store.pending(peer=phone) == []
    assert store.pending(peer=tablet) == [item]
    store.close()
    store = Store(path)
    assert store.pending(peer=tablet) == [item]
    store.acknowledge(item["id"], tablet)
    assert store.pending_count() == 0
    received = dict(id=str(uuid.uuid4()), origin=phone, seq=1, created="now", text="From phone")
    assert store.receive(received, phone)
    assert store.pending(peer=phone) == []
    assert store.pending(peer=tablet) == [received]
    store.close()
