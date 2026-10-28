# -*- coding: utf-8 -*-
"""Gerador do pacote instalável (zip) do plugin Divisão Balanceada de Áreas.

Uso::

    python make_zip.py

Gera ``dist/balanced_work_areas-<versao>.zip`` com a pasta
``balanced_work_areas/`` na raiz do zip — formato exigido pelo instalador
de plugins do QGIS ("Complementos → Instalar a partir de um ZIP").

São excluídos caches (``__pycache__``, ``*.pyc``), a pasta de testes e
artefatos de desenvolvimento.
"""

import configparser
import os
import sys
import zipfile

RAIZ = os.path.dirname(os.path.abspath(__file__))
NOME_PACOTE = "balanced_work_areas"

# Diretórios e extensões excluídos do pacote instalável.
DIRETORIOS_EXCLUIDOS = {"__pycache__", "tests", ".pytest_cache"}
EXTENSOES_EXCLUIDAS = {".pyc", ".pyo"}


def ler_versao() -> str:
    """Lê a versão declarada em ``balanced_work_areas/metadata.txt``."""
    metadata = configparser.ConfigParser()
    metadata.read(
        os.path.join(RAIZ, NOME_PACOTE, "metadata.txt"), encoding="utf-8"
    )
    return metadata["general"]["version"]


def arquivos_do_pacote():
    """Itera os arquivos a empacotar (caminhos absoluto e no zip)."""
    base = os.path.join(RAIZ, NOME_PACOTE)
    for pasta, subpastas, arquivos in os.walk(base):
        subpastas[:] = [
            s for s in subpastas if s not in DIRETORIOS_EXCLUIDOS
        ]
        for nome in arquivos:
            if os.path.splitext(nome)[1] in EXTENSOES_EXCLUIDAS:
                continue
            caminho = os.path.join(pasta, nome)
            relativo = os.path.relpath(caminho, RAIZ)
            yield caminho, relativo


def main() -> int:
    """Gera o zip instalável em ``dist/``."""
    versao = ler_versao()
    pasta_dist = os.path.join(RAIZ, "dist")
    os.makedirs(pasta_dist, exist_ok=True)
    destino = os.path.join(
        pasta_dist, "%s-%s.zip" % (NOME_PACOTE, versao)
    )
    with zipfile.ZipFile(
        destino, "w", compression=zipfile.ZIP_DEFLATED
    ) as pacote:
        total = 0
        for caminho, relativo in arquivos_do_pacote():
            # Separador POSIX no zip (exigência de portabilidade).
            pacote.write(caminho, relativo.replace(os.sep, "/"))
            total += 1
    print("Gerado %s (%d arquivos)." % (destino, total))
    print(
        'Instale no QGIS em: Complementos > Gerenciar e Instalar '
        'Complementos > "Instalar a partir de um ZIP".'
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
