# -*- coding: utf-8 -*-
"""Testes dos algoritmos puros (core/algorithms.py)."""

import math
import random

import pytest

from balanced_work_areas.core import algorithms as alg


# ------------------------------ fuso UTM ------------------------------


def test_fuso_utm_brasilia():
    """Brasília (lon -47.9) está no fuso 23S → EPSG 31983."""
    fuso, epsg = alg.detectar_fuso_utm(-47.9, -15.8)
    assert fuso == 23
    assert epsg == 31983


def test_fuso_utm_extremos_brasil():
    """Extremos oeste (Acre, fuso 18/19) e leste (Noronha, fuso 25)."""
    assert alg.detectar_fuso_utm(-73.8, -7.5)[0] == 18
    assert alg.detectar_fuso_utm(-32.4, -3.85) == (25, 31985)


def test_fuso_utm_grampeado_para_intervalo_brasileiro():
    """Longitudes fora do Brasil são grampeadas para [18, 25]."""
    assert alg.detectar_fuso_utm(-120.0, 40.0)[0] == 18
    assert alg.detectar_fuso_utm(10.0, 50.0)[0] == 25


def test_fuso_utm_coordenada_invalida():
    with pytest.raises(ValueError):
        alg.detectar_fuso_utm(-500.0, 0.0)


# --------------------------- defaults escala --------------------------


def test_defaults_por_escala_tabelada():
    assert alg.defaults_por_escala(50000) == {"d": 100.0, "r": 500.0}


def test_defaults_por_escala_nao_tabelada_usa_vizinha():
    assert alg.defaults_por_escala(60000) == alg.defaults_por_escala(50000)


# ------------------------ alocação de geradores -----------------------


def test_alocacao_soma_exata():
    pesos = [1.0, 2.0, 3.0, 4.0]
    aloc = alg.alocar_geradores(pesos, 100)
    assert sum(aloc) == 100


def test_alocacao_proporcional():
    aloc = alg.alocar_geradores([1.0, 1.0, 2.0], 40)
    assert aloc == [10, 10, 20]


def test_alocacao_pesos_nulos_distribui_uniforme():
    aloc = alg.alocar_geradores([0.0, 0.0, 0.0], 10)
    assert sum(aloc) == 10
    assert max(aloc) - min(aloc) <= 1


def test_alocacao_celula_sem_dados_recebe_zero():
    aloc = alg.alocar_geradores([0.0, 5.0], 10)
    assert aloc == [0, 10]


def test_alocacao_n_zero():
    assert alg.alocar_geradores([1.0, 2.0], 0) == [0, 0]


# ---------------------------- disco de Poisson ------------------------


def test_poisson_disk_respeita_distancia_minima():
    rng = random.Random(42)
    raio = 10.0
    pontos = alg.poisson_disk(200.0, 100.0, raio, rng=rng)
    assert len(pontos) > 10
    for i, p in enumerate(pontos):
        assert 0.0 <= p[0] <= 200.0
        assert 0.0 <= p[1] <= 100.0
        for q in pontos[i + 1 :]:
            assert math.hypot(p[0] - q[0], p[1] - q[1]) >= raio - 1e-9


def test_poisson_disk_reprodutivel_com_seed():
    p1 = alg.poisson_disk(100.0, 100.0, 8.0, rng=random.Random(7))
    p2 = alg.poisson_disk(100.0, 100.0, 8.0, rng=random.Random(7))
    assert p1 == p2


def test_poisson_disk_limite_n_max():
    pontos = alg.poisson_disk(1000.0, 1000.0, 5.0, rng=random.Random(1), n_max=20)
    assert len(pontos) == 20


def test_poisson_disk_dominio_invalido():
    assert alg.poisson_disk(0.0, 10.0, 5.0) == []


# ------------------------------ cargas-alvo ---------------------------


def test_cargas_alvo_proporcionais_experiencia():
    alvos = alg.cargas_alvo(300.0, [1.0, 2.0])
    assert alvos == [100.0, 200.0]


def test_cargas_alvo_vazio():
    assert alg.cargas_alvo(100.0, []) == []


# --------------------------- agrupamento guloso -----------------------


def _grade_adjacencia(ncols, nlins):
    """Grafo de adjacência rook de uma grade ncols x nlins."""
    adj = {}
    for lin in range(nlins):
        for col in range(ncols):
            i = lin * ncols + col
            viz = set()
            if col > 0:
                viz.add(i - 1)
            if col < ncols - 1:
                viz.add(i + 1)
            if lin > 0:
                viz.add(i - ncols)
            if lin < nlins - 1:
                viz.add(i + ncols)
            adj[i] = viz
    return adj


def _conexo(celulas, adjacencia):
    """Verifica por BFS se o conjunto de células é conexo."""
    celulas = set(celulas)
    if not celulas:
        return True
    inicio = next(iter(celulas))
    visitado = {inicio}
    fila = [inicio]
    while fila:
        atual = fila.pop()
        for v in adjacencia[atual]:
            if v in celulas and v not in visitado:
                visitado.add(v)
                fila.append(v)
    return visitado == celulas


def test_agrupamento_atribui_todas_e_conexo():
    """Grade 6x6 uniforme, 4 operadores iguais: cobertura total + conexidade."""
    ncols = nlins = 6
    adj = _grade_adjacencia(ncols, nlins)
    cargas = {i: 1.0 for i in range(ncols * nlins)}
    alvos = alg.cargas_alvo(sum(cargas.values()), [1.0] * 4)
    atrib = alg.agrupamento_guloso(adj, cargas, alvos)
    assert set(atrib) == set(cargas)  # todas as células atribuídas
    for j in range(4):
        lote = [c for c, g in atrib.items() if g == j]
        assert lote, "lote %d vazio" % j
        assert _conexo(lote, adj), "lote %d desconexo" % j


def test_agrupamento_balanceado_caso_uniforme():
    """No caso uniforme o CV das cargas finais deve ser baixo."""
    ncols = nlins = 8
    adj = _grade_adjacencia(ncols, nlins)
    cargas = {i: 1.0 for i in range(ncols * nlins)}
    alvos = alg.cargas_alvo(64.0, [1.0] * 4)
    atrib = alg.agrupamento_guloso(adj, cargas, alvos)
    finais = [0.0] * 4
    for c, j in atrib.items():
        finais[j] += cargas[c]
    assert alg.coeficiente_variacao(finais) < 0.25


def test_agrupamento_respeita_experiencia():
    """Operador mais experiente (ej maior) recebe carga maior."""
    ncols = nlins = 6
    adj = _grade_adjacencia(ncols, nlins)
    cargas = {i: 1.0 for i in range(ncols * nlins)}
    alvos = alg.cargas_alvo(36.0, [3.0, 1.0])  # 27 / 9
    atrib = alg.agrupamento_guloso(adj, cargas, alvos)
    finais = [0.0, 0.0]
    for c, j in atrib.items():
        finais[j] += cargas[c]
    assert finais[0] > finais[1]


def test_agrupamento_grafo_desconexo_nao_perde_celulas():
    """Moldura multipolígono (grafo desconexo): tudo ainda é atribuído."""
    adj = {0: {1}, 1: {0}, 2: {3}, 3: {2}}  # dois pares isolados
    cargas = {0: 1.0, 1: 1.0, 2: 1.0, 3: 1.0}
    atrib = alg.agrupamento_guloso(adj, cargas, alg.cargas_alvo(4.0, [1.0, 1.0]))
    assert set(atrib) == {0, 1, 2, 3}


def test_agrupamento_k_maior_que_celulas():
    """k > número de células: nenhum erro e todas as células atribuídas."""
    adj = {0: {1}, 1: {0}}
    cargas = {0: 1.0, 1: 1.0}
    atrib = alg.agrupamento_guloso(adj, cargas, alg.cargas_alvo(2.0, [1.0] * 5))
    assert set(atrib) == {0, 1}
    assert all(0 <= j < 5 for j in atrib.values())


# ------------------------- coeficiente de variação --------------------


def test_cv_valores_iguais_zero():
    assert alg.coeficiente_variacao([5.0, 5.0, 5.0]) == 0.0


def test_cv_conhecido():
    # média 3, desvio populacional sqrt(2) → CV = sqrt(2)/3
    assert alg.coeficiente_variacao([1.0, 3.0, 5.0]) == pytest.approx(
        math.sqrt(8.0 / 3.0) / 3.0
    )


def test_cv_lista_vazia():
    assert alg.coeficiente_variacao([]) == 0.0
