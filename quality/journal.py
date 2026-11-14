"""Regras de qualidade da entidade Journal.

Padrão declarativo: cada regra é um common.Rule com uma Expectation do GX.
Pandas/SQL apenas selecionam e preparam os dados; a decisão sobre o que é erro
fica com o Great Expectations.
"""
from __future__ import annotations

import pandas as pd
import re
import great_expectations.expectations as gxe

from quality import authority, checks, common

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
# URL: ver common.URL_REGEX (aceita www., linktree e outros endereços sem http).
URL_REGEX = common.URL_REGEX
BOOLEAN_VALUES = {"true", "false"}
CURRENCY_REGEX = r"^[A-Z]{3}$"   # código de moeda ISO 4217 (3 letras maiúsculas)


def _load_journals(con, columns: list[str]) -> pd.DataFrame:
    """Carrega apenas as colunas necessárias às validações de Journal."""
    wanted = [
        "ref", "source", "title", "identifier.openalex", "identifier.issn",
        "identifier.issn_l", "identifier.brcris", "websiteURL", "isOa",
        "isInDoaj", "type", "countryCode", "apcCost.apcCurrency", "h_index", "i10_index", "qualis",
    ] + [c for c in columns if c.startswith("identifier.")]
    selected = [c for c in dict.fromkeys(wanted) if c in columns]
    if not selected:
        raise ValueError(f"A view {ENTITY!r} não tem nenhuma das colunas esperadas.")
    projection = ", ".join(common.quote_ident(c) for c in selected)
    return con.execute(
        f"SELECT {projection} FROM {common.quote_ident(ENTITY)}"
    ).fetchdf()


_broken_rule = common.make_broken_rule
_base_rule = common.make_rule


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


def _build_rules(con, columns: list[str], journals: pd.DataFrame) -> list[common.Rule]:
    rules: list[common.Rule] = []
    identifier_columns = [c for c in columns if c.startswith("identifier.")]

    # Singularidade (antes da unicidade): um único valor por identificador em cada registro.
    common.add_singularity_rules(rules, "JOU-SIN-ID", journals, identifier_columns)

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
        description = f"{column} deve seguir o formato XXXX-XXXX (vários ISSN separados por '|' são aceitos; cada um é avaliado)."
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

    # 4b. Dígito verificador do ISSN (só nos valores que já têm o formato XXXX-XXXX).
    for column, rule_id in [("identifier.issn", "JOU-VAL-ISSN-DV"), ("identifier.issn_l", "JOU-VAL-ISSN-L-DV")]:
        if column not in columns:
            continue
        rules.append(common.make_check_rule(
            rule_id, "validade", "dígito verificador", column,
            f"O dígito verificador de {column} deve ser válido (avaliado nos valores com formato XXXX-XXXX).",
            f"O dígito verificador de {column} não confere.",
            lambda column=column: _issn_format_ok(journals, column),
            checks.issn,
        ))

    # 5. websiteURL deve ser um endereço web válido; valores ausentes são ignorados aqui.
    if "websiteURL" in columns:
        rules.append(_base_rule(
            "JOU-VAL-WEBSITE-URL", "validade", "formato de URL", "websiteURL",
            "websiteURL, quando preenchido, deve conter um endereço web válido (com ou sem http/https, ex.: www.site.com).",
            "O valor de websiteURL não corresponde ao formato de endereço web (domínio com ponto, sem espaços).",
            gxe.ExpectColumnValuesToMatchRegex(column="value", regex=URL_REGEX),
            lambda: common.split_tokens(journals, "websiteURL"),
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
    authority.add_authority_rule(
        rules, entity=ENTITY, frame=journals, columns=columns, column="identifier.issn",
        authority_file="journals2026.json", authority_fields=("code",),
        rule_id="JOU-AUT-ISSN",
        description="identifier.issn deve corresponder a um ISSN da lista de periódicos de autoridade.",
        tokenized=True,
        transform=lambda value: re.sub(r"^issn::", "", str(value), flags=re.I),
    )
    authority.add_authority_rule(
        rules, entity=ENTITY, frame=journals, columns=columns, column="countryCode",
        authority_file="country_authority.json", authority_fields=("code", "name"),
        rule_id="JOU-AUT-COUNTRY",
        description="countryCode deve corresponder a um código ou nome de país aceito.",
    )
    authority.add_authority_rule(
        rules, entity=ENTITY, frame=journals, columns=columns, column="qualis",
        authority_file="dominios.json", authority_fields=("qualis",),
        rule_id="JOU-AUT-QUALIS",
        description="qualis deve ser um dos conceitos A1-A4, B1-B4 ou C.",
    )
    authority.add_authority_rule(
        rules, entity=ENTITY, frame=journals, columns=columns, column="title",
        authority_file="journals2026.json", authority_fields=("name",),
        rule_id="JOU-AUT-TITLE",
        description="title deve corresponder a um nome da lista de periódicos de autoridade.",
    )

    # 8. Moeda do APC (código de 3 letras) e índices numéricos não negativos.
    if "apcCost.apcCurrency" in columns:
        rules.append(_base_rule(
            "JOU-VAL-APC-CURRENCY", "validade", "formato", "apcCost.apcCurrency",
            "apcCost.apcCurrency, quando preenchido, deve ser um código de moeda de 3 letras maiúsculas (ex.: USD); com vários valores separados por '|', cada um é avaliado.",
            "O valor de apcCost.apcCurrency não é um código de moeda de 3 letras maiúsculas.",
            gxe.ExpectColumnValuesToMatchRegex(column="value", regex=CURRENCY_REGEX),
            lambda: common.split_tokens(journals, "apcCost.apcCurrency"),
        ))
    for column, rule_id in [("h_index", "JOU-VAL-H-INDEX"), ("i10_index", "JOU-VAL-I10-INDEX")]:
        if column not in columns:
            continue
        rules.append(common.make_check_rule(
            rule_id, "validade", "limite", column,
            f"{column}, quando preenchido, deve ser um número maior ou igual a zero.",
            f"O valor de {column} não é um número maior ou igual a zero.",
            lambda column=column: _non_null_base_rows(journals, column),
            _non_negative_number,
        ))

    return rules


def _issn_format_ok(journals: pd.DataFrame, column: str) -> pd.DataFrame:
    """ISSN já no formato XXXX-XXXX; só eles passam pela checagem do dígito verificador."""
    rows = common.split_tokens(journals, column)
    return rows.loc[rows["value"].str.fullmatch(ISSN_REGEX, na=False)].reset_index(drop=True)


def _non_negative_number(value) -> bool:
    try:
        return float(str(value).replace(",", ".")) >= 0
    except ValueError:
        return False


def validate() -> tuple[list[dict], list[dict], dict]:
    """Executa as regras de Journal e devolve (scores, errors, metadata)."""
    with common.connect() as con:
        columns = common.get_columns(con, ENTITY)
        journals = _load_journals(con, columns)
        rules = _build_rules(con, columns, journals)
    return common.run_quality_checks(
        ENTITY, rules, extra_metadata={"record_count": len(journals)},
    )
