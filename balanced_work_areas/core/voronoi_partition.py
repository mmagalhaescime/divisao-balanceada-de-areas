# -*- coding: utf-8 -*-
"""Etapa 4 — Partição por Diagrama de Voronoi adaptativo ponderado.

Aloca N geradores proporcionalmente aos pesos da grade auxiliar
(N = multiplicador x k), posiciona-os por amostragem por disco de Poisson
(Bridson) dentro de cada célula (delta = sqrt(Ai/ni) x fator) e gera o
Diagrama de Voronoi recortado pela moldura.

O diagrama usa preferencialmente ``native:voronoipolygons`` (framework
Processing). Se o algoritmo não estiver disponível, usa o fallback
``scipy.spatial.Voronoi`` (dependência opcional); sem ambos, uma
``RuntimeError`` explica a limitação ao usuário.
"""

import math
import random
from typing import Dict, List, Optional

from qgis.core import (
    QgsApplication,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsVectorLayer,
)

from . import qgis_utils
from .algorithms import alocar_geradores, poisson_disk
from .density_grid import CelulaGrade

# Tentativas de reamostragem com delta reduzido quando o disco de Poisson
# não atinge o número de geradores desejado na célula.
_MAX_TENTATIVAS_DELTA = 5
_FATOR_REDUCAO_DELTA = 0.8


def gerar_geradores(
    celulas: List[CelulaGrade],
    pesos: Dict[int, float],
    n_total: int,
    moldura: QgsGeometry,
    fator_delta: float = 1.0,
    seed: Optional[int] = None,
) -> List[QgsPointXY]:
    """Posiciona os N geradores do Voronoi por disco de Poisson.

    :param celulas: células da grade auxiliar (Etapa 3).
    :param pesos: peso wi de cada célula (contagem de pontos de esforço).
    :param n_total: número total de geradores N (múltiplo de k).
    :param moldura: geometria da moldura (para descartar geradores fora).
    :param fator_delta: fator de ajuste da distância mínima delta.
    :param seed: semente para reprodutibilidade (opcional).
    :returns: lista de geradores dentro da moldura.
    """
    lista_pesos = [pesos.get(c.id, 0.0) for c in celulas]
    alocacao = alocar_geradores(lista_pesos, n_total)
    motor = QgsGeometry.createGeometryEngine(moldura.constGet())
    motor.prepareGeometry()
    geradores: List[QgsPointXY] = []
    for celula, ni in zip(celulas, alocacao):
        if ni <= 0:
            continue
        retangulo = celula.retangulo
        largura = retangulo.width()
        altura = retangulo.height()
        area = largura * altura
        if area <= 0.0:
            continue
        delta = math.sqrt(area / ni) * max(fator_delta, 1e-6)
        # Semente derivada por célula: mantém a reprodutibilidade global
        # sem correlacionar a amostragem entre células.
        rng = random.Random(
            None if seed is None else seed * 1000003 + celula.id
        )
        aceitos: List[QgsPointXY] = []
        for _ in range(_MAX_TENTATIVAS_DELTA):
            candidatos = poisson_disk(
                largura, altura, delta, rng=rng, n_max=ni * 2
            )
            aceitos = []
            for x, y in candidatos:
                ponto = QgsPointXY(
                    retangulo.xMinimum() + x, retangulo.yMinimum() + y
                )
                g = QgsGeometry.fromPointXY(ponto)
                if motor.intersects(g.constGet()):
                    aceitos.append(ponto)
                if len(aceitos) >= ni:
                    break
            if len(aceitos) >= ni:
                break
            # Célula parcialmente fora da moldura ou delta alto demais:
            # reduz delta e tenta de novo.
            delta *= _FATOR_REDUCAO_DELTA
        geradores.extend(aceitos[:ni] if len(aceitos) >= ni else aceitos)
    return _remover_duplicados(geradores)


def _remover_duplicados(pontos: List[QgsPointXY]) -> List[QgsPointXY]:
    """Remove geradores coincidentes (o Voronoi exige pontos distintos)."""
    vistos = set()
    unicos: List[QgsPointXY] = []
    for p in pontos:
        chave = (round(p.x(), 3), round(p.y(), 3))
        if chave not in vistos:
            vistos.add(chave)
            unicos.append(p)
    return unicos


def _camada_de_pontos(pontos, crs_authid: str) -> QgsVectorLayer:
    """Camada em memória com os geradores (entrada do Processing)."""
    camada = QgsVectorLayer(
        "Point?crs=%s" % crs_authid, "geradores", "memory"
    )
    provedor = camada.dataProvider()
    feicoes = []
    for p in pontos:
        f = QgsFeature()
        f.setGeometry(QgsGeometry.fromPointXY(p))
        feicoes.append(f)
    provedor.addFeatures(feicoes)
    camada.updateExtents()
    return camada


def _voronoi_processing(
    pontos: List[QgsPointXY], crs_authid: str
) -> Optional[List[QgsGeometry]]:
    """Diagrama de Voronoi via ``native:voronoipolygons`` (se disponível)."""
    registro = QgsApplication.processingRegistry()
    if registro.algorithmById("native:voronoipolygons") is None:
        return None
    import processing

    resultado = processing.run(
        "native:voronoipolygons",
        {
            "INPUT": _camada_de_pontos(pontos, crs_authid),
            # Buffer percentual para estender o diagrama além da
            # extensão dos geradores (o recorte final é pela moldura).
            "BUFFER": 50.0,
            "OUTPUT": "memory:voronoi",
        },
    )
    camada = resultado["OUTPUT"]
    return [QgsGeometry(f.geometry()) for f in camada.getFeatures()]


def _voronoi_scipy(pontos: List[QgsPointXY]) -> List[QgsGeometry]:
    """Fallback com ``scipy.spatial.Voronoi``.

    Usa o truque da reflexão: os geradores são espelhados nas quatro
    bordas da caixa envolvente expandida, garantindo que as regiões dos
    pontos originais sejam todas finitas.

    :raises RuntimeError: se o scipy não estiver instalado.
    """
    try:
        import numpy as np
        from scipy.spatial import Voronoi
    except ImportError as exc:
        raise RuntimeError(
            "O algoritmo 'native:voronoipolygons' não está disponível e o "
            "fallback requer o pacote opcional 'scipy'. Instale-o com: "
            "python -m pip install scipy (no Python do QGIS)."
        ) from exc

    coords = np.array([[p.x(), p.y()] for p in pontos])
    x_min, y_min = coords.min(axis=0)
    x_max, y_max = coords.max(axis=0)
    margem = max(x_max - x_min, y_max - y_min, 1.0) * 0.5
    x_min -= margem
    x_max += margem
    y_min -= margem
    y_max += margem
    esq = coords.copy()
    esq[:, 0] = 2 * x_min - esq[:, 0]
    dir_ = coords.copy()
    dir_[:, 0] = 2 * x_max - dir_[:, 0]
    baixo = coords.copy()
    baixo[:, 1] = 2 * y_min - baixo[:, 1]
    cima = coords.copy()
    cima[:, 1] = 2 * y_max - cima[:, 1]
    todos = np.concatenate([coords, esq, dir_, baixo, cima])
    voronoi = Voronoi(todos)
    geometrias: List[QgsGeometry] = []
    for i in range(len(pontos)):
        regiao = voronoi.regions[voronoi.point_region[i]]
        if not regiao or -1 in regiao:
            continue
        vertices = [
            QgsPointXY(voronoi.vertices[v][0], voronoi.vertices[v][1])
            for v in regiao
        ]
        geometrias.append(QgsGeometry.fromPolygonXY([vertices]))
    return geometrias


def diagrama_voronoi(
    geradores: List[QgsPointXY],
    moldura: QgsGeometry,
    crs_authid: str,
) -> List[QgsGeometry]:
    """Gera as células de Voronoi recortadas pela moldura.

    :param geradores: pontos geradores (>= 1).
    :param moldura: geometria da moldura no CRS de trabalho.
    :param crs_authid: authid do CRS de trabalho (ex.: ``EPSG:31983``).
    :returns: lista de células (polígonos) não vazias.
    """
    if len(geradores) < 3:
        # Poucos geradores (moldura minúscula/área sem dados): não há
        # diagrama útil; devolve a própria moldura como célula única.
        qgis_utils.log(
            "Menos de 3 geradores; usando a moldura como célula única."
        )
        return [QgsGeometry(moldura)]
    brutas = _voronoi_processing(geradores, crs_authid)
    if brutas is None:
        qgis_utils.log(
            "native:voronoipolygons indisponível; usando fallback scipy."
        )
        brutas = _voronoi_scipy(geradores)
    celulas: List[QgsGeometry] = []
    for geometria in brutas:
        recorte = qgis_utils.geometria_valida(geometria).intersection(
            moldura
        )
        if not recorte.isEmpty() and recorte.area() > 0.0:
            celulas.append(recorte)
    return celulas
