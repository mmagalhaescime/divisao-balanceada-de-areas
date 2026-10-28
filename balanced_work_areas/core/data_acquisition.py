# -*- coding: utf-8 -*-
"""Etapa 1 — Aquisição e pré-processamento de dados abertos.

Baixa dados vetoriais das fontes marcadas (OSM/Overpass, hidrografia ANA,
geoserviços IBGE, Google Open Buildings), recortados pela bounding box da
moldura (+ buffer), com:

- retry com backoff e rotação de endpoints (Overpass);
- particionamento da bbox em tiles quando a área excede o limite prático
  da Overpass, com mesclagem/deduplicação por id de elemento;
- cache local em GeoPackage (``downloads.gpkg``) para não rebaixar dados
  em reexecuções;
- tolerância a falhas: a falha de uma fonte gera aviso e o processamento
  continua com as demais.

Os endpoints ficam em ``config/sources.json`` (editável), pois mudam.
"""

import csv
import gzip
import hashlib
import io
import json
import math
import os
import time
import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsRectangle,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)

from . import edgv_classes, qgis_utils

_AGENTE = "DivisaoBalanceadaAreas/0.1 (plugin QGIS; SAP/DSG)"

# Tipo de camada em memória por primitiva.
_TIPO_MEMORIA = {
    "ponto": "Point",
    "linha": "LineString",
    "poligono": "Polygon",
}

CamadaInsumo = Tuple[QgsVectorLayer, str, str]  # (camada, classe, fonte)


def carregar_config(caminho: Optional[str] = None) -> Dict:
    """Lê o ``config/sources.json`` (endpoints editáveis)."""
    if caminho is None:
        caminho = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "config",
            "sources.json",
        )
    with open(caminho, "r", encoding="utf-8") as arquivo:
        return json.load(arquivo)


def bbox_geografica(
    moldura: QgsGeometry,
    crs_trabalho: QgsCoordinateReferenceSystem,
    buffer_m: float,
    epsg_geografico: int = 4326,
) -> QgsRectangle:
    """Bounding box da moldura (+ buffer em metros) em coordenadas geográficas."""
    com_buffer = moldura.buffer(max(buffer_m, 0.0), 8)
    geografica = qgis_utils.transformar_geometria(
        com_buffer,
        crs_trabalho,
        QgsCoordinateReferenceSystem.fromEpsgId(epsg_geografico),
    )
    return geografica.boundingBox()


# ------------------------------------------------------------------ HTTP


def _http_get(
    url: str,
    dados: Optional[bytes] = None,
    timeout: float = 120.0,
    tentativas: int = 3,
    backoff_s: float = 5.0,
    cancelado: Optional[Callable[[], bool]] = None,
) -> bytes:
    """GET/POST com retry e backoff exponencial simples."""
    ultima_excecao: Optional[Exception] = None
    for tentativa in range(tentativas):
        if cancelado is not None and cancelado():
            raise InterruptedError("Operação cancelada pelo usuário.")
        try:
            requisicao = urllib.request.Request(
                url, data=dados, headers={"User-Agent": _AGENTE}
            )
            with urllib.request.urlopen(
                requisicao, timeout=timeout
            ) as resposta:
                return resposta.read()
        except Exception as exc:  # noqa: BLE001 - rede é imprevisível
            ultima_excecao = exc
            if tentativa < tentativas - 1:
                time.sleep(backoff_s * (2 ** tentativa))
    raise RuntimeError(
        "Falha ao acessar %s após %d tentativas: %s"
        % (url, tentativas, ultima_excecao)
    )


# ----------------------------------------------------------------- cache


def _chave_cache(fonte: str, classe: str, bbox: QgsRectangle) -> str:
    """Nome estável de camada de cache para (fonte, classe, bbox)."""
    resumo = hashlib.md5(
        (
            "%s|%s|%.4f|%.4f|%.4f|%.4f"
            % (
                fonte,
                classe,
                bbox.xMinimum(),
                bbox.yMinimum(),
                bbox.xMaximum(),
                bbox.yMaximum(),
            )
        ).encode("utf-8")
    ).hexdigest()[:10]
    return "%s_%s_%s" % (fonte, classe, resumo)


def caminho_cache(pasta_cache: str) -> str:
    """Caminho do GeoPackage de cache (``downloads.gpkg``)."""
    return os.path.join(pasta_cache, "downloads.gpkg")


def carregar_do_cache(
    pasta_cache: str, nome_camada: str
) -> Optional[QgsVectorLayer]:
    """Tenta carregar uma camada do cache; ``None`` se ausente/inválida."""
    gpkg = caminho_cache(pasta_cache)
    if not os.path.exists(gpkg):
        return None
    camada = QgsVectorLayer(
        "%s|layername=%s" % (gpkg, nome_camada), nome_camada, "ogr"
    )
    if camada.isValid():
        return camada
    return None


def salvar_no_cache(
    camada: QgsVectorLayer, pasta_cache: str, nome_camada: str
) -> Optional[QgsVectorLayer]:
    """Grava a camada no GeoPackage de cache e a recarrega de lá."""
    os.makedirs(pasta_cache, exist_ok=True)
    gpkg = caminho_cache(pasta_cache)
    opcoes = QgsVectorFileWriter.SaveVectorOptions()
    opcoes.driverName = "GPKG"
    opcoes.layerName = nome_camada
    if os.path.exists(gpkg):
        opcoes.actionOnExistingFile = (
            QgsVectorFileWriter.CreateOrOverwriteLayer
        )
    resultado = QgsVectorFileWriter.writeAsVectorFormatV3(
        camada, gpkg, camada.transformContext(), opcoes
    )
    if resultado[0] != QgsVectorFileWriter.NoError:
        qgis_utils.log(
            "Falha ao gravar cache '%s': %s" % (nome_camada, resultado[1])
        )
        return None
    return carregar_do_cache(pasta_cache, nome_camada)


def limpar_cache(pasta_cache: str) -> bool:
    """Remove o GeoPackage de cache (botão "limpar cache" da GUI).

    No Windows a remoção falha se alguma camada do cache ainda estiver
    aberta (arquivo bloqueado); libera referências Python pendentes antes
    de tentar e reporta a falha ao usuário quando o bloqueio persiste.
    """
    import gc

    gpkg = caminho_cache(pasta_cache)
    if os.path.exists(gpkg):
        gc.collect()  # solta datasets OGR de camadas já descartadas
        try:
            os.remove(gpkg)
            return True
        except OSError as exc:
            qgis_utils.log(
                "Falha ao limpar cache (alguma camada do cache ainda está "
                "carregada no projeto?): %s" % exc
            )
            return False
    return True


# ------------------------------------------------------------- Overpass


def montar_consulta_overpass(
    classe: Dict, bbox: QgsRectangle, timeout_s: int
) -> str:
    """Monta a consulta Overpass QL de uma classe EDGV para a bbox.

    ``out geom`` devolve a geometria completa de nodes/ways; para
    relations o bloco ``bounds`` (caixa envolvente) é usado como
    aproximação de polígono (documentado no README).
    """
    caixa = "(%f,%f,%f,%f)" % (
        bbox.yMinimum(),
        bbox.xMinimum(),
        bbox.yMaximum(),
        bbox.xMaximum(),
    )
    linhas = []
    for elemento in edgv_classes.elementos_osm(classe["primitiva"]):
        for filtro in classe["osm"]:
            linhas.append("%s%s%s;" % (elemento, filtro, caixa))
    return "[out:json][timeout:%d];(%s);out geom;" % (
        timeout_s,
        "".join(linhas),
    )


def _tiles_bbox(bbox: QgsRectangle, max_area_graus2: float) -> List[QgsRectangle]:
    """Divide a bbox em tiles quando excede o limite prático da Overpass."""
    area = bbox.width() * bbox.height()
    if area <= max_area_graus2 or area <= 0.0:
        return [bbox]
    divisoes = int(math.ceil(math.sqrt(area / max_area_graus2)))
    passo_x = bbox.width() / divisoes
    passo_y = bbox.height() / divisoes
    tiles = []
    for i in range(divisoes):
        for j in range(divisoes):
            tiles.append(
                QgsRectangle(
                    bbox.xMinimum() + i * passo_x,
                    bbox.yMinimum() + j * passo_y,
                    bbox.xMinimum() + (i + 1) * passo_x,
                    bbox.yMinimum() + (j + 1) * passo_y,
                )
            )
    return tiles


def _consultar_overpass(
    consulta: str,
    config_osm: Dict,
    cancelado: Optional[Callable[[], bool]] = None,
) -> Dict:
    """Executa a consulta com rotação de endpoints e retry/backoff."""
    ultima: Optional[Exception] = None
    for endpoint in config_osm["endpoints"]:
        try:
            dados = _http_get(
                endpoint,
                dados=urllib.parse.urlencode({"data": consulta}).encode(),
                timeout=float(config_osm.get("timeout_s", 180)),
                tentativas=int(config_osm.get("max_tentativas", 3)),
                backoff_s=float(config_osm.get("backoff_s", 5)),
                cancelado=cancelado,
            )
            return json.loads(dados.decode("utf-8"))
        except InterruptedError:
            raise
        except Exception as exc:  # noqa: BLE001
            ultima = exc
            qgis_utils.log(
                "Overpass %s falhou (%s); tentando próximo endpoint."
                % (endpoint, exc)
            )
    raise RuntimeError("Todos os endpoints Overpass falharam: %s" % ultima)


def _geometria_de_elemento_osm(
    elemento: Dict, primitiva: str
) -> Optional[QgsGeometry]:
    """Converte um elemento Overpass (JSON) em geometria QGIS."""
    tipo = elemento.get("type")
    if primitiva == "ponto":
        if tipo == "node":
            return QgsGeometry.fromPointXY(
                QgsPointXY(elemento["lon"], elemento["lat"])
            )
        centro = elemento.get("center") or elemento.get("bounds")
        if centro and "lat" in centro:
            return QgsGeometry.fromPointXY(
                QgsPointXY(centro["lon"], centro["lat"])
            )
        return None
    if tipo == "way":
        vertices = [
            QgsPointXY(p["lon"], p["lat"])
            for p in elemento.get("geometry") or []
        ]
        if len(vertices) < 2:
            return None
        if primitiva == "linha":
            return QgsGeometry.fromPolylineXY(vertices)
        if len(vertices) < 3:
            return None
        if vertices[0] != vertices[-1]:
            vertices.append(vertices[0])
        return QgsGeometry.fromPolygonXY([vertices])
    if tipo == "relation" and primitiva == "poligono":
        # Aproximação: caixa envolvente da relation como polígono (a
        # montagem dos anéis de multipolígonos OSM está fora do escopo).
        limites = elemento.get("bounds")
        if not limites:
            return None
        return QgsGeometry.fromRect(
            QgsRectangle(
                limites["minlon"],
                limites["minlat"],
                limites["maxlon"],
                limites["maxlat"],
            )
        )
    return None


def baixar_osm_classe(
    classe: Dict,
    bbox: QgsRectangle,
    config: Dict,
    cancelado: Optional[Callable[[], bool]] = None,
) -> QgsVectorLayer:
    """Baixa uma classe EDGV da Overpass (com tiling e deduplicação)."""
    config_osm = config["osm"]
    primitiva = classe["primitiva"]
    camada = QgsVectorLayer(
        "%s?crs=EPSG:4326" % _TIPO_MEMORIA[primitiva],
        "osm_%s" % classe["id"],
        "memory",
    )
    provedor = camada.dataProvider()
    vistos = set()
    feicoes = []
    for tile in _tiles_bbox(
        bbox, float(config_osm.get("max_area_graus2", 0.25))
    ):
        consulta = montar_consulta_overpass(
            classe, tile, int(config_osm.get("timeout_s", 180))
        )
        resposta = _consultar_overpass(consulta, config_osm, cancelado)
        for elemento in resposta.get("elements", []):
            chave = (elemento.get("type"), elemento.get("id"))
            if chave in vistos:
                continue
            vistos.add(chave)
            geometria = _geometria_de_elemento_osm(elemento, primitiva)
            if geometria is None or geometria.isEmpty():
                continue
            feicao = QgsFeature()
            feicao.setGeometry(geometria)
            feicoes.append(feicao)
    provedor.addFeatures(feicoes)
    camada.updateExtents()
    return camada


# ------------------------------------------------------------------ WFS


def baixar_wfs(
    urls_base: Sequence[str],
    typename: str,
    bbox: QgsRectangle,
    srs: str,
    timeout_s: float,
    pasta_temporaria: str,
    cancelado: Optional[Callable[[], bool]] = None,
) -> QgsVectorLayer:
    """GetFeature WFS 1.0.0 (GeoJSON) recortado pela bbox.

    A versão 1.0.0 é usada de propósito: a ordem dos eixos é sempre
    lon/lat, evitando as ambiguidades de eixo do WFS 1.1/2.0.
    """
    parametros = urllib.parse.urlencode(
        {
            "service": "WFS",
            "version": "1.0.0",
            "request": "GetFeature",
            "typeName": typename,
            "outputFormat": "application/json",
            "srsName": srs,
            "bbox": "%f,%f,%f,%f"
            % (
                bbox.xMinimum(),
                bbox.yMinimum(),
                bbox.xMaximum(),
                bbox.yMaximum(),
            ),
        }
    )
    ultima: Optional[Exception] = None
    for url_base in urls_base:
        url = "%s?%s" % (url_base, parametros)
        try:
            dados = _http_get(
                url, timeout=timeout_s, tentativas=2, cancelado=cancelado
            )
            texto = dados.decode("utf-8", errors="replace")
            if "FeatureCollection" not in texto[:4096]:
                raise RuntimeError(
                    "Resposta WFS inesperada (não é GeoJSON): %s..."
                    % texto[:200].replace("\n", " ")
                )
            os.makedirs(pasta_temporaria, exist_ok=True)
            caminho = os.path.join(
                pasta_temporaria,
                "wfs_%s.json"
                % hashlib.md5(url.encode()).hexdigest()[:10],
            )
            with open(caminho, "w", encoding="utf-8") as arquivo:
                arquivo.write(texto)
            camada = QgsVectorLayer(caminho, typename, "ogr")
            if not camada.isValid():
                raise RuntimeError("GeoJSON WFS inválido para o OGR.")
            return camada
        except InterruptedError:
            raise
        except Exception as exc:  # noqa: BLE001
            ultima = exc
            qgis_utils.log(
                "WFS %s (%s) falhou: %s" % (url_base, typename, exc)
            )
    raise RuntimeError(
        "Falha no WFS '%s' em todos os endpoints: %s" % (typename, ultima)
    )


# ------------------------------------------------- Google Open Buildings


def _tokens_s2_para_bbox(
    bbox: QgsRectangle,
    config_ob: Dict,
    pasta_cache: str,
    cancelado: Optional[Callable[[], bool]] = None,
) -> List[str]:
    """Descobre os tokens S2 (nível 4) que intersectam a bbox.

    Usa o ``tiles.geojson`` publicado pelo projeto Open Buildings (cache
    em disco) para evitar reimplementar a matemática de células S2.
    """
    os.makedirs(pasta_cache, exist_ok=True)
    caminho = os.path.join(pasta_cache, "open_buildings_tiles.geojson")
    if not os.path.exists(caminho):
        dados = _http_get(
            config_ob["tiles_geojson"],
            timeout=float(config_ob.get("timeout_s", 600)),
            cancelado=cancelado,
        )
        with open(caminho, "wb") as arquivo:
            arquivo.write(dados)
    with open(caminho, "r", encoding="utf-8") as arquivo:
        colecao = json.load(arquivo)
    retangulo = QgsGeometry.fromRect(bbox)
    tokens = []
    for feicao in colecao.get("features", []):
        propriedades = feicao.get("properties", {})
        token = (
            propriedades.get("tile_id")
            or propriedades.get("token")
            or propriedades.get("s2_token")
        )
        if not token:
            continue
        try:
            geometria = QgsGeometry.fromWkt(
                _geojson_para_wkt(feicao.get("geometry"))
            )
        except Exception:  # noqa: BLE001
            continue
        if geometria and not geometria.isEmpty() and geometria.intersects(
            retangulo
        ):
            tokens.append(str(token))
    return tokens


def _geojson_para_wkt(geometria_json: Optional[Dict]) -> str:
    """Conversão mínima GeoJSON→WKT para polígonos/multipolígonos."""
    if not geometria_json:
        raise ValueError("Geometria GeoJSON vazia.")
    tipo = geometria_json.get("type")
    coords = geometria_json.get("coordinates")

    def anel(a):
        return ", ".join("%f %f" % (p[0], p[1]) for p in a)

    if tipo == "Polygon":
        return "POLYGON(%s)" % ", ".join(
            "(%s)" % anel(a) for a in coords
        )
    if tipo == "MultiPolygon":
        return "MULTIPOLYGON(%s)" % ", ".join(
            "(%s)" % ", ".join("(%s)" % anel(a) for a in pol)
            for pol in coords
        )
    raise ValueError("Tipo GeoJSON não suportado: %s" % tipo)


def _iterar_csv_open_buildings(fluxo_texto, bbox, confianca_minima):
    """Itera linhas do CSV do Open Buildings filtrando por bbox/confiança."""
    leitor = csv.DictReader(fluxo_texto)
    for linha in leitor:
        try:
            latitude = float(linha["latitude"])
            longitude = float(linha["longitude"])
            confianca = float(linha.get("confidence", 1.0))
        except (KeyError, ValueError):
            continue
        if confianca < confianca_minima:
            continue
        if not (
            bbox.xMinimum() <= longitude <= bbox.xMaximum()
            and bbox.yMinimum() <= latitude <= bbox.yMaximum()
        ):
            continue
        wkt = linha.get("geometry")
        if wkt:
            yield wkt


def baixar_open_buildings(
    bbox: QgsRectangle,
    config: Dict,
    pasta_cache: str,
    arquivo_local: Optional[str] = None,
    cancelado: Optional[Callable[[], bool]] = None,
) -> QgsVectorLayer:
    """Edificações do Google Open Buildings recortadas pela bbox.

    :param arquivo_local: CSV(.gz) já baixado pelo usuário (alternativa
        ao download automático dos tiles S2 — que podem ter centenas de
        MB; limitação documentada no README).
    """
    config_ob = config["google_open_buildings"]
    confianca = float(config_ob.get("confianca_minima", 0.7))
    camada = QgsVectorLayer(
        "Polygon?crs=EPSG:4326", "open_buildings", "memory"
    )
    provedor = camada.dataProvider()
    feicoes: List[QgsFeature] = []

    def consumir(fluxo_texto):
        for wkt in _iterar_csv_open_buildings(fluxo_texto, bbox, confianca):
            if cancelado is not None and cancelado():
                raise InterruptedError("Cancelado pelo usuário.")
            geometria = QgsGeometry.fromWkt(wkt)
            if geometria.isEmpty():
                continue
            feicao = QgsFeature()
            feicao.setGeometry(geometria)
            feicoes.append(feicao)

    if arquivo_local:
        if arquivo_local.lower().endswith(".gz"):
            with gzip.open(
                arquivo_local, "rt", encoding="utf-8", newline=""
            ) as fluxo:
                consumir(fluxo)
        else:
            with open(
                arquivo_local, "r", encoding="utf-8", newline=""
            ) as fluxo:
                consumir(fluxo)
    else:
        tokens = _tokens_s2_para_bbox(
            bbox, config_ob, pasta_cache, cancelado
        )
        if not tokens:
            raise RuntimeError(
                "Nenhum tile S2 do Open Buildings intersecta a área."
            )
        pasta_ob = os.path.join(pasta_cache, "open_buildings")
        os.makedirs(pasta_ob, exist_ok=True)
        for token in tokens:
            nome = "%s%s" % (token, config_ob.get(
                "sufixo_arquivo", "_buildings.csv.gz"
            ))
            caminho = os.path.join(pasta_ob, nome)
            if not os.path.exists(caminho):
                url = "%s/%s" % (config_ob["url_base_dados"], nome)
                dados = _http_get(
                    url,
                    timeout=float(config_ob.get("timeout_s", 600)),
                    cancelado=cancelado,
                )
                with open(caminho, "wb") as arquivo:
                    arquivo.write(dados)
            with gzip.open(
                caminho, "rt", encoding="utf-8", newline=""
            ) as fluxo:
                consumir(fluxo)
    provedor.addFeatures(feicoes)
    camada.updateExtents()
    return camada


# ------------------------------------------------------------ orquestra


def adquirir_dados(
    ids_classes: Sequence[str],
    fontes: Sequence[str],
    bbox_geo: QgsRectangle,
    pasta_cache: str,
    denominador_escala: int,
    arquivo_open_buildings: Optional[str] = None,
    usar_cache: bool = True,
    cancelado: Optional[Callable[[], bool]] = None,
    progresso: Optional[Callable[[int, int], None]] = None,
) -> Tuple[List[CamadaInsumo], List[str]]:
    """Baixa (ou lê do cache) todas as fontes/classes marcadas (Etapa 1).

    :param ids_classes: classes ET-EDGV marcadas na GUI.
    :param fontes: subconjunto de {'osm', 'ana', 'ibge',
        'google_open_buildings'} marcado na GUI.
    :param bbox_geo: bbox da moldura + buffer em EPSG:4326/4674.
    :param pasta_cache: pasta do cache (``downloads.gpkg`` + tiles).
    :param denominador_escala: escala de trabalho (filtra classes).
    :param arquivo_open_buildings: CSV local opcional do Open Buildings.
    :param usar_cache: se False, ignora o cache e rebaixa tudo.
    :param cancelado: função que devolve True quando o usuário cancelou.
    :param progresso: callback ``(concluidos, total)``.
    :returns: tupla ``(camadas, avisos)`` — cada camada com sua classe e
        fonte; avisos descrevem fontes que falharam (o pipeline segue).
    """
    config = carregar_config()
    ids_uteis = edgv_classes.filtrar_por_escala(
        list(ids_classes), denominador_escala
    )
    tarefas: List[Tuple[str, Dict]] = []
    for id_classe in ids_uteis:
        classe = edgv_classes.obter_classe(id_classe)
        if "osm" in fontes and classe["osm"]:
            tarefas.append(("osm", classe))
        if "ana" in fontes and classe["ana"]:
            tarefas.append(("ana", classe))
        if "ibge" in fontes and classe["ibge"]:
            tarefas.append(("ibge", classe))
        if (
            "google_open_buildings" in fontes
            and classe["google_open_buildings"]
        ):
            tarefas.append(("google_open_buildings", classe))

    camadas: List[CamadaInsumo] = []
    avisos: List[str] = []
    for indice, (fonte, classe) in enumerate(tarefas):
        if cancelado is not None and cancelado():
            raise InterruptedError("Cancelado pelo usuário.")
        nome_cache = _chave_cache(fonte, classe["id"], bbox_geo)
        camada = (
            carregar_do_cache(pasta_cache, nome_cache)
            if usar_cache
            else None
        )
        if camada is not None:
            qgis_utils.log(
                "Cache: %s (%d feições)."
                % (nome_cache, camada.featureCount())
            )
            camadas.append((camada, classe["id"], fonte))
        else:
            try:
                camada = _baixar_fonte(
                    fonte,
                    classe,
                    bbox_geo,
                    config,
                    pasta_cache,
                    arquivo_open_buildings,
                    cancelado,
                )
                em_cache = salvar_no_cache(
                    camada, pasta_cache, nome_cache
                )
                camadas.append((em_cache or camada, classe["id"], fonte))
                qgis_utils.log(
                    "Baixado %s/%s: %d feições."
                    % (fonte, classe["id"], camada.featureCount())
                )
            except InterruptedError:
                raise
            except Exception as exc:  # noqa: BLE001
                aviso = "Fonte %s, classe %s: %s" % (
                    fonte,
                    classe["nome"],
                    exc,
                )
                avisos.append(aviso)
                qgis_utils.log(aviso)
        if progresso is not None:
            progresso(indice + 1, len(tarefas))
    return camadas, avisos


def _baixar_fonte(
    fonte: str,
    classe: Dict,
    bbox_geo: QgsRectangle,
    config: Dict,
    pasta_cache: str,
    arquivo_open_buildings: Optional[str],
    cancelado: Optional[Callable[[], bool]],
) -> QgsVectorLayer:
    """Despacha o download para a implementação da fonte."""
    if fonte == "osm":
        return baixar_osm_classe(classe, bbox_geo, config, cancelado)
    if fonte in ("ana", "ibge"):
        config_fonte = config[fonte]
        camadas_fonte = config_fonte.get("camadas", {})
        chaves = classe[fonte]
        # Uma classe pode mapear para mais de uma camada da fonte; a
        # primeira que funcionar é usada.
        ultima: Optional[Exception] = None
        for chave in chaves:
            typename = camadas_fonte.get(chave)
            if not typename:
                continue
            try:
                return baixar_wfs(
                    config_fonte["wfs"],
                    typename,
                    bbox_geo,
                    config_fonte.get("srs_nativo", "EPSG:4674"),
                    float(config_fonte.get("timeout_s", 120)),
                    os.path.join(pasta_cache, "wfs"),
                    cancelado,
                )
            except Exception as exc:  # noqa: BLE001
                ultima = exc
        raise RuntimeError(
            "Nenhuma camada %s configurada funcionou: %s" % (fonte, ultima)
        )
    if fonte == "google_open_buildings":
        return baixar_open_buildings(
            bbox_geo,
            config,
            pasta_cache,
            arquivo_open_buildings,
            cancelado,
        )
    raise ValueError("Fonte desconhecida: %s" % fonte)


def recortar_camada_pela_moldura(
    camada: QgsVectorLayer,
    moldura: QgsGeometry,
    crs_trabalho: QgsCoordinateReferenceSystem,
) -> QgsVectorLayer:
    """Recorte exato pela moldura (após o recorte grosseiro por bbox).

    Observação: a normalização (Etapa 2) já recorta pela moldura ao gerar
    os pontos de esforço; esta função existe para inspeção/depuração das
    camadas intermediárias e não é usada no caminho crítico do pipeline.
    """
    tipo = QgsWkbTypes.geometryType(camada.wkbType())
    nomes = {0: "Point", 1: "LineString", 2: "Polygon"}
    saida = QgsVectorLayer(
        "%s?crs=%s" % (nomes.get(tipo, "Point"), crs_trabalho.authid()),
        camada.name() + "_recorte",
        "memory",
    )
    provedor = saida.dataProvider()
    feicoes = []
    for feicao in camada.getFeatures():
        if not feicao.hasGeometry():
            continue
        geometria = qgis_utils.transformar_geometria(
            qgis_utils.geometria_valida(feicao.geometry()),
            camada.crs(),
            crs_trabalho,
        )
        recorte = geometria.intersection(moldura)
        if recorte.isEmpty():
            continue
        nova = QgsFeature()
        nova.setGeometry(recorte)
        feicoes.append(nova)
    provedor.addFeatures(feicoes)
    saida.updateExtents()
    return saida
