"""Keyboard state for game logic (Arcade-agnostic)."""

from __future__ import annotations

KEY_LEFT = "left"
KEY_RIGHT = "right"
KEY_UP = "up"
KEY_DOWN = "down"


class KeyState:
    def __init__(self) -> None:
        self._pressed: set[str] = set()

    def clear(self) -> None:
        self._pressed.clear()

    def press(self, key: str) -> None:
        self._pressed.add(key)

    def release(self, key: str) -> None:
        self._pressed.discard(key)

    def pressed(self, *keys: str) -> bool:
        return any(k in self._pressed for k in keys)


def key_labels_from_state(keys: KeyState) -> list[str]:
    labels = []
    if keys.pressed(KEY_LEFT):
        labels.append("left")
    if keys.pressed(KEY_RIGHT):
        labels.append("right")
    if keys.pressed(KEY_UP):
        labels.append("up")
    if keys.pressed(KEY_DOWN):
        labels.append("down")
    return labels
