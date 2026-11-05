"""Validações contra listas de autoridade versionadas em quality/autoridade/."""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Callable

import pandas as pd
import great_expectations.expectations as gxe
from quality import common

AUTHORITY_DIR = Path(__file__).resolve().parent / "autoridade"


def normalize_authority(value) -> str | None:
    value = common.normalize_text(value)
    if value is None:
        return None
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return value.casefold().strip()


@lru_cache(maxsize=None)
def authority_values(filename: str, fields: tuple[str, ...]) -> frozenset[str]:
    """Carrega e normaliza os valores permitidos; cacheia por arquivo/campos."""
    path = AUTHORITY_DIR / filename
    if filename == "dominios.json":
        # listas fechadas: {"nome_da_lista": [valores...]}; `fields` traz o nome da lista
        data = json.loads(path.read_text(encoding="utf-8"))
        values = {normalize_authority(v) for v in data[fields[0]]}
        return frozenset(v for v in values if v is not None)
    if filename.endswith(".json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            candidates = []
            for key, value in data.items():
                candidates.append(key)
                if isinstance(value, str):
                    candidates.append(value)
                elif isinstance(value, dict):
                    candidates.extend(value.get(field) for field in fields)
        elif isinstance(data, list):
            candidates = [
                item.get(field)
                for item in data if isinstance(item, dict)
                for field in fields
            ]
        else:
            raise ValueError(f"Formato JSON não suportado: {filename}")
    elif filename.endswith(".csv"):
        # A lista de cidades usa ponto e vírgula; as demais usam vírgula.
        sep = ";" if filename == "cidades_ibge.csv" else ","
        frame = pd.read_csv(path, sep=sep, dtype=str, keep_default_na=False)
        candidates = []
        for field in fields:
            if field in frame.columns:
                candidates.extend(frame[field].tolist())
    else:
        raise ValueError(f"Formato de autoridade não suportado: {filename}")

    values = set()
    for candidate in candidates:
        normalized = normalize_authority(candidate)
        if normalized is not None:
            values.add(normalized)
    return frozenset(values)


def lattes_id(value) -> str | None:
    normalized = common.normalize_text(value)
    if normalized is None:
        return None
    # Aceita tanto o ID puro quanto URLs/identificadores que contenham o ID.
    matches = re.findall(r"\d{10,}", normalized)
    return matches[-1].zfill(16) if matches else normalize_authority(normalized)


def add_authority_rule(
    rules: list[common.Rule],
    *,
    entity: str,
    frame: pd.DataFrame,
    columns: list[str],
    column: str,
    authority_file: str,
    authority_fields: tuple[str, ...],
    rule_id: str,
    description: str,
    tokenized: bool = True,
    transform: Callable | None = None,
    country_column: str | None = None,
    only_brazil: bool = False,
) -> None:
    """Acrescenta regra GX de domínio; a preparação não decide o que é inválido."""
    dimension = "validade"
    validation = "lista de autoridade"
    reason = f"O valor de {column} não consta na lista de autoridade {authority_file}."

    def missing_column():
        raise ValueError(f"Coluna {column!r} ausente na view {entity!r}.")

    if column not in columns:
        rules.append(common.Rule(
            id=rule_id, dimension=dimension, validation=validation, column=column,
            description=description, reason=f"Coluna {column!r} ausente na view {entity!r}.",
            expectation=None, data=missing_column,
        ))
        return

    values = authority_values(authority_file, authority_fields)
    if transform is not None:
        values = frozenset(normalize_authority(transform(v)) for v in values)
    if only_brazil:
        if not country_column or country_column not in columns:
            rules.append(common.Rule(
                id=rule_id, dimension=dimension, validation=validation, column=column,
                description=description,
                reason=f"Não foi possível condicionar a validação: coluna de país {country_column!r} ausente.",
                expectation=None,
                data=lambda: (_ for _ in ()).throw(ValueError(
                    f"Coluna de país {country_column!r} ausente na view {entity!r}."
                )),
            ))
            return

    def make_rows():
        source = frame
        if only_brazil:
            brazil_values = {"br", "brasil", "brazil"}
            mask = source[country_column].map(normalize_authority).isin(brazil_values)
            source = source.loc[mask].copy()
        rows = common.split_tokens(source, column) if tokenized else common.base_rows(source, column)
        rows = rows[rows["value"].notna()].reset_index(drop=True)
        if transform is not None:
            rows["value"] = rows["value"].map(transform)
        rows["value"] = rows["value"].map(normalize_authority)
        rows = rows[rows["value"].notna()].reset_index(drop=True)
        return rows

    rules.append(common.Rule(
        id=rule_id, dimension=dimension, validation=validation, column=column,
        description=description, reason=reason,
        expectation=gxe.ExpectColumnValuesToBeInSet(column="value", value_set=set(values)),
        data=make_rows,
    ))
