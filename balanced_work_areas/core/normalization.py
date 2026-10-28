# -*- coding: utf-8 -*-
"""Etapa 2 — Normalização das feições para pontos de esforço.

Converte as camadas de insumo em uma única camada de pontos de esforço:

- pontos: mantidos (1 ponto = 1 unidade de esforço, tipo ``ponto``);
- linhas: segmentadas em trechos de comprimento ~``d``; o centroide de
  cada trecho vira um ponto de esforço (tipo ``linha``);
- polígonos: substituídos pelo ``pointOnSurface`` de cada parte, que
  garante ponto interno mesmo em geometrias côncavas (tipo ``poligono``).
"""

import math
from typing import Iterable, List, Optional, Tuple

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsGeometry,
    QgsPointXY,
    QgsVectorLayer,
    QgsWkbTypes,
)

from . import qgis_utils


def _pontos_de_ponto(geometria: QgsGeometry) -> List[QgsPointXY]:
    """Extrai os vértices de geometrias ponto/multiponto."""
    if geometria.isMultipart():
        return list(geometria.asMultiPoint())
    return [geometria.asPoint()]


def _pontos_de_linha(geometria: QgsGeometry, d: float) -> List[QgsPointXY]:
    """Centroides dos trechos de comprimento ~``d`` de cada parte da linha.

    A linha é dividida em ``ceil(L/d)`` trechos de comprimento igual
    (<= d); o ponto médio (ao longo do arco) de cada trecho é o ponto de
    esforço, o que preserva a contagem esperada ``~L/d`` da metodologia.
    """
    pontos: List[QgsPointXY] = []
    for parte in geometria.constParts():
        g = QgsGeometry(parte.clone())
        comprimento = g.length()
        if comprimento <= 0.0:
            continue
        n_trechos = max(1, int(math.ceil(comprimento / d)))
        tamanho = comprimento / n_trechos
        for i in range(n_trechos):
            p = g.interpolate((i + 0.5) * tamanho)
            if not p.isEmpty():
                pontos.append(p.asPoint())
    return pontos


def _pontos_de_poligono(geometria: QgsGeometry) -> List[QgsPointXY]:
    """``pointOnSurface`` de cada parte do (multi)polígono."""
    pontos: List[QgsPointXY] = []
    for parte in geometria.constParts():
        g = QgsGeometry(parte.clone())
        p = g.pointOnSurface()
        if not p.isEmpty():
            pontos.append(p.asPoint())
    return pontos


def normalizar_camadas(
    camadas: Iterable[Tuple[QgsVectorLayer, str, str]],
    d: float,
    crs_destino: QgsCoordinateReferenceSystem,
    moldura: Optional[QgsGeometry] = None,
    callback_progresso=None,
) -> QgsVectorLayer:
    """Gera a camada unificada de pontos de esforço (Etapa 2).

    :param camadas: iterável de tuplas ``(camada, classe_edgv, fonte)``.
    :param d: comprimento de segmentação de linhas (metros, no CRS destino).
    :param crs_destino: CRS de trabalho (UTM, métrico).
    :param moldura: se informada (no CRS destino), as feições são
        recortadas/filtradas pela moldura (necessário para camadas locais
        que extrapolam a área de interesse).
    :param callback_progresso: função ``(indice_camada, total)`` opcional.
    :returns: camada de pontos com ``tipo_primitiva``, ``classe_edgv``,
        ``fonte``.
    """
    saida = qgis_utils.criar_camada_pontos_esforco(crs_destino)
    lista = list(camadas)
    filtro_moldura = None
    if moldura is not None and not moldura.isEmpty():
        filtro_moldura = QgsGeometry(moldura)
        motor_moldura = QgsGeometry.createGeometryEngine(
            filtro_moldura.constGet()
        )
        motor_moldura.prepareGeometry()
    for indice, (camada, classe, fonte) in enumerate(lista):
        if camada is None or not camada.isValid():
            continue
        tipo_geometria = QgsWkbTypes.geometryType(camada.wkbType())
        if tipo_geometria == QgsWkbTypes.PointGeometry:
            tipo = "ponto"
        elif tipo_geometria == QgsWkbTypes.LineGeometry:
            tipo = "linha"
        elif tipo_geometria == QgsWkbTypes.PolygonGeometry:
            tipo = "poligono"
        else:
            continue
        crs_origem = camada.crs()
        pontos: List[QgsPointXY] = []
        for feicao in camada.getFeatures():
            if not feicao.hasGeometry():
                continue
            geometria = qgis_utils.geometria_valida(feicao.geometry())
            if geometria.isEmpty():
                continue
            geometria = qgis_utils.transformar_geometria(
                geometria, crs_origem, crs_destino
            )
            # Recorte pela moldura: linhas/polígonos são recortados;
            # pontos fora são descartados.
            if filtro_moldura is not None:
                if not motor_moldura.intersects(geometria.constGet()):
                    continue
                if tipo != "ponto" and not motor_moldura.contains(
                    geometria.constGet()
                ):
                    geometria = geometria.intersection(filtro_moldura)
                    if geometria.isEmpty():
                        continue
            if tipo == "ponto":
                candidatos = _pontos_de_ponto(geometria)
                if filtro_moldura is not None:
                    candidatos = [
                        p
                        for p in candidatos
                        if filtro_moldura.intersects(
                            QgsGeometry.fromPointXY(p).boundingBox()
                        )
                        and filtro_moldura.contains(
                            QgsGeometry.fromPointXY(p)
                        )
                    ]
                pontos.extend(candidatos)
            elif tipo == "linha":
                pontos.extend(_pontos_de_linha(geometria, d))
            else:
                pontos.extend(_pontos_de_poligono(geometria))
        qgis_utils.adicionar_pontos(saida, pontos, tipo, classe, fonte)
        if callback_progresso is not None:
            callback_progresso(indice + 1, len(lista))
    return saida
