"""
Migraciones de datos en segundo plano (idempotentes).

Módulo ligero a propósito: importa solo database y scrapers (sin FastAPI ni
init_db al importar), para que sea trivial de testear de forma aislada.
"""
from __future__ import annotations

import logging
import time as _time

import database as db
from metadatos import cambios_seguros
from scrapers import SCRAPERS

log = logging.getLogger("miraru.migrations")


class Cortocircuito:
    """Aparta las fuentes que están fallando sistemáticamente.

    Las migraciones recorren cientos de animes probando las fuentes en serie.
    Cuando una está caída —como AniList devolviendo 403 durante días— cada
    anime perdía varios segundos en ella (con sus reintentos y backoff) antes de
    llegar a una que funcionase. Medido: 6 animes reparados en 15 minutos.

    Tras `umbral` fallos seguidos, esa fuente se deja de consultar durante el
    resto del recorrido. Un acierto reinicia su contador, así que una fuente
    intermitente no queda excluida para siempre.
    """

    def __init__(self, umbral: int = 3):
        self.umbral = umbral
        self.fallos: dict[str, int] = {}

    def descartada(self, fuente: str) -> bool:
        return self.fallos.get(fuente, 0) >= self.umbral

    def anotar_fallo(self, fuente: str) -> None:
        self.fallos[fuente] = self.fallos.get(fuente, 0) + 1
        if self.fallos[fuente] == self.umbral:
            log.info("fuente %r apartada: %d fallos seguidos", fuente, self.umbral)

    def anotar_acierto(self, fuente: str) -> None:
        self.fallos.pop(fuente, None)

    def todas_caidas(self) -> bool:
        return all(self.descartada(f) for f in SCRAPERS)


def buscar_sync_con_fallback(nombre: str, fuente_pref: str, corto: Cortocircuito | None = None):
    """Búsqueda sincrónica con fallback: prueba la fuente preferida y, si falla,
    el resto de fuentes. Devuelve (AnimeData|None, fuente).

    `corto` es opcional para no cambiar la firma a quien ya la llamaba.
    """
    orden = [fuente_pref] + [f for f in SCRAPERS if f != fuente_pref]
    for f in orden:
        scr = SCRAPERS.get(f)
        if not scr:
            continue
        if corto is not None and corto.descartada(f):
            continue
        try:
            r = scr.buscar(nombre)
        except Exception:
            r = None
        if r:
            if corto is not None:
                corto.anotar_acierto(f)
            return r, f
        if corto is not None:
            corto.anotar_fallo(f)
    return None, fuente_pref


# Si falla más de este porcentaje, se asume que el problema es la red o que las
# APIs están caídas, no que esos animes no existan.
_UMBRAL_FALLO_MASIVO = 0.8
_MINIMO_PARA_JUZGAR = 5        # con 2 o 3 intentos no se puede deducir nada


def migrar_cap200(sleep: float = 0.4) -> dict:
    """Repara entradas con el cap=200 fantasma del bug viejo (<v2.6.2).

    Re-consulta la fuente (con fallback) para poner el número real; si no se
    puede resolver, lo deja en '?' para no mostrar un dato falso. Preserva el
    progreso del usuario.

    Sin flag de "ya migrado", a propósito. Antes había uno y causó este fallo
    real: al arrancar con la biblioteca vacía no encontraba nada que reparar,
    marcaba la migración como terminada PARA SIEMPRE, y cuando después llegaban
    datos afectados —importando una instalación antigua, restaurando una copia
    de seguridad o sincronizando— ya no volvía a ejecutarse nunca. El usuario se
    quedaba con 180 animes mintiendo sobre sus episodios y sin forma de saberlo.

    No hace falta flag: la propia consulta es la condición de parada. Cada
    entrada acaba con su número real o con '?', así que sale del conjunto y el
    trabajo se reduce a una consulta barata en los arranques siguientes.

    Devuelve un resumen {revisados, reparados, sin_resolver, abortado}.
    """
    resumen = {"revisados": 0, "reparados": 0, "sin_resolver": 0, "abortado": False}
    try:
        afectados = [a for a in db.listar_animes() if str(a.get("capitulos")) == "200"]
        if not afectados:
            return resumen

        log.info("cap=200: reparando %d entradas heredadas del bug viejo", len(afectados))
        fallos_seguidos = 0
        corto = Cortocircuito()

        for a in afectados:
            nombre = a["nombre"]
            fuente = a.get("fuente") or "anilist"
            if fuente not in SCRAPERS:
                fuente = "anilist"
            if corto.todas_caidas():
                log.warning("cap=200: todas las fuentes están caídas; "
                            "se deja para el próximo arranque")
                resumen["abortado"] = True
                return resumen
            nuevo, _f = buscar_sync_con_fallback(nombre, fuente, corto)
            resumen["revisados"] += 1

            if nuevo:
                fallos_seguidos = 0
                # Confiamos en el dato fresco de la fuente (aunque sean 200 reales)
                cambios = {"capitulos": str(nuevo.capitulos)}
                if nuevo.imagen:
                    cambios["imagen"] = nuevo.imagen
                if nuevo.sinopsis:
                    cambios["sinopsis"] = nuevo.sinopsis
                if nuevo.genero:
                    cambios["genero"] = ",".join(nuevo.genero)
                db.refrescar_metadata_anime(nombre, cambios)
                resumen["reparados"] += 1
            else:
                fallos_seguidos += 1
                # Si está fallando TODO, el problema no son estos animes: es que
                # no hay red o las fuentes están caídas. Poner '?' entonces
                # destruiría 180 episodios correctos por un corte pasajero.
                # Mejor dejarlos como están y reintentar en el próximo arranque.
                proporcion = fallos_seguidos / max(1, resumen["revisados"])
                if (resumen["revisados"] >= _MINIMO_PARA_JUZGAR
                        and proporcion >= _UMBRAL_FALLO_MASIVO):
                    log.warning(
                        "cap=200: %d fallos seguidos de %d intentos. Las fuentes "
                        "parecen caídas; se deja para el próximo arranque.",
                        fallos_seguidos, resumen["revisados"])
                    resumen["abortado"] = True
                    return resumen
                # Fallo aislado: el 200 era casi con seguridad falso → '?'
                db.refrescar_metadata_anime(nombre, {"capitulos": "?"})
                resumen["sin_resolver"] += 1

            if sleep:
                _time.sleep(sleep)  # ser amable con las APIs externas

        log.info("cap=200: %d reparados, %d sin resolver",
                 resumen["reparados"], resumen["sin_resolver"])
        return resumen
    except Exception as e:
        log.warning("cap=200 migración: %s", e)
        return resumen


# Estados que consideramos "en emisión" (en cualquiera de los idiomas/fuentes).
EN_EMISION = {
    "en emisión", "en emision", "releasing", "currently airing", "airing",
}


# Campos que el refresco periódico puede tocar (la sinopsis/géneros no cambian
# por emitirse un episodio y no merece la pena reescribirlos cada 12h).
_CAMPOS_REFRESCO_EMISION = ("capitulos", "estado_anime", "imagen", "anilist_id")


def refrescar_en_emision(sleep: float = 0.4) -> int:
    """Re-consulta las series EN EMISIÓN para actualizar nº de episodios, imagen
    y estado (al terminar la temporada crecen los episodios o pasa a Finalizado).
    NO toca el progreso del usuario. Pensado para correr periódicamente en
    segundo plano. Devuelve cuántas se actualizaron.

    - Con anilist_id → AniList por lotes de 50 IDs (exacto y 1 petición/lote).
    - Sin ID → fuente original con fallback.
    - Usa metadatos.cambios_seguros: nunca pone "?" sobre un número conocido
      ni cambia una portada buena por una de anime-planet/AnimeFLV."""
    actualizados = 0

    def _aplicar(a, nuevo) -> None:
        nonlocal actualizados
        cambios = {k: v for k, v in cambios_seguros(a, nuevo).items()
                   if k in _CAMPOS_REFRESCO_EMISION}
        if cambios:
            db.refrescar_metadata_anime(a["nombre"], cambios)
            actualizados += 1

    try:
        animes = [
            a for a in db.listar_animes()
            if (a.get("estado_anime") or "").strip().lower() in EN_EMISION
        ]
        anilist = SCRAPERS.get("anilist")
        por_id = hasattr(anilist, "buscar_por_ids")
        con_id = [a for a in animes if por_id and a.get("anilist_id")
                  and (a.get("tipo") or "anime") == "anime"]
        resto = [a for a in animes if a not in con_id]

        for i in range(0, len(con_id), 50):
            lote = con_id[i:i + 50]
            try:
                res = anilist.buscar_por_ids([int(a["anilist_id"]) for a in lote])
            except Exception:
                res = {}
            for a in lote:
                nuevo = res.get(int(a["anilist_id"]))
                if nuevo:
                    _aplicar(a, nuevo)
                else:
                    resto.append(a)      # ID no encontrado: probar por nombre
            if sleep:
                _time.sleep(max(sleep, 2.1))

        corto = Cortocircuito()
        for a in resto:
            nombre = a["nombre"]
            fuente = a.get("fuente") or "anilist"
            if fuente not in SCRAPERS:
                fuente = "anilist"
            if corto.todas_caidas():
                log.warning("refresco emisión: todas las fuentes caídas, se corta")
                break
            nuevo, _f = buscar_sync_con_fallback(nombre, fuente, corto)
            if nuevo:
                _aplicar(a, nuevo)
            if sleep:
                _time.sleep(sleep)
        if actualizados:
            log.info("refresco emisión: %d series actualizadas", actualizados)
    except Exception as e:
        log.warning("refresco emisión: %s", e)
    return actualizados


def completar_episodios_vistos() -> int:
    """Completados con 0 episodios vistos → vistos = nº de capítulos.

    La importación antigua dejó los 334 completados a 0: la ficha y las barras
    mostraban 0/12. Misma regla que "marcar como completado" en la UI
    (parseInt de capítulos; "1179+" → 1179). Películas y "?" no se tocan.
    Idempotente: solo actúa sobre completados con 0. Devuelve cuántos cambió."""
    import re
    cambiados = 0
    try:
        with db.get_conn() as conn:
            filas = conn.execute(
                "SELECT nombre, capitulos FROM animes WHERE estado_usuario='completado' "
                "AND COALESCE(episodios_vistos, 0) = 0").fetchall()
            for nombre, caps in filas:
                m = re.match(r"\s*(\d+)", str(caps or ""))
                n = int(m.group(1)) if m else 0
                if n > 0:
                    conn.execute("UPDATE animes SET episodios_vistos=? WHERE nombre=?", (n, nombre))
                    cambiados += 1
        if cambiados:
            db._invalidar_cache()
            log.info("completados: %d con episodios_vistos rellenados", cambiados)
    except Exception as e:
        log.warning("completar_episodios_vistos: %s", e)
    return cambiados
