# Validações realizadas por classe

Lista de todas as regras de qualidade que o projeto executa, por classe. Foi gerada a partir do código (`quality/*.py`) com o conjunto real de colunas de cada classe, então reflete o que de fato roda.

**Total: 265 regras em 10 classes.**

## Como ler

Cada regra tem um **id** (`PREFIXO-DIMENSÃO-…`), uma **dimensão** e um **tipo de validação**:

| Dimensão (id) | O que verifica |
|---|---|
| Singularidade (`SIN`) | O campo tem **um único** valor por registro (sem `\|`). Roda antes da unicidade, para o `\|` não esconder duplicatas. |
| Unicidade (`UNI`) | O mesmo valor não aparece em mais de um registro. Em campos com vários valores, cada valor separado por `\|` é testado. |
| Completude (`COM`) | O campo obrigatório está preenchido. |
| Validade (`VAL`) | O valor tem formato, dígito verificador, intervalo ou data válidos. |
| Autoridade (`AUT`) | O valor existe em uma lista de referência (países, estados, municípios IBGE, idiomas, Qualis, domínios fixos…) em `quality/autoridade/`. |
| Consistência (`CON`) | O valor é coerente com outro campo do mesmo registro, com outros registros ou, em `relation`, com a classe de destino. |

Se uma coluna não existe na classe, as regras dela simplesmente não são geradas. Como regra geral, valor vazio não conta como erro de formato: a ausência é medida pela completude.

## Resumo

| Classe | Regras |
|---|---|
| [Pessoa (person)](#person) | 45 |
| [Unidade organizacional (orgunit)](#orgunit) | 35 |
| [Periódico (journal)](#journal) | 28 |
| [Patente (patent)](#patent) | 17 |
| [Programa de pós-graduação (program)](#program) | 14 |
| [Software (software)](#software) | 17 |
| [Grupo de pesquisa (researchgroup)](#researchgroup) | 11 |
| [Curso (course)](#course) | 23 |
| [Publicação (publication)](#publication) | 45 |
| [Relações (relation)](#relation) | 30 |

## Pessoa (person) <a id="person"></a>

| Id | Dimensão / tipo | Coluna | O que verifica |
|---|---|---|---|
| `PER-SIN-01` … `PER-SIN-13` | singularidade | `identifier.brcris`, `identifier.lattes`, `identifier.lattesShort`, `identifier.cpf`, `identifier.email`, `identifier.orcid`, `identifier.researcherID`, `identifier.scopusAuthorID`, `identifier.cienciaID`, `identifier.capes`, `identifier.openalex`, `identifier.dark`, `identifier.other` | Cada registro tem um único valor (sem `\|`) em cada um destes identificadores. |
| `PER-UNI-01` … `PER-UNI-13` | unicidade | `identifier.brcris`, `identifier.lattes`, `identifier.lattesShort`, `identifier.cpf`, `identifier.email`, `identifier.orcid`, `identifier.researcherID`, `identifier.scopusAuthorID`, `identifier.cienciaID`, `identifier.capes`, `identifier.openalex`, `identifier.dark`, `identifier.other` | Cada valor do identificador não se repete em outros registros (valores separados por `\|` são testados um a um). |
| `PER-COM-IDENTIFIER-LATTES` | completude | `identifier.lattes` | identifier.lattes deve estar preenchido. |
| `PER-COM-NAME` | completude | `name` | name deve estar preenchido. |
| `PER-COM-REF` | completude | `ref` | ref deve estar preenchido. |
| `PER-UNI-REF` | unicidade | `ref` | Cada pessoa deve ter uma referência ref única. |
| `PER-VAL-01` | validade | `identifier.lattes` | Cada identificador Lattes deve ter exatamente 16 dígitos, sem URL nem prefixo. |
| `PER-VAL-02` | validade | `identifier.orcid` | ORCID deve seguir o formato XXXX-XXXX-XXXX-XXXX (apenas o formato textual). |
| `PER-VAL-ORCID-DV` | dígito verificador | `identifier.orcid` | O dígito verificador do ORCID deve ser válido (avaliado nos valores com formato correto). |
| `PER-VAL-CPF` | dígito verificador | `identifier.cpf` | identifier.cpf, quando preenchido, deve ter 11 dígitos com dígito verificador válido. |
| `PER-VAL-URL` | formato de URL | `personalURL` | personalURL, quando preenchido, deve conter um endereço web válido (com ou sem http/https, ex.: www.site.com). |
| `PER-VAL-BIRTHDATE` | data | `birthDate` | birthDate, quando preenchida, deve ser uma data válida (dd/mm/aaaa, aaaa-mm-dd ou aaaa), entre 1900 e hoje. |
| `PER-CON-BRCRIS-LATTES` | consistência entre campos | `identifier.brcris` | identifier.brcris deve ser o MD5 do identifier.lattes do mesmo registro. |
| `PER-CON-ID-01` | consistência | `identifier.lattes` | O mesmo identifier.lattes não deve estar associado a pessoas com refs diferentes. |
| `PER-CON-ID-02` | consistência | `identifier.orcid` | O mesmo identifier.orcid não deve estar associado a pessoas com refs diferentes. |
| `PER-VAL-EMAIL-01` | formato de e-mail | `identifier.email` | Cada endereço em identifier.email deve ter um formato básico de e-mail válido. |
| `PER-AUT-BIRTH-COUNTRY` | lista de autoridade | `birthCountry` | birthCountry deve corresponder a um código ou nome de país aceito. |
| `PER-AUT-BIRTH-STATE` | lista de autoridade | `birthState` | birthState deve corresponder a um código ou nome de estado aceito. |
| `PER-AUT-BIRTH-CITY` | lista de autoridade | `birthCity` | birthCity deve corresponder a um município da lista IBGE. |
| `PER-AUT-LATTES` | lista de autoridade | `identifier.lattes` | identifier.lattes deve existir na lista de IDs Lattes de autoridade. |
| `PER-AUT-ORCID` | lista de autoridade | `identifier.orcid` | identifier.orcid deve existir na lista de ORCIDs de autoridade. |

## Unidade organizacional (orgunit) <a id="orgunit"></a>

| Id | Dimensão / tipo | Coluna | O que verifica |
|---|---|---|---|
| `ORG-SIN-ID-01` … `ORG-SIN-ID-07` | singularidade | `identifier.brcris`, `identifier.brcrisName`, `identifier.cnpj`, `identifier.isni`, `identifier.grid`, `identifier.ror`, `identifier.wikidata` | Cada registro tem um único valor (sem `\|`) em cada um destes identificadores. |
| `ORG-UNI-ID-01` … `ORG-UNI-ID-07` | unicidade | `identifier.brcris`, `identifier.brcrisName`, `identifier.cnpj`, `identifier.isni`, `identifier.grid`, `identifier.ror`, `identifier.wikidata` | Cada valor do identificador não se repete em outros registros (valores separados por `\|` são testados um a um). |
| `ORG-COM-IDENTIFIER-BRCRIS` | completude | `identifier.brcris` | identifier.brcris deve estar preenchido. |
| `ORG-COM-NAME` | completude | `name` | name deve estar preenchido. |
| `ORG-COM-REF` | completude | `ref` | ref deve estar preenchido. |
| `ORG-UNI-REF` | unicidade | `ref` | Cada organização deve ter uma referência ref única. |
| `ORG-UNI-NAME` | unicidade | `name` | Cada organização deve ter um nome único. |
| `ORG-VAL-BRCRIS` | formato | `identifier.brcris` | identifier.brcris deve seguir o formato BRCRIS- seguido de oito dígitos. |
| `ORG-VAL-ISNI` | formato | `identifier.isni` | identifier.isni deve seguir o formato XXXX XXXX XXXX XXXX (o último caractere pode ser X). |
| `ORG-VAL-ROR` | formato | `identifier.ror` | identifier.ror deve ter 9 caracteres: 0, seis letras/números e dois dígitos (ex.: 04cwrbc27). |
| `ORG-VAL-GRID` | formato | `identifier.grid` | identifier.grid deve seguir o formato grid.NNNNNN.x. |
| `ORG-VAL-WIKIDATA` | formato | `identifier.wikidata` | identifier.wikidata deve seguir o formato Q seguido de números. |
| `ORG-VAL-CEP` | formato | `cep` | Para country = 'Brasil', cep deve ter 8 dígitos (xxxxx-xxx ou xxxxxxxx). |
| `ORG-VAL-CNPJ` | formato | `identifier.cnpj` | identifier.cnpj deve conter exatamente 14 dígitos numéricos. |
| `ORG-VAL-EMAIL` | formato | `electronicAddress` | electronicAddress deve seguir o formato básico de e-mail usado em Person. |
| `ORG-VAL-URL` | formato | `websiteUrl` | websiteUrl deve conter um endereço web válido (com ou sem http/https, ex.: www.site.com). |
| `ORG-VAL-PHONE` | formato | `phone` | Para country = 'Brasil', phone deve seguir o formato (xx) xxxx-xxxx ou (xx) 9xxxx-xxxx (DDD pode ter 0 inicial; hífen opcional ou trocado por espaço). |
| `ORG-VAL-CNPJ-DV` | dígito verificador | `identifier.cnpj` | O dígito verificador de identifier.cnpj deve ser válido (avaliado nos valores com formato correto). |
| `ORG-VAL-ISNI-DV` | dígito verificador | `identifier.isni` | O dígito verificador de identifier.isni deve ser válido (avaliado nos valores com formato correto). |
| `ORG-AUT-COUNTRY` | lista de autoridade | `country` | country deve corresponder a um código ou nome de país aceito. |
| `ORG-AUT-STATE` | lista de autoridade | `state` | state deve corresponder a um código ou nome de estado aceito. |
| `ORG-AUT-CITY-BR` | lista de autoridade | `city` | Quando country for Brasil, city deve corresponder a um município da lista IBGE. |
| `ORG-AUT-BRCRIS` | lista de autoridade | `identifier.brcris` | identifier.brcris deve existir na lista de códigos BrCris de autoridade. |

## Periódico (journal) <a id="journal"></a>

| Id | Dimensão / tipo | Coluna | O que verifica |
|---|---|---|---|
| `JOU-SIN-ID-01` … `JOU-SIN-ID-04` | singularidade | `identifier.issn`, `identifier.issn_l`, `identifier.openalex`, `identifier.brcris` | Cada registro tem um único valor (sem `\|`) em cada um destes identificadores. |
| `JOU-UNI-ID-01` … `JOU-UNI-ID-04` | unicidade | `identifier.issn`, `identifier.issn_l`, `identifier.openalex`, `identifier.brcris` | Cada valor do identificador não se repete em outros registros (valores separados por `\|` são testados um a um). |
| `JOU-COM-REF` | completude | `ref` | ref deve estar preenchido. |
| `JOU-COM-TITLE` | completude | `title` | title deve estar preenchido. |
| `JOU-COM-IDENTIFIER-OPENALEX` | completude | `identifier.openalex` | identifier.openalex deve estar preenchido. |
| `JOU-COM-IDENTIFIER-ISSN` | completude | `identifier.issn` | identifier.issn deve estar preenchido. |
| `JOU-COM-IDENTIFIER-BRCRIS` | completude | `identifier.brcris` | identifier.brcris deve estar preenchido. |
| `JOU-UNI-REF` | unicidade | `ref` | Cada periódico deve ter uma referência ref única. |
| `JOU-VAL-ISSN` | formato | `identifier.issn` | identifier.issn deve seguir o formato XXXX-XXXX (vários ISSN separados por '\|' são aceitos; cada um é avaliado). |
| `JOU-VAL-ISSN-L` | formato | `identifier.issn_l` | identifier.issn_l deve seguir o formato XXXX-XXXX (vários ISSN separados por '\|' são aceitos; cada um é avaliado). |
| `JOU-VAL-ISSN-DV` | dígito verificador | `identifier.issn` | O dígito verificador de identifier.issn deve ser válido (avaliado nos valores com formato XXXX-XXXX). |
| `JOU-VAL-ISSN-L-DV` | dígito verificador | `identifier.issn_l` | O dígito verificador de identifier.issn_l deve ser válido (avaliado nos valores com formato XXXX-XXXX). |
| `JOU-VAL-WEBSITE-URL` | formato de URL | `websiteURL` | websiteURL, quando preenchido, deve conter um endereço web válido (com ou sem http/https, ex.: www.site.com). |
| `JOU-VAL-ISOA` | domínio de valores | `isOa` | isOa deve ter o valor true ou false. |
| `JOU-VAL-IS-IN-DOAJ` | domínio de valores | `isInDoaj` | isInDoaj deve ter o valor true ou false. |
| `JOU-VAL-TYPE` | domínio de valores | `type` | type deve ser igual a 'journal'. |
| `JOU-AUT-ISSN` | lista de autoridade | `identifier.issn` | identifier.issn deve corresponder a um ISSN da lista de periódicos de autoridade. |
| `JOU-AUT-COUNTRY` | lista de autoridade | `countryCode` | countryCode deve corresponder a um código ou nome de país aceito. |
| `JOU-AUT-QUALIS` | lista de autoridade | `qualis` | qualis deve ser um dos conceitos A1-A4, B1-B4 ou C. |
| `JOU-AUT-TITLE` | lista de autoridade | `title` | title deve corresponder a um nome da lista de periódicos de autoridade. |
| `JOU-VAL-H-INDEX` | limite | `h_index` | h_index, quando preenchido, deve ser um número maior ou igual a zero. |
| `JOU-VAL-I10-INDEX` | limite | `i10_index` | i10_index, quando preenchido, deve ser um número maior ou igual a zero. |

## Patente (patent) <a id="patent"></a>

| Id | Dimensão / tipo | Coluna | O que verifica |
|---|---|---|---|
| `PAT-SIN-ID-01` … `PAT-SIN-ID-03` | singularidade | `identifier.brcris`, `identifier.lattes`, `identifier.espacenet` | Cada registro tem um único valor (sem `\|`) em cada um destes identificadores. |
| `PAT-UNI-ID-01` … `PAT-UNI-ID-03` | unicidade | `identifier.brcris`, `identifier.lattes`, `identifier.espacenet` | Cada valor do identificador não se repete em outros registros (valores separados por `\|` são testados um a um). |
| `PAT-COM-IDENTIFIER-ESPACENET` | completude | `identifier.espacenet` | identifier.espacenet deve estar preenchido. |
| `PAT-COM-TITLE` | completude | `title` | title deve estar preenchido. |
| `PAT-COM-INVENTOR` | completude | `inventor` | inventor deve estar preenchido. |
| `PAT-UNI-REF` | unicidade | `ref` | Cada patente deve ter uma referência ref única. |
| `PAT-VAL-RESOURCE-URL` | formato | `resourceUrl` | resourceUrl deve conter um endereço web válido (com ou sem http/https, ex.: www.site.com). |
| `PAT-VAL-KINDCODE` | formato | `kindCode` | kindCode deve ser uma letra, opcionalmente seguida de um dígito (ex.: A, B1, C1). |
| `PAT-VAL-COUNTRYCODE` | formato | `countryCode` | countryCode deve ter 2 letras maiúsculas (ex.: BR, US, WO). |
| `PAT-VAL-IPC-SECTION` | formato | `classification.ipc.section` | Cada seção IPC deve ser uma letra de A a H. |
| `PAT-VAL-DATE-DEPOSIT` | formato | `depositDate` | depositDate deve estar no formato dd/mm/yyyy. |
| `PAT-VAL-DATE-PUBLICATION` | formato | `publicationDate` | publicationDate deve estar no formato dd/mm/yyyy. |
| `PAT-VAL-PUBLICATION-AFTER-DEPOSIT` | ordem temporal | `publicationDate` | publicationDate deve ser posterior a depositDate. |

## Programa de pós-graduação (program) <a id="program"></a>

| Id | Dimensão / tipo | Coluna | O que verifica |
|---|---|---|---|
| `PRO-SIN-ID-01` … `PRO-SIN-ID-03` | singularidade | `identifier.brcris`, `identifier.capes`, `identifier.cnpq` | Cada registro tem um único valor (sem `\|`) em cada um destes identificadores. |
| `PRO-UNI-ID-01` … `PRO-UNI-ID-03` | unicidade | `identifier.brcris`, `identifier.capes`, `identifier.cnpq` | Cada valor do identificador não se repete em outros registros (valores separados por `\|` são testados um a um). |
| `PRO-COM-REF` | completude | `ref` | ref deve estar preenchido. |
| `PRO-COM-NAME` | completude | `name` | name deve estar preenchido. |
| `PRO-COM-IDENTIFIER-BRCRIS` | completude | `identifier.brcris` | identifier.brcris deve estar preenchido. |
| `PRO-COM-IDENTIFIER-CAPES` | completude | `identifier.capes` | identifier.capes deve estar preenchido. |
| `PRO-UNI-REF` | unicidade | `ref` | Cada programa deve ter uma referência ref única. |
| `PRO-VAL-PHONE` | formato | `phone` | phone deve seguir o formato (xx) xxxx-xxxx ou (xx) 9xxxx-xxxx (DDD pode ter 0 inicial; hífen opcional ou trocado por espaço). |
| `PRO-VAL-EMAIL` | formato | `email` | email deve seguir um formato básico de endereço de e-mail. |
| `PRO-VAL-WEBSITE-URL` | formato | `websiteUrl` | websiteUrl deve conter um endereço web válido (com ou sem http/https, ex.: www.site.com). |

## Software (software) <a id="software"></a>

| Id | Dimensão / tipo | Coluna | O que verifica |
|---|---|---|---|
| `SFT-SIN-ID-01` … `SFT-SIN-ID-02` | singularidade | `identifier.brcris`, `identifier.inpi` | Cada registro tem um único valor (sem `\|`) em cada um destes identificadores. |
| `SFT-UNI-ID-01` … `SFT-UNI-ID-02` | unicidade | `identifier.brcris`, `identifier.inpi` | Cada valor do identificador não se repete em outros registros (valores separados por `\|` são testados um a um). |
| `SFT-COM-REF` | completude | `ref` | ref deve estar preenchido. |
| `SFT-COM-TITLE` | completude | `title` | title deve estar preenchido. |
| `SFT-COM-IDENTIFIER-BRCRIS` | completude | `identifier.brcris` | identifier.brcris deve estar preenchido. |
| `SFT-COM-IDENTIFIER-INPI` | completude | `identifier.inpi` | identifier.inpi deve estar preenchido. |
| `SFT-UNI-REF` | unicidade | `ref` | Cada software deve ter uma referência ref única. |
| `SFT-VAL-RELEASEYEAR` | limite | `releaseYear` | releaseYear deve ser menor ou igual ao ano atual (2026). |
| `SFT-VAL-URLINPI` | formato | `urlINPI` | urlINPI deve conter um endereço web válido (com ou sem http/https, ex.: www.site.com). |
| `SFT-VAL-DEPOSIT-DATE` | data | `depositDate` | depositDate, quando preenchida, deve ser uma data válida (dd/mm/aaaa, aaaa-mm-dd ou aaaa), entre 1900 e hoje. |
| `SFT-VAL-CONCESSION-DATE` | data | `concessionDate` | concessionDate, quando preenchida, deve ser uma data válida (dd/mm/aaaa, aaaa-mm-dd ou aaaa), entre 1900 e hoje. |
| `SFT-VAL-CONCESSION-AFTER-DEPOSIT` | ordem temporal | `concessionDate` | concessionDate não pode ser anterior a depositDate (avaliado quando ambas são datas válidas). |
| `SFT-AUT-KIND` | lista de autoridade | `kind` | kind deve ser um dos valores aceitos: COMPUTACIONAL, MULTIMIDIA ou OUTRO. |
| `SFT-AUT-REGISTRATION-COUNTRY` | lista de autoridade | `registrationCountry` | registrationCountry deve corresponder a um código ou nome de país aceito. |
| `SFT-AUT-LANGUAGE` | lista de autoridade | `language` | language deve corresponder a um código ou nome de idioma aceito. |

## Grupo de pesquisa (researchgroup) <a id="researchgroup"></a>

| Id | Dimensão / tipo | Coluna | O que verifica |
|---|---|---|---|
| `RGR-SIN-ID-01` … `RGR-SIN-ID-02` | singularidade | `identifier.brcris`, `identifier.dgp` | Cada registro tem um único valor (sem `\|`) em cada um destes identificadores. |
| `RGR-UNI-ID-01` … `RGR-UNI-ID-02` | unicidade | `identifier.brcris`, `identifier.dgp` | Cada valor do identificador não se repete em outros registros (valores separados por `\|` são testados um a um). |
| `RGR-COM-REF` | completude | `ref` | ref deve estar preenchido. |
| `RGR-COM-NAME` | completude | `name` | name deve estar preenchido. |
| `RGR-COM-IDENTIFIER-BRCRIS` | completude | `identifier.brcris` | identifier.brcris deve estar preenchido. |
| `RGR-COM-IDENTIFIER-DGP` | completude | `identifier.dgp` | identifier.dgp deve estar preenchido. |
| `RGR-UNI-REF` | unicidade | `ref` | Cada grupo de pesquisa deve ter uma referência ref única. |
| `RGR-VAL-CREATIONYEAR` | limite | `creationYear` | creationYear deve ser menor ou igual ao ano atual (2026). |
| `RGR-VAL-URL` | formato | `URL` | URL deve conter um endereço web válido (com ou sem http/https, ex.: www.site.com). |

## Curso (course) <a id="course"></a>

| Id | Dimensão / tipo | Coluna | O que verifica |
|---|---|---|---|
| `CRS-SIN-ID-01` … `CRS-SIN-ID-06` | singularidade | `identifier.brcris`, `identifier.capes`, `identifier.mec`, `identifier.inep`, `identifier.cnpq`, `identifier.other` | Cada registro tem um único valor (sem `\|`) em cada um destes identificadores. |
| `CRS-UNI-ID-01` … `CRS-UNI-ID-06` | unicidade | `identifier.brcris`, `identifier.capes`, `identifier.mec`, `identifier.inep`, `identifier.cnpq`, `identifier.other` | Cada valor do identificador não se repete em outros registros (valores separados por `\|` são testados um a um). |
| `CRS-COM-REF` | completude | `ref` | ref deve estar preenchido. |
| `CRS-COM-NAME` | completude | `name` | name deve estar preenchido. |
| `CRS-COM-IDENTIFIER-BRCRIS` | completude | `identifier.brcris` | identifier.brcris deve estar preenchido. |
| `CRS-COM-IDENTIFIER-CAPES` | completude | `identifier.capes` | identifier.capes deve estar preenchido. |
| `CRS-UNI-REF` | unicidade | `ref` | Cada curso deve ter uma referência ref única. |
| `CRS-AUT-DEGREE` | lista de autoridade | `degree` | degree deve ser um grau aceito (graduation, specialization, master, doctoral, posDoctoral, fullProfessor ou equivalente em português). |
| `CRS-AUT-TYPE` | lista de autoridade | `type` | type deve ser Academic/Professional (ou Acadêmico/Profissional). |
| `CRS-VAL-YEAR-STARTDATE` | formato de ano | `startDate` | startDate deve conter somente o ano no formato YYYY quando preenchido. |
| `CRS-VAL-YEAR-ENDDATE` | formato de ano | `endDate` | endDate deve conter somente o ano no formato YYYY quando preenchido. |
| `CRS-VAL-START-YEAR-CURRENT` | limite | `startDate` | startDate deve ser menor ou igual ao ano atual (2026). |
| `CRS-CON-END-AFTER-START` | ordem temporal | `endDate` | endDate deve ser maior ou igual a startDate quando ambas estiverem preenchidas. |

## Publicação (publication) <a id="publication"></a>

Roda em SQL no DuckDB (`quality/fast.py`), sobre a base completa.

| Id | Dimensão / tipo | Coluna | O que verifica |
|---|---|---|---|
| `PUB-SIN-ID-01` … `PUB-SIN-ID-13` | singularidade | `identifier.brcris`, `identifier.doi`, `identifier.capes`, `identifier.bdtd`, `identifier.oasisbr`, `identifier.handle`, `identifier.pmcid`, `identifier.isi-number`, `identifier.scp-number`, `identifier.issn`, `identifier.isbn`, `identifier.dark`, `identifier.other` | Cada registro tem um único valor (sem `\|`) em cada um destes identificadores. |
| `PUB-UNI-ID-01` … `PUB-UNI-ID-13` | unicidade | `identifier.brcris`, `identifier.doi`, `identifier.capes`, `identifier.bdtd`, `identifier.oasisbr`, `identifier.handle`, `identifier.pmcid`, `identifier.isi-number`, `identifier.scp-number`, `identifier.issn`, `identifier.isbn`, `identifier.dark`, `identifier.other` | Cada valor do identificador não se repete em outros registros (valores separados por `\|` são testados um a um). |
| `PUB-COM-REF` | completude | `ref` | ref deve estar preenchido. |
| `PUB-COM-TITLE` | completude | `title` | title deve estar preenchido. |
| `PUB-COM-AUTHOR` | completude | `author` | author deve estar preenchido. |
| `PUB-COM-TYPE` | completude | `type` | type deve estar preenchido. |
| `PUB-COM-IDENTIFIER-BRCRIS` | completude | `identifier.brcris` | identifier.brcris deve estar preenchido. |
| `PUB-UNI-REF` | unicidade | `ref` | Cada referência ref deve ser única na base completa. |
| `PUB-VAL-YEAR-PUBLICATIONDATE` | limite | `publicationDate` | publicationDate deve ter ano de 4 dígitos entre 1500 e o ano atual (2026). |
| `PUB-VAL-YEAR-DEFENCEDAY` | limite | `defenceDay` | defenceDay deve ter ano de 4 dígitos entre 1500 e o ano atual (2026). |
| `PUB-VAL-YEAR-DEGREEDATE` | limite | `degreeDate` | degreeDate deve ter ano de 4 dígitos entre 1500 e o ano atual (2026). |
| `PUB-VAL-NUM-STARTPAGE` | formato numérico | `startPage` | startPage deve conter um valor numérico quando preenchido. |
| `PUB-VAL-NUM-ENDPAGE` | formato numérico | `endPage` | endPage deve conter um valor numérico quando preenchido. |
| `PUB-VAL-PAGES-ORDER` | consistência entre campos | `startPage` | startPage não pode ser maior que endPage (avaliado quando ambos são numéricos). |
| `PUB-VAL-DOI` | formato | `identifier.doi` | Cada DOI em identifier.doi deve começar com 10.<4 a 9 dígitos>/ seguido do sufixo, sem espaços. |
| `PUB-VAL-ISBN-DV` | dígito verificador | `identifier.isbn` | Cada ISBN em identifier.isbn deve ser um ISBN-10 ou ISBN-13 com dígito verificador válido (hifens ignorados). |
| `PUB-AUT-TYPE` | lista de autoridade | `type` | type deve ser um dos tipos aceitos: Artigo, Dissertação, Capítulo de Livro, Tese, Livro, Artigo de Conferência, Preprint, Conjunto de Dados. |
| `PUB-AUT-ACCESSTYPE` | lista de autoridade | `accessType` | accessType deve ser um dos valores aceitos (open/embargoed/restricted/metadata only access, ou equivalentes em português). |
| `PUB-VAL-RESOURCE-URL` | formato de URL | `resourceUrl` | resourceUrl deve conter um endereço web válido (com ou sem http/https, ex.: www.site.com) quando preenchido. |
| `PUB-COM-THESIS-ADVISOR` | completude | `advisor` | Publicações do tipo Tese devem ter advisor preenchido. |
| `PUB-AUT-LANGUAGE` | lista de autoridade | `language` | language deve corresponder a um código ou nome de idioma aceito. |

## Relações (relation) <a id="relation"></a>

Regras de **consistência referencial**: cada ponta (`fromSemanticIdentifier` / `toSemanticIdentifier`) de uma relação deve existir na classe de destino. O prefixo do `semanticIdentifier` (`lattes::`, `brcris::`, `docdb::`…) define qual coluna `identifier.<prefixo>` do destino é usada na comparação. O valor é normalizado antes (remove `prefixo::` e espaços; em `docdb` ignora código do país, tipo e símbolos; em `orgunit`, `brcris::` é o MD5 de `identifier.brcris` em minúsculas).

| Id | Tipo de relação | Ponta | Deve existir em |
|---|---|---|---|
| `REL-CON-SEM-001` | Applicant | origem (from) | patent |
| `REL-CON-SEM-002` | Applicant | destino (to) | orgunit |
| `REL-CON-SEM-003` | OrgUnitProgram | origem (from) | orgunit |
| `REL-CON-SEM-004` | OrgUnitProgram | destino (to) | program |
| `REL-CON-SEM-005` | IsProgramOf | origem (from) | program |
| `REL-CON-SEM-006` | IsProgramOf | destino (to) | course |
| `REL-CON-SEM-007` | Creator | origem (from) | software |
| `REL-CON-SEM-008` | Creator | destino (to) | person |
| `REL-CON-SEM-009` | PartnerResearchGroupOrgUnit | origem (from) | orgunit |
| `REL-CON-SEM-010` | PartnerResearchGroupOrgUnit | destino (to) | researchgroup |
| `REL-CON-SEM-011` | LeaderResearchGroup | origem (from) | person |
| `REL-CON-SEM-012` | LeaderResearchGroup | destino (to) | researchgroup |
| `REL-CON-SEM-013` | Inventor | origem (from) | patent |
| `REL-CON-SEM-014` | Inventor | destino (to) | person |
| `REL-CON-SEM-015` | CoAdivisoring | origem (from) | publication |
| `REL-CON-SEM-016` | CoAdivisoring | destino (to) | person |
| `REL-CON-SEM-017` | MemberResearchGroup | origem (from) | person |
| `REL-CON-SEM-018` | MemberResearchGroup | destino (to) | researchgroup |
| `REL-CON-SEM-019` | Affiliation | origem (from) | orgunit |
| `REL-CON-SEM-020` | Affiliation | destino (to) | person |
| `REL-CON-SEM-021` | CourseThesis | origem (from) | course |
| `REL-CON-SEM-022` | CourseThesis | destino (to) | publication |
| `REL-CON-SEM-023` | Adivisoring | origem (from) | publication |
| `REL-CON-SEM-024` | Adivisoring | destino (to) | person |
| `REL-CON-SEM-025` | PublisherJournal | origem (from) | publication |
| `REL-CON-SEM-026` | PublisherJournal | destino (to) | journal |
| `REL-CON-SEM-027` | ThesisSponsorship | origem (from) | orgunit |
| `REL-CON-SEM-028` | ThesisSponsorship | destino (to) | publication |
| `REL-CON-SEM-029` | Authorship | origem (from) | publication |
| `REL-CON-SEM-030` | Authorship | destino (to) | person |
