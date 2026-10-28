# -*- coding: utf-8 -*-
"""Testes dos módulos core que dependem do QGIS (rodar com python-qgis)."""

import pytest

pytest.importorskip("qgis")

from qgis.core import (  # noqa: E402
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsGeometry,
    QgsVectorLayer,
)

from balanced_work_areas.core import (  # noqa: E402
    algorithms,
    clustering,
    density_grid,
    grid_partition,
    load_calculation,
    normalization,
    qgis_utils,
    voronoi_partition,
)

CRS_TESTE = "EPSG:31983"


def _camada_memoria(tipo, wkts, qgis_app):
    """Camada em memória com geometrias a partir de WKT."""
    camada = QgsVectorLayer("%s?crs=%s" % (tipo, CRS_TESTE), "t", "memory")
    feicoes = []
    for wkt in wkts:
        f = QgsFeature()
        f.setGeometry(QgsGeometry.fromWkt(wkt))
        feicoes.append(f)
    camada.dataProvider().addFeatures(feicoes)
    camada.updateExtents()
    return camada


def _moldura_quadrada(lado=1000.0):
    return QgsGeometry.fromWkt(
        "POLYGON((0 0, %s 0, %s %s, 0 %s, 0 0))" % (lado, lado, lado, lado)
    )


# ------------------------------ qgis_utils ----------------------------


def test_moldura_unificada_multiplas_feicoes(qgis_app):
    camada = _camada_memoria(
        "Polygon",
        [
            "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))",
            "POLYGON((10 0, 20 0, 20 10, 10 10, 10 0))",
        ],
        qgis_app,
    )
    uniao = qgis_utils.moldura_unificada(camada)
    assert uniao.area() == pytest.approx(200.0)


def test_moldura_unificada_sem_feicoes_erro(qgis_app):
    camada = _camada_memoria("Polygon", [], qgis_app)
    with pytest.raises(ValueError):
        qgis_utils.moldura_unificada(camada)


def test_geometria_valida_conserta_bowtie(qgis_app):
    invalida = QgsGeometry.fromWkt(
        "POLYGON((0 0, 10 10, 10 0, 0 10, 0 0))"
    )
    consertada = qgis_utils.geometria_valida(invalida)
    assert consertada.isGeosValid()


# ----------------------------- normalização ---------------------------


def test_normalizacao_pontos_mantidos(qgis_app):
    camada = _camada_memoria(
        "Point", ["POINT(10 10)", "POINT(20 20)", "POINT(30 30)"], qgis_app
    )
    crs = QgsCoordinateReferenceSystem(CRS_TESTE)
    saida = normalization.normalizar_camadas(
        [(camada, "localidades_ponto", "teste")], d=100.0, crs_destino=crs
    )
    feicoes = list(saida.getFeatures())
    assert len(feicoes) == 3
    assert all(f["tipo_primitiva"] == "ponto" for f in feicoes)
    assert all(f["classe_edgv"] == "localidades_ponto" for f in feicoes)


def test_normalizacao_linha_segmentada(qgis_app):
    # Linha de 1000 m com d = 100 m → 10 pontos de esforço.
    camada = _camada_memoria("LineString", ["LINESTRING(0 0, 1000 0)"], qgis_app)
    crs = QgsCoordinateReferenceSystem(CRS_TESTE)
    saida = normalization.normalizar_camadas(
        [(camada, "vias_rodoviarias", "teste")], d=100.0, crs_destino=crs
    )
    feicoes = list(saida.getFeatures())
    assert len(feicoes) == 10
    assert all(f["tipo_primitiva"] == "linha" for f in feicoes)
    # Primeiro centroide no meio do primeiro trecho (x = 50).
    xs = sorted(f.geometry().asPoint().x() for f in feicoes)
    assert xs[0] == pytest.approx(50.0)
    assert xs[-1] == pytest.approx(950.0)


def test_normalizacao_poligono_ponto_interno(qgis_app):
    poligono = "POLYGON((0 0, 100 0, 100 100, 0 100, 0 0))"
    camada = _camada_memoria("Polygon", [poligono], qgis_app)
    crs = QgsCoordinateReferenceSystem(CRS_TESTE)
    saida = normalization.normalizar_camadas(
        [(camada, "edificacoes", "teste")], d=100.0, crs_destino=crs
    )
    feicoes = list(saida.getFeatures())
    assert len(feicoes) == 1
    assert feicoes[0]["tipo_primitiva"] == "poligono"
    assert QgsGeometry.fromWkt(poligono).contains(feicoes[0].geometry())


def test_normalizacao_recorta_pela_moldura(qgis_app):
    # Dois pontos, um dentro e um fora da moldura.
    camada = _camada_memoria(
        "Point", ["POINT(10 10)", "POINT(5000 5000)"], qgis_app
    )
    crs = QgsCoordinateReferenceSystem(CRS_TESTE)
    saida = normalization.normalizar_camadas(
        [(camada, "localidades_ponto", "teste")],
        d=100.0,
        crs_destino=crs,
        moldura=_moldura_quadrada(1000.0),
    )
    assert len(list(saida.getFeatures())) == 1


# ---------------------------- grade densidade -------------------------


def test_grade_densidade_dimensoes(qgis_app):
    celulas = density_grid.construir_grade(_moldura_quadrada(1000.0), 250.0)
    assert len(celulas) == 16
    assert celulas[0].id == 0 and celulas[-1].id == 15


def test_grade_densidade_contagem(qgis_app):
    moldura = _moldura_quadrada(1000.0)
    celulas = density_grid.construir_grade(moldura, 500.0)
    camada = _camada_memoria(
        "Point", ["POINT(100 100)", "POINT(200 200)", "POINT(900 900)"], qgis_app
    )
    pesos = density_grid.contar_pontos_por_celula(celulas, camada)
    assert sum(pesos.values()) == 3.0
    # Célula inferior-esquerda concentra 2 pontos.
    assert max(pesos.values()) == 2.0


def test_grade_densidade_r_invalido(qgis_app):
    with pytest.raises(ValueError):
        density_grid.construir_grade(_moldura_quadrada(), 0.0)


# ------------------------------- voronoi ------------------------------


def _particao_voronoi_teste(qgis_app, moldura, n=40):
    celulas = density_grid.construir_grade(moldura, 250.0)
    pesos = {c.id: 1.0 for c in celulas}
    geradores = voronoi_partition.gerar_geradores(
        celulas, pesos, n, moldura, seed=123
    )
    return geradores, voronoi_partition.diagrama_voronoi(
        geradores, moldura, CRS_TESTE
    )


def test_voronoi_cobre_moldura(qgis_app):
    moldura = _moldura_quadrada(1000.0)
    geradores, particao = _particao_voronoi_teste(qgis_app, moldura)
    assert len(geradores) > 30
    soma_areas = sum(g.area() for g in particao)
    assert soma_areas == pytest.approx(moldura.area(), rel=1e-3)


def test_voronoi_reprodutivel_com_seed(qgis_app):
    moldura = _moldura_quadrada(1000.0)
    celulas = density_grid.construir_grade(moldura, 250.0)
    pesos = {c.id: 1.0 for c in celulas}
    g1 = voronoi_partition.gerar_geradores(celulas, pesos, 40, moldura, seed=7)
    g2 = voronoi_partition.gerar_geradores(celulas, pesos, 40, moldura, seed=7)
    assert [(p.x(), p.y()) for p in g1] == [(p.x(), p.y()) for p in g2]


def test_voronoi_scipy_fallback(qgis_app):
    pytest.importorskip("scipy")
    moldura = _moldura_quadrada(1000.0)
    celulas = density_grid.construir_grade(moldura, 250.0)
    pesos = {c.id: 1.0 for c in celulas}
    geradores = voronoi_partition.gerar_geradores(
        celulas, pesos, 40, moldura, seed=5
    )
    brutas = voronoi_partition._voronoi_scipy(geradores)
    recortadas = [g.intersection(moldura) for g in brutas]
    soma = sum(g.area() for g in recortadas if not g.isEmpty())
    assert soma == pytest.approx(moldura.area(), rel=1e-3)


def test_voronoi_poucos_geradores_devolve_moldura(qgis_app):
    moldura = _moldura_quadrada(100.0)
    from qgis.core import QgsPointXY

    particao = voronoi_partition.diagrama_voronoi(
        [QgsPointXY(50, 50)], moldura, CRS_TESTE
    )
    assert len(particao) == 1
    assert particao[0].area() == pytest.approx(moldura.area())


def test_alocacao_geradores_celula_sem_dados(qgis_app):
    """Célula com wi = 0 não recebe geradores."""
    moldura = _moldura_quadrada(1000.0)
    celulas = density_grid.construir_grade(moldura, 500.0)
    pesos = {c.id: 0.0 for c in celulas}
    pesos[0] = 10.0
    geradores = voronoi_partition.gerar_geradores(
        celulas, pesos, 20, moldura, seed=3
    )
    ret0 = celulas[0].retangulo
    assert geradores
    assert all(ret0.contains(p) for p in geradores)


# ---------------------------- grade regular ---------------------------


def test_grade_regular_numero_e_area(qgis_app):
    moldura = _moldura_quadrada(1200.0)
    quadrados = grid_partition.gerar_grade_regular(moldura, k=6, m=6)
    assert len(quadrados) == 36
    soma = sum(q.area() for q in quadrados)
    assert soma == pytest.approx(moldura.area(), rel=1e-6)


def test_grade_regular_recorta_borda(qgis_app):
    # Moldura triangular: quadrados de borda são parciais.
    moldura = QgsGeometry.fromWkt(
        "POLYGON((0 0, 1000 0, 0 1000, 0 0))"
    )
    quadrados = grid_partition.gerar_grade_regular(moldura, k=4, m=4)
    soma = sum(q.area() for q in quadrados)
    assert soma == pytest.approx(moldura.area(), rel=1e-6)
    assert any(q.area() < (1000.0 * 1000.0) / 16.0 - 1.0 for q in quadrados)


def test_grade_regular_parametros_invalidos(qgis_app):
    with pytest.raises(ValueError):
        grid_partition.gerar_grade_regular(_moldura_quadrada(), 1, 4)
    with pytest.raises(ValueError):
        grid_partition.gerar_grade_regular(_moldura_quadrada(), 4, 0)


# -------------------------- cálculo de carga --------------------------


def test_calculo_carga_ponderada(qgis_app):
    crs = QgsCoordinateReferenceSystem(CRS_TESTE)
    saida = qgis_utils.criar_camada_pontos_esforco(crs)
    from qgis.core import QgsPointXY

    qgis_utils.adicionar_pontos(
        saida, [QgsPointXY(10, 10)], "ponto", "c", "f"
    )
    qgis_utils.adicionar_pontos(
        saida, [QgsPointXY(20, 20), QgsPointXY(30, 30)], "linha", "c", "f"
    )
    qgis_utils.adicionar_pontos(
        saida, [QgsPointXY(40, 40)], "poligono", "c", "f"
    )
    celulas = [_moldura_quadrada(100.0)]
    cargas = load_calculation.calcular_cargas(
        celulas, saida, alfa=1.0, beta=2.0, gama=3.0
    )
    c = cargas[0]
    assert (c.n_ponto, c.n_linha, c.n_poligono) == (1, 2, 1)
    assert c.carga == pytest.approx(1.0 * 1 + 2.0 * 2 + 3.0 * 1)


def test_calculo_carga_ponto_fronteira_conta_uma_vez(qgis_app):
    """Ponto na fronteira de duas células é atribuído a apenas uma."""
    crs = QgsCoordinateReferenceSystem(CRS_TESTE)
    saida = qgis_utils.criar_camada_pontos_esforco(crs)
    from qgis.core import QgsPointXY

    qgis_utils.adicionar_pontos(
        saida, [QgsPointXY(50.0, 25.0)], "ponto", "c", "f"
    )
    esquerda = QgsGeometry.fromWkt("POLYGON((0 0,50 0,50 50,0 50,0 0))")
    direita = QgsGeometry.fromWkt("POLYGON((50 0,100 0,100 50,50 50,50 0))")
    cargas = load_calculation.calcular_cargas(
        [esquerda, direita], saida, 1.0, 2.0, 3.0
    )
    total = cargas[0].n_ponto + cargas[1].n_ponto
    assert total == 1


# ------------------------------ clustering ----------------------------


def test_grafo_adjacencia_rook(qgis_app):
    # Grade 2x2 de quadrados: cada célula tem exatamente 2 vizinhos rook
    # (o contato diagonal por vértice não conta).
    quadrados = [
        QgsGeometry.fromWkt("POLYGON((0 0,10 0,10 10,0 10,0 0))"),
        QgsGeometry.fromWkt("POLYGON((10 0,20 0,20 10,10 10,10 0))"),
        QgsGeometry.fromWkt("POLYGON((0 10,10 10,10 20,0 20,0 10))"),
        QgsGeometry.fromWkt("POLYGON((10 10,20 10,20 20,10 20,10 10))"),
    ]
    adj = clustering.grafo_adjacencia(quadrados)
    assert adj[0] == {1, 2}
    assert adj[3] == {1, 2}


def test_dissolver_lotes(qgis_app):
    quadrados = [
        QgsGeometry.fromWkt("POLYGON((0 0,10 0,10 10,0 10,0 0))"),
        QgsGeometry.fromWkt("POLYGON((10 0,20 0,20 10,10 10,10 0))"),
        QgsGeometry.fromWkt("POLYGON((0 10,10 10,10 20,0 20,0 10))"),
    ]
    lotes = clustering.dissolver_lotes(
        quadrados, {0: 0, 1: 0, 2: 1}, k=2
    )
    assert lotes[0].area() == pytest.approx(200.0)
    assert lotes[1].area() == pytest.approx(100.0)


def test_pipeline_agrupamento_com_geometrias(qgis_app):
    """Integração: grade regular → cargas → agrupamento → dissolve."""
    moldura = _moldura_quadrada(1200.0)
    quadrados = grid_partition.gerar_grade_regular(moldura, k=4, m=4)
    crs = QgsCoordinateReferenceSystem(CRS_TESTE)
    pontos = qgis_utils.criar_camada_pontos_esforco(crs)
    from qgis.core import QgsPointXY
    import random as rnd

    gerador = rnd.Random(99)
    qgis_utils.adicionar_pontos(
        pontos,
        [
            QgsPointXY(gerador.uniform(0, 1200), gerador.uniform(0, 1200))
            for _ in range(400)
        ],
        "ponto",
        "c",
        "f",
    )
    cargas = load_calculation.calcular_cargas(quadrados, pontos, 1, 2, 3)
    adj = clustering.grafo_adjacencia(quadrados)
    alvos = algorithms.cargas_alvo(
        sum(c.carga for c in cargas.values()), [1.0] * 4
    )
    atrib = algorithms.agrupamento_guloso(
        adj, {i: c.carga for i, c in cargas.items()}, alvos
    )
    assert set(atrib) == set(range(len(quadrados)))
    lotes = clustering.dissolver_lotes(quadrados, atrib, 4)
    soma = sum(l.area() for l in lotes if not l.isEmpty())
    assert soma == pytest.approx(moldura.area(), rel=1e-6)
    finais = [0.0] * 4
    for i, j in atrib.items():
        finais[j] += cargas[i].carga
    assert algorithms.coeficiente_variacao(finais) < 0.35
