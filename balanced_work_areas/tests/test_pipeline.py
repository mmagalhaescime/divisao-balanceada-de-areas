# -*- coding: utf-8 -*-
"""Teste integrado do pipeline ponta a ponta com dados mock (sem rede)."""

import random

import pytest

pytest.importorskip("qgis")

from qgis.core import (  # noqa: E402
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsGeometry,
    QgsVectorLayer,
)

from balanced_work_areas.core import pipeline  # noqa: E402

CRS_TESTE = "EPSG:31983"


def _camada(tipo, wkts):
    camada = QgsVectorLayer("%s?crs=%s" % (tipo, CRS_TESTE), "mock", "memory")
    feicoes = []
    for wkt in wkts:
        f = QgsFeature()
        f.setGeometry(QgsGeometry.fromWkt(wkt))
        feicoes.append(f)
    camada.dataProvider().addFeatures(feicoes)
    camada.updateExtents()
    return camada


def _parametros_mock(tmp_path, metodo, k=3):
    """Cenário sintético: moldura 4x4 km com dados concentrados a oeste."""
    rng = random.Random(2024)
    pontos = [
        "POINT(%f %f)" % (rng.uniform(0, 2000), rng.uniform(0, 4000))
        for _ in range(120)
    ] + [
        "POINT(%f %f)" % (rng.uniform(2000, 4000), rng.uniform(0, 4000))
        for _ in range(30)
    ]
    linhas = [
        "LINESTRING(%f %f, %f %f)"
        % (
            rng.uniform(0, 3000),
            rng.uniform(0, 4000),
            rng.uniform(0, 3000),
            rng.uniform(0, 4000),
        )
        for _ in range(20)
    ]
    poligonos = [
        "POLYGON((%f %f, %f %f, %f %f, %f %f))"
        % tuple(
            v
            for x, y in [(x0, y0), (x0 + 80, y0), (x0 + 80, y0 + 80), (x0, y0)]
            for v in (x, y)
        )
        for x0, y0 in (
            (rng.uniform(0, 1800), rng.uniform(0, 3800)) for _ in range(40)
        )
    ]

    parametros = pipeline.ParametrosPipeline()
    parametros.moldura = QgsGeometry.fromWkt(
        "POLYGON((0 0, 4000 0, 4000 4000, 0 4000, 0 0))"
    )
    parametros.crs_moldura = QgsCoordinateReferenceSystem(CRS_TESTE)
    parametros.crs_saida = QgsCoordinateReferenceSystem(CRS_TESTE)
    parametros.k = k
    parametros.metodo = metodo
    parametros.multiplicador_n = 20
    # m maior que o padrão (m=k) para dar granularidade suficiente ao
    # balanceamento no cenário de densidade assimétrica deste mock.
    parametros.fator_subdivisao_m = 8
    parametros.camadas_locais = [
        (_camada("Point", pontos), "pontos_mock"),
        (_camada("LineString", linhas), "linhas_mock"),
        (_camada("Polygon", poligonos), "poligonos_mock"),
    ]
    parametros.pasta_trabalho = str(tmp_path)
    parametros.d = 100.0
    parametros.r = 500.0
    parametros.operadores = [
        ("Operador %d" % (j + 1), 1.0) for j in range(k)
    ]
    parametros.seed = 42
    return parametros


@pytest.mark.parametrize(
    "metodo", [pipeline.METODO_VORONOI, pipeline.METODO_GRADE]
)
def test_pipeline_ponta_a_ponta(qgis_app, tmp_path, metodo):
    parametros = _parametros_mock(tmp_path, metodo)
    parametros.validar()
    progresso = []
    resultado = pipeline.executar_pipeline(
        parametros, progresso=progresso.append
    )

    # Progresso monotônico até 100.
    assert progresso[-1] == 100.0
    assert all(b >= a for a, b in zip(progresso, progresso[1:]))

    # Lotes: um por operador, cobrindo toda a moldura.
    assert len(resultado.lotes) == 3
    assert all(not l.geometria.isEmpty() for l in resultado.lotes)
    soma_areas = sum(l.geometria.area() for l in resultado.lotes)
    assert soma_areas == pytest.approx(parametros.moldura.area(), rel=1e-3)

    # Cargas: soma dos lotes = total dos pontos de esforço ponderados.
    assert resultado.n_pontos_esforco > 150
    total_contagens = sum(
        l.n_pontos + l.n_linhas + l.n_poligonos for l in resultado.lotes
    )
    assert total_contagens == resultado.n_pontos_esforco
    assert resultado.cv < 0.5

    # GeoPackage gravado e legível, com todos os atributos da Etapa 7.
    camada = QgsVectorLayer(
        "%s|layername=lotes_trabalho" % resultado.caminho_gpkg,
        "lotes",
        "ogr",
    )
    assert camada.isValid()
    assert camada.featureCount() == 3
    nomes_campos = [c.name() for c in camada.fields()]
    for campo in (
        "operador",
        "fator_experiencia",
        "carga_alvo",
        "carga_total",
        "n_pontos",
        "n_linhas",
        "n_poligonos",
        "desvio_percentual",
    ):
        assert campo in nomes_campos


def test_pipeline_respeita_experiencia(qgis_app, tmp_path):
    parametros = _parametros_mock(tmp_path, pipeline.METODO_GRADE, k=2)
    parametros.operadores = [("Veterano", 2.0), ("Novato", 1.0)]
    resultado = pipeline.executar_pipeline(parametros)
    cargas = {l.operador: l.carga_total for l in resultado.lotes}
    assert cargas["Veterano"] > cargas["Novato"]


def test_pipeline_cancelamento(qgis_app, tmp_path):
    parametros = _parametros_mock(tmp_path, pipeline.METODO_GRADE)
    with pytest.raises(InterruptedError):
        pipeline.executar_pipeline(parametros, cancelado=lambda: True)


def test_pipeline_validacao_pesos(qgis_app, tmp_path):
    parametros = _parametros_mock(tmp_path, pipeline.METODO_VORONOI)
    parametros.alfa, parametros.beta, parametros.gama = 3.0, 2.0, 1.0
    with pytest.raises(ValueError):
        parametros.validar()


def test_pipeline_sem_insumos_erro(qgis_app, tmp_path):
    parametros = _parametros_mock(tmp_path, pipeline.METODO_VORONOI)
    parametros.camadas_locais = []
    parametros.fontes = []
    with pytest.raises(ValueError):
        parametros.validar()


def test_pipeline_moldura_com_buraco(qgis_app, tmp_path):
    """Caso-limite: moldura com buraco — lotes não cobrem o buraco."""
    parametros = _parametros_mock(tmp_path, pipeline.METODO_GRADE)
    parametros.moldura = QgsGeometry.fromWkt(
        "POLYGON((0 0, 4000 0, 4000 4000, 0 4000, 0 0),"
        "(1500 1500, 2500 1500, 2500 2500, 1500 2500, 1500 1500))"
    )
    resultado = pipeline.executar_pipeline(parametros)
    soma = sum(l.geometria.area() for l in resultado.lotes)
    assert soma == pytest.approx(parametros.moldura.area(), rel=1e-3)


def test_pipeline_moldura_multipoligono(qgis_app, tmp_path):
    """Caso-limite: moldura multipolígono (duas ilhas)."""
    parametros = _parametros_mock(tmp_path, pipeline.METODO_GRADE)
    parametros.moldura = QgsGeometry.fromWkt(
        "MULTIPOLYGON(((0 0, 1800 0, 1800 4000, 0 4000, 0 0)),"
        "((2200 0, 4000 0, 4000 4000, 2200 4000, 2200 0)))"
    )
    resultado = pipeline.executar_pipeline(parametros)
    soma = sum(l.geometria.area() for l in resultado.lotes)
    assert soma == pytest.approx(parametros.moldura.area(), rel=1e-3)
