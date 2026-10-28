# -*- coding: utf-8 -*-
"""Testes do catálogo de classes ET-EDGV (core/edgv_classes.py)."""

import pytest

from balanced_work_areas.core import edgv_classes as edgv


CATEGORIAS_OBRIGATORIAS = {
    "Edificações",
    "Vias de deslocamento",
    "Hidrografia",
    "Vegetação",
    "Energia e comunicações",
    "Limites",
    "Localidades",
    "Relevo (pontos cotados)",
    "Estrutura econômica",
    "Abastecimento e saneamento",
}


def test_todas_categorias_obrigatorias_presentes():
    categorias = {c["categoria"] for c in edgv.CLASSES_EDGV}
    faltando = CATEGORIAS_OBRIGATORIAS - categorias
    assert not faltando, "categorias ausentes: %s" % faltando


def test_ids_unicos():
    ids = [c["id"] for c in edgv.CLASSES_EDGV]
    assert len(ids) == len(set(ids))


def test_primitivas_validas():
    for c in edgv.CLASSES_EDGV:
        assert c["primitiva"] in edgv.PRIMITIVAS


def test_classes_por_primitiva_cobre_catalogo():
    grupos = edgv.classes_por_primitiva()
    total = sum(len(v) for v in grupos.values())
    assert total == len(edgv.CLASSES_EDGV)
    assert set(grupos) == set(edgv.PRIMITIVAS)


def test_mapeamentos_esperados():
    """Exemplos do enunciado: Edificações → OSM building + Open Buildings;
    Hidrografia linha → OSM waterway + ANA; Vias → OSM highway/railway."""
    edif = edgv.obter_classe("edificacoes")
    assert any("building" in f for f in edif["osm"])
    assert edif["google_open_buildings"] is True

    hidro = edgv.obter_classe("hidrografia_cursos")
    assert any("waterway" in f for f in hidro["osm"])
    assert "cursos_dagua" in hidro["ana"]

    vias = edgv.obter_classe("vias_rodoviarias")
    assert any("highway" in f for f in vias["osm"])
    ferro = edgv.obter_classe("vias_ferroviarias")
    assert any("railway" in f for f in ferro["osm"])


def test_obter_classe_inexistente():
    with pytest.raises(KeyError):
        edgv.obter_classe("nao_existe")


def test_filtrar_por_escala_remove_edificacoes_em_250k():
    ids = ["edificacoes", "vias_rodoviarias"]
    assert edgv.filtrar_por_escala(ids, 250000) == ["vias_rodoviarias"]
    assert edgv.filtrar_por_escala(ids, 50000) == ids


def test_elementos_osm_por_primitiva():
    assert edgv.elementos_osm("ponto") == ("node",)
    assert edgv.elementos_osm("linha") == ("way",)
    assert set(edgv.elementos_osm("poligono")) == {"way", "relation"}


def test_ids_padrao_nao_vazio():
    padrao = edgv.ids_padrao()
    assert "edificacoes" in padrao
    assert "vias_rodoviarias" in padrao
