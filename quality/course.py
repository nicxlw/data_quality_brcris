"""Regras de qualidade da entidade Course com Great Expectations."""
from __future__ import annotations

from datetime import date

import pandas as pd
import great_expectations.expectations as gxe

from quality import authority, common

ENTITY = "course"
MANDATORY_COLUMNS = ["ref", "name", "identifier.brcris", "identifier.capes"]
YEAR_REGEX = r"^[0-9]{4}$"
CURRENT_YEAR = date.today().year


def _load_courses(con, columns: list[str]) -> pd.DataFrame:
    wanted = ["ref", "source", *MANDATORY_COLUMNS, "startDate", "endDate", "degree", "type"]
    wanted += [column for column in columns if column.startswith("identifier.")]
    selected = [column for column in dict.fromkeys(wanted) if column in columns]
    if not selected:
        raise ValueError(f"A view {ENTITY!r} não tem colunas esperadas.")
    projection = ", ".join(common.quote_ident(column) for column in selected)
    return con.execute(
        f"SELECT {projection} FROM {common.quote_ident(ENTITY)}"
    ).fetchdf()


_rule = common.make_rule
_broken_rule = common.make_broken_rule


def _non_null_rows(courses: pd.DataFrame, column: str) -> pd.DataFrame:
    rows = common.base_rows(courses, column)
    return rows[rows["value"].notna()].reset_index(drop=True)


def _valid_year_rows(courses: pd.DataFrame, column: str) -> pd.DataFrame:
    rows = _non_null_rows(courses, column)
    valid = rows["value"].str.fullmatch(YEAR_REGEX, na=False)
    rows = rows.loc[valid].copy().reset_index(drop=True)
    rows["value"] = rows["value"].astype(int)
    return rows


def _date_pair_rows(courses: pd.DataFrame) -> pd.DataFrame:
    frame = courses[["ref", "source", "startDate", "endDate"]].copy()
    start = frame["startDate"].map(common.normalize_text)
    end = frame["endDate"].map(common.normalize_text)
    valid_pair = (
        start.str.fullmatch(YEAR_REGEX, na=False)
        & end.str.fullmatch(YEAR_REGEX, na=False)
    )
    frame = frame.loc[valid_pair].copy()
    start = start.loc[valid_pair]
    end = end.loc[valid_pair]
    frame["start_year"] = start.astype(int)
    frame["end_year"] = end.astype(int)
    frame["record_value"] = (
        start.astype("string") + " / " + end.astype("string")
    )
    frame["value"] = frame["record_value"]
    frame["__dq_row_id"] = range(len(frame))
    return frame[[
        "__dq_row_id", "ref", "source", "record_value", "value",
        "start_year", "end_year",
    ]]


def _build_rules(columns: list[str], courses: pd.DataFrame) -> list[common.Rule]:
    rules: list[common.Rule] = []
    identifier_columns = [
        column for column in columns if column.startswith("identifier.")
    ]

    # Singularidade (antes da unicidade): um único valor por identificador em cada registro.
    common.add_singularity_rules(rules, "CRS-SIN-ID", courses, identifier_columns)

    for number, column in enumerate(identifier_columns, start=1):
        rules.append(_rule(
            f"CRS-UNI-ID-{number:02d}", "unicidade", "unicidade", column,
            f"Cada valor de {column} deve ser único entre os cursos.",
            f"Valor de {column} duplicado.",
            gxe.ExpectColumnValuesToBeUnique(column="value"),
            lambda column=column: common.split_tokens(courses, column),
        ))

    for column in MANDATORY_COLUMNS:
        rule_id = f"CRS-COM-{column.replace('.', '-').upper()}"
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
            lambda column=column: common.base_rows(courses, column),
        ))

    if "ref" in columns:
        rules.append(_rule(
            "CRS-UNI-REF", "unicidade", "unicidade", "ref",
            "Cada curso deve ter uma referência ref única.",
            "A referência ref está associada a mais de um registro.",
            gxe.ExpectColumnValuesToBeUnique(column="value"),
            lambda: _non_null_rows(courses, "ref"),
        ))
    else:
        rules.append(_broken_rule(
            "CRS-UNI-REF", "unicidade", "unicidade", "ref",
            "Cada curso deve ter uma referência ref única.",
            f"Coluna obrigatória 'ref' ausente na view {ENTITY!r}.",
        ))

    authority.add_authority_rule(
        rules, entity=ENTITY, frame=courses, columns=columns, column="degree",
        authority_file="dominios.json", authority_fields=("course_degree",),
        rule_id="CRS-AUT-DEGREE",
        description="degree deve ser um grau aceito (graduation, specialization, master, doctoral, posDoctoral, fullProfessor ou equivalente em português).",
    )
    authority.add_authority_rule(
        rules, entity=ENTITY, frame=courses, columns=columns, column="type",
        authority_file="dominios.json", authority_fields=("course_type",),
        rule_id="CRS-AUT-TYPE",
        description="type deve ser Academic/Professional (ou Acadêmico/Profissional).",
    )

    for column in ["startDate", "endDate"]:
        rule_id = f"CRS-VAL-YEAR-{column.upper()}"
        description = f"{column} deve conter somente o ano no formato YYYY quando preenchido."
        if column not in columns:
            rules.append(_broken_rule(
                rule_id, "validade", "formato de ano", column, description,
                f"Coluna {column!r} ausente na view {ENTITY!r}.",
            ))
            continue
        rules.append(_rule(
            rule_id, "validade", "formato de ano", column, description,
            f"{column} não corresponde ao formato YYYY.",
            gxe.ExpectColumnValuesToMatchRegex(column="value", regex=YEAR_REGEX),
            lambda column=column: _non_null_rows(courses, column),
        ))

    if "startDate" in columns:
        rules.append(_rule(
            "CRS-VAL-START-YEAR-CURRENT", "validade", "limite", "startDate",
            f"startDate deve ser menor ou igual ao ano atual ({CURRENT_YEAR}).",
            "startDate é posterior ao ano atual.",
            gxe.ExpectColumnValuesToBeBetween(
                column="value", max_value=CURRENT_YEAR,
            ),
            lambda: _valid_year_rows(courses, "startDate"),
        ))
    else:
        rules.append(_broken_rule(
            "CRS-VAL-START-YEAR-CURRENT", "validade", "limite", "startDate",
            f"startDate deve ser menor ou igual ao ano atual ({CURRENT_YEAR}).",
            f"Coluna 'startDate' ausente na view {ENTITY!r}.",
        ))

    if {"startDate", "endDate"}.issubset(columns):
        rules.append(_rule(
            "CRS-CON-END-AFTER-START", "consistência", "ordem temporal", "endDate",
            "endDate deve ser maior ou igual a startDate quando ambas estiverem preenchidas.",
            "endDate é anterior a startDate.",
            gxe.ExpectColumnPairValuesAToBeGreaterThanB(
                column_A="end_year", column_B="start_year", or_equal=True,
            ),
            lambda: _date_pair_rows(courses),
        ))
    else:
        rules.append(_broken_rule(
            "CRS-CON-END-AFTER-START", "consistência", "ordem temporal", "endDate",
            "endDate deve ser maior ou igual a startDate quando ambas estiverem preenchidas.",
            "Não foi possível comparar as datas: startDate e/ou endDate ausente.",
        ))

    return rules


def validate() -> tuple[list[dict], list[dict], dict]:
    """Executa as regras de Course e retorna (scores, errors, metadata)."""
    with common.connect() as con:
        columns = common.get_columns(con, ENTITY)
        courses = _load_courses(con, columns)
        rules = _build_rules(columns, courses)
    return common.run_quality_checks(
        ENTITY, rules, extra_metadata={"record_count": len(courses)},
    )
