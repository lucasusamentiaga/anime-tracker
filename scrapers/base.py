from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class AnimeData:
    nombre: str
    capitulos: int | str          # int o "película"
    imagen: str
    genero: list[str]
    sinopsis: str
    fuente: str                   # "anilist", "mal", "animeflv", etc.
    estado_anime: str             # "En emisión", "Finalizado", etc.
    # Campos que rellena el usuario
    estado_usuario: str = "pendiente"   # pendiente / viendo / completado / abandonado
    puntuacion: Optional[float] = None
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None


class BaseScraper(ABC):
    """Interfaz común que deben implementar todos los scrapers."""

    @property
    @abstractmethod
    def nombre_fuente(self) -> str:
        ...

    @abstractmethod
    def buscar(self, nombre: str) -> Optional[AnimeData]:
        """Devuelve AnimeData o None si no se encuentra."""
        ...
