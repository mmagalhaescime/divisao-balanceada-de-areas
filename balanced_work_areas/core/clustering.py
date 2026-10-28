# -*- coding: utf-8 -*-
"""Etapa 6 — Agrupamento contíguo das células e delegação de lotes.

Constrói o grafo de adjacência das células (arestas entre células que
compartilham fronteira linear — adjacência rook), aplica a heurística
gulosa de ``core.algorithms.agrupamento_guloso`` e dissolve as células de
cada lote em um único polígono.
"""

from typing import Dict, List, Sequence, Set

from qgis.core import QgsGeometry, QgsSpatialIndex, QgsFeature

from . import qgis_utils
from .algorithms import agrupamento_guloso  # noqa: F401  (reexportado)

# Comprimento mínimo de fronteira compartilhada (m) para considerar duas
# células adjacentes (adjacência rook — descarta contatos pontuais).
_TOLERANCIA_FRONTEIRA = 1e-6


def grafo_adjacencia(
    celulas: Sequence[QgsGeometry],
) -> Dict[int, Set[int]]:
    """Grafo de adjacência das células da partição.

    Duas células são adjacentes quando a interseção entre elas tem
    comprimento > 0 (fronteira compartilhada por aresta, não por vértice).

    :param celulas: geometrias das células (índice = id).
    :returns: dicionário ``id -> conjunto de ids vizinhos``.
    """
    indice = QgsSpatialIndex()
    for i, geometria in enumerate(celulas):
        feicao = QgsFeature(i)
        feicao.setGeometry(QgsGeometry(geometria))
        indice.addFeature(feicao)
    adjacencia: Dict[int, Set[int]] = {
        i: set() for i in range(len(celulas))
    }
    for i, geometria in enumerate(celulas):
        motor = QgsGeometry.createGeometryEngine(geometria.constGet())
        motor.prepareGeometry()
        for j in indice.intersects(geometria.boundingBox()):
            if j <= i:
                continue
            if not motor.intersects(celulas[j].constGet()):
                continue
            intersecao = geometria.intersection(celulas[j])
            if intersecao.isEmpty():
                continue
            if intersecao.length() > _TOLERANCIA_FRONTEIRA or (
                intersecao.area() > 0.0
            ):
                adjacencia[i].add(j)
                adjacencia[j].add(i)
    return adjacencia


def dissolver_lotes(
    celulas: Sequence[QgsGeometry],
    atribuicao: Dict[int, int],
    k: int,
) -> List[QgsGeometry]:
    """Dissolve as células de cada lote em um único polígono (Etapa 6).

    :param celulas: geometrias das células.
    :param atribuicao: dicionário célula -> índice do lote (0..k-1).
    :param k: número de lotes.
    :returns: lista de k geometrias (lotes sem células ficam vazios).
    """
    grupos: List[List[QgsGeometry]] = [[] for _ in range(k)]
    for id_celula, lote in atribuicao.items():
        if 0 <= lote < k:
            grupos[lote].append(QgsGeometry(celulas[id_celula]))
    lotes: List[QgsGeometry] = []
    for geometrias in grupos:
        if geometrias:
            uniao = QgsGeometry.unaryUnion(geometrias)
            lotes.append(qgis_utils.geometria_valida(uniao))
        else:
            lotes.append(QgsGeometry())
    return lotes
