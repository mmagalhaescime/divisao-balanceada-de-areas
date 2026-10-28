# Divisão Balanceada de Áreas

Plugin QGIS de apoio ao **SAP** (DSG/Exército Brasileiro). Pacote Python: `balanced_work_areas`.

Plugin QGIS (≥ 3.28 LTR) que divide uma área de interesse (**moldura**) em
**k áreas de trabalho com carga cartográfica equilibrada**, usando dados
vetoriais de fontes abertas como *proxy* da densidade/complexidade das
feições. Apoio à distribuição de atividades de produção cartográfica no
**SAP** (Sistema de Apoio à Produção — DSG/Exército Brasileiro).

Autores: Matheus Magalhães Cardoso, Bruno Lixandrão Silvestre e
Giovana Baroni Cadorin (IME) — ver [Autores](#autores). Licença:
GPL-2.0-or-later.

## Instalação

### A partir do ZIP (recomendado)

1. Gere o pacote (ou use um zip já distribuído):

   ```bash
   python make_zip.py
   ```

   O zip é criado em `dist/balanced_work_areas-<versão>.zip`.
2. No QGIS: **Complementos → Gerenciar e Instalar Complementos →
   Instalar a partir de um ZIP**, aponte o arquivo e instale.
3. Habilite o plugin na lista ("Divisão Balanceada de Áreas").

### Por cópia da pasta

Copie a pasta `balanced_work_areas/` para o diretório de plugins do seu
perfil QGIS e reinicie o QGIS:

- Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
- Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`

## Uso

Abra o diálogo pelo menu **Vetor → Divisão Balanceada de Áreas** ou pelo
botão da barra de ferramentas.

1. **Área e divisão** — escolha a camada de moldura (polígonos; há opção
   de usar somente as feições selecionadas), a quantidade de áreas **k**
   e o método:
   - **Voronoi adaptativo ponderado por densidade** (metodologia
     principal): N = multiplicador × k geradores são alocados
     proporcionalmente à densidade de feições e posicionados por
     amostragem por disco de Poisson (Bridson); o diagrama de Voronoi é
     recortado pela moldura;
   - **Grade regular (quadrados)**: a moldura é dividida em ~m×k
     quadrados (padrão m = k; ex.: k = 6 → 36 quadrados), que são
     aglutinados em k áreas contíguas de complexidade equilibrada.
2. **Dados de entrada** — marque as fontes de download automático
   (OpenStreetMap/Overpass, hidrografia ANA, malhas IBGE, Google Open
   Buildings) e/ou adicione camadas locais do projeto. Selecione na
   árvore as classes ET-EDGV (por primitiva: ponto/linha/polígono) que
   entram no cálculo de complexidade. Os downloads são recortados pela
   bounding box da moldura + buffer e ficam em cache
   (`downloads.gpkg`, na pasta do projeto) para reexecuções.
3. **Parâmetros** — escala de trabalho (preenche padrões de **d**,
   comprimento de segmentação de linhas, e **r**, resolução da grade
   auxiliar), pesos de aquisição **α ≤ β ≤ γ** (ponto/linha/polígono),
   tabela de **operadores** com fator de experiência **ej ≥ 1** (uma
   linha por área; botão "todos iguais" remove a ponderação), fator de
   ajuste do δ do disco de Poisson, CRS de saída (padrão: SIRGAS 2000 /
   UTM detectado pelo centroide da moldura, EPSG 31978–31985) e seed
   opcional para reprodutibilidade.
4. **Executar** — o processamento roda em segundo plano (`QgsTask`), com
   barra de progresso e cancelamento; a interface do QGIS não trava.

### Saída

- Camada GeoPackage `lotes_trabalho_<data>.gpkg` com um polígono por
  operador e os atributos: `operador`, `fator_experiencia`,
  `carga_alvo`, `carga_total`, `n_pontos`, `n_linhas`, `n_poligonos`,
  `desvio_percentual`. A camada é carregada no canvas com simbologia
  categorizada por operador e rótulos;
- Diálogo de relatório com a tabela de cargas, o **coeficiente de
  variação CV = σ/μ** e exportação para CSV;
- Log detalhado na aba **Divisão Balanceada de Áreas** do painel de mensagens.

## Metodologia (resumo das 7 etapas)

1. **Aquisição**: download dos dados vetoriais das fontes marcadas,
   recortados pela bbox da moldura + buffer (padrão 500 m), com retry,
   rotação de endpoints e particionamento de consultas grandes em tiles;
2. **Normalização**: pontos mantidos; linhas segmentadas a cada *d*
   metros (centroide de cada trecho); polígonos → ponto interno
   (`pointOnSurface`) — tudo vira uma camada de **pontos de esforço**
   com `tipo_primitiva`, `classe_edgv`, `fonte`;
3. **Grade auxiliar**: grade de resolução *r*; contagem de pontos por
   célula → pesos {wi};
4. **Voronoi adaptativo**: alocação proporcional dos N geradores
   (método dos maiores restos), amostragem por disco de Poisson com
   δ = √(Ai/ni) × fator, diagrama de Voronoi
   (`native:voronoipolygons`; *fallback* `scipy.spatial.Voronoi`)
   recortado pela moldura;
5. **Carga por célula**: ci = α·n_ponto + β·n_linha + γ·n_polígono;
6. **Agrupamento contíguo**: carga-alvo Ctj = (ej/Σe)·Σci; heurística
   gulosa sobre o grafo de adjacência (células que compartilham
   fronteira), garantindo atribuição total e lotes conexos; células
   órfãs vão para o lote adjacente de menor carga;
7. **Saída**: dissolve por lote, GeoPackage + relatório com CV.

## Estrutura do código

```
balanced_work_areas/
├── __init__.py                  # classFactory (entrada do plugin)
├── balanced_work_areas.py       # classe principal (ação, task, canvas)
├── metadata.txt
├── config/sources.json          # endpoints editáveis das fontes
├── core/
│   ├── algorithms.py            # algoritmos puros (testáveis sem QGIS)
│   ├── edgv_classes.py          # catálogo ET-EDGV → tags/camadas
│   ├── data_acquisition.py      # Etapa 1 (Overpass/WFS/Open Buildings)
│   ├── normalization.py         # Etapa 2 (pontos de esforço)
│   ├── density_grid.py          # Etapa 3 (grade auxiliar)
│   ├── voronoi_partition.py     # Etapa 4 (Voronoi adaptativo)
│   ├── grid_partition.py        # método alternativo (grade regular)
│   ├── load_calculation.py      # Etapa 5 (carga ponderada)
│   ├── clustering.py            # Etapa 6 (adjacência, dissolve)
│   ├── pipeline.py              # orquestração em QgsTask
│   └── qgis_utils.py            # log, CRS/UTM, makeValid, camadas
├── gui/
│   ├── main_dialog.py           # diálogo principal (3 abas)
│   └── results_dialog.py        # relatório + exportar CSV
└── tests/                       # pytest (93 testes)
```

A interface é construída programaticamente em PyQt (sem arquivo `.ui`) —
escolha deliberada e consistente em todo o plugin.

## Testes

Os testes de lógica pura rodam em qualquer Python; os demais exigem o
Python do QGIS. No Windows:

```bash
"C:/Program Files/QGIS 3.34.3/bin/python-qgis.bat" -m pip install --user pytest
```

```bash
"C:/Program Files/QGIS 3.34.3/bin/python-qgis.bat" -m pytest
```

Nenhum teste depende de rede: as fontes de dados são simuladas
(*monkeypatch*) e o pipeline integrado usa dados sintéticos em memória.

## Dependências

- **Obrigatórias**: nenhuma além do próprio QGIS (PyQGIS + PyQt5);
- **Opcional**: `scipy` — *fallback* do diagrama de Voronoi quando
  `native:voronoipolygons` não está disponível. Sem ambos, o plugin
  exibe mensagem clara pedindo a instalação (`python -m pip install
  scipy` no Python do QGIS).

## Limitações e observações

- **Google Open Buildings**: os tiles S2 (nível 4) podem ter centenas de
  MB; o plugin transmite e filtra pela bbox, mas o download pode ser
  demorado. Alternativamente aponte na interface um CSV(.gz) já baixado.
  A descoberta dos tiles usa o `tiles.geojson` público do projeto;
- **Relations OSM (multipolígonos)**: a geometria é aproximada pela
  caixa envolvente (a montagem dos anéis está fora do escopo); ways
  fechados são tratados integralmente;
- **Endpoints ANA/IBGE**: serviços WFS públicos mudam com frequência;
  os endpoints e `typeNames` ficam em `config/sources.json` (editável).
  A falha de uma fonte não interrompe o processamento — vira aviso e o
  pipeline continua com as demais;
- **Moldura multipolígono**: suportada; se uma ilha ficar isolada no
  grafo de adjacência, ela é atribuída ao lote de menor carga (a
  conexidade estrita é geometricamente impossível nesse caso);
- Todas as medidas são em metros no CRS de trabalho (SIRGAS 2000/UTM).

## Autores

Software desenvolvido em conjunto, como Projeto de Fim de Curso (PFC) de
graduação em Engenharia Cartográfica da Seção de Ensino de Engenharia
Cartográfica (SE/6) do Instituto Militar de Engenharia (IME), por:

- **Matheus Magalhães Cardoso**
- **Bruno Lixandrão Silvestre**
- **Giovana Baroni Cadorin**

Orientador: Prof. Cel Leonardo Assumpção Moreira, D.Sc. (IME).

Para citar este software, use o botão *Cite this repository* do GitHub
(gerado a partir do arquivo [`CITATION.cff`](CITATION.cff)).
