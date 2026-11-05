"""Regras de qualidade da entidade Software com Great Expectations."""
from __future__ import annotations

from datetime import date

import pandas as pd
import great_expectations.expectations as gxe
from quality import authority, checks, common

ENTITY = "software"
MANDATORY_COLUMNS = ["ref", "title", "identifier.brcris", "identifier.inpi"]
URL_REGEX = common.URL_REGEX
CURRENT_YEAR = date.today().year


def _load_software(con, columns: list[str]) -> pd.DataFrame:
    wanted = ["ref", "source", "title", "identifier.brcris", "identifier.inpi", "releaseYear", "urlINPI", "registrationCountry", "language",
              "depositDate", "concessionDate", "kind"]
    wanted += [column for column in columns if column.startswith("identifier.")]
    selected = [column for column in dict.fromkeys(wanted) if column in columns]
    if not selected:
        raise ValueError(f"A view {ENTITY!r} não tem colunas esperadas.")
    projection = ", ".join(common.quote_ident(column) for column in selected)
    return con.execute(f"SELECT {projection} FROM {common.quote_ident(ENTITY)}").fetchdf()


_rule = common.make_rule
_broken_rule = common.make_broken_rule


def _non_null_rows(software: pd.DataFrame, column: str) -> pd.DataFrame:
    rows = common.base_rows(software, column)
    return rows[rows["value"].notna()].reset_index(drop=True)


def _valid_date(value) -> bool:
    parsed = checks.parse_date(value)
    return parsed is not None and date(1900, 1, 1) <= parsed <= date.today()


def _date_pairs(software: pd.DataFrame) -> pd.DataFrame:
    """Registros com as duas datas legíveis: value = 'depósito / concessão'."""
    frame = software[["ref", "source", "depositDate", "concessionDate"]].copy()
    dep = frame["depositDate"].map(common.normalize_text)
    con = frame["concessionDate"].map(common.normalize_text)
    keep = dep.map(lambda v: v is not None and checks.parse_date(v) is not None) & \
        con.map(lambda v: v is not None and checks.parse_date(v) is not None)
    out = frame.loc[keep, ["ref", "source"]].copy()
    out["record_value"] = dep[keep] + " / " + con[keep]
    out["value"] = out["record_value"]
    out = out.reset_index(drop=True)
    out.insert(0, "__dq_row_id", range(len(out)))
    return out


def _concession_not_before_deposit(pair: str) -> bool:
    deposit, _, concession = pair.partition(" / ")
    return checks.parse_date(concession) >= checks.parse_date(deposit)


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
            "urlINPI deve conter um endereço web válido (com ou sem http/https, ex.: www.site.com).",
            f"Coluna 'urlINPI' ausente na view {ENTITY!r}.",
        ))
    else:
        rules.append(_rule(
            "SFT-VAL-URLINPI", "validade", "formato", "urlINPI",
            "urlINPI deve conter um endereço web válido (com ou sem http/https, ex.: www.site.com).",
            "O valor não corresponde ao formato de endereço web (domínio com ponto, sem espaços).",
            gxe.ExpectColumnValuesToMatchRegex(column="value", regex=URL_REGEX),
            lambda: common.split_tokens(software, "urlINPI"),
        ))
    # datas de depósito e concessão: data válida, não futura
    for column in ("depositDate", "concessionDate"):
        if column in columns:
            rules.append(common.make_check_rule(
                f"SFT-VAL-{column.replace('Date', '').upper()}-DATE", "validade", "data", column,
                f"{column}, quando preenchida, deve ser uma data válida (dd/mm/aaaa, aaaa-mm-dd ou aaaa), entre 1900 e hoje.",
                f"{column} não é uma data válida entre 1900 e hoje.",
                lambda column=column: _non_null_rows(software, column),
                _valid_date,
            ))
    if {"depositDate", "concessionDate"}.issubset(columns):
        rules.append(common.make_check_rule(
            "SFT-VAL-CONCESSION-AFTER-DEPOSIT", "consistência", "ordem temporal", "concessionDate",
            "concessionDate não pode ser anterior a depositDate (avaliado quando ambas são datas válidas).",
            "concessionDate é anterior a depositDate.",
            lambda: _date_pairs(software),
            _concession_not_before_deposit,
        ))
    authority.add_authority_rule(
        rules, entity=ENTITY, frame=software, columns=columns, column="kind",
        authority_file="dominios.json", authority_fields=("software_kind",),
        rule_id="SFT-AUT-KIND",
        description="kind deve ser um dos valores aceitos: COMPUTACIONAL, MULTIMIDIA ou OUTRO.",
    )
    authority.add_authority_rule(
        rules, entity=ENTITY, frame=software, columns=columns, column="registrationCountry",
        authority_file="country_authority.json", authority_fields=("code", "name"),
        rule_id="SFT-AUT-REGISTRATION-COUNTRY",
        description="registrationCountry deve corresponder a um código ou nome de país aceito.",
    )
    authority.add_authority_rule(
        rules, entity=ENTITY, frame=software, columns=columns, column="language",
        authority_file="language2026.json",
        authority_fields=("sigla", "name_original", "name_pt", "name_en"),
        rule_id="SFT-AUT-LANGUAGE",
        description="language deve corresponder a um código ou nome de idioma aceito.",
    )

    return rules


def validate() -> tuple[list[dict], list[dict], dict]:
    """Executa as regras de Software e devolve (scores, errors, metadata)."""
    with common.connect() as con:
        columns = common.get_columns(con, ENTITY)
        softwares = _load_software(con, columns)
        rules = _build_rules(con, columns, softwares)
    return common.run_quality_checks(ENTITY, rules, extra_metadata={"record_count": len(softwares)})
