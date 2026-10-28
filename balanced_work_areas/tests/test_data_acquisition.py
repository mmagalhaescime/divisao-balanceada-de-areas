# -*- coding: utf-8 -*-
"""Testes (sem rede) do módulo de aquisição de dados."""

import io

import pytest

pytest.importorskip("qgis")

from qgis.core import (  # noqa: E402
    QgsFeature,
    QgsGeometry,
    QgsRectangle,
    QgsVectorLayer,
)

from balanced_work_areas.core import data_acquisition as aq  # noqa: E402
from balanced_work_areas.core import edgv_classes  # noqa: E402


def test_carregar_config_tem_todas_as_fontes(qgis_app):
    config = aq.carregar_config()
    for fonte in ("osm", "ana", "ibge", "google_open_buildings"):
        assert fonte in config


def test_montar_consulta_overpass_edificacoes(qgis_app):
    classe = edgv_classes.obter_classe("edificacoes")
    bbox = QgsRectangle(-48.0, -16.0, -47.5, -15.5)
    consulta = aq.montar_consulta_overpass(classe, bbox, 180)
    assert consulta.startswith("[out:json][timeout:180];(")
    assert 'way["building"](-16.0' in consulta.replace("00000", "0")
    assert "relation" in consulta  # polígonos consultam ways e relations
    assert consulta.endswith("out geom;")


def test_montar_consulta_overpass_pontos_usa_node(qgis_app):
    classe = edgv_classes.obter_classe("relevo_pontos_cotados")
    consulta = aq.montar_consulta_overpass(
        classe, QgsRectangle(0, 0, 1, 1), 60
    )
    assert "node" in consulta
    assert "way" not in consulta


def test_tiles_bbox_divide_areas_grandes(qgis_app):
    bbox = QgsRectangle(-48.0, -16.0, -46.0, -14.0)  # 4 graus²
    tiles = aq._tiles_bbox(bbox, 0.25)
    assert len(tiles) == 16
    # A união dos tiles cobre a bbox original.
    uniao = QgsRectangle(tiles[0])
    for t in tiles[1:]:
        uniao.combineExtentWith(t)
    assert uniao == bbox


def test_tiles_bbox_pequena_nao_divide(qgis_app):
    bbox = QgsRectangle(-48.0, -16.0, -47.9, -15.9)
    assert aq._tiles_bbox(bbox, 0.25) == [bbox]


def test_geometria_elemento_osm_node(qgis_app):
    geometria = aq._geometria_de_elemento_osm(
        {"type": "node", "lat": -15.5, "lon": -47.5}, "ponto"
    )
    assert geometria.asPoint().x() == pytest.approx(-47.5)


def test_geometria_elemento_osm_way_linha(qgis_app):
    elemento = {
        "type": "way",
        "geometry": [
            {"lat": 0.0, "lon": 0.0},
            {"lat": 0.0, "lon": 1.0},
        ],
    }
    geometria = aq._geometria_de_elemento_osm(elemento, "linha")
    assert geometria.length() == pytest.approx(1.0)


def test_geometria_elemento_osm_way_poligono_fecha_anel(qgis_app):
    elemento = {
        "type": "way",
        "geometry": [
            {"lat": 0.0, "lon": 0.0},
            {"lat": 0.0, "lon": 1.0},
            {"lat": 1.0, "lon": 1.0},
        ],
    }
    geometria = aq._geometria_de_elemento_osm(elemento, "poligono")
    assert geometria.area() == pytest.approx(0.5)


def test_geometria_elemento_osm_relation_usa_bounds(qgis_app):
    elemento = {
        "type": "relation",
        "bounds": {
            "minlat": 0.0,
            "minlon": 0.0,
            "maxlat": 2.0,
            "maxlon": 1.0,
        },
    }
    geometria = aq._geometria_de_elemento_osm(elemento, "poligono")
    assert geometria.area() == pytest.approx(2.0)


def test_geojson_para_wkt_poligono(qgis_app):
    wkt = aq._geojson_para_wkt(
        {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
        }
    )
    assert QgsGeometry.fromWkt(wkt).area() == pytest.approx(0.5)


def test_iterar_csv_open_buildings_filtra(qgis_app):
    csv_texto = io.StringIO(
        "latitude,longitude,area_in_meters,confidence,geometry,full_plus_code\n"
        "-15.5,-47.5,100,0.9,\"POLYGON((0 0,1 0,1 1,0 0))\",X\n"
        "-15.5,-47.5,100,0.5,\"POLYGON((0 0,1 0,1 1,0 0))\",X\n"  # confiança baixa
        "-30.0,-60.0,100,0.9,\"POLYGON((0 0,1 0,1 1,0 0))\",X\n"  # fora da bbox
    )
    bbox = QgsRectangle(-48.0, -16.0, -47.0, -15.0)
    wkts = list(aq._iterar_csv_open_buildings(csv_texto, bbox, 0.7))
    assert len(wkts) == 1


def test_cache_gravar_carregar_limpar(qgis_app, tmp_path):
    pasta = str(tmp_path)
    camada = QgsVectorLayer("Point?crs=EPSG:4326", "t", "memory")
    feicao = QgsFeature()
    feicao.setGeometry(QgsGeometry.fromWkt("POINT(1 2)"))
    camada.dataProvider().addFeatures([feicao])
    camada.updateExtents()

    em_cache = aq.salvar_no_cache(camada, pasta, "osm_teste_abc")
    assert em_cache is not None and em_cache.featureCount() == 1

    recarregada = aq.carregar_do_cache(pasta, "osm_teste_abc")
    assert recarregada is not None and recarregada.featureCount() == 1

    assert aq.carregar_do_cache(pasta, "inexistente") is None

    # No Windows o gpkg fica bloqueado enquanto houver camadas abertas;
    # libera as referências antes de limpar (mesmo contrato da GUI).
    del em_cache, recarregada
    assert aq.limpar_cache(pasta) is True
    assert aq.carregar_do_cache(pasta, "osm_teste_abc") is None


def test_chave_cache_estavel_e_distinta(qgis_app):
    bbox1 = QgsRectangle(-48.0, -16.0, -47.0, -15.0)
    bbox2 = QgsRectangle(-49.0, -16.0, -47.0, -15.0)
    chave_a = aq._chave_cache("osm", "edificacoes", bbox1)
    chave_b = aq._chave_cache("osm", "edificacoes", bbox1)
    chave_c = aq._chave_cache("osm", "edificacoes", bbox2)
    assert chave_a == chave_b
    assert chave_a != chave_c


def test_adquirir_dados_fonte_com_falha_gera_aviso(qgis_app, tmp_path, monkeypatch):
    """Falha de rede em uma fonte não derruba o pipeline: vira aviso."""

    def explode(*args, **kwargs):
        raise RuntimeError("rede indisponível (simulada)")

    monkeypatch.setattr(aq, "_baixar_fonte", explode)
    camadas, avisos = aq.adquirir_dados(
        ["vias_rodoviarias"],
        ["osm"],
        QgsRectangle(-48.0, -16.0, -47.9, -15.9),
        str(tmp_path),
        50000,
        usar_cache=False,
    )
    assert camadas == []
    assert len(avisos) == 1
    assert "rede indisponível" in avisos[0]


def test_adquirir_dados_usa_cache(qgis_app, tmp_path, monkeypatch):
    """Segunda execução não rebaixa: camada vem do downloads.gpkg."""
    bbox = QgsRectangle(-48.0, -16.0, -47.9, -15.9)
    pasta = str(tmp_path)

    chamadas = {"n": 0}

    def download_falso(fonte, classe, *args, **kwargs):
        chamadas["n"] += 1
        camada = QgsVectorLayer("LineString?crs=EPSG:4326", "t", "memory")
        feicao = QgsFeature()
        feicao.setGeometry(QgsGeometry.fromWkt("LINESTRING(0 0, 1 1)"))
        camada.dataProvider().addFeatures([feicao])
        camada.updateExtents()
        return camada

    monkeypatch.setattr(aq, "_baixar_fonte", download_falso)
    camadas1, avisos1 = aq.adquirir_dados(
        ["vias_rodoviarias"], ["osm"], bbox, pasta, 50000
    )
    camadas2, avisos2 = aq.adquirir_dados(
        ["vias_rodoviarias"], ["osm"], bbox, pasta, 50000
    )
    assert chamadas["n"] == 1  # segunda execução veio do cache
    assert not avisos1 and not avisos2
    assert camadas1[0][0].featureCount() == 1
    assert camadas2[0][0].featureCount() == 1


def test_adquirir_dados_filtra_classes_pela_escala(qgis_app, tmp_path, monkeypatch):
    """Edificações (escala_max=100k) não são baixadas em 1:250.000."""
    baixadas = []

    def download_falso(fonte, classe, *args, **kwargs):
        baixadas.append(classe["id"])
        return QgsVectorLayer("Polygon?crs=EPSG:4326", "t", "memory")

    monkeypatch.setattr(aq, "_baixar_fonte", download_falso)
    aq.adquirir_dados(
        ["edificacoes", "vias_rodoviarias"],
        ["osm"],
        QgsRectangle(0, 0, 0.1, 0.1),
        str(tmp_path),
        250000,
        usar_cache=False,
    )
    assert "edificacoes" not in baixadas
    assert "vias_rodoviarias" in baixadas
