# -*- coding: utf-8 -*-
"""Algoritmos puros da metodologia (sem dependência de QGIS).

Concentra a lógica matemática/combinatória do plugin para que possa ser
testada com pytest em qualquer ambiente Python:

- detecção do fuso UTM (SIRGAS 2000) a partir de lon/lat;
- parâmetros padrão (d, r) por escala de trabalho;
- alocação proporcional de geradores por célula (maiores restos);
- amostragem por disco de Poisson (algoritmo de Bridson);
- cargas-alvo por operador a partir dos fatores de experiência;
- agrupamento guloso contíguo (bin packing) sobre grafo de adjacência;
- coeficiente de variação (CV = sigma/mu).
"""

import math
import random
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

# Fusos UTM válidos para o Brasil em SIRGAS 2000: 18S..25S.
EPSG_SIRGAS_UTM_18S = 31978
FUSO_UTM_MIN_BRASIL = 18
FUSO_UTM_MAX_BRASIL = 25

# Padrões (d = segmentação de linhas, r = resolução da grade auxiliar),
# em metros, calibrados pela escala de trabalho.
DEFAULTS_POR_ESCALA = {
    25000: {"d": 50.0, "r": 250.0},
    50000: {"d": 100.0, "r": 500.0},
    100000: {"d": 200.0, "r": 1000.0},
    250000: {"d": 500.0, "r": 2500.0},
}


def detectar_fuso_utm(lon: float, lat: float) -> Tuple[int, int]:
    """Detecta o fuso UTM e o código EPSG SIRGAS 2000 / UTM Sul.

    :param lon: longitude do centroide da moldura (graus, WGS84/SIRGAS).
    :param lat: latitude do centroide (graus). Usada apenas para validação
        grosseira (o plugin assume hemisfério sul / território brasileiro).
    :returns: tupla ``(fuso, epsg)``. O fuso é limitado ao intervalo
        brasileiro [18, 25]; centroides fora desse intervalo são
        "grampeados" para o fuso válido mais próximo (o usuário pode
        sobrescrever o CRS manualmente na interface).
    """
    if not (-180.0 <= lon <= 180.0) or not (-90.0 <= lat <= 90.0):
        raise ValueError(
            "Centroide inválido (lon=%r, lat=%r)." % (lon, lat)
        )
    fuso = int(math.floor((lon + 180.0) / 6.0)) + 1
    fuso = max(FUSO_UTM_MIN_BRASIL, min(FUSO_UTM_MAX_BRASIL, fuso))
    epsg = EPSG_SIRGAS_UTM_18S + (fuso - FUSO_UTM_MIN_BRASIL)
    return fuso, epsg


def defaults_por_escala(denominador_escala: int) -> Dict[str, float]:
    """Retorna os padrões de ``d`` e ``r`` para a escala de trabalho.

    :param denominador_escala: denominador da escala (ex.: 50000).
    :returns: dicionário ``{"d": ..., "r": ...}`` em metros. Escalas não
        tabeladas caem no vizinho tabelado mais próximo.
    """
    if denominador_escala in DEFAULTS_POR_ESCALA:
        return dict(DEFAULTS_POR_ESCALA[denominador_escala])
    mais_proxima = min(
        DEFAULTS_POR_ESCALA, key=lambda e: abs(e - denominador_escala)
    )
    return dict(DEFAULTS_POR_ESCALA[mais_proxima])


def alocar_geradores(pesos: Sequence[float], n_total: int) -> List[int]:
    """Aloca ``n_total`` geradores proporcionalmente aos pesos das células.

    Implementa o método dos maiores restos (largest remainder) para que a
    soma das alocações seja exatamente ``n_total`` — o arredondamento
    simples ``round(N*wi/soma)`` da Etapa 4 não garante a soma.

    :param pesos: peso (contagem de pontos de esforço) de cada célula.
    :param n_total: número total de geradores N (múltiplo de k).
    :returns: lista com o número de geradores por célula (mesma ordem dos
        pesos). Se todos os pesos forem nulos, distribui uniformemente.
    """
    if n_total <= 0:
        return [0] * len(pesos)
    if not pesos:
        return []
    soma = float(sum(pesos))
    if soma <= 0.0:
        # Área sem dados: distribuição uniforme para ainda permitir a
        # partição geométrica (carga zero será refletida nas cargas).
        base = n_total // len(pesos)
        alocacao = [base] * len(pesos)
        for i in range(n_total - base * len(pesos)):
            alocacao[i] += 1
        return alocacao
    cotas = [n_total * (p / soma) for p in pesos]
    alocacao = [int(math.floor(c)) for c in cotas]
    restantes = n_total - sum(alocacao)
    # Distribui as sobras às células de maior resto fracionário.
    ordem = sorted(
        range(len(pesos)), key=lambda i: cotas[i] - alocacao[i], reverse=True
    )
    for i in ordem[:restantes]:
        alocacao[i] += 1
    return alocacao


def poisson_disk(
    largura: float,
    altura: float,
    raio: float,
    rng: Optional[random.Random] = None,
    k_tentativas: int = 30,
    n_max: Optional[int] = None,
) -> List[Tuple[float, float]]:
    """Amostragem por disco de Poisson (algoritmo de Bridson, 2007).

    Gera pontos no retângulo ``[0, largura] x [0, altura]`` tais que a
    distância entre quaisquer dois pontos seja >= ``raio``.

    :param largura: largura do domínio (metros).
    :param altura: altura do domínio (metros).
    :param raio: distância mínima delta entre pontos.
    :param rng: gerador de números aleatórios (para reprodutibilidade).
    :param k_tentativas: tentativas por ponto ativo antes de desativá-lo.
    :param n_max: se informado, interrompe ao atingir esse número de pontos.
    :returns: lista de tuplas ``(x, y)``.
    """
    if largura <= 0 or altura <= 0 or raio <= 0:
        return []
    rng = rng or random.Random()
    tam_celula = raio / math.sqrt(2.0)
    ncols = max(1, int(math.ceil(largura / tam_celula)))
    nlins = max(1, int(math.ceil(altura / tam_celula)))
    grade: List[Optional[int]] = [None] * (ncols * nlins)
    pontos: List[Tuple[float, float]] = []
    ativos: List[int] = []

    def indice_grade(p: Tuple[float, float]) -> Tuple[int, int]:
        return (
            min(ncols - 1, int(p[0] / tam_celula)),
            min(nlins - 1, int(p[1] / tam_celula)),
        )

    def valido(p: Tuple[float, float]) -> bool:
        if not (0.0 <= p[0] <= largura and 0.0 <= p[1] <= altura):
            return False
        cx, cy = indice_grade(p)
        for gx in range(max(0, cx - 2), min(ncols, cx + 3)):
            for gy in range(max(0, cy - 2), min(nlins, cy + 3)):
                idx = grade[gy * ncols + gx]
                if idx is not None:
                    q = pontos[idx]
                    if math.hypot(p[0] - q[0], p[1] - q[1]) < raio:
                        return False
        return True

    def inserir(p: Tuple[float, float]) -> None:
        pontos.append(p)
        ativos.append(len(pontos) - 1)
        cx, cy = indice_grade(p)
        grade[cy * ncols + cx] = len(pontos) - 1

    inserir((rng.uniform(0.0, largura), rng.uniform(0.0, altura)))
    while ativos and (n_max is None or len(pontos) < n_max):
        pos = rng.randrange(len(ativos))
        origem = pontos[ativos[pos]]
        aceito = False
        for _ in range(k_tentativas):
            ang = rng.uniform(0.0, 2.0 * math.pi)
            dist = rng.uniform(raio, 2.0 * raio)
            cand = (
                origem[0] + dist * math.cos(ang),
                origem[1] + dist * math.sin(ang),
            )
            if valido(cand):
                inserir(cand)
                aceito = True
                break
        if not aceito:
            ativos.pop(pos)
    return pontos


def cargas_alvo(
    carga_total: float, fatores_experiencia: Sequence[float]
) -> List[float]:
    """Cargas-alvo Ctj = (ej / soma(e)) * carga_total (Etapa 6).

    :param carga_total: soma das cargas ponderadas de todas as células.
    :param fatores_experiencia: fatores ej >= 1 de cada operador.
    :returns: lista de cargas-alvo, uma por operador.
    """
    if not fatores_experiencia:
        return []
    soma = float(sum(fatores_experiencia))
    if soma <= 0.0:
        return [carga_total / len(fatores_experiencia)] * len(
            fatores_experiencia
        )
    return [carga_total * (e / soma) for e in fatores_experiencia]


def _componentes_conexos(
    nos: Set[int], adjacencia: Dict[int, Set[int]]
) -> List[Set[int]]:
    """Componentes conexos do subgrafo induzido por ``nos``."""
    restantes = set(nos)
    componentes: List[Set[int]] = []
    while restantes:
        semente = next(iter(restantes))
        comp = {semente}
        fila = [semente]
        while fila:
            atual = fila.pop()
            for viz in adjacencia.get(atual, ()):  # pragma: no branch
                if viz in restantes and viz not in comp:
                    comp.add(viz)
                    fila.append(viz)
        componentes.append(comp)
        restantes -= comp
    return componentes


def agrupamento_guloso(
    adjacencia: Dict[int, Set[int]],
    cargas: Dict[int, float],
    alvos: Sequence[float],
) -> Dict[int, int]:
    """Agrupa células em lotes contíguos com cargas próximas das metas.

    Heurística gulosa da Etapa 6: para cada operador, em ordem decrescente
    de carga-alvo (experiência), inicia o lote pela célula não atribuída de
    maior carga e anexa iterativamente a célula adjacente que minimiza
    ``|carga_acumulada + c - alvo|``, parando ao atingir a meta ou esgotar
    adjacências. Ao final, células órfãs são anexadas ao lote adjacente de
    menor carga, garantindo atribuição total e lotes conexos (exceto se o
    próprio grafo for desconexo, ex.: moldura multipolígono).

    :param adjacencia: grafo célula -> conjunto de células vizinhas.
    :param cargas: carga ponderada de cada célula.
    :param alvos: carga-alvo de cada operador (índice = id do lote).
    :returns: dicionário célula -> índice do lote (0..k-1).
    """
    celulas = set(cargas)
    atribuicao: Dict[int, int] = {}
    carga_lote = [0.0] * len(alvos)

    # Operadores em ordem decrescente de carga-alvo (mais experientes
    # recebem lotes maiores e escolhem primeiro).
    ordem_ops = sorted(
        range(len(alvos)), key=lambda j: alvos[j], reverse=True
    )
    nao_atribuidas = set(celulas)
    for j in ordem_ops:
        if not nao_atribuidas:
            break
        alvo = alvos[j]
        # Semente: célula livre de maior carga.
        semente = max(nao_atribuidas, key=lambda c: (cargas[c], -c))
        lote = {semente}
        nao_atribuidas.discard(semente)
        atribuicao[semente] = j
        carga_lote[j] = cargas[semente]
        fronteira = {
            v for v in adjacencia.get(semente, ()) if v in nao_atribuidas
        }
        while carga_lote[j] < alvo and fronteira:
            # Anexa o vizinho que minimiza |carga acumulada - alvo|.
            melhor = min(
                fronteira,
                key=lambda c: (abs(carga_lote[j] + cargas[c] - alvo), c),
            )
            # Se já passamos da meta e o melhor candidato só piora o
            # desvio, interrompe o crescimento deste lote.
            if abs(carga_lote[j] + cargas[melhor] - alvo) > abs(
                carga_lote[j] - alvo
            ):
                break
            fronteira.discard(melhor)
            nao_atribuidas.discard(melhor)
            lote.add(melhor)
            atribuicao[melhor] = j
            carga_lote[j] += cargas[melhor]
            fronteira.update(
                v for v in adjacencia.get(melhor, ()) if v in nao_atribuidas
            )

    # Passo final: células órfãs vão para o lote adjacente de menor carga.
    # Trabalha por componente conexo para preservar a conexidade dos lotes.
    while nao_atribuidas:
        progrediu = False
        for comp in _componentes_conexos(nao_atribuidas, adjacencia):
            # Lotes adjacentes ao componente.
            lotes_vizinhos = set()
            for c in comp:
                for v in adjacencia.get(c, ()):
                    if v in atribuicao:
                        lotes_vizinhos.add(atribuicao[v])
            if lotes_vizinhos:
                destino = min(
                    lotes_vizinhos, key=lambda j: (carga_lote[j], j)
                )
            elif carga_lote:
                # Componente isolado (grafo desconexo): vai para o lote de
                # menor carga, mesmo sem adjacência (conexidade impossível).
                destino = min(
                    range(len(carga_lote)), key=lambda j: (carga_lote[j], j)
                )
            else:
                break
            for c in comp:
                atribuicao[c] = destino
                carga_lote[destino] += cargas[c]
            nao_atribuidas -= comp
            progrediu = True
        if not progrediu:  # pragma: no cover - salvaguarda
            break
    return atribuicao


def coeficiente_variacao(valores: Iterable[float]) -> float:
    """Coeficiente de variação CV = sigma/mu (desvio-padrão populacional).

    :param valores: cargas finais dos lotes.
    :returns: CV; 0.0 para lista vazia ou média nula.
    """
    lista = list(valores)
    if not lista:
        return 0.0
    mu = sum(lista) / len(lista)
    if mu == 0.0:
        return 0.0
    var = sum((v - mu) ** 2 for v in lista) / len(lista)
    return math.sqrt(var) / mu
