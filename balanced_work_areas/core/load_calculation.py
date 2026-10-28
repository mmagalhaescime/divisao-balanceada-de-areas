# -*- coding: utf-8 -*-
"""Etapa 5 — Cálculo de carga ponderada por célula.

Para cada célula da partição (Voronoi ou grade regular):

    ci = alfa * n_ponto + beta * n_linha + gama * n_poligono

onde as contagens são de pontos de esforço por tipo de primitiva
originária, dentro da célula.
"""

from typing import Dict, List

from qgis.core import (
    QgsFeatureRequest,
    QgsGeometry,
    QgsSpatialIndex,
    QgsVectorLayer,
)


class CargaCelula:
    """Contagens e carga ponderada de uma célula da partição."""

    __slots__ = ("n_ponto", "n_linha", "n_poligono", "carga")

    def __init__(self, n_ponto=0, n_linha=0, n_poligono=0, carga=0.0):
        self.n_ponto = n_ponto
        self.n_linha = n_linha
        self.n_poligono = n_poligono
        self.carga = carga


def calcular_cargas(
    celulas: List[QgsGeometry],
    camada_pontos: QgsVectorLayer,
    alfa: float,
    beta: float,
    gama: float,
    callback_progresso=None,
) -> Dict[int, CargaCelula]:
    """Calcula a carga ponderada de cada célula da partição.

    Cada ponto de esforço é atribuído a no máximo uma célula (a primeira
    que o contém, em caso de ponto exatamente na fronteira), de modo que
    a soma das cargas das células equivale ao total da área.

    :param celulas: geometrias das células (índice = id da célula).
    :param camada_pontos: camada de pontos de esforço (Etapa 2).
    :param alfa: peso de aquisição de pontos.
    :param beta: peso de aquisição de linhas.
    :param gama: peso de aquisição de polígonos.
    :param callback_progresso: função ``(indice, total)`` opcional.
    :returns: dicionário ``id da célula -> CargaCelula``.
    """
    indice_espacial = QgsSpatialIndex(camada_pontos.getFeatures())
    campo_tipo = camada_pontos.fields().indexOf("tipo_primitiva")
    cargas: Dict[int, CargaCelula] = {}
    atribuidos = set()
    for id_celula, geometria in enumerate(celulas):
        motor = QgsGeometry.createGeometryEngine(geometria.constGet())
        motor.prepareGeometry()
        carga = CargaCelula()
        candidatos = indice_espacial.intersects(geometria.boundingBox())
        if candidatos:
            requisicao = QgsFeatureRequest().setFilterFids(candidatos)
            requisicao.setSubsetOfAttributes([campo_tipo])
            for feicao in camada_pontos.getFeatures(requisicao):
                if feicao.id() in atribuidos:
                    continue
                if not motor.intersects(feicao.geometry().constGet()):
                    continue
                atribuidos.add(feicao.id())
                tipo = feicao.attribute(campo_tipo)
                if tipo == "ponto":
                    carga.n_ponto += 1
                elif tipo == "linha":
                    carga.n_linha += 1
                else:
                    carga.n_poligono += 1
        carga.carga = (
            alfa * carga.n_ponto
            + beta * carga.n_linha
            + gama * carga.n_poligono
        )
        cargas[id_celula] = carga
        if callback_progresso is not None:
            callback_progresso(id_celula + 1, len(celulas))
    return cargas
