"""Shared wire contract. Dates are informational, never conflict clocks."""
import json
import uuid

VERSION = 1
MAX_TEXT = 256 * 1024
MAX_MESSAGE = MAX_TEXT * 6 + 4096


class ProtocolError(ValueError):
    pass


def identifier(value):
    if not isinstance(value, str):
        raise ProtocolError("Identificador inválido")
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError()
    except ValueError as exc:
        raise ProtocolError("Identificador inválido") from exc
    return value


def validate_item(item, origin=None):
    if not isinstance(item, dict):
        raise ProtocolError("Elemento inválido")
    result = {key: item.get(key) for key in ("id", "origin", "seq", "created", "text")}
    identifier(result["id"])
    identifier(result["origin"])
    if origin is not None and result["origin"] != origin:
        raise ProtocolError("Origen incorrecto")
    if type(result["seq"]) is not int or not 1 <= result["seq"] <= 2**53 - 1:
        raise ProtocolError("Secuencia inválida")
    if not isinstance(result["created"], str) or len(result["created"]) > 64:
        raise ProtocolError("Fecha inválida")
    value = result["text"]
    if not isinstance(value, str) or not value:
        raise ProtocolError("El texto debe tener entre 1 byte y 256 KiB")
    try:
        if len(value.encode("utf-8")) > MAX_TEXT:
            raise ProtocolError("El texto supera 256 KiB")
        result["created"].encode("utf-8")
    except UnicodeError as exc:
        raise ProtocolError("El contenido no es Unicode válido") from exc
    return result


def encode(kind, **fields):
    return json.dumps({"v": VERSION, "type": kind, **fields}, ensure_ascii=False)


def decode(raw):
    try:
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_MESSAGE:
            raise ProtocolError("Mensaje demasiado grande o binario")
        msg = json.loads(raw)
        if not isinstance(msg, dict) or type(msg.get("v")) is not int or msg["v"] != VERSION:
            raise ProtocolError("Versión de protocolo incompatible")
        if not isinstance(msg.get("type"), str):
            raise ProtocolError("Falta tipo de mensaje")
        return msg
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ProtocolError("JSON inválido") from exc
