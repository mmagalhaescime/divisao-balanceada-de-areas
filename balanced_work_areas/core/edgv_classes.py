# -*- coding: utf-8 -*-
"""Catálogo de classes de feições ET-EDGV 3.0 e mapeamento para as fontes.

Cada entrada do catálogo descreve uma classe de feição relevante para o
cálculo de complexidade cartográfica, organizada por primitiva geométrica
(ponto/linha/polígono) e categoria da ET-EDGV, com o mapeamento para as
consultas/camadas correspondentes em cada fonte de dados aberta:

- ``osm``: lista de filtros de tag Overpass (ex.: ``'["building"]'``);
- ``ana``: chaves de camada no ``config/sources.json`` (hidrografia ANA);
- ``ibge``: chaves de camada no ``config/sources.json`` (geoserviços IBGE);
- ``google_open_buildings``: ``True`` se a classe usa o Open Buildings.

O módulo é Python puro (sem QGIS) para permitir testes fora do QGIS.
"""

from typing import Dict, List

PRIMITIVAS = ("ponto", "linha", "poligono")

ROTULOS_PRIMITIVA = {
    "ponto": "Ponto",
    "linha": "Linha",
    "poligono": "Polígono",
}

# Elementos OSM consultados por primitiva (ndoe/way/relation do Overpass).
_ELEMENTOS_OSM = {
    "ponto": ("node",),
    "linha": ("way",),
    "poligono": ("way", "relation"),
}

# Catálogo de classes. ``escala_max`` é o maior denominador de escala em
# que a classe ainda é relevante para o cálculo de complexidade (ex.:
# edificações individuais deixam de ser adquiridas em 1:250.000).
CLASSES_EDGV: List[Dict] = [
    # ------------------------------- PONTO -------------------------------
    {
        "id": "localidades_ponto",
        "nome": "Localidades (sedes, vilas, povoados)",
        "categoria": "Localidades",
        "primitiva": "ponto",
        "escala_max": 250000,
        "padrao": True,
        "osm": ['["place"~"city|town|village|hamlet|isolated_dwelling"]'],
        "ana": [],
        "ibge": ["localidades"],
        "google_open_buildings": False,
    },
    {
        "id": "relevo_pontos_cotados",
        "nome": "Relevo — pontos cotados / picos",
        "categoria": "Relevo (pontos cotados)",
        "primitiva": "ponto",
        "escala_max": 250000,
        "padrao": True,
        "osm": ['["natural"="peak"]'],
        "ana": [],
        "ibge": [],
        "google_open_buildings": False,
    },
    {
        "id": "energia_com_ponto",
        "nome": "Energia e comunicações — torres e antenas",
        "categoria": "Energia e comunicações",
        "primitiva": "ponto",
        "escala_max": 100000,
        "padrao": True,
        "osm": [
            '["power"~"tower|pole|substation"]',
            '["man_made"~"mast|communications_tower|tower"]',
        ],
        "ana": [],
        "ibge": [],
        "google_open_buildings": False,
    },
    {
        "id": "economia_ponto",
        "nome": "Estrutura econômica — equipamentos pontuais",
        "categoria": "Estrutura econômica",
        "primitiva": "ponto",
        "escala_max": 50000,
        "padrao": False,
        "osm": ['["amenity"]', '["shop"]'],
        "ana": [],
        "ibge": [],
        "google_open_buildings": False,
    },
    {
        "id": "saneamento_ponto",
        "nome": "Abastecimento e saneamento — poços e caixas d'água",
        "categoria": "Abastecimento e saneamento",
        "primitiva": "ponto",
        "escala_max": 50000,
        "padrao": False,
        "osm": ['["man_made"~"water_well|water_tower|storage_tank"]'],
        "ana": [],
        "ibge": [],
        "google_open_buildings": False,
    },
    # ------------------------------- LINHA -------------------------------
    {
        "id": "vias_rodoviarias",
        "nome": "Vias de deslocamento — rodovias e arruamento",
        "categoria": "Vias de deslocamento",
        "primitiva": "linha",
        "escala_max": 250000,
        "padrao": True,
        "osm": ['["highway"]'],
        "ana": [],
        "ibge": [],
        "google_open_buildings": False,
    },
    {
        "id": "vias_ferroviarias",
        "nome": "Vias de deslocamento — ferrovias",
        "categoria": "Vias de deslocamento",
        "primitiva": "linha",
        "escala_max": 250000,
        "padrao": True,
        "osm": ['["railway"~"rail|light_rail|narrow_gauge|subway|tram"]'],
        "ana": [],
        "ibge": [],
        "google_open_buildings": False,
    },
    {
        "id": "hidrografia_cursos",
        "nome": "Hidrografia — cursos d'água",
        "categoria": "Hidrografia",
        "primitiva": "linha",
        "escala_max": 250000,
        "padrao": True,
        "osm": ['["waterway"~"river|stream|canal|drain|ditch"]'],
        "ana": ["cursos_dagua"],
        "ibge": [],
        "google_open_buildings": False,
    },
    {
        "id": "energia_linha",
        "nome": "Energia e comunicações — linhas de transmissão",
        "categoria": "Energia e comunicações",
        "primitiva": "linha",
        "escala_max": 250000,
        "padrao": True,
        "osm": ['["power"~"line|minor_line"]'],
        "ana": [],
        "ibge": [],
        "google_open_buildings": False,
    },
    {
        "id": "limites_linha",
        "nome": "Limites — limites administrativos",
        "categoria": "Limites",
        "primitiva": "linha",
        "escala_max": 250000,
        "padrao": False,
        "osm": ['["boundary"="administrative"]["admin_level"~"^([2-8])$"]'],
        "ana": [],
        "ibge": ["municipios"],
        "google_open_buildings": False,
    },
    {
        "id": "saneamento_linha",
        "nome": "Abastecimento e saneamento — adutoras e dutos",
        "categoria": "Abastecimento e saneamento",
        "primitiva": "linha",
        "escala_max": 100000,
        "padrao": False,
        "osm": ['["man_made"="pipeline"]'],
        "ana": [],
        "ibge": [],
        "google_open_buildings": False,
    },
    # ----------------------------- POLÍGONO ------------------------------
    {
        "id": "edificacoes",
        "nome": "Edificações",
        "categoria": "Edificações",
        "primitiva": "poligono",
        "escala_max": 100000,
        "padrao": True,
        "osm": ['["building"]'],
        "ana": [],
        "ibge": [],
        "google_open_buildings": True,
    },
    {
        "id": "hidrografia_massas",
        "nome": "Hidrografia — massas d'água",
        "categoria": "Hidrografia",
        "primitiva": "poligono",
        "escala_max": 250000,
        "padrao": True,
        "osm": ['["natural"="water"]', '["landuse"="reservoir"]'],
        "ana": ["massas_dagua"],
        "ibge": [],
        "google_open_buildings": False,
    },
    {
        "id": "vegetacao",
        "nome": "Vegetação — matas e florestas",
        "categoria": "Vegetação",
        "primitiva": "poligono",
        "escala_max": 250000,
        "padrao": True,
        "osm": ['["natural"~"wood|scrub|wetland"]', '["landuse"="forest"]'],
        "ana": [],
        "ibge": [],
        "google_open_buildings": False,
    },
    {
        "id": "economia_poligono",
        "nome": "Estrutura econômica — áreas industriais/comerciais",
        "categoria": "Estrutura econômica",
        "primitiva": "poligono",
        "escala_max": 100000,
        "padrao": False,
        "osm": ['["landuse"~"industrial|commercial|quarry"]'],
        "ana": [],
        "ibge": [],
        "google_open_buildings": False,
    },
    {
        "id": "localidades_poligono",
        "nome": "Localidades — áreas edificadas",
        "categoria": "Localidades",
        "primitiva": "poligono",
        "escala_max": 250000,
        "padrao": False,
        "osm": ['["landuse"="residential"]'],
        "ana": [],
        "ibge": [],
        "google_open_buildings": False,
    },
]


def classes_por_primitiva() -> Dict[str, List[Dict]]:
    """Agrupa o catálogo por primitiva geométrica (para a árvore da GUI).

    :returns: dicionário ``primitiva -> lista de classes`` preservando a
        ordem do catálogo.
    """
    grupos: Dict[str, List[Dict]] = {p: [] for p in PRIMITIVAS}
    for cls in CLASSES_EDGV:
        grupos[cls["primitiva"]].append(cls)
    return grupos


def obter_classe(id_classe: str) -> Dict:
    """Busca uma classe do catálogo pelo identificador.

    :raises KeyError: se o identificador não existir.
    """
    for cls in CLASSES_EDGV:
        if cls["id"] == id_classe:
            return cls
    raise KeyError("Classe EDGV desconhecida: %s" % id_classe)


def filtrar_por_escala(
    ids_classes: List[str], denominador_escala: int
) -> List[str]:
    """Remove classes irrelevantes para a escala de trabalho.

    :param ids_classes: identificadores de classes marcadas pelo usuário.
    :param denominador_escala: denominador da escala (ex.: 250000).
    :returns: subconjunto de ``ids_classes`` cujas classes têm
        ``escala_max >= denominador_escala``.
    """
    return [
        i
        for i in ids_classes
        if obter_classe(i)["escala_max"] >= denominador_escala
    ]


def elementos_osm(primitiva: str) -> tuple:
    """Elementos Overpass (node/way/relation) usados pela primitiva."""
    return _ELEMENTOS_OSM[primitiva]


def ids_padrao() -> List[str]:
    """Identificadores das classes marcadas por padrão na GUI."""
    return [c["id"] for c in CLASSES_EDGV if c["padrao"]]
