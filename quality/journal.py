"""Regras de qualidade da entidade Journal.

Padrão declarativo: cada regra é um common.Rule com uma Expectation do GX.
Pandas/SQL apenas selecionam e preparam os dados; a decisão sobre o que é erro
fica com o Great Expectations. Esta entidade não possui validações relacionais,
pois a view relation não está disponível para Journal neste momento.
"""
from __future__ import annotations

import pandas as pd
import great_expectations.expectations as gxe

from quality import common

ENTITY = "journal"

MANDATORY_COLUMNS = [
    "ref",
    "title",
    "identifier.openalex",
    "identifier.issn",
    "identifier.brcris",
]

# ISSN tem sete dígitos e um dígito de controle, que também pode ser X.
ISSN_REGEX = r"^[0-9]{4}-[0-9]{3}[0-9Xx]$"
# URL HTTP(S) com domínio e caminho/query/fragmento opcionais.
URL_REGEX = r"^https?://[^\s./]+(?:\.[^\s./]+)+(?:[/:?#][^\s]*)?$"
BOOLEAN_VALUES = {"true", "false"}


def _load_journals(con, columns: list[str]) -> pd.DataFrame:
    """Carrega apenas as colunas necessárias às validações de Journal."""
    wanted = [
        "ref", "source", "title", "identifier.openalex", "identifier.issn",
        "identifier.issn_l", "identifier.brcris", "websiteURL", "isOa",
        "isInDoaj", "type",
    ] + [c for c in columns if c.startswith("identifier.")]
    selected = [c for c in dict.fromkeys(wanted) if c in columns]
    if not selected:
        raise ValueError(f"A view {ENTITY!r} não tem nenhuma das colunas esperadas.")
    projection = ", ".join(common.quote_ident(c) for c in selected)
    return con.execute(
        f"SELECT {projection} FROM {common.quote_ident(ENTITY)}"
    ).fetchdf()


def _broken_rule(rule_id: str, validation: str, dimension: str, column: str,
                 description: str, problem: str) -> common.Rule:
    """Representa incompatibilidades de schema como erros técnicos explícitos."""
    def _raise():
        raise ValueError(problem)
    return common.Rule(
        id=rule_id, dimension=dimension, validation=validation, column=column,
        description=description, reason=problem, expectation=None, data=_raise,
    )


def _base_rule(rule_id: str, dimension: str, validation: str, column: str,
               description: str, reason: str, expectation, data) -> common.Rule:
    return common.Rule(
        id=rule_id, dimension=dimension, validation=validation, column=column,
        description=description, reason=reason, expectation=expectation, data=data,
    )


def _non_null_base_rows(journals: pd.DataFrame, column: str) -> pd.DataFrame:
    """Prepara valores preenchidos, sem classificar ausências como erros de formato."""
    rows = common.base_rows(journals, column)
    return rows[rows["value"].notna()].reset_index(drop=True)


def _boolean_rows(journals: pd.DataFrame, column: str) -> pd.DataFrame:
    """Normaliza booleanos e strings true/false para comparação pelo GX."""
    rows = common.base_rows(journals, column)
    rows["value"] = rows["value"].map(
        lambda value: value.lower() if isinstance(value, str) else value
    )
    return rows


def _build_rules(columns: list[str], journals: pd.DataFrame) -> list[common.Rule]:
    rules: list[common.Rule] = []
    identifier_columns = [c for c in columns if c.startswith("identifier.")]

    # 1. Unicidade de cada coluna identifier.*; valores separados por '|' são avaliados individualmente.
    for number, column in enumerate(identifier_columns, start=1):
        rules.append(_base_rule(
            f"JOU-UNI-ID-{number:02d}", "unicidade", "unicidade", column,
            f"Cada valor de {column} deve ser único entre os periódicos.",
            f"Valor de {column} duplicado.",
            gxe.ExpectColumnValuesToBeUnique(column="value"),
            lambda column=column: common.split_tokens(journals, column),
        ))

    # 2. Completude dos campos obrigatórios.
    for column in MANDATORY_COLUMNS:
        rule_id = f"JOU-COM-{column.replace('.', '-').upper()}"
        description = f"{column} deve estar preenchido."
        if column not in columns:
            rules.append(_broken_rule(
                rule_id, "completude", "completude", column, description,
                f"Coluna obrigatória {column!r} ausente na view {ENTITY!r}.",
            ))
            continue
        rules.append(_base_rule(
            rule_id, "completude", "completude", column, description,
            f"{column} está nulo, vazio ou contém apenas espaços.",
            gxe.ExpectColumnValuesToNotBeNull(column="value"),
            lambda column=column: common.base_rows(journals, column),
        ))

    # 3. Unicidade da referência ref.
    if "ref" in columns:
        rules.append(_base_rule(
            "JOU-UNI-REF", "unicidade", "unicidade", "ref",
            "Cada periódico deve ter uma referência ref única.",
            "A referência ref está associada a mais de um registro.",
            gxe.ExpectColumnValuesToBeUnique(column="value"),
            lambda: _non_null_base_rows(journals, "ref"),
        ))
    else:
        rules.append(_broken_rule(
            "JOU-UNI-REF", "unicidade", "unicidade", "ref",
            "Cada periódico deve ter uma referência ref única.",
            f"Coluna obrigatória 'ref' ausente na view {ENTITY!r}.",
        ))

    # 4. Formato ISSN e ISSN-L. O ISSN pode terminar em X como dígito de controle.
    for column, rule_id in [
        ("identifier.issn", "JOU-VAL-ISSN"),
        ("identifier.issn_l", "JOU-VAL-ISSN-L"),
    ]:
        description = f"{column} deve seguir o formato XXXX-XXXX."
        if column not in columns:
            rules.append(_broken_rule(
                rule_id, "validade", "validade", column, description,
                f"Coluna {column!r} ausente na view {ENTITY!r}.",
            ))
            continue
        rules.append(_base_rule(
            rule_id, "validade", "formato", column, description,
            f"O valor de {column} não segue o formato XXXX-XXXX.",
            gxe.ExpectColumnValuesToMatchRegex(column="value", regex=ISSN_REGEX),
            lambda column=column: common.split_tokens(journals, column),
        ))

    # 5. websiteURL deve ser uma URL HTTP(S); valores ausentes são ignorados aqui.
    if "websiteURL" in columns:
        rules.append(_base_rule(
            "JOU-VAL-WEBSITE-URL", "validade", "formato de URL", "websiteURL",
            "websiteURL, quando preenchido, deve conter uma URL HTTP(S).",
            "O valor de websiteURL não corresponde ao formato básico de URL HTTP(S).",
            gxe.ExpectColumnValuesToMatchRegex(column="value", regex=URL_REGEX),
            lambda: _non_null_base_rows(journals, "websiteURL"),
        ))

    # 6. isOa e isInDoaj devem ser true ou false (aceita booleanos e strings em qualquer caixa).
    for column, rule_id in [
        ("isOa", "JOU-VAL-ISOA"),
        ("isInDoaj", "JOU-VAL-IS-IN-DOAJ"),
    ]:
        description = f"{column} deve ter o valor true ou false."
        if column not in columns:
            rules.append(_broken_rule(
                rule_id, "validade", "domínio de valores", column, description,
                f"Coluna {column!r} ausente na view {ENTITY!r}.",
            ))
            continue
        rules.append(_base_rule(
            rule_id, "validade", "domínio de valores", column, description,
            f"O valor de {column} não é true nem false (ou está ausente).",
            gxe.ExpectColumnValuesToBeInSet(column="value", value_set=BOOLEAN_VALUES),
            lambda column=column: _boolean_rows(journals, column),
        ))

    # 7. Todos os registros devem ter type exatamente igual a 'journal'.
    if "type" not in columns:
        rules.append(_broken_rule(
            "JOU-VAL-TYPE", "validade", "domínio de valores", "type",
            "type deve ser igual a 'journal'.",
            f"Coluna 'type' ausente na view {ENTITY!r}.",
        ))
    else:
        rules.append(_base_rule(
            "JOU-VAL-TYPE", "validade", "domínio de valores", "type",
            "type deve ser igual a 'journal'.",
            "O valor de type é diferente de 'journal' ou está ausente.",
            gxe.ExpectColumnValuesToBeInSet(column="value", value_set={"journal"}),
            lambda: common.base_rows(journals, "type"),
        ))

    return rules


def validate() -> tuple[list[dict], list[dict], dict]:
    """Executa as regras de Journal e devolve (scores, errors, metadata)."""
    with common.connect() as con:
        columns = common.get_columns(con, ENTITY)
        journals = _load_journals(con, columns)
        rules = _build_rules(columns, journals)
    return common.run_quality_checks(
        ENTITY, rules, extra_metadata={"record_count": len(journals)},
    )
