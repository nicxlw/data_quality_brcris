"""Regras de qualidade da entidade Patent usando Great Expectations."""
from __future__ import annotations

import pandas as pd
import great_expectations.expectations as gxe

from quality import common

ENTITY = "patent"
MANDATORY_COLUMNS = ["identifier.espacenet", "title", "inventor"]
DATE_REGEX = r"^(0[1-9]|[12][0-9]|3[01])/(0[1-9]|1[0-2])/([0-9]{4})$"
URL_REGEX = common.URL_REGEX
KIND_CODE_REGEX = r"^[A-Z][0-9]?$"                 # A, B1, C1, U2...
COUNTRY_CODE_REGEX = r"^[A-Z]{2}$"                 # BR, US, WO...
IPC_SECTION_REGEX = r"^[A-H]$"                     # seções IPC: A a H

def _load_patents(con, columns: list[str]) -> pd.DataFrame:
    wanted = [
        "ref", "source", "identifier.espacenet", "title", "inventor",
        "resourceUrl", "depositDate", "publicationDate", "kindCode", "countryCode",
        "classification.ipc.section",
    ] + [c for c in columns if c.startswith("identifier.")]
    selected = [c for c in dict.fromkeys(wanted) if c in columns]
    if not selected:
        raise ValueError(f"A view {ENTITY!r} não tem colunas esperadas.")
    projection = ", ".join(common.quote_ident(c) for c in selected)
    return con.execute(f"SELECT {projection} FROM {common.quote_ident(ENTITY)}").fetchdf()


_rule = common.make_rule
_broken_rule = common.make_broken_rule


def _non_null_rows(patents: pd.DataFrame, column: str) -> pd.DataFrame:
    rows = common.base_rows(patents, column)
    return rows[rows["value"].notna()].reset_index(drop=True)


def _build_rules(con, columns: list[str], patents: pd.DataFrame) -> list[common.Rule]:
    rules: list[common.Rule] = []
    identifier_columns = [c for c in columns if c.startswith("identifier.")]

    # Singularidade (antes da unicidade): um único valor por identificador em cada registro.
    common.add_singularity_rules(rules, "PAT-SIN-ID", patents, identifier_columns)

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
            "resourceUrl deve conter um endereço web válido (com ou sem http/https, ex.: www.site.com).",
            "O valor de resourceUrl não corresponde ao formato de endereço web (domínio com ponto, sem espaços).",
            gxe.ExpectColumnValuesToMatchRegex(column="value", regex=URL_REGEX),
            lambda: common.split_tokens(patents, "resourceUrl"),
        ))
    else:
        rules.append(_broken_rule(
            "PAT-VAL-RESOURCE-URL", "validade", "formato", "resourceUrl",
            "resourceUrl deve conter um endereço web válido (com ou sem http/https, ex.: www.site.com).",
            f"Coluna resourceUrl ausente na view {ENTITY!r}.",
        ))

    # formato de códigos e classificação IPC (só quando a coluna existe)
    for column, regex, rule_id, text, reason in [
        ("kindCode", KIND_CODE_REGEX, "PAT-VAL-KINDCODE",
         "kindCode deve ser uma letra, opcionalmente seguida de um dígito (ex.: A, B1, C1).",
         "kindCode não tem o formato letra + dígito opcional."),
        ("countryCode", COUNTRY_CODE_REGEX, "PAT-VAL-COUNTRYCODE",
         "countryCode deve ter 2 letras maiúsculas (ex.: BR, US, WO).",
         "countryCode não tem 2 letras maiúsculas."),
        ("classification.ipc.section", IPC_SECTION_REGEX, "PAT-VAL-IPC-SECTION",
         "Cada seção IPC deve ser uma letra de A a H.",
         "A seção IPC não é uma letra de A a H."),
    ]:
        if column not in columns:
            continue
        rules.append(_rule(
            rule_id, "validade", "formato", column, text, reason,
            gxe.ExpectColumnValuesToMatchRegex(column="value", regex=regex),
            lambda column=column: common.split_tokens(patents, column),
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
