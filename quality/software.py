"""Regras de qualidade da entidade Software com Great Expectations."""
from __future__ import annotations

from datetime import date

import pandas as pd
import great_expectations.expectations as gxe
from quality import common

ENTITY = "software"
MANDATORY_COLUMNS = ["ref", "title", "identifier.brcris", "identifier.inpi"]
URL_REGEX = r"^https?://[^\s./]+(?:\.[^\s./]+)+(?:[/:?#][^\s]*)?$"
RELATION_TYPES = ["creator"]
CURRENT_YEAR = date.today().year


def _load_software(con, columns: list[str]) -> pd.DataFrame:
    wanted = ["ref", "source", "title", "identifier.brcris", "identifier.inpi", "releaseYear", "urlINPI"]
    wanted += [column for column in columns if column.startswith("identifier.")]
    selected = [column for column in dict.fromkeys(wanted) if column in columns]
    if not selected:
        raise ValueError(f"A view {ENTITY!r} não tem colunas esperadas.")
    projection = ", ".join(common.quote_ident(column) for column in selected)
    return con.execute(f"SELECT {projection} FROM {common.quote_ident(ENTITY)}").fetchdf()


def _rule(rule_id: str, dimension: str, validation: str, column: str,
          description: str, reason: str, expectation, data) -> common.Rule:
    return common.Rule(
        id=rule_id,
        dimension=dimension,
        validation=validation,
        column=column,
        description=description,
        reason=reason,
        expectation=expectation,
        data=data,
    )


def _broken_rule(rule_id: str, dimension: str, validation: str, column: str,
                 description: str, problem: str) -> common.Rule:
    def _raise():
        raise ValueError(problem)

    return common.Rule(
        id=rule_id,
        dimension=dimension,
        validation=validation,
        column=column,
        description=description,
        reason=problem,
        expectation=None,
        data=_raise,
    )


def _non_null_rows(software: pd.DataFrame, column: str) -> pd.DataFrame:
    rows = common.base_rows(software, column)
    return rows[rows["value"].notna()].reset_index(drop=True)


def _build_rules(con, columns: list[str], software: pd.DataFrame) -> list[common.Rule]:
    rules: list[common.Rule] = []

    # Unicidade de todos os identificadores, incluindo identificadores multivalorados.
    identifier_columns = [column for column in columns if column.startswith("identifier.")]
    for number, column in enumerate(identifier_columns, start=1):
        rules.append(_rule(
            f"SFT-UNI-ID-{number:02d}", "unicidade", "unicidade", column,
            f"Cada valor de {column} deve ser único entre os softwares.",
            f"Valor de {column} duplicado.",
            gxe.ExpectColumnValuesToBeUnique(column="value"),
            lambda column=column: common.split_tokens(software, column),
        ))

    # Completude dos campos definidos como obrigatórios.
    for column in MANDATORY_COLUMNS:
        rule_id = f"SFT-COM-{column.replace('.', '-').upper()}"
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
                lambda column=column: common.base_rows(software, column),
            ))

    # A referência principal também deve ser única.
    if "ref" in columns:
        rules.append(_rule(
            "SFT-UNI-REF", "unicidade", "unicidade", "ref",
            "Cada software deve ter uma referência ref única.",
            "A referência ref está associada a mais de um registro.",
            gxe.ExpectColumnValuesToBeUnique(column="value"),
            lambda: _non_null_rows(software, "ref"),
        ))
    else:
        rules.append(_broken_rule(
            "SFT-UNI-REF", "unicidade", "unicidade", "ref",
            "Cada software deve ter uma referência ref única.",
            f"Coluna obrigatória 'ref' ausente na view {ENTITY!r}.",
        ))

    # releaseYear precisa ser numérico para que a comparação de ano seja válida;
    # valores não numéricos são preparados como falha para a Expectation de limite.
    if "releaseYear" not in columns:
        rules.append(_broken_rule(
            "SFT-VAL-RELEASEYEAR", "validade", "limite", "releaseYear",
            f"releaseYear deve ser menor ou igual a {CURRENT_YEAR}.",
            f"Coluna 'releaseYear' ausente na view {ENTITY!r}.",
        ))
    else:
        def _releaseyear_rows() -> pd.DataFrame:
            rows = common.split_tokens(software, "releaseYear")
            raw = rows["value"].copy()
            numeric = pd.to_numeric(raw, errors="coerce")
            invalid_non_null = raw.notna() & numeric.isna()
            numeric.loc[invalid_non_null] = CURRENT_YEAR + 1
            rows["value"] = numeric
            return rows

        rules.append(_rule(
            "SFT-VAL-RELEASEYEAR", "validade", "limite", "releaseYear",
            f"releaseYear deve ser menor ou igual ao ano atual ({CURRENT_YEAR}).",
            f"O ano de lançamento é posterior a {CURRENT_YEAR} ou não representa um ano numérico.",
            gxe.ExpectColumnValuesToBeBetween(column="value", max_value=CURRENT_YEAR),
            _releaseyear_rows,
        ))

    # urlINPI é validada quando preenchida; não foi definida como campo obrigatório.
    if "urlINPI" not in columns:
        rules.append(_broken_rule(
            "SFT-VAL-URLINPI", "validade", "formato", "urlINPI",
            "urlINPI deve conter uma URL HTTP ou HTTPS válida em formato básico.",
            f"Coluna 'urlINPI' ausente na view {ENTITY!r}.",
        ))
    else:
        rules.append(_rule(
            "SFT-VAL-URLINPI", "validade", "formato", "urlINPI",
            "urlINPI deve conter uma URL HTTP ou HTTPS válida em formato básico.",
            "O valor não corresponde ao formato básico de URL HTTP(S).",
            gxe.ExpectColumnValuesToMatchRegex(column="value", regex=URL_REGEX),
            lambda: _non_null_rows(software, "urlINPI"),
        ))

    rules.extend(_referential_rules(con, columns, software))
    return rules


def _referential_rules(con, columns: list[str], software: pd.DataFrame) -> list[common.Rule]:
    problem = None
    if "ref" not in columns:
        problem = f"a view {ENTITY!r} não tem a coluna ref"
    elif not common.view_exists(con, "relation"):
        problem = "a view relation não existe (extraia as relações antes desta validação)"
    else:
        relation_columns = common.get_columns(con, "relation")
        missing = {"type", "fromEntityRef"} - set(relation_columns)
        if missing:
            problem = f"a view relation não tem as colunas obrigatórias {sorted(missing)}"

    if problem:
        message = f"Validação referencial impossível: {problem}."
        return [
            _broken_rule(
                f"SFT-CON-REF-{number:02d}", "consistência", "consistência referencial",
                f"relation.fromEntityRef",
                f"A relação {relation_type} deve apontar, em fromEntityRef, para um software.ref existente.",
                message,
            )
            for number, relation_type in enumerate(RELATION_TYPES, start=1)
        ]

    software_refs = sorted(
        software["ref"].map(common.normalize_text).dropna().unique().tolist()
    )
    relation_columns = common.get_columns(con, "relation")
    selected = [column for column in ["type", "fromEntityRef", "info", "source"]
                if column in relation_columns]
    placeholders = ", ".join("?" for _ in RELATION_TYPES)
    relations = con.execute(
        f"SELECT {', '.join(common.quote_ident(column) for column in selected)} "
        f"FROM \"relation\" WHERE lower(CAST(\"type\" AS VARCHAR)) IN ({placeholders})",
        [relation_type.lower() for relation_type in RELATION_TYPES],
    ).fetchdf()

    rules: list[common.Rule] = []
    for number, relation_type in enumerate(RELATION_TYPES, start=1):
        subset = relations[relations["type"].astype(str).str.lower() == relation_type.lower()].copy()
        rules.append(_rule(
            f"SFT-CON-REF-{number:02d}", "consistência", "consistência referencial",
            f"relation.{relation_type}.fromEntityRef",
            f"A relação {relation_type} deve ter fromEntityRef correspondente a software.ref.",
            f"fromEntityRef da relação {relation_type} não existe em software.ref.",
            gxe.ExpectColumnValuesToBeInSet(column="value", value_set=software_refs),
            lambda subset=subset: common.relation_rows(subset, "fromEntityRef"),
        ))
    return rules


def validate() -> tuple[list[dict], list[dict], dict]:
    """Executa as regras de Software e devolve (scores, errors, metadata)."""
    with common.connect() as con:
        columns = common.get_columns(con, ENTITY)
        softwares = _load_software(con, columns)
        rules = _build_rules(con, columns, softwares)
    return common.run_quality_checks(ENTITY, rules, extra_metadata={"record_count": len(softwares)})
