"""Definição das regras de integridade referencial de `relation`.

Os refs do XML são locais ao arquivo. O prefixo do semanticIdentifier determina
a coluna `identifier.<prefixo>` do dataset-alvo usada na comparação global
(docdb usa `identifier.espacenet`; ver IDENTIFIER_PREFIX_ALIASES).
A execução é feita em SQL no DuckDB por quality/fast.py (chamado por run.py).
"""
from __future__ import annotations

import re

from quality import common

IDENTIFIER_PREFIX_ALIASES = {"docdb": "espacenet"}

# Nestes alvos o semanticIdentifier 'brcris::<hash>' é o MD5 de identifier.brcris em minúsculas
# (ex.: orgunit BRCRIS-00019532 -> brcris::df0fc514...). A comparação usa md5(lower(brcris)).
HASHED_BRCRIS_TARGETS = {"orgunit"}

# (tipo, endpoint semântico, dataset-alvo, aliases de type)
RELATION_ENDPOINTS = [
    ("Applicant", "fromSemanticIdentifier", "patent", ("Applicant",)),
    ("Applicant", "toSemanticIdentifier", "orgunit", ("Applicant",)),
    ("OrgUnitProgram", "fromSemanticIdentifier", "orgunit", ("OrgUnitProgram",)),
    ("OrgUnitProgram", "toSemanticIdentifier", "program", ("OrgUnitProgram",)),
    ("IsProgramOf", "fromSemanticIdentifier", "program", ("IsProgramOf",)),
    ("IsProgramOf", "toSemanticIdentifier", "course", ("IsProgramOf",)),
    ("Creator", "fromSemanticIdentifier", "software", ("Creator", "creator")),
    ("Creator", "toSemanticIdentifier", "person", ("Creator", "creator")),
    ("PartnerResearchGroupOrgUnit", "fromSemanticIdentifier", "orgunit", ("PartnerResearchGroupOrgUnit",)),
    ("PartnerResearchGroupOrgUnit", "toSemanticIdentifier", "researchgroup", ("PartnerResearchGroupOrgUnit",)),
    ("LeaderResearchGroup", "fromSemanticIdentifier", "person", ("LeaderResearchGroup",)),
    ("LeaderResearchGroup", "toSemanticIdentifier", "researchgroup", ("LeaderResearchGroup",)),
    ("Inventor", "fromSemanticIdentifier", "patent", ("Inventor",)),
    ("Inventor", "toSemanticIdentifier", "person", ("Inventor",)),
    ("CoAdivisoring", "fromSemanticIdentifier", "publication", ("CoAdivisoring", "CoAdvisoring")),
    ("CoAdivisoring", "toSemanticIdentifier", "person", ("CoAdivisoring", "CoAdvisoring")),
    ("MemberResearchGroup", "fromSemanticIdentifier", "person", ("MemberResearchGroup",)),
    ("MemberResearchGroup", "toSemanticIdentifier", "researchgroup", ("MemberResearchGroup",)),
    ("Affiliation", "fromSemanticIdentifier", "orgunit", ("Affiliation",)),
    ("Affiliation", "toSemanticIdentifier", "person", ("Affiliation",)),
    ("CourseThesis", "fromSemanticIdentifier", "course", ("CourseThesis",)),
    ("CourseThesis", "toSemanticIdentifier", "publication", ("CourseThesis",)),
    ("Adivisoring", "fromSemanticIdentifier", "publication", ("Adivisoring",)),
    ("Adivisoring", "toSemanticIdentifier", "person", ("Adivisoring",)),
    ("PublisherJournal", "fromSemanticIdentifier", "publication", ("PublisherJournal",)),
    ("PublisherJournal", "toSemanticIdentifier", "journal", ("PublisherJournal",)),
    ("ThesisSponsorship", "fromSemanticIdentifier", "orgunit", ("ThesisSponsorship",)),
    ("ThesisSponsorship", "toSemanticIdentifier", "publication", ("ThesisSponsorship",)),
    ("Authorship", "fromSemanticIdentifier", "publication", ("Authorship", "Authirship")),
    ("Authorship", "toSemanticIdentifier", "person", ("Authorship", "Authirship")),
]


def docdb_keys(text: object) -> set[str]:
    """Chaves de comparação de um número docdb/espacenet.

    O mesmo número pode vir com ou sem código do país (BR), com ou sem código de
    tipo (A2, B1...) e com símbolos (BR-PI0701760-A2). Gera as variações; dois
    valores são o mesmo documento se tiverem alguma chave em comum.
    """
    text = str(text or "")
    text = text.partition("::")[2] if "::" in text else text
    base = re.sub(r"[^0-9A-Za-z]", "", text).upper()
    keys = {base, re.sub(r"^[A-Z]{2}", "", base)}
    keys |= {re.sub(r"[A-Z][0-9]?$", "", key) for key in keys}
    return {key for key in keys if key}


def endpoint_texts(side: str, relation_type: str, target: str, columns: list[str],
                   sample_scope: str) -> tuple[str, str]:
    """Descrição e motivo de uma regra, com o nome real da coluna comparada."""
    where = " ou ".join(columns) if columns else "identifier.<prefixo>"
    docdb = ("; em docdb, também se ignoram código do país, código de tipo e símbolos"
             if any(c.casefold().endswith(".espacenet") for c in columns) else "")
    md5 = ("; em orgunit, brcris:: é o MD5 de identifier.brcris em minúsculas"
           if target in HASHED_BRCRIS_TARGETS and any(c.casefold().endswith(".brcris") for c in columns) else "")
    description = (
        f"{side} da relação {relation_type} deve corresponder à coluna {where} de {target}, "
        f"conforme o prefixo do semanticIdentifier. O valor é normalizado antes da comparação "
        f"(remove-se 'prefixo::' e espaços{docdb}{md5}); os exemplos mostram o valor original; "
        f"{sample_scope}."
    )
    reason = (f"{side} da relação {relation_type} não corresponde à coluna {where} de {target} "
              f"indicada pelo prefixo (comparação após normalização).")
    return description, reason


def endpoint_columns(con, aliases: tuple[str, ...], side: str,
                     identifier_columns: dict[str, str]) -> list[str]:
    """Colunas identifier.* do alvo usadas pelos prefixos que existem no endpoint."""
    placeholders = ", ".join("?" for _ in aliases)
    side_sql = common.quote_ident(side)
    query = (
        f"SELECT DISTINCT lower(trim(split_part(CAST({side_sql} AS VARCHAR), '::', 1))) "
        f'FROM "relation" WHERE lower(trim(CAST("type" AS VARCHAR))) IN ({placeholders}) '
        f"AND position('::' IN CAST({side_sql} AS VARCHAR)) > 0"
    )
    prefixes = sorted(r[0] for r in con.execute(query, [a.casefold() for a in aliases]).fetchall() if r[0])
    columns = [identifier_column_for_prefix(identifier_columns, p) for p in prefixes]
    return sorted({c for c in columns if c})


def identifier_columns(con, target: str) -> dict[str, str]:
    return {
        column[len("identifier."):].casefold(): column
        for column in common.get_columns(con, target)
        if column.casefold().startswith("identifier.")
    }


def identifier_column_for_prefix(columns: dict[str, str], prefix: str) -> str | None:
    identifier_name = IDENTIFIER_PREFIX_ALIASES.get(prefix, prefix).casefold()
    return columns.get(identifier_name)


def check_schema(con, target: str, side: str) -> None:
    if not common.view_exists(con, target):
        raise ValueError(f"A view {target!r} necessária à validação de relation não existe.")
    if not common.view_exists(con, "relation"):
        raise ValueError("A view 'relation' não existe no DuckDB.")
    relation_columns = set(common.get_columns(con, "relation"))
    if side not in relation_columns:
        raise ValueError(
            f"A view relation não tem {side}. Reextraia as fontes de relações após atualizar extract.py."
        )
