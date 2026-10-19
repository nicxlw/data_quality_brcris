"""Regras de qualidade da entidade OrgUnit.

Padrão declarativo: cada regra é um common.Rule com uma Expectation do GX.
Pandas/SQL apenas preparam os dados (por exemplo, dividindo identificadores
multivalorados); a decisão sobre o que é erro fica com o Great Expectations.
"""
from __future__ import annotations

import pandas as pd
import great_expectations.expectations as gxe

from quality import common

ENTITY = "orgunit"

MANDATORY_COLUMNS = ["identifier.brcris", "name", "ref"]
EMAIL_REGEX = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
BRCRIS_REGEX = r"^BRCRIS-[0-9]{8}$"
ISNI_REGEX = r"^[0-9]{4} [0-9]{4} [0-9]{4} [0-9]{4}$"
CNPJ_REGEX = r"^[0-9]{14}$"
PHONE_REGEX = r"^\([0-9]{2}\) (?:[0-9]{4}|9[0-9]{4})-[0-9]{4}$"
# Aceita URL com esquema HTTP(S), domínio e, opcionalmente, caminho/query/fragmento.
URL_REGEX = r"^https?://[^\s./]+(?:\.[^\s./]+)+(?:[/:?#][^\s]*)?$"

# Endpoint que representa OrgUnit em cada tipo de relação.
# IsProgramOf foi incluída conforme solicitado; o lado fromEntityRef é a
# interpretação adotada para a referência de OrgUnit nesta validação.
REFERENTIAL_SIDES = [
    ("Affiliation", "fromEntityRef"),
    ("IsProgramOf", "fromEntityRef"),
    ("OrgUnitProgram", "fromEntityRef"),
    ("Applicant", "toEntityRef"),
    ("PartnerResearchGroupOrgUnit", "fromEntityRef"),
]


def _load_orgunits(con, columns: list[str]) -> pd.DataFrame:
    """Carrega somente as colunas necessárias às regras de OrgUnit."""
    wanted = [
        "ref", "source", "name", "country", "identifier.brcris", "identifier.isni",
        "identifier.cnpj", "electronicAddress", "websiteUrl", "phone",
    ] + [c for c in columns if c.startswith("identifier.")]
    selected = [c for c in dict.fromkeys(wanted) if c in columns]
    if not selected:
        raise ValueError(f"A view {ENTITY!r} não tem nenhuma das colunas esperadas.")
    projection = ", ".join(common.quote_ident(c) for c in selected)
    return con.execute(f"SELECT {projection} FROM {common.quote_ident(ENTITY)}").fetchdf()


def _broken_rule(rule_id: str, validation: str, dimension: str, column: str,
                 description: str, problem: str) -> common.Rule:
    """Transforma incompatibilidade de schema em erro técnico explícito."""
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


def _build_rules(con, columns: list[str], orgunits: pd.DataFrame) -> list[common.Rule]:
    rules: list[common.Rule] = []
    identifier_columns = [c for c in columns if c.startswith("identifier.")]

    # 1. Unicidade de todos os identificadores; valores com '|' são avaliados item a item.
    for number, column in enumerate(identifier_columns, start=1):
        rules.append(_base_rule(
            f"ORG-UNI-ID-{number:02d}", "unicidade", "unicidade", column,
            f"Cada valor de {column} deve ser único entre as organizações.",
            f"Valor de {column} duplicado.",
            gxe.ExpectColumnValuesToBeUnique(column="value"),
            lambda column=column: common.split_tokens(orgunits, column),
        ))

    # 2. Completude dos campos obrigatórios, incluindo ref.
    for column in MANDATORY_COLUMNS:
        rule_id = f"ORG-COM-{column.replace('.', '-').upper()}"
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
            lambda column=column: common.base_rows(orgunits, column),
        ))

    # 3. Unicidade de ref.
    if "ref" in columns:
        rules.append(_base_rule(
            "ORG-UNI-REF", "unicidade", "unicidade", "ref",
            "Cada organização deve ter uma referência ref única.",
            "A referência ref está associada a mais de um registro.",
            gxe.ExpectColumnValuesToBeUnique(column="value"),
            lambda: _non_null_base_rows(orgunits, "ref"),
        ))
    else:
        rules.append(_broken_rule(
            "ORG-UNI-REF", "unicidade", "unicidade", "ref",
            "Cada organização deve ter uma referência ref única.",
            f"Coluna obrigatória 'ref' ausente na view {ENTITY!r}.",
        ))

    # 4. Nome único. A regra compara o valor textual após remover espaços externos.
    if "name" in columns:
        rules.append(_base_rule(
            "ORG-UNI-NAME", "unicidade", "unicidade", "name",
            "Cada organização deve ter um nome único.",
            "O nome está associado a mais de um registro de OrgUnit.",
            gxe.ExpectColumnValuesToBeUnique(column="value"),
            lambda: _non_null_base_rows(orgunits, "name"),
        ))

    # 5. Formatos dos identificadores e campos de contato, somente se presentes.
    format_rules = [
        ("identifier.brcris", BRCRIS_REGEX, "ORG-VAL-BRCRIS",
         "identifier.brcris deve seguir o formato BRCRIS- seguido de oito dígitos.",
         "O identificador BRCRIS não segue o formato BRCRIS-xxxxxxxx com oito dígitos."),
        ("identifier.isni", ISNI_REGEX, "ORG-VAL-ISNI",
         "identifier.isni deve seguir o formato XXXX XXXX XXXX XXXX.",
         "O ISNI não segue o formato textual de quatro grupos de quatro dígitos."),
        ("identifier.cnpj", CNPJ_REGEX, "ORG-VAL-CNPJ",
         "identifier.cnpj deve conter exatamente 14 dígitos numéricos.",
         "O CNPJ não contém exatamente 14 dígitos numéricos."),
        ("electronicAddress", EMAIL_REGEX, "ORG-VAL-EMAIL",
         "electronicAddress deve seguir o formato básico de e-mail usado em Person.",
         "O endereço eletrônico não corresponde ao formato básico de e-mail."),
        ("websiteUrl", URL_REGEX, "ORG-VAL-URL",
         "websiteUrl deve conter uma URL HTTP ou HTTPS válida em formato básico.",
         "O valor de websiteUrl não corresponde ao formato básico de URL HTTP(S)."),
        ("phone", PHONE_REGEX, "ORG-VAL-PHONE",
         "Para country = 'Brasil', phone deve seguir o formato (xx) xxxx-xxxx ou (xx) 9xxxx-xxxx.",
         "O telefone de uma organização no Brasil não segue o formato (xx) xxxx-xxxx ou (xx) 9xxxx-xxxx."),
    ]
    for column, regex, rule_id, description, reason in format_rules:
        if column not in columns:
            # Campos opcionais: não gerar erro técnico quando não existirem no esquema.
            continue
        if column == "phone" and "country" not in columns:
            rules.append(_broken_rule(
                rule_id, "validade", "formato", column, description,
                "A validação de phone exige a coluna country para aplicá-la apenas ao Brasil.",
            ))
            continue
        expectation = gxe.ExpectColumnValuesToMatchRegex(column="value", regex=regex)
        if column == "phone":
            expectation = gxe.ExpectColumnValuesToMatchRegex(
                column="value", regex=regex,
                row_condition="country == 'Brasil'", condition_parser="pandas",
            )
        rules.append(_base_rule(
            rule_id, "validade", "formato", column, description, reason,
            expectation,
            lambda column=column: _split_phone_tokens(orgunits)
            if column == "phone" else common.split_tokens(orgunits, column)
            if column.startswith("identifier.") or column == "electronicAddress"
            else _non_null_base_rows(orgunits, column),
        ))

    rules.extend(_referential_rules(con, columns, orgunits))
    return rules


def _split_phone_tokens(orgunits: pd.DataFrame) -> pd.DataFrame:
    """Divide telefones multivalorados preservando country para row_condition."""
    rows = []
    for ref, source, country, original in zip(
        orgunits["ref"] if "ref" in orgunits.columns else [None] * len(orgunits),
        orgunits["source"] if "source" in orgunits.columns else [None] * len(orgunits),
        orgunits["country"],
        orgunits["phone"],
    ):
        if common.normalize_text(original) is None:
            continue
        for token in str(original).split("|"):
            token = token.strip()
            if token:
                rows.append({
                    "__dq_row_id": len(rows), "ref": ref, "source": source,
                    "country": country, "record_value": original, "value": token,
                })
    return pd.DataFrame(
        rows, columns=["__dq_row_id", "ref", "source", "country", "record_value", "value"],
    )


def _non_null_base_rows(orgunits: pd.DataFrame, column: str) -> pd.DataFrame:
    """Prepara valores preenchidos para unicidade, sem contar ausências como duplicadas."""
    rows = common.base_rows(orgunits, column)
    return rows[rows["value"].notna()].reset_index(drop=True)


def _referential_rules(con, columns: list[str], orgunits: pd.DataFrame) -> list[common.Rule]:
    """Verifica se o endpoint configurado de cada relação existe em orgunit.ref."""
    def description_of(relation_type: str, side: str) -> str:
        return (f"A relação {relation_type} deve apontar, em {side}, "
                "para uma organização existente em orgunit.ref.")

    problem = None
    relation_columns: list[str] = []
    if "ref" not in columns:
        problem = f"a view {ENTITY!r} não tem a coluna ref"
    elif not common.view_exists(con, "relation"):
        problem = "a view relation não existe (extraia as relações antes desta validação)"
    else:
        relation_columns = common.get_columns(con, "relation")
        missing = {"type", "fromEntityRef", "toEntityRef"} - set(relation_columns)
        if missing:
            problem = f"a view relation não tem as colunas obrigatórias {sorted(missing)}"

    if problem:
        message = f"Validação referencial impossível: {problem}."
        return [
            _broken_rule(
                f"ORG-CON-REF-{number:02d}", "consistência referencial", "consistência",
                f"relation.{side}", description_of(relation_type, side), message,
            )
            for number, (relation_type, side) in enumerate(REFERENTIAL_SIDES, start=1)
        ]

    orgunit_refs = sorted(orgunits["ref"].map(common.normalize_text).dropna().unique().tolist())
    selected = [c for c in ["type", "fromEntityRef", "toEntityRef", "info", "source"]
                if c in relation_columns]
    relations = con.execute(
        f"SELECT {', '.join(common.quote_ident(c) for c in selected)} "
        f'FROM "relation" WHERE lower(CAST("type" AS VARCHAR)) IN ({", ".join("?" for _ in REFERENTIAL_SIDES)})',
        [relation_type.lower() for relation_type, _ in REFERENTIAL_SIDES],
    ).fetchdf()

    rules = []
    for number, (relation_type, side) in enumerate(REFERENTIAL_SIDES, start=1):
        subset = relations[relations["type"].astype(str).str.lower() == relation_type.lower()].copy()
        rules.append(_base_rule(
            f"ORG-CON-REF-{number:02d}", "consistência", "consistência referencial",
            f"relation.{side}", description_of(relation_type, side),
            f"A referência de OrgUnit na relação {relation_type} não existe em orgunit.ref.",
            gxe.ExpectColumnValuesToBeInSet(column="value", value_set=orgunit_refs),
            lambda subset=subset, side=side: common.relation_rows(subset, side),
        ))
    return rules


def validate() -> tuple[list[dict], list[dict], dict]:
    """Executa as regras de OrgUnit e devolve (scores, errors, metadata)."""
    with common.connect() as con:
        columns = common.get_columns(con, ENTITY)
        orgunits = _load_orgunits(con, columns)
        rules = _build_rules(con, columns, orgunits)
    return common.run_quality_checks(
        ENTITY, rules, extra_metadata={"record_count": len(orgunits)},
    )
