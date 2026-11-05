"""Regras de qualidade da entidade Program com Great Expectations."""
from __future__ import annotations

import pandas as pd
import great_expectations.expectations as gxe
from quality import common

ENTITY = "program"
MANDATORY_COLUMNS = ["ref", "name", "identifier.brcris", "identifier.capes"]
PHONE_REGEX = common.PHONE_REGEX      # (xx) xxxx-xxxx ou (xx) 9xxxx-xxxx; hífen opcional
EMAIL_REGEX = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
URL_REGEX = common.URL_REGEX
AREA_COLUMNS = ["researchArea.capes", "researchArea.cnpq", "evaluationArea"]
def _load_programs(con, columns: list[str]) -> pd.DataFrame:
    wanted = ["ref", "source", "name", "identifier.brcris", "identifier.capes", "phone", "email", "websiteUrl", "websiteurl",
              *AREA_COLUMNS]
    wanted += [c for c in columns if c.startswith("identifier.")]
    selected = [c for c in dict.fromkeys(wanted) if c in columns]
    if not selected:
        raise ValueError(f"A view {ENTITY!r} não tem colunas esperadas.")
    projection = ", ".join(common.quote_ident(c) for c in selected)
    return con.execute(f"SELECT {projection} FROM {common.quote_ident(ENTITY)}").fetchdf()


_rule = common.make_rule
_broken_rule = common.make_broken_rule


def _non_null_rows(programs: pd.DataFrame, column: str) -> pd.DataFrame:
    rows = common.base_rows(programs, column)
    return rows[rows["value"].notna()].reset_index(drop=True)


def _not_all_caps(value) -> bool:
    """Falso se algum nível (entre '/') tem mais de 3 letras e todas maiúsculas (siglas curtas passam)."""
    for level in str(value).split("/"):
        letters = [ch for ch in level if ch.isalpha()]
        if len(letters) > 3 and all(ch.isupper() for ch in letters):
            return False
    return True


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
        ("phone", "PRO-VAL-PHONE", PHONE_REGEX, "phone deve seguir o formato (xx) xxxx-xxxx ou (xx) 9xxxx-xxxx (o hífen é opcional).", "O telefone não corresponde a nenhum dos formatos aceitos."),
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
            "websiteurl deve conter um endereço web válido (com ou sem http/https, ex.: www.site.com).", "Coluna 'websiteurl'/'websiteUrl' ausente na view program."))
    else:
        rules.append(_rule("PRO-VAL-WEBSITE-URL", "validade", "formato", website_column,
            f"{website_column} deve conter um endereço web válido (com ou sem http/https, ex.: www.site.com).", "O valor não corresponde ao formato de endereço web (domínio com ponto, sem espaços).",
            gxe.ExpectColumnValuesToMatchRegex(column="value", regex=URL_REGEX), lambda: common.split_tokens(programs, website_column)))

    # Áreas: o modelo pede capitalização correta (não tudo em maiúsculas), em cada nível da árvore.
    for column in AREA_COLUMNS:
        if column in columns:
            rules.append(common.make_check_rule(
                f"PRO-VAL-CAPS-{column.replace('.', '-').upper()}", "validade", "capitalização", column,
                f"{column} deve estar com capitalização correta: nenhum nível da árvore (separado por '/') pode estar todo em maiúsculas.",
                "Algum nível da área está todo em letras maiúsculas.",
                lambda column=column: _non_null_rows(programs, column),
                _not_all_caps,
            ))
    return rules


def validate() -> tuple[list[dict], list[dict], dict]:
    """Executa as regras de Program e devolve (scores, errors, metadata)."""
    with common.connect() as con:
        columns = common.get_columns(con, ENTITY)
        programs = _load_programs(con, columns)
        rules = _build_rules(con, columns, programs)
    return common.run_quality_checks(ENTITY, rules, extra_metadata={"record_count": len(programs)})
