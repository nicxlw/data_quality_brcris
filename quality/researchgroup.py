"""Regras de qualidade da entidade ResearchGroup com Great Expectations."""
from __future__ import annotations

from datetime import date

import pandas as pd
import great_expectations.expectations as gxe
from quality import common

ENTITY = "researchgroup"
MANDATORY_COLUMNS = ["ref", "name", "identifier.brcris", "identifier.dgp"]
URL_REGEX = common.URL_REGEX
CURRENT_YEAR = date.today().year


def _load_researchgroups(con, columns: list[str]) -> pd.DataFrame:
    wanted = ["ref", "source", "name", "identifier.brcris", "identifier.dgp", "creationYear", "URL"]
    wanted += [column for column in columns if column.startswith("identifier.")]
    selected = [column for column in dict.fromkeys(wanted) if column in columns]
    if not selected:
        raise ValueError(f"A view {ENTITY!r} não tem colunas esperadas.")
    projection = ", ".join(common.quote_ident(column) for column in selected)
    return con.execute(f"SELECT {projection} FROM {common.quote_ident(ENTITY)}").fetchdf()


_rule = common.make_rule
_broken_rule = common.make_broken_rule


def _non_null_rows(researchgroups: pd.DataFrame, column: str) -> pd.DataFrame:
    rows = common.base_rows(researchgroups, column)
    return rows[rows["value"].notna()].reset_index(drop=True)


def _build_rules(con, columns: list[str], researchgroups: pd.DataFrame) -> list[common.Rule]:
    rules: list[common.Rule] = []

    # Unicidade de todos os identificadores, incluindo identificadores multivalorados.
    identifier_columns = [column for column in columns if column.startswith("identifier.")]
    for number, column in enumerate(identifier_columns, start=1):
        rules.append(_rule(
            f"RGR-UNI-ID-{number:02d}", "unicidade", "unicidade", column,
            f"Cada valor de {column} deve ser único entre os grupos de pesquisa.",
            f"Valor de {column} duplicado.",
            gxe.ExpectColumnValuesToBeUnique(column="value"),
            lambda column=column: common.split_tokens(researchgroups, column),
        ))

    # Completude dos campos definidos como obrigatórios.
    for column in MANDATORY_COLUMNS:
        rule_id = f"RGR-COM-{column.replace('.', '-').upper()}"
        description = f"{column} deve estar preenchido."
        if column not in columns:
            rules.append(_broken_rule(
                rule_id, "completude", "completude", column, description,
                f"Coluna obrigatória {column!r} ausente na view {ENTITY!r}.",
            ))
        else:
            rules.append(_rule(
                rule_id, "completude", "completude", column, description,
                f"{column} está nulo, vazio ou contém apenas espaços.",
                gxe.ExpectColumnValuesToNotBeNull(column="value"),
                lambda column=column: common.base_rows(researchgroups, column),
            ))

    # A referência principal também deve ser única.
    if "ref" in columns:
        rules.append(_rule(
            "RGR-UNI-REF", "unicidade", "unicidade", "ref",
            "Cada grupo de pesquisa deve ter uma referência ref única.",
            "A referência ref está associada a mais de um registro.",
            gxe.ExpectColumnValuesToBeUnique(column="value"),
            lambda: _non_null_rows(researchgroups, "ref"),
        ))
    else:
        rules.append(_broken_rule(
            "RGR-UNI-REF", "unicidade", "unicidade", "ref",
            "Cada grupo de pesquisa deve ter uma referência ref única.",
            f"Coluna obrigatória 'ref' ausente na view {ENTITY!r}.",
        ))

    # creationYear precisa ser numérico para que a comparação de ano seja válida;
    # valores não numéricos são preparados como falha para a Expectation de limite.
    if "creationYear" not in columns:
        rules.append(_broken_rule(
            "RGR-VAL-CREATIONYEAR", "validade", "limite", "creationYear",
            f"creationYear deve ser menor ou igual a {CURRENT_YEAR}.",
            f"Coluna 'creationYear' ausente na view {ENTITY!r}.",
        ))
    else:
        def _creationyear_rows() -> pd.DataFrame:
            rows = common.base_rows(researchgroups, "creationYear")
            raw = rows["value"].copy()
            numeric = pd.to_numeric(raw, errors="coerce")
            invalid_non_null = raw.notna() & numeric.isna()
            numeric.loc[invalid_non_null] = CURRENT_YEAR + 1
            rows["value"] = numeric
            return rows

        rules.append(_rule(
            "RGR-VAL-CREATIONYEAR", "validade", "limite", "creationYear",
            f"creationYear deve ser menor ou igual ao ano atual ({CURRENT_YEAR}).",
            f"O ano de criação é posterior a {CURRENT_YEAR} ou não representa um ano numérico.",
            gxe.ExpectColumnValuesToBeBetween(column="value", max_value=CURRENT_YEAR),
            _creationyear_rows,
        ))

    # URL é validada quando preenchida; não foi definida como campo obrigatório.
    if "URL" not in columns:
        rules.append(_broken_rule(
            "RGR-VAL-URL", "validade", "formato", "URL",
            "URL deve conter um endereço web válido (com ou sem http/https, ex.: www.site.com).",
            f"Coluna 'URL' ausente na view {ENTITY!r}.",
        ))
    else:
        rules.append(_rule(
            "RGR-VAL-URL", "validade", "formato", "URL",
            "URL deve conter um endereço web válido (com ou sem http/https, ex.: www.site.com).",
            "O valor não corresponde ao formato de endereço web (domínio com ponto, sem espaços).",
            gxe.ExpectColumnValuesToMatchRegex(column="value", regex=URL_REGEX),
            lambda: common.split_tokens(researchgroups, "URL"),
        ))
    return rules


def validate() -> tuple[list[dict], list[dict], dict]:
    """Executa as regras de ResearchGroup e devolve (scores, errors, metadata)."""
    with common.connect() as con:
        columns = common.get_columns(con, ENTITY)
        researchgroups = _load_researchgroups(con, columns)
        rules = _build_rules(con, columns, researchgroups)
    return common.run_quality_checks(ENTITY, rules, extra_metadata={"record_count": len(researchgroups)})
