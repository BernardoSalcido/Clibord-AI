"""Native macOS keyboard bridge. Imported only on Darwin.

Qt uses Ctrl for the Command key and Meta for the physical Control key on
macOS; the saved QKeySequence values are translated accordingly.
"""
from __future__ import annotations

import sys

from .desktop_platform import parse_hotkey


def _native():
    if sys.platform != "darwin":
        raise RuntimeError("Los atajos de macOS requieren un Mac")
    import AppKit
    import Quartz
    return AppKit, Quartz


def _key(event):
    characters = event.charactersIgnoringModifiers()
    if characters and len(characters) == 1 and characters.isascii() and characters.isalnum():
        return ord(characters.upper())
    # NSEvent's function-key characters start at U+F704 (F1).
    if characters and len(characters) == 1 and 0xF704 <= ord(characters) <= 0xF71B:
        return 0x70 + ord(characters) - 0xF704
    return None


def _modifiers(flags, appkit):
    value = 0
    if flags & appkit.NSEventModifierFlagOption: value |= 1
    if flags & appkit.NSEventModifierFlagCommand: value |= 2  # Qt Ctrl
    if flags & appkit.NSEventModifierFlagShift: value |= 4
    if flags & appkit.NSEventModifierFlagControl: value |= 8  # Qt Meta
    return value


class MacHotkeys:
    """Observe global and in-app keyDown events without stealing normal keys."""

    def __init__(self, callbacks):
        self.callbacks = callbacks
        self.global_monitor = None
        self.local_monitor = None
        self.bindings = {}
        self.last_keycode = None

    def configure(self, bindings):
        self.close()
        appkit, quartz = _native()
        errors = []
        for name, text in bindings.items():
            if text:
                try:
                    mods, key = parse_hotkey(text)
                    self.bindings[(mods & ~0x4000, key)] = name
                except ValueError as exc:
                    errors.append(str(exc))
        if not self.bindings:
            return errors
        if not quartz.AXIsProcessTrusted():
            errors.append("macOS: concede Accesibilidad a la terminal o a Clipboard AI en Ajustes del Sistema → Privacidad y seguridad")
        mask = appkit.NSEventMaskKeyDown
        self.global_monitor = appkit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(mask, self._global)
        self.local_monitor = appkit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(mask, self._local)
        return errors

    def _dispatch(self, event):
        appkit, _ = _native()
        mods = _modifiers(event.modifierFlags(), appkit)
        key = _key(event)
        if key is None:
            return False
        name = self.bindings.get((mods, key))
        if name is None and mods & 4:
            # Shift must not break a letter shortcut unless separately assigned.
            name = self.bindings.get((mods & ~4, key))
        if name and not event.isARepeat():
            self.last_keycode = event.keyCode()
            self.callbacks[name]()
            return True
        return False

    def _global(self, event):
        self._dispatch(event)

    def _local(self, event):
        return None if self._dispatch(event) else event

    def released(self, binding):
        _, quartz = _native()
        state = quartz.kCGEventSourceStateCombinedSessionState
        keys = (self.last_keycode, 54, 55, 56, 59, 60, 61, 62, 58)
        return all(key is None or not quartz.CGEventSourceKeyState(state, key) for key in keys)

    def close(self):
        if sys.platform == "darwin":
            appkit, _ = _native()
            for monitor in (self.global_monitor, self.local_monitor):
                if monitor is not None:
                    appkit.NSEvent.removeMonitor_(monitor)
        self.global_monitor = self.local_monitor = None
        self.bindings.clear()


def copy_focused_selection():
    """Copy the focused app's selection with Command+C."""
    _, quartz = _native()
    source = quartz.CGEventSourceCreate(quartz.kCGEventSourceStateCombinedSessionState)
    for code, down in ((55, True), (8, True), (8, False), (55, False)):
        event = quartz.CGEventCreateKeyboardEvent(source, code, down)
        if event is None:
            return False
        if code == 8:
            quartz.CGEventSetFlags(event, quartz.kCGEventFlagMaskCommand)
        quartz.CGEventPost(quartz.kCGHIDEventTap, event)
    return True
