"""Definição das regras de Publication.

Aqui ficam só as regras (id, descrição, motivo) e as constantes. A execução é feita
em SQL no DuckDB por quality/fast.py, que é o que `python run.py validate publication`
chama. Publication tem milhões de linhas, então não passa pelo Pandas.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from quality import common

ENTITY = "publication"
MANDATORY_COLUMNS = ["ref", "title", "author", "type", "identifier.brcris"]
DATE_COLUMNS = ["publicationDate", "defenceDay", "degreeDate"]
URL_REGEX = common.URL_REGEX
NUMBER_REGEX = r"^[+-]?(?:[0-9]+(?:[.,][0-9]*)?|[.,][0-9]+)(?:[eE][+-]?[0-9]+)?$"
CURRENT_YEAR = date.today().year
MIN_YEAR = 1500                       # anos anteriores são tratados como erro de digitação
DOI_REGEX = r"^10\.[0-9]{4,9}/[^\s]+$"


@dataclass
class RuleDef:
    """Uma regra de Publication. `problem` preenchido = regra impossível (coluna ausente)."""
    id: str
    dimension: str
    validation: str
    column: str
    description: str
    reason: str
    problem: str | None = None


DOMAIN_NOTE_TYPES = ("Artigo", "Dissertação", "Capítulo de Livro", "Tese", "Livro",
                     "Artigo de Conferência", "Preprint", "Conjunto de Dados")


def date_year(value) -> int | None:
    """Ano de um valor de data (ano, ISO ou dd/mm/aaaa); None se não der para ler."""
    normalized = common.normalize_text(value)
    if normalized is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if float(value).is_integer():
            return int(value)
    if re.fullmatch(r"[0-9]{4}", normalized):
        return int(normalized)
    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00")).year
    except ValueError:
        pass
    try:
        return datetime.strptime(normalized, "%d/%m/%Y").year
    except ValueError:
        return None


def build_rules(columns: list[str], sample_size: int | None = None) -> list[RuleDef]:
    rules: list[RuleDef] = []
    scope = (f"na amostra repetível de até {sample_size:,} registros"
             if sample_size is not None else "na base completa")

    def add(rule_id, dimension, validation, column, description, reason, missing=None):
        """`missing`: mensagem de problema quando a coluna necessária não existe."""
        rules.append(RuleDef(rule_id, dimension, validation, column, description,
                             missing or reason, problem=missing))

    # Singularidade (vem antes da unicidade): cada identifier.* deve ter um único valor por registro
    identifier_columns = [c for c in columns if c.startswith("identifier.")]
    for number, column in enumerate(identifier_columns, start=1):
        add(f"PUB-SIN-ID-{number:02d}", "validade", "singularidade", column,
            f"Cada publicação deve ter um único valor em {column} (sem '|') {scope}.",
            f"{column} tem mais de um valor no mesmo registro.")

    # Unicidade de cada coluna identifier.* (valores separados por '|')
    for number, column in enumerate(identifier_columns, start=1):
        add(f"PUB-UNI-ID-{number:02d}", "unicidade", "unicidade", column,
            f"Cada valor de {column} deve ser único {scope}.", f"Valor de {column} duplicado.")

    # Completude das colunas obrigatórias
    for column in MANDATORY_COLUMNS:
        add(f"PUB-COM-{column.replace('.', '-').upper()}", "completude", "completude", column,
            f"{column} deve estar preenchido.", f"{column} está nulo, vazio ou contém apenas espaços.",
            missing=None if column in columns else f"Coluna obrigatória {column!r} ausente na view {ENTITY!r}.")

    add("PUB-UNI-REF", "unicidade", "unicidade", "ref",
        f"Cada referência ref deve ser única {scope}.", "A referência ref está associada a mais de um registro.",
        missing=None if "ref" in columns else f"Coluna obrigatória 'ref' ausente na view {ENTITY!r}.")

    # Ano das datas: entre MIN_YEAR e o ano atual
    for column in DATE_COLUMNS:
        add(f"PUB-VAL-YEAR-{column.upper()}", "validade", "limite", column,
            f"{column} deve ter ano de 4 dígitos entre {MIN_YEAR} e o ano atual ({CURRENT_YEAR}).",
            f"{column} tem ano anterior a {MIN_YEAR}, posterior ao ano atual, ou não é uma data/ano válido.",
            missing=None if column in columns else f"Coluna {column!r} ausente na view {ENTITY!r}.")

    for column in ["startPage", "endPage"]:
        add(f"PUB-VAL-NUM-{column.upper()}", "validade", "formato numérico", column,
            f"{column} deve conter um valor numérico quando preenchido.", f"O valor de {column} não é numérico.",
            missing=None if column in columns else f"Coluna {column!r} ausente na view {ENTITY!r}.")

    add("PUB-VAL-PAGES-ORDER", "validade", "consistência entre campos", "startPage",
        "startPage não pode ser maior que endPage (avaliado quando ambos são numéricos).",
        "startPage é maior que endPage.",
        missing=None if {"startPage", "endPage"}.issubset(columns) else f"Coluna startPage ou endPage ausente na view {ENTITY!r}.")

    add("PUB-VAL-DOI", "validade", "formato", "identifier.doi",
        "Cada DOI em identifier.doi deve começar com 10.<4 a 9 dígitos>/ seguido do sufixo, sem espaços.",
        "O valor não tem o formato de um DOI (10.xxxx/sufixo).",
        missing=None if "identifier.doi" in columns else f"Coluna 'identifier.doi' ausente na view {ENTITY!r}.")
    add("PUB-VAL-ISBN-DV", "validade", "dígito verificador", "identifier.isbn",
        "Cada ISBN em identifier.isbn deve ser um ISBN-10 ou ISBN-13 com dígito verificador válido (hifens ignorados).",
        "O ISBN não tem 10/13 dígitos ou o dígito verificador não confere.",
        missing=None if "identifier.isbn" in columns else f"Coluna 'identifier.isbn' ausente na view {ENTITY!r}.")
    add("PUB-AUT-TYPE", "validade", "lista de autoridade", "type",
        "type deve ser um dos tipos aceitos: " + ", ".join(DOMAIN_NOTE_TYPES) + ".",
        "O valor de type não consta na lista de tipos aceitos (dominios.json).",
        missing=None if "type" in columns else f"Coluna 'type' ausente na view {ENTITY!r}.")
    add("PUB-AUT-ACCESSTYPE", "validade", "lista de autoridade", "accessType",
        "accessType deve ser um dos valores aceitos (open/embargoed/restricted/metadata only access, ou equivalentes em português).",
        "O valor de accessType não consta na lista de valores aceitos (dominios.json).",
        missing=None if "accessType" in columns else f"Coluna 'accessType' ausente na view {ENTITY!r}.")

    # A origem pode usar resourceURL ou resourceUrl
    add("PUB-VAL-RESOURCE-URL", "validade", "formato de URL", "resourceUrl",
        "resourceUrl deve conter um endereço web válido (com ou sem http/https, ex.: www.site.com) quando preenchido.",
        "O valor de resourceUrl não corresponde ao formato de endereço web (domínio com ponto, sem espaços).",
        missing=None if any(c.casefold() == "resourceurl" for c in columns)
        else f"Coluna equivalente a 'resourceUrl' ausente na view {ENTITY!r}.")

    missing_cols = sorted({"type", "advisor"} - set(columns))
    add("PUB-COM-THESIS-ADVISOR", "completude", "completude", "advisor",
        "Publicações do tipo Tese devem ter advisor preenchido.",
        "advisor está nulo ou vazio em uma publicação do tipo Tese.",
        missing=(f"Validação de advisor impossível: coluna(s) ausente(s) na view {ENTITY!r}: {missing_cols}."
                 if missing_cols else None))

    add("PUB-AUT-LANGUAGE", "validade", "lista de autoridade", "language",
        "language deve corresponder a um código ou nome de idioma aceito.",
        "O valor de language não consta na lista de autoridade language2026.json.",
        missing=None if "language" in columns else f"Coluna 'language' ausente na view {ENTITY!r}.")
    return rules
