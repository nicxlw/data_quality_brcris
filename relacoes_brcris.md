# Relações do metamodelo BrCris

Lista das relações **não comentadas** no metamodelo fornecido. A seta segue o formato solicitado: `toEntity -> fromEntity`. Relações com o mesmo par de entidades foram agrupadas. Quando uma relação já aparece em um bloco anterior, ela não é repetida nos blocos seguintes.

## Legenda de disponibilidade

- **[deveria ter]** — as entidades envolvidas estão na lista de entidades disponíveis: `Person`, `OrgUnit`, `Patent`, `Program`, `Software`, `Journal` e `ResearchGroup`.
- **[futuro]** — envolve `Publication` ou `Event`.
- **[indisponível]** — envolve entidade que não consta na lista de disponíveis e não se enquadra na categoria futuro.

## 1. Relações que envolvem Person

| Relação (`toEntity -> fromEntity`) | Nome(s) da relação | Status |
|---|---|---|
| `Person -> OrgUnit` | `Affiliation`, `ResearchGroupMembership` | **[deveria ter]** |
| `Person -> Patent` | `Inventor`, `Depositor` | **[deveria ter]** |
| `Person -> Project` | `ProjectMembership`, `TeamMembership` | **[indisponível]** |
| `Person -> Publication` | `Authorship`, `Adivisoring`, `CoAdivisoring`, `Referee` | **[futuro]** |
| `Person -> Software` | `Creator` | **[deveria ter]** |
| `ResearchGroup -> Person` | `LeaderResearchGroup`, `MemberResearchGroup` | **[deveria ter]** |

## 2. Relações que envolvem OrgUnit

As relações já listadas no bloco Person não são repetidas aqui.

| Relação (`toEntity -> fromEntity`) | Nome(s) da relação | Status |
|---|---|---|
| `Course -> OrgUnit` | `CourseOrgUnit` | **[indisponível]** |
| `OrgUnit -> Journal` | `JournalOrgUnit` | **[deveria ter]** |
| `OrgUnit -> OrgUnit` | `IsUnitOf` | **[deveria ter]** |
| `OrgUnit -> Patent` | `Applicant` | **[deveria ter]** |
| `Program -> OrgUnit` | `OrgUnitProgram` | **[deveria ter]** |
| `Project -> OrgUnit` | `OrgUnitProject` | **[indisponível]** |
| `Publication -> OrgUnit` | `ThesisSponsorship` | **[futuro]** |
| `ResearchGroup -> OrgUnit` | `LeaderResearchGroupOrgUnit`, `PartnerResearchGroupOrgUnit` | **[deveria ter]** |

## 3. Relações que envolvem Publication

As relações já listadas nos blocos Person e OrgUnit não são repetidas aqui.

| Relação (`toEntity -> fromEntity`) | Nome(s) da relação | Status |
|---|---|---|
| `Event -> Publication` | `PublicationEvent` | **[futuro]** |
| `Journal -> Publication` | `PublisherJournal` | **[futuro]** |
| `Program -> Publication` | `ProgramThesis` | **[futuro]** |
| `Publication -> Course` | `CourseThesis` | **[futuro]** |
| `Publication -> Publication` | `PartOf` | **[futuro]** |

## 4. Outras relações

As relações já listadas nos blocos anteriores não são repetidas aqui.

| Relação (`toEntity -> fromEntity`) | Nome(s) da relação | Status |
|---|---|---|
| `Course -> Program` | `IsProgramOf` | **[indisponível]** |
| `Funding -> Funding` | `SubFunding` | **[indisponível]** |
| `Funding -> Project` | `FundedBy` | **[indisponível]** |

## Resumo

| Status | Quantidade de relações |
|---|---:|
| **[deveria ter]** | 13 |
| **[futuro]** | 10 |
| **[indisponível]** | 7 |
| **Total** | **30** |

## Observações

1. Os nomes e as direções foram mantidos conforme os atributos `fromEntity` e `toEntity` do metamodelo. A notação da tabela, por solicitação, aparece como `toEntity -> fromEntity`.
2. Algumas descrições do metamodelo parecem inconsistentes com os tipos declarados; a classificação foi baseada nos tipos de entidade declarados, não na descrição textual.
3. `Course` foi considerada indisponível, pois não aparece na lista de entidades informada como disponível. Se já estiver implementada no extrator, `CourseOrgUnit` e `IsProgramOf` podem ser reclassificadas como **[deveria ter]**.
4. O metamodelo contém outras relações totalmente dentro de comentários XML; elas foram excluídas da lista conforme solicitado.
