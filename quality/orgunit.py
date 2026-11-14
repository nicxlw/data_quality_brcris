"""Regras de qualidade da entidade OrgUnit.

Padrão declarativo: cada regra é um common.Rule com uma Expectation do GX.
Pandas/SQL apenas preparam os dados (por exemplo, dividindo identificadores
multivalorados); a decisão sobre o que é erro fica com o Great Expectations.
"""
from __future__ import annotations

import pandas as pd
import great_expectations.expectations as gxe

from quality import authority, checks, common

ENTITY = "orgunit"

MANDATORY_COLUMNS = ["identifier.brcris", "name", "ref"]
EMAIL_REGEX = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
BRCRIS_REGEX = r"^BRCRIS-[0-9]{8}$"
# O último caractere do ISNI pode ser X (dígito de controle de valor 10).
ISNI_REGEX = r"^[0-9]{4} [0-9]{4} [0-9]{4} [0-9]{3}[0-9Xx]$"
CNPJ_REGEX = r"^[0-9]{14}$"
ROR_REGEX = r"(?i)^0[a-hj-km-np-tv-z0-9]{6}[0-9]{2}$"
GRID_REGEX = r"(?i)^grid\.[0-9]+\.[0-9a-f]{1,2}$"
WIKIDATA_REGEX = r"^Q[0-9]+$"
CEP_REGEX = r"^[0-9]{5}-?[0-9]{3}$"
# Telefone e CEP só são avaliados para organizações do Brasil.
BRAZIL_ONLY_COLUMNS = ("phone", "cep")
PHONE_REGEX = common.PHONE_REGEX
# URL: ver common.URL_REGEX (aceita www., linktree e outros endereços sem http).
URL_REGEX = common.URL_REGEX

# Endpoint que representa OrgUnit em cada tipo de relação.
# IsProgramOf foi incluída conforme solicitado; o lado fromEntityRef é a
# interpretação adotada para a referência de OrgUnit nesta validação.
def _load_orgunits(con, columns: list[str]) -> pd.DataFrame:
    """Carrega somente as colunas necessárias às regras de OrgUnit."""
    wanted = [
        "ref", "source", "name", "country", "identifier.brcris", "identifier.isni",
        "identifier.cnpj", "electronicAddress", "websiteUrl", "phone", "state", "city",
        "cep", "latitude", "longitude",
    ] + [c for c in columns if c.startswith("identifier.")]
    selected = [c for c in dict.fromkeys(wanted) if c in columns]
    if not selected:
        raise ValueError(f"A view {ENTITY!r} não tem nenhuma das colunas esperadas.")
    projection = ", ".join(common.quote_ident(c) for c in selected)
    return con.execute(f"SELECT {projection} FROM {common.quote_ident(ENTITY)}").fetchdf()


_broken_rule = common.make_broken_rule
_base_rule = common.make_rule


def _build_rules(con, columns: list[str], orgunits: pd.DataFrame) -> list[common.Rule]:
    rules: list[common.Rule] = []
    identifier_columns = [c for c in columns if c.startswith("identifier.")]

    # Singularidade (antes da unicidade): um único valor por identificador em cada registro.
    common.add_singularity_rules(rules, "ORG-SIN-ID", orgunits, identifier_columns)

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
         "identifier.isni deve seguir o formato XXXX XXXX XXXX XXXX (o último caractere pode ser X).",
         "O ISNI não segue o formato de quatro grupos de quatro caracteres (o último pode ser X)."),
        ("identifier.ror", ROR_REGEX, "ORG-VAL-ROR",
         "identifier.ror deve ter 9 caracteres: 0, seis letras/números e dois dígitos (ex.: 04cwrbc27).",
         "O ROR não segue o formato de 9 caracteres iniciado por 0."),
        ("identifier.grid", GRID_REGEX, "ORG-VAL-GRID",
         "identifier.grid deve seguir o formato grid.NNNNNN.x.",
         "O GRID não segue o formato grid.NNNNNN.x."),
        ("identifier.wikidata", WIKIDATA_REGEX, "ORG-VAL-WIKIDATA",
         "identifier.wikidata deve seguir o formato Q seguido de números.",
         "O identificador Wikidata não segue o formato Q + números."),
        ("cep", CEP_REGEX, "ORG-VAL-CEP",
         "Para country = 'Brasil', cep deve ter 8 dígitos (xxxxx-xxx ou xxxxxxxx).",
         "O CEP de uma organização no Brasil não tem 8 dígitos."),
        ("identifier.cnpj", CNPJ_REGEX, "ORG-VAL-CNPJ",
         "identifier.cnpj deve conter exatamente 14 dígitos numéricos.",
         "O CNPJ não contém exatamente 14 dígitos numéricos."),
        ("electronicAddress", EMAIL_REGEX, "ORG-VAL-EMAIL",
         "electronicAddress deve seguir o formato básico de e-mail usado em Person.",
         "O endereço eletrônico não corresponde ao formato básico de e-mail."),
        ("websiteUrl", URL_REGEX, "ORG-VAL-URL",
         "websiteUrl deve conter um endereço web válido (com ou sem http/https, ex.: www.site.com).",
         "O valor de websiteUrl não corresponde ao formato de endereço web (domínio com ponto, sem espaços)."),
        ("phone", PHONE_REGEX, "ORG-VAL-PHONE",
         f"Para country = 'Brasil', phone deve seguir o formato {common.PHONE_TEXT}.",
         "O telefone de uma organização no Brasil não segue o formato de telefone aceito."),
    ]
    for column, regex, rule_id, description, reason in format_rules:
        if column not in columns:
            # Campos opcionais: não gerar erro técnico quando não existirem no esquema.
            continue
        if column in BRAZIL_ONLY_COLUMNS and "country" not in columns:
            rules.append(_broken_rule(
                rule_id, "validade", "formato", column, description,
                f"A validação de {column} exige a coluna country para aplicá-la apenas ao Brasil.",
            ))
            continue
        expectation = gxe.ExpectColumnValuesToMatchRegex(column="value", regex=regex)
        if column in BRAZIL_ONLY_COLUMNS:
            expectation = gxe.ExpectColumnValuesToMatchRegex(
                column="value", regex=regex,
                row_condition="country == 'Brasil'", condition_parser="pandas",
            )
        rules.append(_base_rule(
            rule_id, "validade", "formato", column, description, reason,
            expectation,
            lambda column=column: _split_brazil_tokens(orgunits, column)
            if column in BRAZIL_ONLY_COLUMNS else common.split_tokens(orgunits, column)
            if column.startswith("identifier.") or column in ("electronicAddress", "websiteUrl")
            else _non_null_base_rows(orgunits, column),
        ))

    # Dígito verificador de CNPJ e ISNI (só nos valores que já têm o formato correto).
    for column, regex, rule_id, name, predicate in [
        ("identifier.cnpj", CNPJ_REGEX, "ORG-VAL-CNPJ-DV", "CNPJ", checks.cnpj),
        ("identifier.isni", ISNI_REGEX, "ORG-VAL-ISNI-DV", "ISNI", checks.iso7064_mod11_2),
    ]:
        if column not in columns:
            continue
        rules.append(common.make_check_rule(
            rule_id, "validade", "dígito verificador", column,
            f"O dígito verificador de {column} deve ser válido (avaliado nos valores com formato correto).",
            f"O dígito verificador do {name} não confere.",
            lambda column=column, regex=regex: _format_ok_tokens(orgunits, column, regex),
            predicate,
        ))

    # Latitude e longitude dentro da faixa geográfica (só se as colunas existirem).
    for column, limit in [("latitude", 90), ("longitude", 180)]:
        if column not in columns:
            continue
        rules.append(common.make_check_rule(
            f"ORG-VAL-{column.upper()}", "validade", "limite", column,
            f"{column} deve ser um número entre -{limit} e {limit}.",
            f"{column} não é um número entre -{limit} e {limit}.",
            lambda column=column: _non_null_base_rows(orgunits, column),
            lambda v, limit=limit: _number_in_range(v, limit),
        ))
    authority.add_authority_rule(
        rules, entity=ENTITY, frame=orgunits, columns=columns, column="country",
        authority_file="country_authority.json", authority_fields=("code", "name"),
        rule_id="ORG-AUT-COUNTRY",
        description="country deve corresponder a um código ou nome de país aceito.",
    )
    authority.add_authority_rule(
        rules, entity=ENTITY, frame=orgunits, columns=columns, column="state",
        authority_file="state_authority.json", authority_fields=("code", "name"),
        rule_id="ORG-AUT-STATE",
        description="state deve corresponder a um código ou nome de estado aceito.",
    )
    authority.add_authority_rule(
        rules, entity=ENTITY, frame=orgunits, columns=columns, column="city",
        authority_file="cidades_ibge.csv", authority_fields=("municipio",),
        rule_id="ORG-AUT-CITY-BR",
        description="Quando country for Brasil, city deve corresponder a um município da lista IBGE.",
        country_column="country", only_brazil=True,
    )
    authority.add_authority_rule(
        rules, entity=ENTITY, frame=orgunits, columns=columns, column="identifier.brcris",
        authority_file="orgunit2026.json", authority_fields=("code",),
        rule_id="ORG-AUT-BRCRIS",
        description="identifier.brcris deve existir na lista de códigos BrCris de autoridade.",
        tokenized=True,
    )

    return rules


def _format_ok_tokens(orgunits: pd.DataFrame, column: str, regex: str) -> pd.DataFrame:
    """Valores já no formato certo; só eles passam pela checagem do dígito verificador."""
    rows = common.split_tokens(orgunits, column)
    ok = rows["value"].str.fullmatch(regex.replace("(?i)", ""), case=False, na=False)
    return rows.loc[ok].reset_index(drop=True)


def _number_in_range(value, limit: float) -> bool:
    try:
        return -limit <= float(str(value).replace(",", ".")) <= limit
    except ValueError:
        return False


def _split_brazil_tokens(orgunits: pd.DataFrame, column: str) -> pd.DataFrame:
    """Divide valores multivalorados preservando country para row_condition."""
    rows = []
    for ref, source, country, original in zip(
        orgunits["ref"] if "ref" in orgunits.columns else [None] * len(orgunits),
        orgunits["source"] if "source" in orgunits.columns else [None] * len(orgunits),
        orgunits["country"],
        orgunits[column],
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


def validate() -> tuple[list[dict], list[dict], dict]:
    """Executa as regras de OrgUnit e devolve (scores, errors, metadata)."""
    with common.connect() as con:
        columns = common.get_columns(con, ENTITY)
        orgunits = _load_orgunits(con, columns)
        rules = _build_rules(con, columns, orgunits)
    return common.run_quality_checks(
        ENTITY, rules, extra_metadata={"record_count": len(orgunits)},
    )
