"""Regras de qualidade da entidade Person.

Padrão declarativo: cada regra é um common.Rule com uma Expectation do GX e os
 dados preparados para ela. SQL e Pandas só selecionam e normalizam; quem decide
 o que é erro é sempre a Expectation do Great Expectations.
"""
from __future__ import annotations

import pandas as pd
import great_expectations.expectations as gxe

from quality import common

ENTITY = "person"

# Obrigatoriedade: identifier.brcris não é obrigatório no modelo utilizado.
MANDATORY_COLUMNS = ["identifier.lattes", "name", "ref"]
REFERENTIAL_SIDES = [
    ("Affiliation", "toEntityRef"),
    ("Inventor", "toEntityRef"),
    ("Creator", "toEntityRef"),
    ("LeaderResearchGroup", "fromEntityRef"),
    ("MemberResearchGroup", "fromEntityRef"),
]

LATTES_REGEX = r"^[0-9]+$"
ORCID_REGEX = r"^[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9Xx]$"
# Verificação básica: texto sem espaços, um @ e um domínio com ponto.
EMAIL_REGEX = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


def _load_people(con, columns: list[str]) -> pd.DataFrame:
    """Carrega uma única vez somente as colunas usadas pelas regras de Person."""
    wanted = ["ref", "source", "name", "email", "identifier.email"] + [
        c for c in columns if c.startswith("identifier.")
    ]
    selected = [c for c in dict.fromkeys(wanted) if c in columns]
    if not selected:
        raise ValueError(f"A view {ENTITY!r} não tem nenhuma das colunas esperadas.")
    projection = ", ".join(common.quote_ident(c) for c in selected)
    return con.execute(f"SELECT {projection} FROM {common.quote_ident(ENTITY)}").fetchdf()


def _broken_rule(rule_id: str, validation: str, dimension: str, column: str,
                 description: str, problem: str) -> common.Rule:
    """Regra impossível de executar (schema incompatível): vira ERRO TÉCNICO explícito."""
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


def _build_rules(con, columns: list[str], people: pd.DataFrame) -> list[common.Rule]:
    rules = []
    identifier_columns = [c for c in columns if c.startswith("identifier.")]

    # 1. Unicidade de cada identificador; valores concatenados são avaliados item a item.
    for number, column in enumerate(identifier_columns, start=1):
        rules.append(_base_rule(
            f"PER-UNI-{number:02d}", "unicidade", "unicidade", column,
            f"Cada identificador de {column} deve ser único.",
            f"Identificador duplicado em {column}.",
            gxe.ExpectColumnValuesToBeUnique(column="value"),
            lambda column=column: common.split_tokens(people, column),
        ))

    # 2. Completude dos campos definidos como obrigatórios. identifier.brcris não é obrigatório.
    for column in MANDATORY_COLUMNS:
        rule_id = f"PER-COM-{column.replace('.', '-').upper()}"
        description = f"{column} deve estar preenchido."
        if column not in columns:
            rules.append(_broken_rule(rule_id, "completude", "completude", column, description,
                                      f"Coluna obrigatória {column!r} ausente na view {ENTITY!r}."))
            continue
        rules.append(_base_rule(
            rule_id, "completude", "completude", column, description,
            f"{column} está nulo ou vazio.",
            gxe.ExpectColumnValuesToNotBeNull(column="value"),
            lambda column=column: common.base_rows(people, column),
        ))

    # 3. Unicidade estrutural da chave ref (completude já está acima).
    if "ref" in columns:
        rules.append(_base_rule(
            "PER-UNI-REF", "unicidade", "unicidade", "ref",
            "Cada pessoa deve ter uma referência ref única.",
            "A referência ref está associada a mais de um registro.",
            gxe.ExpectColumnValuesToBeUnique(column="value"),
            lambda: common.base_rows(people, "ref").loc[
                common.base_rows(people, "ref")["value"].notna()
            ].reset_index(drop=True),
        ))
    else:
        rules.append(_broken_rule("PER-UNI-REF", "unicidade", "unicidade", "ref",
                                  "Cada pessoa deve ter uma referência ref única.",
                                  f"Coluna obrigatória 'ref' ausente na view {ENTITY!r}."))

    # 4. Formato textual dos identificadores.
    for column, regex, rule_id, description, reason in [
        ("identifier.lattes", LATTES_REGEX, "PER-VAL-01",
         "Cada identificador Lattes deve conter apenas números.",
         "Identificador Lattes contém caracteres que não são dígitos."),
        ("identifier.orcid", ORCID_REGEX, "PER-VAL-02",
         "ORCID deve seguir o formato XXXX-XXXX-XXXX-XXXX (apenas o formato textual).",
         "ORCID não segue o formato XXXX-XXXX-XXXX-XXXX."),
    ]:
        if column not in columns:
            rules.append(_broken_rule(rule_id, "validade", "validade", column, description,
                                      f"Coluna {column!r} ausente na view {ENTITY!r}."))
            continue
        rules.append(_base_rule(
            rule_id, "validade", "validade", column, description, reason,
            gxe.ExpectColumnValuesToMatchRegex(column="value", regex=regex),
            lambda column=column: common.split_tokens(people, column),
        ))

    # 5. Consistência de identificadores entre pessoas: deduplica apenas repetições
    #    do mesmo valor dentro da mesma ref; o GX detecta valores ligados a refs distintas.
    for number, column in enumerate(["identifier.lattes", "identifier.orcid"], start=1):
        rule_id = f"PER-CON-ID-{number:02d}"
        description = f"O mesmo {column} não deve estar associado a pessoas com refs diferentes."
        if column not in columns:
            rules.append(_broken_rule(rule_id, "consistência", "consistência", column, description,
                                      f"Coluna {column!r} ausente na view {ENTITY!r}."))
            continue
        rules.append(_base_rule(
            rule_id, "consistência", "consistência", column, description,
            f"O mesmo valor de {column} aparece associado a mais de uma ref.",
            gxe.ExpectColumnValuesToBeUnique(column="value"),
            lambda column=column: _tokens_distinct_people(people, column),
        ))

    # 6. Formato básico de e-mail. Aceita tanto email quanto identifier.email se existirem.
    email_columns = [c for c in ["email", "identifier.email"] if c in columns]
    for number, column in enumerate(email_columns, start=1):
        rules.append(_base_rule(
            f"PER-VAL-EMAIL-{number:02d}", "validade", "formato de e-mail", column,
            f"Cada endereço em {column} deve ter um formato básico de e-mail válido.",
            f"O valor de {column} não corresponde ao formato básico de e-mail.",
            gxe.ExpectColumnValuesToMatchRegex(column="value", regex=EMAIL_REGEX),
            lambda column=column: common.split_tokens(people, column),
        ))

    rules.extend(_referential_rules(con, columns, people))
    return rules


def _tokens_distinct_people(people: pd.DataFrame, column: str) -> pd.DataFrame:
    """Uma ocorrência por par ref/identificador; a Expectation detecta refs diferentes."""
    rows = common.split_tokens(people, column)
    if rows.empty:
        return rows
    rows["ref"] = rows["ref"].map(common.normalize_text)
    rows = rows[rows["ref"].notna()]
    rows = rows.drop_duplicates(subset=["ref", "value"], keep="first").reset_index(drop=True)
    rows["__dq_row_id"] = range(len(rows))
    return rows


def _referential_rules(con, columns: list[str], people: pd.DataFrame) -> list[common.Rule]:
    """O endpoint de Person em cada tipo de relação deve existir em person.ref."""
    def description_of(relation_type: str, side: str) -> str:
        return f"A relação {relation_type} deve apontar, em {side}, para uma pessoa existente em person.ref."

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
            _broken_rule(f"PER-CON-REF-{number:02d}", "consistência referencial", "consistência",
                         f"relation.{side}", description_of(relation_type, side), message)
            for number, (relation_type, side) in enumerate(REFERENTIAL_SIDES, start=1)
        ]

    person_refs = sorted(people["ref"].map(common.normalize_text).dropna().unique().tolist())
    selected = [c for c in ["type", "fromEntityRef", "toEntityRef", "info", "source"]
                if c in relation_columns]
    placeholders = ", ".join("?" for _ in REFERENTIAL_SIDES)
    relations = con.execute(
        f"SELECT {', '.join(common.quote_ident(c) for c in selected)} "
        f'FROM "relation" WHERE CAST("type" AS VARCHAR) IN ({placeholders})',
        [relation_type for relation_type, _ in REFERENTIAL_SIDES],
    ).fetchdf()

    rules = []
    for number, (relation_type, side) in enumerate(REFERENTIAL_SIDES, start=1):
        subset = relations[relations["type"] == relation_type]
        rules.append(_base_rule(
            f"PER-CON-REF-{number:02d}", "consistência", "consistência referencial",
            f"relation.{side}", description_of(relation_type, side),
            f"A referência de Person na relação {relation_type} não existe em person.ref.",
            gxe.ExpectColumnValuesToBeInSet(column="value", value_set=person_refs),
            lambda subset=subset, side=side: common.relation_rows(subset, side),
        ))
    return rules


def validate() -> tuple[list[dict], list[dict], dict]:
    """Executa todas as regras de Person e devolve (scores, errors, metadata)."""
    with common.connect() as con:
        columns = common.get_columns(con, ENTITY)
        people = _load_people(con, columns)
        rules = _build_rules(con, columns, people)
    return common.run_quality_checks(
        ENTITY, rules, extra_metadata={"record_count": len(people)},
    )
