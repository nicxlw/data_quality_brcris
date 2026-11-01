"""Regras de qualidade da entidade Program com Great Expectations."""
from __future__ import annotations

import pandas as pd
import great_expectations.expectations as gxe
from quality import common

ENTITY = "program"
MANDATORY_COLUMNS = ["ref", "name", "identifier.brcris", "identifier.capes"]
PHONE_REGEX = r"^\([0-9]{2}\) (?:[0-9]{8}|9[0-9]{8})$"
EMAIL_REGEX = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
URL_REGEX = r"^https?://[^\s./]+(?:\.[^\s./]+)+(?:[/:?#][^\s]*)?$"
def _load_programs(con, columns: list[str]) -> pd.DataFrame:
    wanted = ["ref", "source", "name", "identifier.brcris", "identifier.capes", "phone", "email", "websiteUrl", "websiteurl"]
    wanted += [c for c in columns if c.startswith("identifier.")]
    selected = [c for c in dict.fromkeys(wanted) if c in columns]
    if not selected:
        raise ValueError(f"A view {ENTITY!r} não tem colunas esperadas.")
    projection = ", ".join(common.quote_ident(c) for c in selected)
    return con.execute(f"SELECT {projection} FROM {common.quote_ident(ENTITY)}").fetchdf()


def _rule(rule_id: str, dimension: str, validation: str, column: str, description: str, reason: str, expectation, data) -> common.Rule:
    return common.Rule(id=rule_id, dimension=dimension, validation=validation, column=column, description=description, reason=reason, expectation=expectation, data=data)


def _broken_rule(rule_id: str, dimension: str, validation: str, column: str, description: str, problem: str) -> common.Rule:
    def _raise():
        raise ValueError(problem)
    return common.Rule(id=rule_id, dimension=dimension, validation=validation, column=column, description=description, reason=problem, expectation=None, data=_raise)


def _non_null_rows(programs: pd.DataFrame, column: str) -> pd.DataFrame:
    rows = common.base_rows(programs, column)
    return rows[rows["value"].notna()].reset_index(drop=True)


def _build_rules(con, columns: list[str], programs: pd.DataFrame) -> list[common.Rule]:
    rules: list[common.Rule] = []
    identifier_columns = [c for c in columns if c.startswith("identifier.")]
    for number, column in enumerate(identifier_columns, start=1):
        rules.append(_rule(
            f"PRO-UNI-ID-{number:02d}", "unicidade", "unicidade", column,
            f"Cada valor de {column} deve ser único entre os programas.", f"Valor de {column} duplicado.",
            gxe.ExpectColumnValuesToBeUnique(column="value"), lambda column=column: common.split_tokens(programs, column)))

    # identifier.brcris foi listado duas vezes; é avaliado uma única vez.
    for column in MANDATORY_COLUMNS:
        rule_id = f"PRO-COM-{column.replace('.', '-').upper()}"
        description = f"{column} deve estar preenchido."
        if column not in columns:
            rules.append(_broken_rule(rule_id, "completude", "completude", column, description,
                                      f"Coluna obrigatória {column!r} ausente na view {ENTITY!r}."))
        else:
            rules.append(_rule(rule_id, "completude", "completude", column, description,
                f"{column} está nulo, vazio ou contém apenas espaços.",
                gxe.ExpectColumnValuesToNotBeNull(column="value"), lambda column=column: common.base_rows(programs, column)))

    if "ref" in columns:
        rules.append(_rule("PRO-UNI-REF", "unicidade", "unicidade", "ref",
            "Cada programa deve ter uma referência ref única.", "A referência ref está associada a mais de um registro.",
            gxe.ExpectColumnValuesToBeUnique(column="value"), lambda: _non_null_rows(programs, "ref")))
    else:
        rules.append(_broken_rule("PRO-UNI-REF", "unicidade", "unicidade", "ref",
            "Cada programa deve ter uma referência ref única.", f"Coluna obrigatória 'ref' ausente na view {ENTITY!r}."))

    for column, rule_id, regex, description, reason in [
        ("phone", "PRO-VAL-PHONE", PHONE_REGEX, "phone deve seguir o formato (xx) xxxxxxxx ou (xx) 9xxxxxxxx.", "O telefone não corresponde a nenhum dos formatos aceitos."),
        ("email", "PRO-VAL-EMAIL", EMAIL_REGEX, "email deve seguir um formato básico de endereço de e-mail.", "O valor de email não corresponde ao formato básico de e-mail."),
    ]:
        if column not in columns:
            rules.append(_broken_rule(rule_id, "validade", "formato", column, description, f"Coluna {column!r} ausente na view {ENTITY!r}."))
        else:
            rules.append(_rule(rule_id, "validade", "formato", column, description, reason,
                gxe.ExpectColumnValuesToMatchRegex(column="value", regex=regex), lambda column=column: _non_null_rows(programs, column)))

    website_column = next((c for c in ["websiteurl", "websiteUrl"] if c in columns), None)
    if website_column is None:
        rules.append(_broken_rule("PRO-VAL-WEBSITE-URL", "validade", "formato", "websiteurl",
            "websiteurl deve conter uma URL HTTP ou HTTPS.", "Coluna 'websiteurl'/'websiteUrl' ausente na view program."))
    else:
        rules.append(_rule("PRO-VAL-WEBSITE-URL", "validade", "formato", website_column,
            f"{website_column} deve conter uma URL HTTP ou HTTPS.", "O valor não corresponde ao formato básico de URL HTTP(S).",
            gxe.ExpectColumnValuesToMatchRegex(column="value", regex=URL_REGEX), lambda: _non_null_rows(programs, website_column)))
    return rules



def validate() -> tuple[list[dict], list[dict], dict]:
    """Executa as regras de Program e devolve (scores, errors, metadata)."""
    with common.connect() as con:
        columns = common.get_columns(con, ENTITY)
        programs = _load_programs(con, columns)
        rules = _build_rules(con, columns, programs)
    return common.run_quality_checks(ENTITY, rules, extra_metadata={"record_count": len(programs)})
