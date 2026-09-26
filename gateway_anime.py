"""
Recomendaciones para principiantes: animes "puerta de entrada" (gateway anime).

Lista curada de títulos muy accesibles y aclamados, ideales para quien empieza
en el anime. Cada uno con sus géneros (vocabulario de AniList) y un motivo. El
ranking se hace por solapamiento con los géneros favoritos del usuario; si no
tiene historial, se mantiene el orden curado (FMA:B primero = mejor primer anime
"por defecto"). Función pura y testeable — la BD y AniList se usan fuera.
"""
from __future__ import annotations

# `id` = AniList media id (para enriquecer con portada/sinopsis en un solo query).
GATEWAY = [
    {"id": 5114,   "titulo": "Fullmetal Alchemist: Brotherhood",
     "generos": ["Action", "Adventure", "Drama", "Fantasy"],
     "motivo": "Historia completa y redonda; de las mejores valoradas de la historia. Un primer anime casi perfecto."},
    {"id": 1535,   "titulo": "Death Note",
     "generos": ["Mystery", "Psychological", "Supernatural", "Thriller"],
     "motivo": "Thriller de gato y ratón que engancha desde el episodio 1. Sin relleno."},
    {"id": 16498,  "titulo": "Attack on Titan",
     "generos": ["Action", "Drama", "Fantasy", "Mystery"],
     "motivo": "Intenso y cinematográfico; el fenómeno que enganchó a millones."},
    {"id": 101922, "titulo": "Demon Slayer",
     "generos": ["Action", "Adventure", "Fantasy", "Supernatural"],
     "motivo": "Animación espectacular y trama fácil de seguir."},
    {"id": 21087,  "titulo": "One Punch Man",
     "generos": ["Action", "Comedy", "Sci-Fi"],
     "motivo": "Acción y comedia con episodios sueltos: entras y sales sin liarte."},
    {"id": 21519,  "titulo": "Your Name",
     "generos": ["Romance", "Drama", "Supernatural"],
     "motivo": "Película de 2 h, autoconclusiva y preciosa. Toma de contacto perfecta."},
    {"id": 199,    "titulo": "Spirited Away",
     "generos": ["Adventure", "Fantasy", "Supernatural"],
     "motivo": "Ghibli, ganadora del Óscar. Mágica y para todos los públicos."},
    {"id": 9253,   "titulo": "Steins;Gate",
     "generos": ["Sci-Fi", "Thriller", "Drama"],
     "motivo": "Viajes en el tiempo con un giro brillante. Paciencia al inicio, recompensa enorme."},
    {"id": 1,      "titulo": "Cowboy Bebop",
     "generos": ["Action", "Adventure", "Sci-Fi", "Drama"],
     "motivo": "Clásico atemporal con estilo noir-jazz; capítulos en gran parte autoconclusivos."},
    {"id": 11061,  "titulo": "Hunter x Hunter (2011)",
     "generos": ["Action", "Adventure", "Fantasy"],
     "motivo": "Aventura shonen muy bien escrita; ideal si te gustan los mundos grandes."},
    {"id": 21459,  "titulo": "My Hero Academia",
     "generos": ["Action", "Comedy", "Adventure"],
     "motivo": "Superhéroes; una entrada moderna y muy accesible al shonen."},
    {"id": 140960, "titulo": "Spy x Family",
     "generos": ["Action", "Comedy", "Slice of Life"],
     "motivo": "Comedia familiar de espías; ligera, divertida y fácil de ver."},
    {"id": 154587, "titulo": "Frieren: Beyond Journey's End",
     "generos": ["Adventure", "Drama", "Fantasy"],
     "motivo": "Fantasía pausada y emotiva; reciente y muy aclamada."},
    {"id": 21753,  "titulo": "A Silent Voice",
     "generos": ["Drama", "Romance"],
     "motivo": "Película; drama humano sobre la culpa, la sordera y la redención."},
    {"id": 20583,  "titulo": "Haikyu!!",
     "generos": ["Sports", "Comedy", "Drama"],
     "motivo": "Deporte (voleibol) trepidante; no hace falta saber del deporte para disfrutarlo."},
    {"id": 113415, "titulo": "Jujutsu Kaisen",
     "generos": ["Action", "Supernatural", "Fantasy"],
     "motivo": "Acción sobrenatural moderna con una animación que entra por los ojos."},
]


def recomendar_principiante(top_genres, limite: int = 12, excluir_ids=(), excluir_claves=(),
                            clave=lambda t: t.strip().lower()) -> dict:
    """Ordena los gateway por solapamiento con los géneros favoritos.
    Devuelve {empieza_aqui, recomendaciones, personalizado}.
    Sin géneros → mantiene el orden curado (primer pick = mejor default).
    `excluir_ids` (AniList) y `excluir_claves` (títulos ya normalizados con `clave`)
    quitan lo que el usuario ya tiene en su lista: antes se recomendaba
    "Attack on Titan" a quien ya lo había visto."""
    tg = {g.strip().lower() for g in (top_genres or []) if (g or "").strip()}
    ids = {int(i) for i in excluir_ids if i}
    claves = set(excluir_claves)
    scored = []
    for i, a in enumerate(GATEWAY):
        if a["id"] in ids or clave(a["titulo"]) in claves:
            continue
        gset = {g.lower() for g in a["generos"]}
        overlap = len(gset & tg)
        # dict(a): copia, para que quien enriquezca (portadas) no mute la lista base
        scored.append((overlap, i, dict(a)))  # i = orden curado como desempate estable
    scored.sort(key=lambda x: (-x[0], x[1]))
    ordenados = [a for _o, _i, a in scored]
    return {
        "empieza_aqui": ordenados[0] if ordenados else None,
        "recomendaciones": ordenados[:limite],
        "personalizado": bool(tg),
    }
