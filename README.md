# Controle de Qualidade de Dados no BrCris

Projeto de apoio ao TCC **"Controle de Qualidade de Dados no BrCris: desafios, estratégias e impactos na Ciência Aberta no Brasil"**.

O projeto implementa um pipeline para extração de dados de arquivos XML do BrCris, armazenamento analítico em **Parquet + DuckDB**, validações com **Great Expectations** e geração de relatórios HTML.

## Visão geral

O pipeline foi projetado para trabalhar com arquivos XML grandes sem precisar extrair todos os XMLs dos arquivos ZIP para o disco.

```text
ZIPs originais
    |
    v
XML em streaming
    | extract.py
    v
Parquet
    |
    v
DuckDB
    | SELECTs
    v
Python / Pandas
    | quality/*.py
    v
Great Expectations
    |
    v
Scores + relatórios HTML
```

A arquitetura separa:

- **dados brutos**: ZIPs originais;
- **dados processados**: arquivos Parquet;
- **camada analítica**: DuckDB;
- **regras de qualidade**: Great Expectations;
- **resultados**: scores, JSON, CSV e relatórios.

## Estrutura do projeto

```text
tcc/
├── config/
│   └── entities.yaml
├── data/
│   ├── raw/
│   ├── parquet/
│   │   ├── <classe>/
│   │   └── relation/
│   └── tcc.duckdb
├── quality/
│   ├── common.py
│   ├── exploration.py
│   ├── journal.py
│   ├── orgunit.py
│   ├── patent.py
│   ├── person.py
│   ├── program.py
│   ├── publication.py
│   ├── relation.py
│   ├── researchgroup.py
│   └── software.py
├── results/
│   └── <classe>/
├── reports/
│   └── <classe>/
├── extract.py
└── run.py
```

### `config/entities.yaml`

Define as fontes de extração: ZIP de origem, prefixo de origem, tipo de registro, dataset e campos-base. Campos adicionais encontrados nos XMLs também são preservados. Fontes sem `record_type` podem extrair apenas relações.

### `data/raw/`

Contém os ZIPs originais. Essa é a fonte bruta e não é modificada pelo pipeline.

### `data/parquet/`

Contém os dados extraídos dos XMLs em formato Parquet, organizados por entidade.

### `data/tcc.duckdb`

Banco DuckDB utilizado pelo projeto. Ele funciona principalmente como uma camada SQL sobre os arquivos Parquet, disponibilizando as entidades como views.

### `extract.py`

Responsável por abrir os ZIPs, processar os XMLs em streaming, extrair os registros definidos no YAML, gravar Parquet, registrar erros e criar/atualizar as views DuckDB.

### `quality/`

Contém as regras de qualidade por entidade e a infraestrutura compartilhada em `common.py`. `exploration.py` gera análises descritivas das views.

### `results/`

Armazena scores, ocorrências de erro e resumos das validações em CSV e JSON. A análise exploratória também salva tabelas e perfis em CSV/JSON.

### `reports/`

Contém os relatórios HTML gerados a partir dos resultados.

# DuckDB

## O que é?

DuckDB é um sistema de banco de dados analítico que roda **dentro do próprio processo da aplicação**, sem exigir um servidor de banco separado. Possui interface SQL e integração com Python, além de suporte direto a Parquet, CSV e JSON. 

Isso permite utilizá-lo em projetos locais de análise de dados sem a infraestrutura de um banco cliente-servidor.

Exemplo:

```python
import duckdb

con = duckdb.connect("data/tcc.duckdb")

resultado = con.sql("""
    SELECT *
    FROM person
    LIMIT 10
""")
```

O arquivo `data/tcc.duckdb` é o banco persistente do projeto.

## DuckDB e Parquet

DuckDB consegue consultar Parquet diretamente:

```sql
SELECT *
FROM 'data/parquet/person/arquivo.parquet';
```

ou:

```sql
SELECT *
FROM read_parquet('data/parquet/person/*.parquet');
```

Também é possível criar uma view:

```sql
CREATE VIEW person AS
SELECT *
FROM read_parquet('data/parquet/person/*.parquet');
```

Assim, os dados continuam armazenados nos arquivos Parquet, mas podem ser consultados como uma tabela SQL.

DuckDB também suporta **projection pushdown** e **filter pushdown**, podendo evitar a leitura de colunas ou partes dos arquivos que não são necessárias para uma consulta.

## Como ele é usado neste projeto

O DuckDB não é o armazenamento principal dos dados. Ele disponibiliza os Parquets como views e é usado para selecionar os dados necessários. As regras convertem esses dados em DataFrames Pandas, que são então validados pelo Great Expectations.

```text
                 ZIP / XML
                    |
                    | extract.py
                    v
                 Parquet
                    |
                    | read_parquet()
                    v
                 DuckDB
                    |
                    | SQL / views
                    v
             Python / Pandas
                    |
                    v
             Great Expectations
```

### 1. Extração

`extract.py` lê os XMLs diretamente dentro dos ZIPs e produz arquivos Parquet:

```text
data/parquet/person/
├── arquivo_001.parquet
├── arquivo_002.parquet
└── arquivo_003.parquet
```

### 2. View no DuckDB

Depois da extração, a entidade é disponibilizada como uma view. Conceitualmente:

```sql
CREATE OR REPLACE VIEW person AS
SELECT *
FROM read_parquet('data/parquet/person/*.parquet');
```

Então uma consulta como:

```sql
SELECT COUNT(*)
FROM person;
```

consulta os Parquets por meio do DuckDB.

### 3. Validação com Great Expectations

Os módulos em `quality/` consultam as views DuckDB, preparam DataFrames Pandas para cada regra e passam os dados ao Great Expectations. O contexto do GX é efêmero; não é configurado como uma conexão SQL persistente com o DuckDB.

Portanto, o fluxo da validação é:

```text
Great Expectations
        |
        v
 Python / Pandas
        |
        v
 Expectation
```

## Por que não carregar tudo para dentro do DuckDB?

Seria possível criar uma tabela física:

```sql
CREATE TABLE person AS
SELECT *
FROM read_parquet('data/parquet/person/*.parquet');
```

Mas isso criaria outra cópia dos dados.

No projeto, é mais interessante manter:

```text
Parquet = armazenamento
DuckDB  = consulta
```

Dessa forma, os Parquets continuam sendo os arquivos de dados processados e o DuckDB fornece a camada SQL necessária para as validações.

Isso também evita aumentar desnecessariamente o uso de armazenamento, algo relevante quando o conjunto de dados é grande.

# Regras de qualidade

As regras são definidas em módulos próprios dentro de `quality/`, incluindo `journal`, `orgunit`, `patent`, `person`, `program`, `publication`, `relation`, `researchgroup` e `software`. Cada módulo (exceto `publication` e `relation`) expõe `validate()`, que devolve scores, ocorrências de erro e metadados; as Expectations do Great Expectations são executadas pelo mecanismo compartilhado em `quality/common.py`. `publication` e `relation` só definem as regras e são executadas em SQL por `quality/fast.py`.

As regras incluem verificações de completude, unicidade, formato, domínio e consistência referencial, conforme a entidade. Consulte o módulo correspondente para ver as regras e seus identificadores atualizados.

## Validação de Publication

`publication` tem milhões de linhas, então roda em SQL dentro do DuckDB (`quality/fast.py`), sem passar pelo Pandas. Todas as regras rodam de uma vez:

```bash
python run.py validate publication --skip-extract
python run.py validate publication --skip-extract --sample-size 200000   # teste rápido
python run.py validate publication --skip-extract --memory-limit 8GB     # limita a RAM
```

As regras ficam em `quality/publication.py` (só a definição: id, descrição, motivo). Todas as ocorrências de erro são gravadas em `results/publication/errors/<REGRA>.parquet`; `errors_sample.csv` traz até 1000 exemplos por regra e o relatório HTML mostra 5.

## Validação de Relation

`relation` é uma view agregada dos Parquets de relações produzidos pelas diversas fontes. Não tem um ZIP próprio. Também roda em SQL no DuckDB (`quality/fast.py`):

```bash
python run.py validate relation
python run.py validate relation --sample-size 200000
```

O prefixo do semanticIdentifier (`lattes::`, `brcris::`, `docdb::`...) indica a coluna `identifier.<prefixo>` do alvo (`docdb` usa `identifier.espacenet`). O valor é normalizado antes de comparar: remove-se `prefixo::` e espaços; em `docdb` também se ignoram código do país, código de tipo e símbolos. Os exemplos do relatório mostram o valor original. A lista de regras (`RELATION_ENDPOINTS`) fica em `quality/relation.py`.

O banco é aberto só para leitura. Feche o DBeaver ou outros programas que usem o mesmo arquivo DuckDB antes de executar.

# Executando o projeto

## Instalação

Crie um ambiente virtual:

```bash
python -m venv .venv
```

Ative no Windows:

```bash
.venv\Scripts\activate
```

Instale ou atualize as dependências usando o mesmo interpretador que executará o projeto:

```bash
python -m pip install --upgrade -r requirements.txt
```

O projeto utiliza Great Expectations 1.x. A versão 0.18.x não corresponde à faixa declarada no arquivo de dependências. Confira também se o DuckDB foi instalado no mesmo ambiente:

```bash
python -c "import sys, great_expectations, duckdb; print(sys.executable); print('GX:', great_expectations.__version__); print('DuckDB:', duckdb.__version__)"
```

## Dados

Coloque os ZIPs originais em:

```text
data/raw/
```

O caminho de cada ZIP é definido em:

```text
config/entities.yaml
```

Os ZIPs, XMLs, Parquets, arquivos CSV/JSON de resultados, o banco DuckDB e o ambiente virtual são dados e artefatos locais e não são incluídos no Git. Cada pessoa deve obter os dados autorizados e colocá-los nos caminhos configurados localmente.

# Extração

Extrair uma entidade:

```bash
python extract.py person
```

Executar com quantidade específica de workers:

```bash
python extract.py person --workers 2
```

Limitar registros para teste:

```bash
python extract.py person --max-records 1000
```

Inspecionar a estrutura dos XMLs:

```bash
python extract.py person --inspect
```

Para testar com apenas alguns XMLs:

```bash
python extract.py person --limit-members 2 --workers 1
```

Forçar uma nova extração:

```bash
python extract.py person --force
```

A extração grava Parquets em `data/parquet/<dataset>/` e as relações em `data/parquet/relation/`. Ela também cria ou atualiza as views correspondentes no DuckDB (`data/tcc.duckdb`). As informações de progresso/idempotência e erros de parse ficam em `data/extraction_state/` e `data/rejects/`.

# Validação

Executar extração e validações para uma entidade:

```bash
python run.py validate person
```

`run.py`:

1. importa `quality.<entidade>` e verifica se o módulo expõe `validate()` (`publication` e `relation` usam `quality/fast.py`);
2. executa a extração, a menos que `--skip-extract` seja informado; para `relation`, reutiliza ou cria a view agregada, sem extrair um ZIP próprio;
3. verifica a reconciliação XML x Parquet quando uma fonte é extraída;
4. executa as validações e calcula os scores;
5. salva resultados CSV/JSON e relatórios HTML.

`--sample-size` e `--memory-limit` estão disponíveis só para `publication` e `relation`; sem `--sample-size`, a validação usa a base completa.

Quando os dados já foram extraídos:

```bash
python run.py validate person --skip-extract
```

Nesse modo, views que já existem no DuckDB são reutilizadas sem recriá-las; views
ausentes são criadas a partir dos Parquets disponíveis.

Para forçar nova extração:

```bash
python run.py validate person --force-extract --workers 2
```

Também é aceita a forma de compatibilidade `python run.py person --skip-extract`.

# Análise exploratória

Gere o perfil descritivo de uma entidade cuja view já exista no DuckDB ou cujos Parquets estejam disponíveis:

```bash
python run.py explore person
```

O relatório HTML é salvo em `reports/exploration/<entidade>.html`. Os perfis de colunas e distribuições categóricas ficam em `results/exploration/<entidade>/`. As colunas categóricas são configuradas em `config/exploration.yaml`.

# Resultados

Após a execução:

```text
results/
└── person/
    ├── scores.csv
    ├── scores.json
    ├── errors.csv
    ├── errors.json
    ├── validation_summary.json
    └── gx_results.json

reports/
└── person/
    └── report.html
```

`scores.csv` e `scores.json` contêm os resultados por regra; `errors.csv` e `errors.json` listam todas as ocorrências inesperadas; `validation_summary.json` reúne os scores e contagens agregados; `gx_results.json` guarda os resultados de auditoria das Expectations. Durante a execução, as ocorrências são armazenadas temporariamente em JSON Lines no disco e exportadas em fluxo, evitando manter toda a lista na memória. A validação também atualiza o resumo geral em `results/quality_summary.json` e `reports/quality_summary.html`.

# Reconciliação da extração

Antes da validação, o projeto compara a quantidade de registros encontrados nos XMLs com a quantidade de registros gravados no Parquet.

```text
Registros XML
      |
      | comparação
      v
Registros Parquet
```

Se as contagens não forem compatíveis, a validação de qualidade não deve prosseguir.

Isso evita confundir um problema de extração com um problema de qualidade dos dados.

# Idempotência

A extração mantém informações de processamento por arquivo XML, permitindo evitar o processamento repetido de arquivos já concluídos.

Quando for necessário refazer uma extração:

```bash
python extract.py person --force
```

# Adicionando uma nova entidade

1. Adicione a fonte e seus campos em:

```text
config/entities.yaml
```

2. Crie o módulo `quality/<entidade>.py` com uma função `validate()` que carregue os dados, construa as regras e retorne `(scores, errors, metadata)`. Use `quality/common.py` para a infraestrutura compartilhada.

3. Inspecione a fonte e teste a estrutura dos XMLs:

```bash
python extract.py nova_entidade --inspect
```

4. Execute a extração:

```bash
python extract.py nova_entidade
```

5. Execute as validações:

```bash
python run.py validate nova_entidade --skip-extract
```

# Tecnologias

- **Python** — implementação do pipeline;
- **lxml** — processamento dos XMLs;
- **PyYAML** — configuração das entidades;
- **PyArrow / Parquet** — armazenamento intermediário;
- **DuckDB** — consultas analíticas, camada SQL e validação das tabelas grandes (publication e relation);
- **Great Expectations** — validação da qualidade dos dados;

# Referências

- [DuckDB](https://duckdb.org/)
- [DuckDB — Parquet](https://duckdb.org/docs/current/data/parquet/overview)
- [DuckDB — Python Client](https://duckdb.org/docs/current/clients/python/overview)

# Autora

Nicole Cardozo dos Santos

Projeto desenvolvido como parte do trabalho de conclusão de curso em Ciência da Computação.
