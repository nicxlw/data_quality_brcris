# Relatório de qualidade de dados: BrCRIS

Este relatório reúne os problemas encontrados nas classes extraídas dos arquivos XML do BrCRIS. As classes estão ordenadas das mais afetadas para as menos afetadas e, dentro de cada classe, os problemas seguem a mesma ordem (do maior para o menor).

Cada problema segue o mesmo roteiro:

- **Em resumo:** uma ou duas frases com o problema.
- **O que acontece:** explicação do que o campo representa e do que está errado.
- **Números / Exemplo:** o tamanho do problema e casos reais dos dados.
- **Hipótese:** causa provável, quando existe. Hipóteses são interpretações minhas e não foram confirmadas com a equipe.

## Resumo geral

| # | Classe | Principais problemas |
|---|---|---|
| 1 | [Publication](#publication) | ~60% dos registros são cópias; 8,5% sem título e sem autor (fonte OASIS); 21,4% das teses sem orientador |
| 2 | [Relation](#relation) | 1,2 milhão de relações apontam para organizações que não existem em `orgunit`; pessoas das relações ausentes em `person` |
| 3 | [Person](#person) | ~500 mil registros reduzidos duplicados (`lattes::`); ~16 mil ORCID fora da lista de autoridade; ORCID repetido |
| 4 | [Journal](#journal) | 60% com mais de um ISSN; 40% sem ISSN; 15% de ISSN repetido |
| 5 | [Patent](#patent) | 25 mil dos 43 mil registros são réplicas; relação `Applicant` sem correspondência |
| 6 | [OrgUnit](#orgunit) | 12% com mais de um `identifier.brcris`; identificadores repetidos; telefones inválidos (10%) |
| 7 | [Software](#software) | Datas fora do formato (~60% com valores estranhos); 15% com mais de um `identifier.brcris` |
| 8 | [Program](#program) | 4% de `identifier.brcris` repetido com `capes` distinto; telefones e URLs estranhos |
| 9 | [Course](#course) | 0,8% de `identifier.brcris` repetido com `capes` distinto |
| 10 | [Research Group](#research-group) | Praticamente sem problemas |

Ao final há as [perguntas para a equipe](#perguntas-para-a-equipe) e dois apêndices: [listas de autoridade criadas](#apêndice-a--listas-de-autoridade-não-encontradas) e [validações extras](#apêndice-b--validações-que-o-modelo-não-pede).

## Antes de ler

### Termos usados

- **Registro:** uma linha da tabela da classe (uma `entity` no XML).
- **`ref`:** identificador do registro no XML. Quando o registro resulta de deduplicação, tem o formato `cluster_{uuid}`.
- **`identifier.brcris`:** identificador próprio do BrCRIS (no XML também aparece como `semanticIdentifier` `brcris::{hash}`). A forma como é calculado muda por classe: em `person` é o MD5 do Lattes; em `journal` é o MD5 do ISSN; em `orgunit` o campo guarda um código `BRCRIS-xxxxxxxx` e o `brcris::` das relações é o MD5 desse código em minúsculas; em `publication`, pelo que observei, é um hash calculado a partir de título, ano e tipo.
- **Singularidade:** um campo identificador deveria ter um único valor por registro. Falha quando há mais de um (aparece com `|`, ver abaixo).
- **Unicidade:** o mesmo valor de identificador não deveria aparecer em registros diferentes. Falha quando se repete. (Não é crítico nesse momento do projeto, mas é um dado interessante)
- **Lista de autoridade:** lista de referência com os valores aceitos (países, idiomas, ORCID, Lattes etc.).

### Uso de `|` para campos com múltiplos valores

Programei os scripts de extração para que, quando um campo se repetisse em um registro, os valores fossem colocados lado a lado na coluna do DBeaver, separados por `|`. Por exemplo, se o XML tem:

```xml
<entity type="Person" ref="cluster_0c222acf-ada5-4521-9e0e-fd0405b2bf2a">
  <semanticIdentifier>lattes::9636606591195952</semanticIdentifier>
  <semanticIdentifier>brcris::be8df12b6517e4d84c05e16e57fcaa2e</semanticIdentifier>
  <semanticIdentifier>orcid::0000-0002-7601-9272</semanticIdentifier>
  <field name="identifier.orcid" preferred="true" value="0000-0002-7601-9272"/>
  <field name="identifier.orcid" preferred="true" value="0009-0004-9869-7447"/>
```

No DBeaver, a coluna `identifier.orcid` do registro `cluster_0c222acf-ada5-4521-9e0e-fd0405b2bf2a` terá o valor `0000-0002-7601-9272|0009-0004-9869-7447`.

---

# Publication

É a maior classe: **18.922.051 registros**, vindos de várias fontes (artigos, livros, capítulos, orientações e formação do Lattes, com as cargas 2025-2026; `PublicacaoOASIS`; `PublicationDOI`; `PublicationORCID`). Por tipo: Artigo (11,2 milhões), Dissertação (3,4 milhões), Capítulo de Livro (2,0 milhões), Tese (1,28 milhão), Livro (913 mil), Artigo de Conferência (51,6 mil), Preprint (36,7 mil) e Conjunto de Dados (13,7 mil).

## Problema 1 – Registros repetidos (unicidade)

> **Em resumo:** a mesma publicação aparece em vários registros, cada um com `ref` diferente e vindo de um arquivo diferente. Cerca de 60% dos registros são cópias.

### `identifier.brcris`

**O que acontece.** Cada publicação deveria ter um `identifier.brcris` único. Na prática, todos os registros têm o campo preenchido, mas os 18,9 milhões de registros correspondem a apenas 11,2 milhões de valores distintos: se a deduplicação usasse só esse identificador, a base cairia cerca de 41%. As cópias são a mesma publicação com pequenas diferenças, como autores em ordem diferente. Nenhuma cópia está no mesmo arquivo: todas vêm de arquivos diferentes.

| Cópias com o mesmo `brcris` | Grupos | Registros |
|---|---|---|
| 1 (sem repetição) | 7.390.835 | 7.390.835 (39%) |
| 2 | 2.129.032 | 4.258.064 |
| 3 | 725.677 | 2.177.031 |
| 4 | 439.675 | 1.758.700 |
| 5 | 235.271 | 1.176.355 |
| 6 | 142.559 | 855.354 |
| 7 ou mais | 147.076 | 1.258.620 |

(Ficam de fora os 47.092 registros com dois `brcris`, tratados no [Problema 5](#problema-5--dois-valores-em-identifierbrcris-singularidade).)

- 89% dos registros repetidos estão em grupos de 2 a 6 cópias; 10% em grupos de 7 a 19; há ~60 grupos com 100 ou mais cópias (máximo de 1.498).

**De onde vêm as cópias** (estimado a partir de uma amostra de 1/20 dos grupos devido ao tamanho da base; as 30 combinações mais frequentes cobrem 99% dos registros repetidos):

| Origem da repetição | % dos registros repetidos |
|---|---|
| Lattes + `PublicationDOI` e/ou `PublicationORCID` | 47% |
| Só Lattes (currículos diferentes ou carga 2025-2026) | 26% |
| Só bases externas (`PublicationDOI`, `PublicationORCID`, OASIS) | 11% |
| OASIS + Orientações/Formação do Lattes (teses e dissertações) | 9% |
| OASIS + artigo ou livro do Lattes | 6% |

- Entre os grupos só do Lattes, a média é de 2,4 a 2,8 cópias por obra (por exemplo, 2,5 em `PublicacaoArtigoLattes`).
- `PublicationDOI` e `PublicationORCID` trazem praticamente as mesmas obras: 40.559 registros na amostra formam grupos que contêm só esses dois arquivos.
- **Hipótese:** a mesma obra aparece uma vez em cada currículo Lattes de coautor; a carga 2025-2026 repete obras da carga anterior; e as bases externas repetem obras que já estão no Lattes.

**O que muda entre as cópias** (grupos repetidos):

| Campo | Grupos em que as cópias divergem |
|---|---|
| Autor (`author`) | 52% |
| Título | 12% |
| Idioma | 12% |
| Página inicial | 11% |
| DOI | 7% |
| Tipo | 0% (o tipo faz parte do hash) |

- Em 35% dos grupos só algumas cópias têm autor, e em 24% só algumas têm DOI. Juntar as cópias recuperaria parte do que falta.

**O `brcris` falha nos dois sentidos.**

- **Junta obras diferentes (colisão).** Os maiores grupos são títulos genéricos: os 10 maiores têm entre 1.009 e 1.498 cópias e todos são `Editorial`, tipo Artigo. Como o hash usa título, ano e tipo, editoriais de periódicos diferentes caem no mesmo valor. Quanto maior o grupo, maior a chance de ser colisão. Medida pela proporção de grupos com DOIs diferentes: 6% nos grupos de 2 a 6 cópias, 25% nos de 7 a 19, 44% nos de 20 a 99 e 67% nos de 100 ou mais.
- **Separa a mesma obra em duas versões de hash:** ver o sufixo `v2` no [Problema 5](#problema-5--dois-valores-em-identifierbrcris-singularidade).

### `identifier.doi`

**O que acontece.** Cerca de 85% dos registros com DOI têm um DOI repetido. O DOI de livro e capítulo compartilhado explicaria parte disso, mas não é a causa principal:

| Causa da repetição do DOI | % dos DOIs repetidos |
|---|---|
| Cópias da mesma publicação (mesmo `brcris`) | 82% |
| **`brcris` diferentes, mesmo DOI** | **17%** |
| Só capítulos (compartilham o DOI do livro) | 0,8% |
| Livro + capítulos | 0,6% |

- Ou seja, 82% da repetição de DOI é a mesma que repete `identifier.brcris`, e só 1,4% vem de capítulos.
- Os 17% restantes (~324 mil DOIs, ~1,4 milhão de registros) são o mais relevante: a mesma obra, com o mesmo DOI e quase o mesmo título, mas com `brcris` diferentes. São duplicatas que a deduplicação por `brcris` não junta.

**Exemplo:** o DOI `10.1016/j.cofs.2014.12.004` (*Improving the functional properties of milk proteins: focus on the specificities of proteolytic enzymes*, Artigo) aparece em 4 registros com 2 `brcris`:

| Fonte | `identifier.brcris` |
|---|---|
| `PublicationORCID` | `90d1891ff08da3ac00fc0f0affd84620` |
| `PublicationDOI` | `90d1891ff08da3ac00fc0f0affd84620` |
| `PublicacaoArtigoLattes` (2 registros) | `3490fbcdc3370fb9d8593beba08fe979` |

Outro exemplo é o DOI `10.1590/1519-6984.17512`: um registro do Lattes tem o título cortado (`…river basin`) e os outros trazem `…river basin, state of são paulo`, e por isso os hashes mudam (`680b8521…` contra `47db6353…`).

- **Hipótese:** diferenças de título (como o corte acima) ou de ano entre a cópia do Lattes e a das bases externas mudam o hash, que depende de título, ano e tipo.

### `identifier.isbn`

**O que acontece.** O ISBN só existe em `Livro` (89% dos registros têm) e `Capítulo de Livro` (88%); em todos os outros tipos é nulo. Cerca de 83% dos registros com ISBN (2,15 milhões de 2,58 milhões) têm ISBN repetido. A repetição vem sobretudo da estrutura livro/capítulo: o ISBN do capítulo é o do livro.

| Causa da repetição do ISBN | % dos ISBNs repetidos |
|---|---|
| Livro + capítulos (média de ~10 registros por ISBN) | 51% |
| Só capítulos (o livro não está na base) | 21% |
| Cópias da mesma publicação (mesmo `brcris`) | 19% |
| Só livros, com `brcris` diferentes | 8,5% |

- Livro e capítulos com o mesmo ISBN não são erro dos dados. Só os 19% de cópias e os 8,5% de livros com `brcris` diferentes (que podem ser duplicatas não detectadas ou edições diferentes) indicam duplicidade.

### `identifier.other`

**O que acontece.** O campo guarda o ID da obra no OpenAlex (`W…`). Só existe em `PublicationDOI` e `PublicationORCID`, então os 73% de repetição vêm de um único fato: os dois arquivos trazem as mesmas obras.

- `PublicationDOI` tem 1.754.146 valores, todos distintos; `PublicationORCID` tem 2.062.753, com 2.051.004 distintos (repetição interna de só 0,6%).
- ~79% das obras de `PublicationDOI` estão também em `PublicationORCID`.

## Problema 2 – Registros sem título (8,5%)

> **Em resumo:** 1,6 milhão de registros não têm título, e praticamente todos vêm de uma única fonte (`PublicacaoOASIS`).

**O que acontece.** Nenhum registro dessa fonte tem título (100%), nem autor, ano, DOI ou ISSN. O que existe é o tipo, as palavras-chave, o resumo e um identificador institucional (`UFMG_…`, `USP-11_…`).

- 1.622.513 registros (8,5%) não têm `title`.
- 99,8% deles (1.619.463) vêm de `PublicacaoOASIS`. Nenhum é do Lattes.
- Os 3.050 restantes (0,2%) vêm de `PublicationORCID` (1.534) e `PublicationDOI` (1.516), cerca de 0,1% de cada fonte.

**Exemplo de registro OASIS** (arquivo `PublicacaoOASIS/LOTE_E9/e9000a0a-09cd-45d0-a87f-eacfa5f7a312.xml`):

```
type:               Artigo
title:              (vazio)
author:             (vazio)
keywords:           Educação|Comunicação cientifica|Jornalismo cientifico|Barragem|Desastres ambientais
abstract:           "Este trabalho investigou as orientações ideológicas presentes em informações
                     científicas. (...) o rompimento da barragem de Fundão (...)"
identificador institucional: UFMG_dfac1362cc08993b3a5b9830dfc8a31c
identifier.brcris:  4d122d607bc1ce06c8fe5e3055530176
```

- **Hipótese:** a fonte OASIS é entregue sem esses campos, ou eles se perdem na extração.
- Pista a favor da segunda: o `brcris` dos registros OASIS casa com o de cópias do Lattes (há grupos com OASIS e Orientações do Lattes, por exemplo). Como o hash depende do título, o título existia quando o `brcris` foi gerado e se perdeu depois. [Quantos desses títulos poderiam ser recuperados pela cópia do Lattes ainda não foi medido.]

## Problema 3 – Registros sem autor (8,5%)

> **Em resumo:** é praticamente o mesmo grupo do problema anterior: quem não tem título quase sempre também não tem autor.

**O que acontece.** O autor pode ser informado de duas formas: no campo `author` do registro e na relação `Authorship`. Comparando as duas:

| Campo `author` | Relação `Authorship` | Registros | % do total |
|---|---|---|---|
| vazio | existe | 1.043.480 | 5,5% |
| vazio | não existe | 578.883 | 3,1% |
| preenchido | existe | 14.752.910 | 78,0% |
| preenchido | não existe | 2.546.778 | 13,5% |

- 1.622.363 registros (8,5%) não têm `author`. Destes, 64% têm a relação `Authorship` (o autor existe, só não foi copiado para o campo) e 36% (3,1% do total) não têm autor em lugar nenhum.
- Campo e relação discordam em 19% das publicações (as duas linhas "existe só um dos dois").
- A interseção com o [Problema 2](#problema-2--registros-sem-título-85) é praticamente total: 99,8% dos registros sem título também não têm autor, e são da fonte `PublicacaoOASIS`. Só 2.900 registros têm título e não têm autor.
- **Ressalva:** a relação é ligada ao registro pelo `brcris`. Como as cópias compartilham o mesmo valor, a relação encontrada pode ter vindo de outra cópia da mesma publicação (por isso os 64% são um limite superior).

## Problema 4 – Teses sem orientador (21,4%)

> **Em resumo:** 273.643 das 1.280.843 teses não têm o campo `advisor`. Metade vem da fonte OASIS (que nunca traz o campo) e a outra metade das Orientações do Lattes.

**O que acontece.** O orientador também pode ser informado de duas formas: no campo `advisor` e na relação `Adivisoring`.

| Campo `advisor` | Relação `Adivisoring` | Teses | % das teses |
|---|---|---|---|
| vazio | existe | 163.359 | 12,8% |
| vazio | não existe | 110.284 | 8,6% |
| preenchido | existe | 855.185 | 66,8% |
| preenchido | não existe | 152.015 | 11,9% |

- Das teses sem o campo, 60% (163.359) têm a relação: o orientador existe, mas não foi copiado. Só as 110.284 restantes (8,6% de todas as teses) não têm orientador em lugar nenhum.
- O inverso também ocorre: 152.015 teses (11,9%) têm o campo, mas não têm a relação. Campo e relação discordam em cerca de 25%.

**Por fonte** (teses sem `advisor`):

| Fonte | Teses sem `advisor` | % |
|---|---|---|
| OASIS | 140.520 | 100% das teses OASIS (51% do total) |
| Orientações do Lattes | 133.016 | ~21% (49% do total) |
| Formação do Lattes | 107 | 0,02% |

- **Hipótese:** nas Orientações do Lattes o dono do currículo é o próprio orientador, então o nome dele pode não ser repetido no campo `advisor` (mas a relação existe); na Formação o orientador é informado pelo aluno, e por isso o campo vem quase sempre preenchido. No OASIS o campo não existe na fonte. [Não testei ainda se as Orientações sem campo têm a relação.]

## Problema 5 – Dois valores em `identifier.brcris` (singularidade)

> **Em resumo:** 0,25% dos registros (47.092) têm dois `identifier.brcris` na mesma linha, sempre no padrão `{md5}|{md5}v2`.

**O que acontece.** O campo deveria ter um único valor. Esses registros têm dois: o segundo termina em `v2`, sufixo que não existe em nenhum dos 18,87 milhões de registros com um único valor. Acontece em todas as fontes e tipos (78% em artigos do Lattes).

- 81,7% desses registros têm entidade HTML no título (`&#945;`, `&#946;`, `&#947;`, que são letras gregas escritas como código), contra 0,25% nos registros com um valor. Exemplos:
  - `3d scaffold of hydroxyapatite/&#946; tricalcium phosphate from mussel shells: synthesis, characterization and cytotoxicity`
  - `Hydrolytic enzyme activity (phytase and &#945;-amylase) is decisive in the germination metabolism of maize seeds under salt stress`
- Os pares se repetem entre esses registros: dos 47.092 registros há ~26 mil pares distintos, ou seja, ~1,8 cópia por par. Se fossem registros já fundidos pela deduplicação, cada par apareceria uma única vez.

**Exemplo:** o artigo *Cannabidiol effect on long-term brain alterations in septic rats: involvement of ppar&#947; activation* aparece em pelo menos 14 registros, todos com o mesmo `identifier.brcris`:

```
6eb72a01cc4d365f341d1791e67916d8|3588dee114733fdabcccd6a01234b72ev2
```

Cada registro tem `ref` diferente e vem de um arquivo diferente do Lattes (`PublicacaoArtigoLattes/LOTE_2C/…`, `PublicacaoArtigoLattes2025-2026/PublicacaoArtigoLattes/LOTE_69/…` etc.).

- **Hipótese:** o `brcris` é gerado em duas versões, uma sobre o título original e outra (`v2`) sobre o título tratado. Quando as duas diferem, a fonte emite as duas no mesmo campo. Isso é compatível com a presença da entidade HTML, mas só 44,6% dos registros com entidade HTML no título têm o par, o que a hipótese não explica. [Perguntar à equipe como o `v2` é calculado.]

## Problema 6 – Erros de formato e digitação

> **Em resumo:** valores fora do formato esperado em ISBN, anos, páginas, DOI e URL.

- 10% dos registros apresentam valores de `identifier.isbn` que não passam na verificação de dígito e formato.
- 1.800 registros (0,03%) com URLs inválidas.
- `startPage` e `endPage` têm, respectivamente, 7% e 4% de registros com valores não numéricos, como `e115942920` ou `676-704`.
- 37 mil registros (<1%) têm `startPage` maior que `endPage`.
- 50 registros têm anos além de 2026 em `publicationDate`, 4 em `defenceDay` e 32 em `degreeDate`. Alguns valores são absurdos, como 2099.
- 2 registros têm `identifier.doi` sem o sufixo que vem depois da barra: `10.36560` e `10.19179`.
- 3 registros com valores estranhos de `identifier.isbn` (não sei afirmar se o `|` é da minha extração):
  - `COR/LA-1-4|UC`
  - `43227|SHIP`
  - `318-423X |`

## Problema 7 – Valores fora da lista de autoridade

> **Em resumo:** 425 registros usam idiomas que existem, mas não estão na lista de autoridade.

- 425 registros (13 valores distintos) com linguagens não contidas na lista de autoridade, mas são línguas que existem.

---

# Relation

A tabela `relation` liga entidades entre si. Cada relação tem um tipo (por exemplo, `Affiliation` liga uma organização a uma pessoa), um identificador de origem (`fromSemanticIdentifier`) e um de destino (`toSemanticIdentifier`). A validação confere se cada ponta existe na tabela da entidade correspondente.

**Como o casamento com `orgunit` funciona.** O `orgunit` guarda `identifier.brcris` no formato `BRCRIS-xxxxxxxx`, enquanto a relação usa `brcris::{hash}`. O hash é o MD5 do código em minúsculas. Por exemplo, `BRCRIS-00019532` (Secretaria da Educação do Estado do Ceará) vira `brcris-00019532`, cujo MD5 é `df0fc514e826bd186001e5b32712abac`, o valor que aparece na relação como `brcris::df0fc514e826bd186001e5b32712abac`.

## Problema 1 – Organizações das relações que não existem em `orgunit`

> **Em resumo:** quatro tipos de relação apontam, do lado `orgunit`, para organizações que não existem na tabela `orgunit`: 1,2 milhão de relações.

**O que acontece.** Mesmo aplicando a conversão MD5 acima, parte das relações não encontra a organização:

| Tipo de relação | Falhas | Total | % |
|---|---|---|---|
| Affiliation | 397.068 | 1.057.825 | 37,5% |
| ThesisSponsorship | 800.624 | 3.663.194 | 21,9% |
| PartnerResearchGroupOrgUnit | 6.377 | 21.731 | 29,3% |
| OrgUnitProgram | 1.094 | 5.164 | 21,2% |

- Confirmado que essas organizações não existem em `orgunit`. Os hashes que falham também não correspondem ao MD5 de nenhum outro campo de `orgunit` (`brcris`, `cnpj`, `isni`, `ror`, `grid`, `wikidata`, `ref` ou `name`), então não é erro de formatação.
- As falhas se concentram: são 16.930 organizações distintas; as 10 maiores respondem por 53,5% das falhas e as 100 maiores por 73,7%.
- 69 organizações falham nos quatro tipos ao mesmo tempo (704.926 relações, 58,5% do total).
- **Hipótese:** organizações grandes e muito citadas (universidades, agências de fomento) sem registro em `orgunit`.

**Exemplo:** a relação `Affiliation` abaixo vem de um arquivo de `person`. A organização `brcris::67059868d60bdbfff6f1f3f8c5a77417` (cluster `cluster_4df100b3-66ce-47e2-9ccc-597f7986665c`) é citada em muitas relações e não existe em `orgunit`:

```
tipo:   Affiliation
de:     brcris::67059868d60bdbfff6f1f3f8c5a77417   (organização)
para:   lattes::5197443719462491                   (pessoa)
fonte:  person/persons/2c/batch_4402_50clusters.xml
```

## Problema 2 – Pessoas das relações que não existem em `person`

> **Em resumo:** parte das pessoas citadas nas relações não existe na tabela `person`.

**O que acontece.** Não é questão de formatação diferente ou campos nulos: são pessoas que simplesmente não existem em `person`.

| Tipo de relação | % sem correspondência em `person` |
|---|---|
| Creator | 8% |
| Inventor | 2% |
| Authorship | 2% |
| Advisoring | 0,3% |
| CoAdvisoring | 1 registro |
| MemberResearchGroup | 2 registros |

- Os IDs Lattes dessas pessoas também não constam na lista de autoridade do Lattes, o que sugere IDs inválidos na fonte.

## Problema 3 – `Applicant` aponta sempre para o mesmo identificador

> **Em resumo:** todas as 196 relações `Applicant` dos arquivos de patent têm `ref` diferentes, mas compartilham o mesmo `semanticIdentifier` `brcris::aba4f9f3644e497efb37559cdcca4fa7`, que não existe em `orgunit`.

Problema já aprofundado, com exemplos, na seção [Patent](#problema-2--relação-applicant-sem-correspondência).

## Problema 4 – Relação `Creator` com `software` sem `identifier.brcris` (1 registro)

> **Em resumo:** uma relação de `creator` falhou do lado `software`.

- O identificador semântico `brcris::bc549f0a39094c775d686cc976636d39` não existe em `software`.
- Investigando mais a fundo, é o registro de `software` com `ref = cluster_505452b2-ae72-453b-9754-53f692ac6fcf`. O identificador semântico é esse de fato, mas o registro não possui o campo `identifier.brcris` (nulo).

## Problema 5 – Relação com `ref` sem registro correspondente (1 relação)

> **Em resumo:** uma relação aponta para um `ref` que não existe em `person`.

- O arquivo `batch_19062_50clusters.xml` do lote `bf` tem uma relação que não corresponde a nenhum registro `person` do arquivo ou de `person` como um todo.
- A `ref` usada foi `b08f03de-f6ef-489d-9345-da3dcc17c961`, fora do padrão `cluster_{hash}` que todos os outros registros da classe usam. Mesmo adicionando `cluster_` não há correspondência.
- Isso causa o erro `(referência vazia)` na regra `REL-CON-SEM-020`.

---

# Person

> Estimativa: 1.782.849 registros, dos quais ~1,25 milhão são pessoas reais e ~530 mil são versões reduzidas duplicadas (Problema 1).

## Problema 1 – Registros reduzidos duplicados (`lattes::`)

> **Em resumo:** ~500 mil registros (528.904) têm o prefixo `lattes::` no `identifier.lattes`. São versões reduzidas, duplicadas dos registros sem prefixo, e compartilham o mesmo `ref`.

**O que acontece.** Esses registros trazem só `lattes`, `name` e `ref` preenchidos. Eles inflam a contagem de pessoas e fazem com que só 40,67% dos valores de `ref` não tenham duplicatas.

- Analisei melhor esse erro e percebi que é parcialmente um problema de conceito na minha extração. Configurei o extrator para percorrer os arquivos XML de uma classe e registrar na tabela do DuckDB todos os registros da entidade em questão. Só reparei agora que os arquivos de `person` têm aquele modelo de "registro reduzido" usado para registrar uma relação, não apenas para entidades externas, mas também para `person` em si. Não percebi esse comportamento de registrar a própria entidade de forma reduzida em outras entidades, somente em `person`.
- De qualquer forma, o valor de `identifier.lattes` é de fato "incorreto" (com prefixo) nesses registros. O número de duplicatas de `ref` é exatamente o dobro de registros com `identifier.lattes` fora do padrão.

Exemplo de registro resumido:

```xml
<entity type="Person" ref="cluster_87747338-4a26-4131-926d-57cccf999970">
  <semanticIdentifier>lattes::7529647492452963</semanticIdentifier>
  <field name="identifier.lattes" preferred="true" value="lattes::7529647492452963"/>
  <field name="name" preferred="true" value="Tania Giandoni Wolkoff" lang="POR"/>
</entity>
```

## Problema 2 – ORCID fora da lista de autoridade

> **Em resumo:** ~16 mil valores de `identifier.orcid` não estão na lista de autoridade de ORCID.

## Problema 3 – ORCID repetido entre pessoas diferentes

> **Em resumo:** 112 registros compartilham ORCID (56 pares, cada um em exatamente 2 registros). Quase todos são pessoas diferentes.

**O que acontece.** O ORCID é um identificador de pessoa e deveria ser único. Aqui o mesmo ORCID aparece em dois registros de lotes de arquivos diferentes.

- Só 2 pares parecem ser a mesma pessoa: `Ruben Johan Christiaan Pauwels`, com nome idêntico e Lattes diferentes, e `Natalia Marques da Silva` e `Natália Marques da Silva`, que só diferem no acento.
- Os outros 54 pares são de pessoas diferentes (similaridade de texto entre 0,41 e 0,87), e com Lattes diferentes.

Alguns exemplos, após análise:

- `Charles Fernando dos Santos` e `Charles Barbosa Santos`: nomes similares, mas ambos têm Lattes diferentes, o que indica que são pessoas diferentes, mas ORCID igual.
- `Rick Souza de Oliveira` e `Geize Carolinne Correia Andrade Oliveira`: nomes totalmente diferentes, mesmo ORCID.
- `Erasmo Benício Santos de Moraes Trindade` e `Arthur Thives Mello`: nomes totalmente diferentes, mas Erasmo aparece com 2 valores de ORCID, dentre eles o de Arthur.
- `Angela Capistrano Camargo Cabral` e `Andrea Capistrano Camargo Ribeiro`: nomes similares, mesmo ORCID.

## Problema 4 – Mais de um ORCID no mesmo registro

> **Em resumo:** 65 registros têm mais de um valor de `identifier.orcid`. Em 7 deles, um dos ORCIDs pertence a outra pessoa.

**O que acontece.** O modelo prevê um ORCID por pessoa. Pode ter correlação com os registros repetidos ([Problema 3](#problema-3--orcid-repetido-entre-pessoas-diferentes)), mas nem todo registro com ORCID duplicado envolve registros com múltiplos ORCIDs e nem todo registro com múltiplos ORCIDs apresenta duplicatas.

- Em 7 desses registros, um dos ORCIDs é compartilhado com outra pessoa de nome sem relação (por exemplo, `Erasmo Benício Santos de Moraes Trindade` e `Arthur Thives Mello`; `Diovani Paiano` e `Reginaldo da Silva Santos`; `Joel Porto Alves` e `Dircelene Teixeira do Nascimento`), com similaridade entre 0,46 e 0,62. Isso indica que o ORCID de outra pessoa foi anexado ao registro.
- Nos outros 58, os dois ORCIDs não aparecem em nenhum outro registro. Nesses casos pode ser uma pessoa que por alguma razão legitimamente tem dois ORCIDs, ou um registro que reúne ORCIDs de duas pessoas. Não consigo distinguir pelos dados, porque o Lattes e o nome são únicos em cada um (por exemplo, `Mara Lucia Martins Rodrigues` tem um Lattes, um nome e dois ORCIDs).

Exemplo de registro com mais de um `identifier.orcid`:

```xml
<entity type="Person" ref="cluster_0c222acf-ada5-4521-9e0e-fd0405b2bf2a">
  <semanticIdentifier>lattes::9636606591195952</semanticIdentifier>
  <semanticIdentifier>brcris::be8df12b6517e4d84c05e16e57fcaa2e</semanticIdentifier>
  <semanticIdentifier>orcid::0000-0002-7601-9272</semanticIdentifier>
  <field name="identifier.orcid" preferred="true" value="0000-0002-7601-9272"/>
  <field name="identifier.orcid" preferred="true" value="0009-0004-9869-7447"/>
  <field name="identifier.lattes" preferred="true" value="9636606591195952"/>
  <field name="name" preferred="true" value="Mara Lucia Martins Rodrigues" lang="POR"/>
  <field name="citationName" preferred="true" value="RODRIGUES, M. L. M." lang="POR"/>
  <field name="citationName" preferred="true" value="RODRIGUES, MARA LUCIA MARTINS" lang="POR"/>
  (...)
</entity>
```

## Problema 5 – `identifier.lattes` fora da lista de autoridade

> **Em resumo:** 2 valores de `identifier.lattes` não estão na lista de autoridade do Lattes.

- `5143086860347393`
- `7509592027132666`

---

# Journal

> `identifier.brcris` do periódico é o MD5 do ISSN. Por isso, tudo o que acontece com o ISSN (mais de um valor, repetição, ausência) se repete no `brcris`.

## Problema 1 – Mais de um ISSN no mesmo registro (singularidade)

> **Em resumo:** ~60% dos registros com `identifier.issn` têm mais de um ISSN e, portanto, mais de um `identifier.brcris`.

**O que acontece.** Um periódico pode ter ISSN impresso e eletrônico, então mais de um ISSN não é por si só erro. O que chama a atenção é a proporção e o que vem junto:

- Dentre esses, a grande maioria apresenta somente 2, e menos de 1% apresenta 3 ou mais.
- Todos eles apresentam somente um `identifier.issn_l` (o ISSN que agrupa as versões do mesmo periódico).
- Metade desses 60% apresenta também mais de um valor em `title`, então talvez sejam dois elementos registrados de forma separada mas que na prática representam a mesma coisa. Mas o que explica os que têm somente um título?

Exemplo:

```xml
<entity type="Journal" ref="7a003529-c993-4857-bc07-7674266f065c">
  <semanticIdentifier>brcris::87b299d334988d48542fc8fae5c9ab4b</semanticIdentifier>
  <semanticIdentifier>issn::2394-2916</semanticIdentifier>
  <semanticIdentifier>brcris::e2bf0e0c7ab7e2fc6935ea0aff9259b7</semanticIdentifier>
  <semanticIdentifier>issn::2394-3432</semanticIdentifier>
  <semanticIdentifier>openalex::S4210190093</semanticIdentifier>
  <field name="identifier.brcris" value="87b299d334988d48542fc8fae5c9ab4b"/>
  <field name="identifier.issn" value="2394-2916"/>
  <field name="identifier.brcris" value="e2bf0e0c7ab7e2fc6935ea0aff9259b7"/>
  <field name="identifier.issn" value="2394-3432"/>
  <field name="identifier.issn_l" value="2394-2916"/>
  <field name="identifier.openalex" value="S4210190093"/>
  <field name="title" value="Journal Of Integrative Nephrology And Andrology"/>
  (...)
</entity>
```

## Problema 2 – 40% dos registros sem `identifier.issn`

> **Em resumo:** 40% dos registros não têm ISSN e, portanto, não têm `identifier.brcris`.

- Em todos esses casos, `identifier.openalex` está preenchido, então o periódico é identificável pelo OpenAlex.

## Problema 3 – Registros repetidos (unicidade)

> **Em resumo:** 15% dos valores de `identifier.issn` (30 mil) falham na unicidade: o mesmo periódico aparece em mais de um registro.

**O que acontece.** Dos cerca de 196 mil valores de `identifier.issn`, 15% (30 mil) falham na unicidade, o que dá cerca de 14,7 mil ISSN que aparecem em mais de um registro. O `identifier.brcris` falha praticamente nos mesmos registros (30.362 contra 30.360), porque é o MD5 do ISSN.

- Em 51% desses ISSN, os registros repetidos têm o mesmo `identifier.openalex` e o mesmo `title`, ou seja, diferem apenas no `ref`.
- Nos outros 49%, o mesmo ISSN está associado a mais de um `identifier.openalex`:
  - em 36% os títulos também mudam, mas por diferenças de grafia ou por apresentar mais de um valor separado por `|` (ex.: `Energia Na Agricultura` e `Energia Na Agricultura|Revista Energia Na Agricultura.`, ou `Humanística` e `Humanistica`);
  - em 13% o título é o mesmo.
- A duplicidade de `identifier.openalex` (4% dos registros, 8 mil falhas) mostra o mesmo padrão: cada OpenAlex repetido aparece 2 vezes (3.995 casos) ou 3 vezes (16 casos), sempre com um único ISSN, e todas as cópias têm `title`, `identifier.issn`, `identifier.issn_l` e `identifier.brcris` idênticos.
- Quase não há registros "fundidos" (com vários ISSN) repetidos junto de registros com ISSN único (81 grupos).

**Exemplo:** o ISSN `0102-9169` aparece em 6 registros, todos com os mesmos 3 ISSN e os mesmos 3 `brcris`: 3 com o OpenAlex `S4306509416` e 3 com `S4210218672`.

- **Hipótese:** duas causas combinadas: (1) o mesmo registro é emitido 2 ou 3 vezes com `ref` diferentes, e (2) o mesmo periódico existe como mais de uma fonte OpenAlex, que foram unidas pelo ISSN. A segunda também explicaria os registros com vários `identifier.issn` e vários `title` ([Problema 1](#problema-1--mais-de-um-issn-no-mesmo-registro-singularidade)).

## Problema 4 – Títulos fora da lista de autoridade

> **Em resumo:** 54% dos registros têm `title` que não consta na lista de periódicos de autoridade.

- Essa validação mede o quanto a lista de autoridade cobre os títulos; não indica necessariamente erro nos dados.

---

# Patent

> `identifier.espacenet` identifica a patente. Os registros de patent não têm `identifier.brcris` nem `identifier.lattes` preenchidos (ver "Pontos de atenção").

## Problema 1 – Registros repetidos

> **Em resumo:** dos 43 mil registros, só 18 mil são patentes distintas. Cerca de 25 mil são réplicas, em arquivos diferentes.

**O que acontece.** A mesma patente aparece uma vez em cada arquivo em que é citada.

- Dos 43 mil registros totais, só existem 18 mil `identifier.espacenet` distintos.
- Dos 25 mil registros duplicados, uns 17 mil são réplicas perfeitas dos originais, com todos os valores exatamente iguais, em arquivos diferentes. E uns 8 mil são quase isso, mas com leves diferenças de grafia no título.
- Só 18% dos registros não apresentam réplicas.

## Problema 2 – Relação `Applicant` sem correspondência

> **Em resumo:** todas as 196 relações `Applicant` apontam para o mesmo `semanticIdentifier` do lado `orgunit`, que não existe em `orgunit`.

**O que acontece.** A relação `Applicant` deveria ligar a patente à organização depositante. Todas as 196 relações do tipo `Applicant` contidas nos arquivos de patente fazem referência ao mesmo `semanticIdentifier` `brcris::aba4f9f3644e497efb37559cdcca4fa7` do lado `orgunit`. Os problemas são:

- Esse `semanticIdentifier`, que é o único que consta nos arquivos, não corresponde a nenhum `identifier.brcris` de `orgunit`, mesmo considerando a conversão MD5.
- Quando olhamos o campo `applicant`, contido na própria entidade, vemos valores diferentes para cada registro.
- Muitas vezes (não conferi todos os 196; é só um palpite) são nomes que não parecem ser organizações, como `STEFANIE ARCA GARRIDO LOUREIRO`.
- Os demais arquivos muitas vezes contêm um campo `applicant`, mas não têm a relação `Applicant` relacionando a patente a algum `orgunit`.

Exemplo 1: arquivo `patent/PatentesLattes/LOTE_00/00f9f31b-1e5c-440f-950b-b0a307eb85ae.xml`

```xml
<entity type="Patent" ref="Patent43749">
  <semanticIdentifier>docdb::BRPI1102356A</semanticIdentifier>
  (...)
  <field name="applicant" value="ITAJARA MINERIOS LTDA"/>
</entity>
```

A relação:

```xml
<relation type="Applicant" fromEntityRef="Patent43749" toEntityRef="OrgUnit4526"/>
```

E `OrgUnit4526` corresponde, no arquivo, a:

```xml
<entity type="OrgUnit" ref="OrgUnit4526">
  <semanticIdentifier>brcris::aba4f9f3644e497efb37559cdcca4fa7</semanticIdentifier>
</entity>
```

Exemplo 2: arquivo `patent/PatentesLattes/LOTE_01/0179a53d-2a63-435e-b46f-b6960d0be819.xml`

```xml
<entity type="Patent" ref="Patent40251">
  <semanticIdentifier>docdb::BRPI0704666A</semanticIdentifier>
  (...)
  <field name="applicant" value="STOLLBERG DO BRASIL LTDA"/>
</entity>
```

A relação:

```xml
<relation type="Applicant" fromEntityRef="Patent40251" toEntityRef="OrgUnit4023"/>
```

E `OrgUnit4023` corresponde, no arquivo, a:

```xml
<entity type="OrgUnit" ref="OrgUnit4023">
  <semanticIdentifier>brcris::aba4f9f3644e497efb37559cdcca4fa7</semanticIdentifier>
</entity>
```

Nos dois exemplos, depositantes diferentes (`ITAJARA MINERIOS LTDA` e `STOLLBERG DO BRASIL LTDA`) apontam para o mesmo `semanticIdentifier`.

## Problema 3 – Padrão estranho de identificadores semânticos

> **Em resumo:** os identificadores semânticos de patent não correspondem aos campos `identifier.*` da entidade e têm mais de um valor por tipo.

Não é uma validação, mas percebi que os registros de patent têm um padrão estranho de identificadores semânticos. Exemplo:

```xml
<semanticIdentifier>docdb::BRPI1102356A</semanticIdentifier>
<semanticIdentifier>docdb::BRPI1102356A2</semanticIdentifier>
<semanticIdentifier>epodoc::BR2011PI02356</semanticIdentifier>
<semanticIdentifier>epodoc::BRPI1102356</semanticIdentifier>
<semanticIdentifier>original::PI 1102356-2 A2</semanticIdentifier>
<semanticIdentifier>espacenet::PI1102356</semanticIdentifier>
<semanticIdentifier>brcris::33e0f13b8b60bb1c8f8c1eda7709486b</semanticIdentifier>
<semanticIdentifier>brcris::dcfd2d25d8a10a9dbd544ef04b45f366</semanticIdentifier>
<field name="identifier.espacenet" value="PI1102356"/>
(...)
```

- `docdb`, `epodoc` e `original` não correspondem a nenhum `identifier.*` da entidade `patent`.
- Há mais de um valor para cada tipo de identificador, inclusive dois valores de `espacenet`, embora só haja um campo `identifier.espacenet`.
- Há identificador do tipo `brcris`, mas não há campo `identifier.brcris`.

## Pontos de atenção

- `identifier.brcris` e `identifier.lattes` estão totalmente nulos. Deveria ser assim mesmo?
- 27 registros não têm o campo `inventor` preenchido, mas têm a relação `inventor` preenchida. É um erro?
- Muitos registros apresentam a seção IPC com valor `Y`, mas deveria ser uma letra de A a H.

---

# OrgUnit

## Problema 1 – Mais de um valor em campos de identificador (singularidade)

> **Em resumo:** 12% dos registros têm mais de um `identifier.brcris`; 5 têm mais de um CNPJ e 2 mais de um ISNI. Em geral são registros fundidos pela deduplicação.

### `identifier.brcris` (12% dos registros)

**O que acontece.** Desses, praticamente todos têm mais de um valor em `name`, mas parece ser exatamente o mesmo nome repetido duas vezes. Também reparei que `identifier.brcrisName` tem sempre somente um valor.

Exemplo:

```xml
<entity type="OrgUnit" ref="cluster_3574b34e-6e68-4b4d-a822-beac3a460e78">
  <semanticIdentifier>brcris::df0fc514e826bd186001e5b32712abac</semanticIdentifier>
  <semanticIdentifier>brcrisName::63850123c4cf890949839aec5933b3d2</semanticIdentifier>
  <semanticIdentifier>brcris::2c8e868cb2fc50beb1005494e20b6f6b</semanticIdentifier>
  <field name="identifier.brcris" value="BRCRIS-00019532"/>
  <field name="identifier.brcris" value="BRCRIS-00019685"/>
  <field name="name" value="Secretaria da Educacao do Estado do Ceara" lang="POR"/>
  <field name="name" value="Secretaria de Educacao do Estado do Ceara" lang="POR"/>
  (...)
</entity>
```

### `identifier.cnpj` (5 registros)

Formato `cnpj: nome`:

- `04034526000143|13128798001680`: Secretaria de Estado Saude|Secretaria de Estado da Saude|Secretaria de Estado de Saude|Secretaria do Estado da Saude
- `00394676000107|08778250000169`: Secretaria de Estado da Educacao|Secretaria de Estado de Educacao|Secretaria de Estado de Educacao do para|Secretaria de Estado e Educacao|Secretaria do Estado da Educacao|Secretaria do Estado de Educacao|Secretaria do Estado de Educacao do para
- `01062213000100|05252176000154`: Secretaria de Estado de Cultura
- `05054945000100|075531295000171`: Secretaria de Estado de Desenvolvimento Agropecuario e da Pesca
- `02809449000120|2520788700114`: Instituto de Ciências Sociais e Humanas

### `identifier.isni` (2 registros)

Formato `isni: nome`:

- `0000 0001 2179 088X|0000 0004 7411 6145`: The University of Melbourne
- `0000 0001 0676 048X|0000 0001 2179 1997`: Albert Einstein College of Medicine

## Problema 2 – Identificadores repetidos em registros diferentes (unicidade)

> **Em resumo:** o mesmo CNPJ, ISNI, GRID, ROR ou Wikidata aparece em registros diferentes. Não são réplicas: nome e `identifier.brcris` sempre diferem.

**O que acontece.** Valores repetidos: 119 registros em `identifier.cnpj` (53 valores repetidos, 12% dos valores avaliados), 24 em `identifier.isni` (12 valores, 3%), 20 em `identifier.grid` e 20 em `identifier.ror` (10 valores cada, 4%) e 16 em `identifier.wikidata` (8 valores, 3%). Observações:

- Nenhuma duplicata é uma réplica: em todos os grupos o `name` e o `identifier.brcris` são diferentes entre os registros. O `identifier.brcris` nunca se repete entre registros.
- Os valores são idênticos entre si. Não há diferença de formatação (espaços, maiúsculas ou pontuação) que escondesse duplicatas.
- Os 20 registros repetidos em GRID e ROR são os mesmos (10 pares), e coincidem com os de ISNI e Wikidata (os 4 registros sem Wikidata são de IUPERJ e FURB, que não têm esse campo). Só 6 desses também repetem o CNPJ. Os outros 113 registros com CNPJ repetido não repetem nenhum outro identificador.
- Nos 10 pares de ROR repetido, vejo quatro situações:
  - 6 pares de instituição e mantenedora, fundação ou associação, com o mesmo ISNI, GRID, ROR e Wikidata. Exemplos: `Universidade de Ribeirão Preto` e `Associacao de Ensino de Ribeirao Preto`; `Universidade Estadual da Zona Oeste` e `Fundacao Centro Universitario Estadual da Zona Oeste`; `Hospital Israelita Albert Einstein` e `Sociedade Beneficente Israelita Brasileira Albert Einstein`.
  - 1 par com a mesma organização em grafias diferentes: `National Institute of Health` e `National Institutes of Health`.
  - 1 par com hierarquia: `Instituto de Fomento e Coordenacao Industrial` e `Departamento de Ciencia e Tecnologia Aeroespacial`, com o mesmo CNPJ.
  - 2 pares de organizações diferentes, em cidades diferentes e com CNPJ diferente, que têm os mesmos ISNI, GRID, ROR e Wikidata: `Pontifícia Universidade Católica de Goiás` e `Universidade Católica de Pelotas`; `Universidade Rio Verde` e `Universidade de Santa Cruz do Sul`. Parece erro de atribuição dos identificadores.
- No CNPJ, os 5 mais repetidos são, em sua maioria, o CNPJ de uma mantenedora compartilhado por unidades de cidades diferentes:
  - `19347410000131`: Faculdades de Ponta Porã (MS), Santa Luzia (MG) e Ibaiti (PR).
  - `33621384000119`: Cenecista de Osório e Faculdades Cnec de Varginha, Santo Ângelo e Gravataí.
  - `88332580000165`: unidades Luteranas de Palmas, Canoas e Manaus.
  - `33787094000140`: Escola Nacional de Ciências Estatísticas, IBGE e Fundação IBGE (hierarquia, e IBGE e Fundação IBGE parecem ser a mesma organização).
  - `77046951000126`: quatro universidades estaduais do Paraná, uma secretaria de ciência e tecnologia de Curitiba e a `Fundacao Universidade Estadual de Maringa`.
- Nos mesmos exemplos, aparecem erros de codificação (`Universidade Estadual de Maringã¡`) e um `city` com nome de estado (`Universidade Estadual do Centro-Oeste`, `city = Paraná`).

## Problema 3 – Erros de formato e digitação

> **Em resumo:** 10% dos telefones e 2% dos e-mails são inválidos; há CNPJs com quantidade errada de dígitos ou dígito verificador inválido.

- 10% dos registros têm formatos inválidos de telefone, provavelmente erros de digitação (considerei apenas instituições brasileiras).
- 2% dos registros têm valores inválidos de e-mail, provavelmente erros de digitação.
- 1% dos registros com formato inválido de CEP (considerei válidos `xxxxx-xxx` ou `xxxxxxxx`).
- 8 registros (<1%) com CNPJ tendo uma quantidade estranha de dígitos, como 10, 11 ou até 15, provavelmente erros de digitação. Além disso, dentre os CNPJs com formato válido, 6 têm dígito verificador inválido.
- 1 registro com formato inválido de `identifier.isni`: `0000 0001 0378 43550000 0001 0378 4355` (dois ISNI colados sem separador, provavelmente colocados em um só campo no xml).

## Problema 4 – Valores fora da lista de autoridade

> **Em resumo:** `country`, `city` e `identifier.brcris` com valores que não constam nas listas de autoridade.

- 261 casos (mas 15 valores distintos) em que `country` não existe na lista de autoridade.
- 25 casos em que `identifier.brcris` não existe na lista de autoridade.
- 18 casos de `city` não correspondendo a valores da lista de autoridade.

## Análise conjunta: singularidade e unicidade (observações e hipóteses)

Os problemas de singularidade (Problema 1) e de unicidade (Problema 2) parecem ser consequência do mesmo processo de deduplicação, que funde registros em clusters (`cluster_…`), em dois resultados distintos:

- **Onde a fusão aconteceu,** o registro fica com vários `identifier.brcris` e vários `name`, e eventualmente com mais de um CNPJ ou ISNI.
- **Onde ela não aconteceu,** o mesmo identificador fica em registros separados.

A hipótese é confirmada pelos dados: nenhum registro com mais de um valor aparece também entre os valores repetidos em outro registro (`brcris`: 223 registros com vários valores e 0 com valor repetido; `cnpj`: 5 e 0; `isni`: 2 e 0; `grid`, `ror` e `wikidata`: 0 com vários valores). Isso é coerente com o `brcris` ser único entre registros apesar de 12% ter mais de um valor.

A fusão parece inconsistente:

- Variações de nome do mesmo tipo (diferença de preposição) foram fundidas em `Secretaria da Educacao do Estado do Ceara` e `Secretaria de Educacao do Estado do Ceara`, mas não em `National Institute of Health` e `National Institutes of Health`, que compartilham ISNI, GRID, ROR e Wikidata e ficaram em registros separados.
- Da mesma forma, `Universidade Estadual de Maringá` é um registro fundido (3 nomes e 3 `brcris`), e ao lado dele existe `Fundacao Universidade Estadual de Maringa`, com o mesmo CNPJ.

Isso sugere que o critério de fusão não considera o identificador igual como evidência suficiente, e que ISNI, GRID, ROR e Wikidata iguais em organizações diferentes (`Pontifícia Universidade Católica de Goiás` e `Universidade Católica de Pelotas`, por exemplo) podem vir de atribuição errada de identificadores externos na origem.

Há também um efeito oposto: a correção da unicidade (fundir os registros repetidos) aumentaria os registros com vários valores, e fundir as unidades de uma mesma mantenedora estaria errado.

---

# Software

## Problema 1 – Datas fora do formato esperado

> **Em resumo:** o modelo pede `dd/mm/yyyy` para `depositDate` e `concessionDate`, mas nenhum valor segue esse formato, e ~60% têm valores estranhos mesmo sem separador.

- Todos os valores estão sem separador, como `14082012`.
- Mesmo dentro desse formato, 60% dos registros apresentam valores estranhos, como `9042019` (7 dígitos, com o zero do dia ou do mês faltando) ou `18052015|2032016` (mais de uma data no mesmo registro: deveria ser permitido?).

## Problema 2 – Mais de um valor em `identifier.brcris` (15%)

> **Em resumo:** 15% dos registros têm mais de um valor em `identifier.brcris`, quase todos também com mais de um `title` ou `releaseYear`.

- Dentre esses, quase todos apresentam mais de um valor para `title` ou para `releaseYear`, então pode ser aquela mesma hipótese de registros "fundidos" descrita em Journal e OrgUnit.

## Problema 3 – Mais de um valor em `identifier.inpi` (10 registros)

> **Em resumo:** 10 registros têm mais de um valor em `identifier.inpi`, alguns com vírgula ou ponto.

- Desses, só 2 também têm 2 valores de `brcris`.
- Alguns têm valores com vírgula ou ponto, o que achei estranho. Exemplos:
  - `516,.163|516.163`
  - `512019001620-3|512019001620-3,`
  - `BR13084-4|BR13084-4,`

## Pontos de atenção

- 2 registros (com títulos `Teste_titulo` e `Tabletpc`) sem `identifier.brcris` e `identifier.inpi`. Pelos nomes, parecem exemplos de teste, mas achei melhor registrar aqui.
- `iugoslavia`, `irlanda do norte` e `gra-bretanha` não estão na lista de autoridade de países e são usados por 9 registros (não é por acentuação).
- 2 registros têm `language = "outros"`, que não está na lista de autoridade de línguas.

---

# Program

## Problema 1 – Registros repetidos (4%)

> **Em resumo:** 195 registros (4%) têm o mesmo `identifier.brcris` e `name`, mas `identifier.capes` (e às vezes `phone`) distintos.

- É bem parecido com o problema de [Course](#course): podem ser programas diferentes que foram confundidos como o mesmo.

## Problema 2 – Telefones em padrões estranhos

> **Em resumo:** 61 registros têm `phone` em formato estranho.

- Exemplos: `(39) 022361`, `(32) 336730`, `(None) None`.

## Problema 3 – URLs estranhas

> **Em resumo:** 5 registros têm URL com erro de digitação ou com texto extra.

1. `http://http:/www.iag.usp.br/pos/node/8155`
2. `http://http:\\naoinformado.naoinformado`
3. `https://sigaa.ufrn.br/sigaa/public/programa/portal.jsf?lc=pt_BR&id=85 ou https://posgraduacao.ufrn.br/quimica`
4. `hhttp://portal.fgv.br/sao-paulo`
5. `http://www.furb.br (selecionar Pós-Graduação - Química)`

---

# Course

## Problema 1 – Registros repetidos (0,8%)

> **Em resumo:** 56 registros (0,8%) têm o mesmo `identifier.brcris` e `name`, mas `identifier.capes` e `start date` distintos. Talvez sejam cursos diferentes confundidos como o mesmo.

Exemplos (`brcris`):

- `138048d8ed792b158edf0be983fb3dff`
- `c928bacb23c512a60a2ca8b5f134a98c`
- `21d6b38f76180045c0bd03dad09ed517`
- `42549dc53d8bb2849fe8b63c366204d9`
- `da24ea5c653f57421504c9b9c558fb90`

## Observação – Lista de autoridade de `degree`

- O modelo diz para validar `degree` contra a lista de autoridade, mas não achei lista de autoridade correspondente. Então criei uma com os valores contidos na descrição do campo (`graduation`, `specialization`, `master`, `doctoral`, `posDoctoral`, `fullProfessor`) em inglês e português. As categorias mestrado profissional e doutorado profissional não estavam inclusas, mas constam nos arquivos.

---

# Research Group

> **Em resumo:** é uma das entidades mais corretas; só um ponto de atenção.

- 0,8% dos registros apresentam mais de um valor na coluna `identifier.dgp` (mas `brcris` está ok).

---

# Apêndice A – Listas de autoridade não encontradas

Não encontrei algumas listas de autoridade pedidas pelo modelo. Para essas, criei uma lista base em `quality/autoridade/dominios.json`, com valores tirados da descrição do modelo e dos valores observados nos dados.

- **`publication.type`** (`PUB-AUT-TYPE`). O modelo diz "validar na lista de autoridade de tipos e gravar no idioma PT". Lista criada: Artigo, Dissertação, Capítulo de Livro, Tese, Livro, Artigo de Conferência, Preprint, Conjunto de Dados.
- **`publication.accessType`** (`PUB-AUT-ACCESSTYPE`). O modelo diz "validar na lista de autoridade de tipos de acesso (baseado no COAR) e gravar no idioma PT". Lista criada: open access, embargoed access, restricted access, metadata only access, e os equivalentes em português (Acesso aberto, Acesso embargado, Acesso restrito, Somente metadados).
- **`course.degree`** (`CRS-AUT-DEGREE`). O modelo diz "validar na lista de autoridade de graus e gravar no idioma PT", com os valores `graduation`, `specialization`, `master`, `doctoral`, `posDoctoral`, `fullProfessor`. Lista criada: esses seis, mais Graduação, Especialização, Mestrado, Doutorado, Pós-doutorado e Livre-docência (esta última é minha interpretação de `fullProfessor`).
- **`course.type`** (`CRS-AUT-TYPE`). O modelo diz "validar na lista de autoridade de tipo (Acadêmico ou Profissional) e gravar no idioma PT". Lista criada: Academic, Professional, Acadêmico, Profissional.
- **`software.kind`** (`SFT-AUT-KIND`). O modelo diz "validar na lista de autoridade de tipo de software". Lista criada: COMPUTACIONAL, MULTIMIDIA, OUTRO (os únicos valores encontrados nos dados).

# Apêndice B – Validações que o modelo não pede

- **`JOU-AUT-COUNTRY`** (`journal.countryCode`). O modelo não pede validação contra lista de autoridade para esse campo. Como já existia a lista de países, resolvi usá-la.
- **`JOU-AUT-QUALIS`** (`journal.qualis`). O modelo também não pede validação. Criei a lista A1–A4, B1–B4, C.
- **Validações de capitalização.** Não implementei as validações de capitalização, porque fiquei em dúvida se deveria implementá-las.
