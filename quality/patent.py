"""Regras de qualidade da entidade Patent usando Great Expectations."""
from __future__ import annotations

import pandas as pd
import great_expectations.expectations as gxe

from quality import common

ENTITY = "patent"
MANDATORY_COLUMNS = ["identifier.espacenet", "title", "inventor"]
DATE_REGEX = r"^(0[1-9]|[12][0-9]|3[01])/(0[1-9]|1[0-2])/([0-9]{4})$"
URL_REGEX = r"^https?://[^\s./]+(?:\.[^\s./]+)+(?:[/:?#][^\s]*)?$"
REFERENTIAL_TYPES = ["Inventor", "Applicant"]


def _load_patents(con, columns: list[str]) -> pd.DataFrame:
    wanted = [
        "ref", "source", "identifier.espacenet", "title", "inventor",
        "resourceUrl", "depositDate", "publicationDate",
    ] + [c for c in columns if c.startswith("identifier.")]
    selected = [c for c in dict.fromkeys(wanted) if c in columns]
    if not selected:
        raise ValueError(f"A view {ENTITY!r} não tem colunas esperadas.")
    projection = ", ".join(common.quote_ident(c) for c in selected)
    return con.execute(f"SELECT {projection} FROM {common.quote_ident(ENTITY)}").fetchdf()


def _broken_rule(rule_id: str, dimension: str, validation: str, column: str,
                 description: str, problem: str) -> common.Rule:
    def _raise():
        raise ValueError(problem)
    return common.Rule(
        id=rule_id, dimension=dimension, validation=validation, column=column,
        description=description, reason=problem, expectation=None, data=_raise,
    )


def _rule(rule_id: str, dimension: str, validation: str, column: str,
          description: str, reason: str, expectation, data) -> common.Rule:
    return common.Rule(
        id=rule_id, dimension=dimension, validation=validation, column=column,
        description=description, reason=reason, expectation=expectation, data=data,
    )


def _non_null_rows(patents: pd.DataFrame, column: str) -> pd.DataFrame:
    rows = common.base_rows(patents, column)
    return rows[rows["value"].notna()].reset_index(drop=True)


def _build_rules(con, columns: list[str], patents: pd.DataFrame) -> list[common.Rule]:
    rules: list[common.Rule] = []
    identifier_columns = [c for c in columns if c.startswith("identifier.")]

    for number, column in enumerate(identifier_columns, start=1):
        rules.append(_rule(
            f"PAT-UNI-ID-{number:02d}", "unicidade", "unicidade", column,
            f"Cada valor de {column} deve ser único entre as patentes.",
            f"Valor de {column} duplicado.",
            gxe.ExpectColumnValuesToBeUnique(column="value"),
            lambda column=column: common.split_tokens(patents, column),
        ))

    for column in MANDATORY_COLUMNS:
        rule_id = f"PAT-COM-{column.replace('.', '-').upper()}"
        description = f"{column} deve estar preenchido."
        if column not in columns:
            rules.append(_broken_rule(
                rule_id, "completude", "completude", column, description,
                f"Coluna obrigatória {column!r} ausente na view {ENTITY!r}.",
            ))
            continue
        rules.append(_rule(
            rule_id, "completude", "completude", column, description,
            f"{column} está nulo, vazio ou contém apenas espaços.",
            gxe.ExpectColumnValuesToNotBeNull(column="value"),
            lambda column=column: common.base_rows(patents, column),
        ))

    if "ref" in columns:
        rules.append(_rule(
            "PAT-UNI-REF", "unicidade", "unicidade", "ref",
            "Cada patente deve ter uma referência ref única.",
            "A referência ref está associada a mais de um registro.",
            gxe.ExpectColumnValuesToBeUnique(column="value"),
            lambda: _non_null_rows(patents, "ref"),
        ))
    else:
        rules.append(_broken_rule(
            "PAT-UNI-REF", "unicidade", "unicidade", "ref",
            "Cada patente deve ter uma referência ref única.",
            f"Coluna obrigatória 'ref' ausente na view {ENTITY!r}.",
        ))

    if "resourceUrl" in columns:
        rules.append(_rule(
            "PAT-VAL-RESOURCE-URL", "validade", "formato", "resourceUrl",
            "resourceUrl deve conter uma URL HTTP ou HTTPS.",
            "O valor de resourceUrl não corresponde ao formato básico de URL HTTP(S).",
            gxe.ExpectColumnValuesToMatchRegex(column="value", regex=URL_REGEX),
            lambda: _non_null_rows(patents, "resourceUrl"),
        ))
    else:
        rules.append(_broken_rule(
            "PAT-VAL-RESOURCE-URL", "validade", "formato", "resourceUrl",
            "resourceUrl deve conter uma URL HTTP ou HTTPS.",
            f"Coluna resourceUrl ausente na view {ENTITY!r}.",
        ))

    for column in ["depositDate", "publicationDate"]:
        rule_id = f"PAT-VAL-DATE-{column.replace('Date', '').upper()}"
        description = f"{column} deve estar no formato dd/mm/yyyy."
        if column not in columns:
            rules.append(_broken_rule(
                rule_id, "validade", "formato", column, description,
                f"Coluna obrigatória {column!r} ausente na view {ENTITY!r}.",
            ))
            continue
        rules.append(_rule(
            rule_id, "validade", "formato", column, description,
            f"{column} não corresponde ao formato dd/mm/yyyy.",
            gxe.ExpectColumnValuesToMatchRegex(column="value", regex=DATE_REGEX),
            lambda column=column: _non_null_rows(patents, column),
        ))

    if {"depositDate", "publicationDate"}.issubset(columns):
        def _date_pair_rows() -> pd.DataFrame:
            frame = patents[["ref", "source", "depositDate", "publicationDate"]].copy()
            frame["depositDate_dt"] = pd.to_datetime(
                frame["depositDate"], format="%d/%m/%Y", errors="coerce"
            )
            frame["publicationDate_dt"] = pd.to_datetime(
                frame["publicationDate"], format="%d/%m/%Y", errors="coerce"
            )
            frame["__dq_row_id"] = range(len(frame))
            frame["record_value"] = (
                frame["depositDate"].astype("string").fillna("")
                + " | " + frame["publicationDate"].astype("string").fillna("")
            )
            frame["value"] = frame["publicationDate_dt"]
            return frame[[
                "__dq_row_id", "ref", "source", "record_value", "value",
                "depositDate_dt", "publicationDate_dt",
            ]]

        rules.append(_rule(
            "PAT-VAL-PUBLICATION-AFTER-DEPOSIT", "consistência", "ordem temporal",
            "publicationDate", "publicationDate deve ser posterior a depositDate.",
            "publicationDate não é posterior a depositDate.",
            gxe.ExpectColumnPairValuesAToBeGreaterThanB(
                column_A="publicationDate_dt", column_B="depositDate_dt", or_equal=True,
            ),
            _date_pair_rows,
        ))
    else:
        rules.append(_broken_rule(
            "PAT-VAL-PUBLICATION-AFTER-DEPOSIT", "consistência", "ordem temporal",
            "publicationDate", "publicationDate deve ser posterior a depositDate.",
            "Não foi possível comparar as datas: depositDate e/ou publicationDate ausente.",
        ))

    rules.extend(_referential_rules(con, columns, patents))
    return rules


def _referential_rules(con, columns: list[str], patents: pd.DataFrame) -> list[common.Rule]:
    problem = None
    if "ref" not in columns:
        problem = f"a view {ENTITY!r} não tem a coluna ref"
    elif not common.view_exists(con, "relation"):
        problem = "a view relation não existe"
    else:
        relation_columns = common.get_columns(con, "relation")
        missing = {"type", "fromEntityRef", "toEntityRef"} - set(relation_columns)
        if missing:
            problem = f"a view relation não tem as colunas obrigatórias {sorted(missing)}"

    if problem:
        message = f"Validação referencial impossível: {problem}."
        return [
            _broken_rule(
                f"PAT-CON-REF-{number:02d}", "consistência", "consistência referencial",
                "relation.fromEntityRef",
                f"A relação {relation_type} deve ter fromEntityRef correspondente a patent.ref.",
                message,
            )
            for number, relation_type in enumerate(REFERENTIAL_TYPES, start=1)
        ]

    patent_refs = sorted(patents["ref"].map(common.normalize_text).dropna().unique().tolist())
    relation_columns = common.get_columns(con, "relation")
    selected = [c for c in ["type", "fromEntityRef", "toEntityRef", "info", "source"]
                if c in relation_columns]
    placeholders = ", ".join("?" for _ in REFERENTIAL_TYPES)
    relations = con.execute(
        f"SELECT {', '.join(common.quote_ident(c) for c in selected)} "
        f'FROM "relation" WHERE lower(CAST("type" AS VARCHAR)) IN ({placeholders})',
        [name.lower() for name in REFERENTIAL_TYPES],
    ).fetchdf()

    rules = []
    for number, relation_type in enumerate(REFERENTIAL_TYPES, start=1):
        subset = relations[
            relations["type"].astype(str).str.lower() == relation_type.lower()
        ].copy()
        rules.append(_rule(
            f"PAT-CON-REF-{number:02d}", "consistência", "consistência referencial",
            "relation.fromEntityRef",
            f"A relação {relation_type} deve ter fromEntityRef correspondente a patent.ref.",
            f"fromEntityRef da relação {relation_type} não existe em patent.ref.",
            gxe.ExpectColumnValuesToBeInSet(column="value", value_set=patent_refs),
            lambda subset=subset: common.relation_rows(subset, "fromEntityRef"),
        ))
    return rules


def validate() -> tuple[list[dict], list[dict], dict]:
    """Executa as regras de Patent e devolve (scores, errors, metadata)."""
    with common.connect() as con:
        columns = common.get_columns(con, ENTITY)
        patents = _load_patents(con, columns)
        rules = _build_rules(con, columns, patents)
    return common.run_quality_checks(
        ENTITY, rules, extra_metadata={"record_count": len(patents)}
    )
