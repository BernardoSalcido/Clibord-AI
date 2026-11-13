"""AI contracts, streaming failure boundaries, automatic modes and clipboard races."""
import asyncio
import base64
from dataclasses import replace
import json
import re
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

from clipboard_ai.ai import (AIConfig, AIError, CONTRACT, END, LocalAI, START,
    extract_ocr_result, extract_result, format_math_blocks, resize_image_for_ocr)
from clipboard_ai.store import Store


def wrapped(value):
    return f"Introduction\n{START}\n{value}\n{END}\nConclusion"


def sample_png():
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage
    image = QImage(16, 16, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    buffer = QBuffer(); buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(buffer.data())


def test_result_preserves_markdown_math_code_and_indentation():
    value = "# Título\n\n| a | b |\n|---|---|\n| $x_1$ | 2 |\n\n```python\n    print('a')\n```\n"
    assert extract_result(wrapped(value)) == value


@pytest.mark.parametrize("source,expected", [
    ("$$E=mc^2$$", "$$\nE=mc^2\n$$"),
    ("$$\nE=mc^2\n$$", "$$\nE=mc^2\n$$"),
    (r"\[x_1 + x_2\]", "$$\nx_1 + x_2\n$$"),
    (r"\(x\)", "$$\nx\n$$"),
    ("$x$", "$$\nx\n$$"),
    ("# Título\n\n$$x$$\n\nTexto", "# Título\n\n$$\nx\n$$\n\nTexto"),
    ("Cost $5 and $10.\n", "Cost $5 and $10.\n"),
    ("`$x$`\n```tex\n$$y$$\n```\n\nTexto\n", "`$x$`\n```tex\n$$y$$\n```\n\nTexto\n"),
    ("`code`$x$", "`code`\n$$\nx\n$$"),
])
def test_math_output_uses_separate_delimiter_lines_and_preserves_other_markdown(source, expected):
    result = format_math_blocks(source)
    assert result == expected
    assert format_math_blocks(result) == result


@pytest.mark.parametrize("raw", ["hello", START + "partial", END + START,
    START + END, wrapped(""), wrapped("text") + START, wrapped("a\0b")])
def test_invalid_output_never_becomes_a_clipboard_result(raw):
    with pytest.raises(AIError): extract_result(raw)


def test_ocr_accepts_finished_unframed_equation_but_not_incomplete_output():
    # Bionic returned exactly this shape for the user's 325 x 75 equation image.
    equation = r"$$\hat { H } = \sum _ { n , s } (\varepsilon _ 2 c ^ \dagger c - \varepsilon _ 1 d ^ \dagger d)$$"
    stats = dict(input_tokens=288, total_output_tokens=82)
    assert format_math_blocks(extract_ocr_result(equation, stats, 2048)).startswith("$$\n\\hat")
    assert extract_ocr_result("El texto en la imagen es:\n```markdown\n" + equation + "\n```", stats, 2048) == equation
    assert extract_ocr_result(wrapped(equation), stats, 2048) == equation
    for raw, counts in ((START + "\npartial", stats),
                        (equation, dict(input_tokens=1908, total_output_tokens=140)),
                        ("El texto en la imagen es: " + equation, stats)):
        with pytest.raises(AIError): extract_ocr_result(raw, counts, 2048)


def test_ocr_resolution_limit_preserves_small_image_and_original_pixels():
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage
    image = QImage(1600, 800, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    buffer = QBuffer(); buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    original = bytes(buffer.data())
    reduced = resize_image_for_ocr(original, 1280)
    assert QImage.fromData(reduced).size().toTuple() == (1280, 640)
    assert QImage.fromData(original).size().toTuple() == (1600, 800)
    assert resize_image_for_ocr(original, 0) == original
    assert resize_image_for_ocr(original, 2048) == original


def test_ocr_sends_downscaled_copy_to_api_without_mutating_original():
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage
    image = QImage(1600, 800, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    buffer = QBuffer(); buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    original = bytes(buffer.data())
    sent_sizes = []

    async def scenario():
        def handler(request):
            if request.method == "GET":
                return httpx.Response(200, json=dict(models=[dict(key="qwen/qwen3.5-9b",
                    capabilities=dict(vision=True, reasoning=dict(allowed_options=["off"])),
                    loaded_instances=[dict(id="qwen")])]))
            payload = json.loads(request.content)
            sent = base64.b64decode(payload["input"][1]["data_url"].split(",", 1)[1])
            sent_sizes.append(QImage.fromData(sent).size().toTuple())
            return httpx.Response(200, text="data: " + json.dumps(dict(type="chat.end", result=dict(
                output=[dict(type="message", content="Recognized text")],
                stats=dict(input_tokens=100, total_output_tokens=20)))) + "\n\n")

        client = LocalAI(AIConfig(autostart=False, image_max_edge=1280), transport=httpx.MockTransport(handler))
        client.warmed = "qwen"
        try:
            result, _ = await client.process("image", "", original)
            assert result == "Recognized text"
            assert sent_sizes == [(1280, 640)]
            assert QImage.fromData(original).size().toTuple() == (1600, 800)
        finally:
            await client.close()
    asyncio.run(scenario())


def test_settings_roundtrip_prompts_modes_and_invalid_endpoint(tmp_path):
    config = AIConfig(endpoint="http://127.0.0.1:1235", image=True, text_mode="grammar", image_max_edge=1024)
    config.prompts["grammar"] = "Custom grammar contract."
    config.save(tmp_path)
    assert AIConfig.load(tmp_path) == config
    assert not list(tmp_path.glob("*.tmp"))
    for endpoint in ("ftp://localhost", "http://user:pass@localhost", "http://localhost/v1", "http://localhost?secret=x"):
        with pytest.raises(AIError): replace(config, endpoint=endpoint).validate()


def stream_response(value="Clean text", error=False, truncate=False, missing_end=False):
    events = [dict(type="chat.start"), dict(type="reasoning.delta", content="IGNORE THIS")]
    if error: events.append(dict(type="error", error=dict(message="internal")))
    events.append(dict(type="chat.end", result=dict(output=[dict(type="reasoning", content="PRIVATE"),
        dict(type="message", content=wrapped(value))], stats=dict(total_output_tokens=1024 if truncate else 20))))
    if missing_end: events.pop()
    return httpx.Response(200, text="".join("data: " + json.dumps(event) + "\n\n" for event in events),
                          headers={"content-type": "text/event-stream"})


@pytest.mark.parametrize("failure", [None, "error", "truncate", "missing_end", "unauthorized"])
def test_native_api_stream_contract_and_failure_boundaries(failure):
    async def scenario():
        calls = []
        def handler(request):
            calls.append(request)
            if request.method == "GET":
                if failure == "unauthorized": return httpx.Response(401)
                return httpx.Response(200, json=dict(models=[dict(key="qwen/qwen3.5-9b", capabilities=dict(vision=True,
                    reasoning=dict(allowed_options=["off", "on"])), loaded_instances=[dict(id="loaded-qwen")])]))
            payload = json.loads(request.content)
            assert payload["store"] is False and payload["integrations"] == [] and payload["reasoning"] == "off"
            assert "previous_response_id" not in payload
            if "Preparación interna." in str(payload["input"]): return stream_response("OK")
            assert CONTRACT in payload["system_prompt"]
            return stream_response(error=failure == "error", truncate=failure == "truncate", missing_end=failure == "missing_end")
        client = LocalAI(AIConfig(autostart=False), transport=httpx.MockTransport(handler))
        try:
            if failure:
                with pytest.raises(AIError): await client.process("spelling", "source")
            else:
                result, stats = await client.process("spelling", "source")
                assert result == "Clean text"
                assert stats["total_output_tokens"] == 20
                assert len([r for r in calls if r.method == "POST"]) == 2
                assert not client.owned
                with pytest.raises(AIError): await client.release()
        finally: await client.close()
    asyncio.run(scenario())


def test_spelling_retries_only_bad_framing_with_new_markers_and_same_source():
    async def scenario():
        requests = []
        def handler(request):
            if request.method == "GET":
                return httpx.Response(200, json=dict(models=[dict(key="qwen/qwen3.5-9b",
                    capabilities=dict(vision=True, reasoning=dict(allowed_options=["off", "on"])),
                    loaded_instances=[dict(id="loaded-qwen")])]))
            payload = json.loads(request.content)
            if "Preparación interna." in str(payload["input"]):
                return stream_response("OK")
            requests.append(payload)
            if len(requests) == 1:
                result = "Texto corregido sin marcadores"
            else:
                marker = re.search(r"<<<RESULT_[A-F0-9]{12}_START>>>", payload["system_prompt"]).group()
                result = marker + "\nTexto corregido\n" + marker.replace("_START", "_END")
            event = dict(type="chat.end", result=dict(output=[dict(type="message", content=result)],
                stats=dict(input_tokens=10, total_output_tokens=20)))
            return httpx.Response(200, text="data: " + json.dumps(event) + "\n\n")
        client = LocalAI(AIConfig(autostart=False), transport=httpx.MockTransport(handler))
        try:
            output, stats = await client.process("spelling", "Texto erróneo")
            assert output == "Texto corregido" and stats["total_output_tokens"] == 40
            assert len(requests) == 2
            assert all(request["input"][0]["content"] == "Texto erróneo" for request in requests)
        finally:
            await client.close()
    asyncio.run(scenario())


def test_ocr_stops_repeating_illegible_without_copying_junk():
    async def scenario():
        def handler(request):
            if request.method == "GET":
                return httpx.Response(200, json=dict(models=[dict(key="qwen/qwen3.5-9b",
                    capabilities=dict(vision=True, reasoning=dict(allowed_options=["off", "on"])),
                    loaded_instances=[dict(id="qwen")])]))
            events = [dict(type="message.delta", content="[ilegible]\n") for _ in range(7)]
            events.append(dict(type="chat.end", result=dict(output=[dict(type="message", content=wrapped("[ilegible]\n" * 7))],
                stats=dict(total_output_tokens=40))))
            return httpx.Response(200, text="".join("data: " + json.dumps(event) + "\n\n" for event in events),
                headers={"content-type": "text/event-stream"})
        client = LocalAI(AIConfig(autostart=False), transport=httpx.MockTransport(handler))
        client.warmed = "qwen"
        try:
            with pytest.raises(AIError, match="repite"):
                await client.process("image", "", sample_png())
        finally:
            await client.close()
    asyncio.run(scenario())


def test_ocr_splits_context_exhausted_screenshot_and_combines_complete_parts():
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage, QColor, QPainter

    picture = QImage(600, 800, QImage.Format.Format_RGB32)
    picture.fill(QColor("red"))
    painter = QPainter(picture); painter.fillRect(0, 400, 600, 400, QColor("blue")); painter.end()
    buffer = QBuffer(); buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert picture.save(buffer, "PNG")
    heights = []

    async def scenario():
        def handler(request):
            if request.method == "GET":
                return httpx.Response(200, json=dict(models=[dict(key="qwen/qwen3.5-9b",
                    capabilities=dict(vision=True, reasoning=dict(allowed_options=["off"])),
                    loaded_instances=[dict(id="qwen")])]))
            payload = json.loads(request.content)
            if "Preparación interna." in str(payload["input"]): return stream_response("OK")
            data_url = payload["input"][1]["data_url"]
            image = QImage.fromData(base64.b64decode(data_url.split(",", 1)[1]))
            heights.append(image.height())
            if image.height() == 800:
                return httpx.Response(200, text="data: " + json.dumps(dict(type="chat.end", result=dict(
                    output=[dict(type="message", content=START + "\nincomplete")],
                    stats=dict(input_tokens=1908, total_output_tokens=140)))) + "\n\n")
            content = "TOP" if image.pixelColor(0, 0).red() > image.pixelColor(0, 0).blue() else "BOTTOM"
            return httpx.Response(200, text="data: " + json.dumps(dict(type="chat.end", result=dict(
                output=[dict(type="message", content=wrapped(content))],
                stats=dict(input_tokens=500, total_output_tokens=20)))) + "\n\n")

        client = LocalAI(AIConfig(autostart=False, image=True), transport=httpx.MockTransport(handler))
        try:
            result, stats = await client.process("image", "", bytes(buffer.data()))
            assert result == "TOP\n\nBOTTOM"
            assert heights == [800, 400, 400]
            assert stats["segments"] == 2 and stats["total_output_tokens"] == 40
        finally:
            await client.close()
    asyncio.run(scenario())


def test_load_once_warm_once_then_reuse_and_release():
    async def scenario():
        loaded = False; loads = 0; warms = 0; unloads = 0
        def handler(request):
            nonlocal loaded, loads, warms, unloads
            if request.method == "GET":
                return httpx.Response(200, json=dict(models=[dict(key="qwen/qwen3.5-9b", capabilities=dict(vision=True),
                    loaded_instances=[dict(id="qwen")] if loaded else [])]))
            if request.url.path.endswith("/load"):
                loads += 1; loaded = True
                assert json.loads(request.content)["context_length"] == 2048
                return httpx.Response(200, json=dict(instance_id="qwen"))
            if request.url.path.endswith("/unload"):
                unloads += 1; loaded = False
                return httpx.Response(200, json={})
            warms += 1
            return stream_response("OK")
        client = LocalAI(AIConfig(autostart=False), transport=httpx.MockTransport(handler))
        try:
            await client.prepare(b"synthetic png")
            await client.prepare()
            assert (loads, warms) == (1, 1)
            await client.release()
            assert unloads == 1
            await client.prepare()
            assert (loads, warms) == (2, 2)
        finally: await client.close()
    asyncio.run(scenario())


def test_thinking_is_enabled_for_grammar_only_and_reasoning_is_never_copied():
    async def scenario():
        modes = []
        def handler(request):
            if request.method == "GET":
                return httpx.Response(200, json=dict(models=[dict(key="qwen/qwen3.5-9b", capabilities=dict(vision=True,
                    reasoning=dict(allowed_options=["off", "on"])), loaded_instances=[dict(id="qwen")])]))
            payload = json.loads(request.content); modes.append(payload["reasoning"])
            assert payload["reasoning_budget"] > 0 if payload["reasoning"] == "on" else payload["reasoning_budget"] == 0
            return stream_response("OK" if "Preparación interna." in str(payload["input"]) else "Clean text")
        client = LocalAI(AIConfig(autostart=False), transport=httpx.MockTransport(handler))
        try:
            result, _ = await client.process("grammar", "She go.")
            assert result == "Clean text"
            await client.process("spelling", "eror")
            await client.process("image", "", sample_png())
            assert modes == ["off", "on", "off", "off"]
        finally: await client.close()
    asyncio.run(scenario())


def test_ai_history_is_local_until_explicitly_queued_and_retains_original(tmp_path):
    store = Store(tmp_path / "dock.sqlite3")
    try:
        item = store.ai_result("Clean", "grammar", dict(text="Original", image=b"png"), dict(elapsed_seconds=1))
        assert store.pending_count() == 0
        assert store.history()[0]["ai_action"] == "grammar"
        record = store.db.execute("SELECT * FROM ai_records").fetchone()
        assert record["source_text"] == "Original" and record["source_image"] == b"png"
        store.enqueue(item["id"])
        assert store.pending_count() == 1
        store.acknowledge(item["id"]); store.delete(item["id"])
        assert store.db.execute("SELECT COUNT(*) FROM ai_records").fetchone()[0] == 0
    finally: store.close()


def test_cancelling_a_job_during_preparation_does_not_duplicate_model_load():
    async def scenario():
        entered = asyncio.Event(); proceed = asyncio.Event(); loads = 0
        async def handler(request):
            nonlocal loads
            if request.method == "GET":
                return httpx.Response(200, json=dict(models=[dict(key="qwen/qwen3.5-9b",
                    capabilities=dict(vision=True), loaded_instances=[])]))
            if request.url.path.endswith("/load"):
                loads += 1; entered.set(); await proceed.wait()
                return httpx.Response(200, json=dict(instance_id="qwen"))
            return stream_response("OK")
        client = LocalAI(AIConfig(autostart=False), transport=httpx.MockTransport(handler))
        try:
            first = asyncio.create_task(client.prepare()); await entered.wait()
            first.cancel(); await asyncio.gather(first, return_exceptions=True)
            second = asyncio.create_task(client.prepare()); await asyncio.sleep(0)
            proceed.set(); await second
            assert loads == 1
        finally: await client.close()
    asyncio.run(scenario())


def test_other_loaded_model_is_not_unloaded_or_loaded_over():
    async def scenario():
        calls = []
        def handler(request):
            calls.append(request.method)
            return httpx.Response(200, json=dict(models=[
                dict(key="qwen/qwen3.5-9b", capabilities=dict(vision=True), loaded_instances=[]),
                dict(key="other", type="llm", loaded_instances=[dict(id="other")])]))
        client = LocalAI(AIConfig(autostart=False), transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(AIError, match="otro modelo"): await client.prepare()
            assert calls == ["GET"]
        finally: await client.close()
    asyncio.run(scenario())


def test_automatic_queue_keeps_latest_cancels_and_does_not_block_network_commands(tmp_path, monkeypatch):
    from clipboard_ai import gui_backend
    from clipboard_ai.gui_backend import Backend
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    started = threading.Event(); proceed = threading.Event(); processed = []; written = []
    class Client:
        def __init__(self, config, status): self.config = config
        async def prepare(self, image=None): pass
        async def close(self): pass
        async def process(self, mode, text, image):
            processed.append(text); started.set()
            while not proceed.is_set(): await asyncio.sleep(.01)
            if text == "failure": raise AIError("synthetic model failure")
            return text + " corrected", {}
    class Clipboard:
        _last = 0
        current = 1
        def revision(self): return self.current
        def changed(self): return None
        def read(self): return ""
        def write(self, text, expected, cancelled):
            if self.current != expected or cancelled.is_set(): return False
            written.append(text); return True
    monkeypatch.setattr(gui_backend, "LocalAI", Client)
    clipboard = Clipboard()
    backend = Backend(SimpleNamespace(data_dir=tmp_path, bind="127.0.0.1", port=0), clipboard,
        ai_config=AIConfig(preload=False, text_mode="grammar"))
    snapshots = []; results = []; errors = []; stopped = []; activities = []
    backend.snapshot.connect(snapshots.append); backend.error.connect(errors.append)
    backend.completed.connect(lambda action, result: results.append((action, result)))
    backend.ai_activity.connect(activities.append)
    backend.stopped.connect(lambda: stopped.append(True))
    def pump(predicate):
        deadline = time.monotonic() + 8
        while not predicate():
            app.processEvents(); time.sleep(.01)
            assert time.monotonic() < deadline, errors
        app.processEvents()
    backend.start()
    try:
        pump(lambda: snapshots or errors); assert not errors
        backend.request("ai_submit", dict(revision=1, text="first", image=None)); pump(started.is_set)
        clipboard.current = 3
        backend.request("ai_submit", dict(revision=2, text="discard", image=None))
        backend.request("ai_submit", dict(revision=3, text="latest", image=None))
        backend.request("automatic", True, False)
        pump(lambda: any(action == "automatic" for action, _ in results))
        proceed.set()
        pump(lambda: sum(action == "ai_result" for action, _ in results) == 2)
        assert processed == ["first", "latest"]
        assert written == ["latest corrected"]
        completed = [value for action, value in results if action == "ai_result"]
        assert [value["written"] for value in completed] == [False, True]
        assert activities.count("working") == 3
        assert activities.count("copied") == 1 and "saved" not in activities
        pump(lambda: snapshots[-1]["pending_text"] == 1)
        # A cancelled generation cannot write or emit a completed result.
        proceed.clear(); started.clear(); clipboard.current = 4
        backend.request("ai_submit", dict(revision=4, text="cancel me", image=None)); pump(started.is_set)
        backend.request("ai_cancel")
        backend.request("automatic", False, False)
        pump(lambda: len([r for r in results if r[0] == "automatic"]) == 2)
        proceed.set(); app.processEvents(); time.sleep(.05); app.processEvents()
        assert written == ["latest corrected"]
        assert activities[-1] == "idle"
        # Clearing the dock also cancels a result still being generated.
        proceed.clear(); started.clear(); clipboard.current = 5
        backend.request("ai_submit", dict(revision=5, text="before clearing", image=None)); pump(started.is_set)
        backend.request("clear_texts")
        pump(lambda: any(action == "clear_texts" for action, _ in results))
        assert snapshots[-1]["texts"] == []
        proceed.set(); app.processEvents(); time.sleep(.05); app.processEvents()
        assert sum(action == "ai_result" for action, _ in results) == 2
        # A completed request whose clipboard changed is saved, not shown as copied.
        clipboard.current = 7
        backend.request("ai_submit", dict(revision=6, text="stale", image=None))
        pump(lambda: activities and activities[-1] == "saved")
        assert results[-1][1]["written"] is False
        # A model error has its own visible state and never gets a green check.
        backend.request("ai_submit", dict(revision=7, text="failure", image=None))
        pump(lambda: activities and activities[-1] == "error")
        assert not errors
    finally:
        proceed.set(); backend.stop(); pump(lambda: stopped); backend.thread.join(3)
        assert not backend.thread.is_alive()
