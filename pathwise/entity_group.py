"""Lightweight sprite groups for entity lists."""


class Entity:
    """Base entity with rect/image and alive/kill lifecycle."""

    def __init__(self) -> None:
        self._alive = True

    def kill(self) -> None:
        self._alive = False

    def alive(self) -> bool:
        return self._alive


class EntityGroup:
    def __init__(self, *sprites: Entity) -> None:
        self._sprites: list[Entity] = list(sprites)

    def add(self, *sprites: Entity) -> None:
        for sprite in sprites:
            if sprite not in self._sprites:
                self._sprites.append(sprite)

    def remove(self, *sprites: Entity) -> None:
        for sprite in sprites:
            if sprite in self._sprites:
                self._sprites.remove(sprite)

    def sprites(self) -> list:
        return [s for s in self._sprites if s.alive()]

    def sprites_into(self, out: list) -> list:
        """Reuse ``out`` as the alive-sprite buffer (avoids per-frame list allocation)."""
        out.clear()
        for sprite in self._sprites:
            if sprite.alive():
                out.append(sprite)
        return out

    def __iter__(self):
        return iter(self.sprites())

    def __contains__(self, item: Entity) -> bool:
        return item in self._sprites and item.alive()

    def __len__(self) -> int:
        return len(self.sprites())
