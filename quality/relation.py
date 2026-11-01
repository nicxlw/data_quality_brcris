"""Validação em lotes da integridade referencial dos endpoints de `relation`.

Os refs do XML são locais ao arquivo. O prefixo do semanticIdentifier determina
a coluna `identifier.*` do dataset-alvo usada na comparação global.
Great Expectations determina quais endpoints são inválidos. SQL serve apenas para
preparar os lotes e os valores de referência candidatos, sem materializar milhões
de relações ou todos os identificadores na memória.
"""
from __future__ import annotations

import re
import time
from datetime import datetime

import pandas as pd
import great_expectations as gx
import great_expectations.expectations as gxe

from quality import common

ENTITY = "relations"
BATCH_SIZE = 25_000
IDENTIFIER_PREFIX_ALIASES = {"docdb": "espacenet"}

# (tipo, endpoint semântico, dataset-alvo, aliases de type)
RELATION_ENDPOINTS = [
    ("Applicant", "fromSemanticIdentifier", "patent", ("Applicant",)),
    ("Applicant", "toSemanticIdentifier", "orgunit", ("Applicant",)),
    ("OrgUnitProgram", "fromSemanticIdentifier", "orgunit", ("OrgUnitProgram",)),
    ("OrgUnitProgram", "toSemanticIdentifier", "program", ("OrgUnitProgram",)),
    ("IsProgramOf", "fromSemanticIdentifier", "program", ("IsProgramOf",)),
    ("IsProgramOf", "toSemanticIdentifier", "course", ("IsProgramOf",)),
    ("Creator", "fromSemanticIdentifier", "software", ("Creator", "creator")),
    ("Creator", "toSemanticIdentifier", "person", ("Creator", "creator")),
    ("PartnerResearchGroupOrgUnit", "fromSemanticIdentifier", "orgunit", ("PartnerResearchGroupOrgUnit",)),
    ("PartnerResearchGroupOrgUnit", "toSemanticIdentifier", "researchgroup", ("PartnerResearchGroupOrgUnit",)),
    ("LeaderResearchGroup", "fromSemanticIdentifier", "person", ("LeaderResearchGroup",)),
    ("LeaderResearchGroup", "toSemanticIdentifier", "researchgroup", ("LeaderResearchGroup",)),
    ("Inventor", "fromSemanticIdentifier", "patent", ("Inventor",)),
    ("Inventor", "toSemanticIdentifier", "person", ("Inventor",)),
    ("CoAdivisoring", "fromSemanticIdentifier", "publication", ("CoAdivisoring", "CoAdvisoring")),
    ("CoAdivisoring", "toSemanticIdentifier", "person", ("CoAdivisoring", "CoAdvisoring")),
    ("MemberResearchGroup", "fromSemanticIdentifier", "person", ("MemberResearchGroup",)),
    ("MemberResearchGroup", "toSemanticIdentifier", "researchgroup", ("MemberResearchGroup",)),
    ("Affiliation", "fromSemanticIdentifier", "orgunit", ("Affiliation",)),
    ("Affiliation", "toSemanticIdentifier", "person", ("Affiliation",)),
    ("CourseThesis", "fromSemanticIdentifier", "course", ("CourseThesis",)),
    ("CourseThesis", "toSemanticIdentifier", "publication", ("CourseThesis",)),
    ("Adivisoring", "fromSemanticIdentifier", "publication", ("Adivisoring",)),
    ("Adivisoring", "toSemanticIdentifier", "person", ("Adivisoring",)),
    ("PublisherJournal", "fromSemanticIdentifier", "publication", ("PublisherJournal",)),
    ("PublisherJournal", "toSemanticIdentifier", "journal", ("PublisherJournal",)),
    ("ThesisSponsorship", "fromSemanticIdentifier", "orgunit", ("ThesisSponsorship",)),
    ("ThesisSponsorship", "toSemanticIdentifier", "publication", ("ThesisSponsorship",)),
    ("Authorship", "fromSemanticIdentifier", "publication", ("Authorship", "Authirship")),
    ("Authorship", "toSemanticIdentifier", "person", ("Authorship", "Authirship")),
]


def _identifier_value(value: object, prefix: str | None = None) -> str | None:
    text = common.normalize_text(value)
    if text is None:
        return None
    _, separator, identifier = text.partition("::")
    if separator:
        text = identifier.strip()
    if prefix == "docdb":
        text = re.sub(r"^[A-Z]{2}", "", text, flags=re.IGNORECASE)
        text = re.sub(r"[A-Z][0-9]?$", "", text, flags=re.IGNORECASE)
    return text or None


def _semantic_identifier_parts(value: object) -> tuple[str, str] | None:
    text = common.normalize_text(value)
    if text is None:
        return None
    prefix, separator, identifier = text.partition("::")
    if not separator or not prefix.strip():
        return None
    normalized_prefix = prefix.strip().casefold()
    normalized_identifier = _identifier_value(identifier, normalized_prefix)
    if normalized_identifier is None:
        return None
    return normalized_prefix, normalized_identifier


def _identifier_columns(con, target: str) -> dict[str, str]:
    return {
        column[len("identifier."):].casefold(): column
        for column in common.get_columns(con, target)
        if column.casefold().startswith("identifier.")
    }


def _identifier_column_for_prefix(columns: dict[str, str], prefix: str) -> str | None:
    identifier_name = IDENTIFIER_PREFIX_ALIASES.get(prefix, prefix).casefold()
    return columns.get(identifier_name)


def _check_schema(con, target: str, side: str) -> None:
    if not common.view_exists(con, target):
        raise ValueError(f"A view {target!r} necessária à validação de relation não existe.")
    if not common.view_exists(con, "relation"):
        raise ValueError("A view 'relation' não existe no DuckDB.")
    relation_columns = set(common.get_columns(con, "relation"))
    if side not in relation_columns:
        raise ValueError(
            f"A view relation não tem {side}. Reextraia as fontes de relações após atualizar extract.py."
        )


def _relation_batches(con, aliases: tuple[str, ...], side: str):
    placeholders = ", ".join("?" for _ in aliases)
    query = f'''
        SELECT "type", "fromEntityRef", "toEntityRef",
               "fromSemanticIdentifier", "toSemanticIdentifier", "info", "source"
        FROM "relation"
        WHERE lower(trim(CAST("type" AS VARCHAR))) IN ({placeholders})
    '''
    cursor = con.execute(query, [alias.casefold() for alias in aliases])
    while True:
        batch = cursor.fetch_df_chunk(vectors_per_chunk=max(1, BATCH_SIZE // 2048))
        if batch is None or batch.empty:
            break
        # DuckDB vectors_per_chunk é número de vetores, não de linhas; corte defensivo.
        for start in range(0, len(batch), BATCH_SIZE):
            yield batch.iloc[start:start + BATCH_SIZE].reset_index(drop=True)


def _valid_identifier_values(con, target: str, column: str, prefix: str) -> set[str]:
    """Carrega os valores de uma coluna identifier.*, separando valores unidos por '|'."""
    quoted_column = common.quote_ident(column)
    query = (
        f'SELECT DISTINCT trim(CAST({quoted_column} AS VARCHAR)) '
        f'FROM {common.quote_ident(target)} '
        f'WHERE {quoted_column} IS NOT NULL '
        f'AND trim(CAST({quoted_column} AS VARCHAR)) <> ?'
    )
    cursor = con.execute(query, [""])
    values: set[str] = set()
    while True:
        chunk = cursor.fetch_df_chunk(vectors_per_chunk=8)
        if chunk is None or chunk.empty:
            break
        for value in chunk.iloc[:, 0].tolist():
            for token in str(value).split("|"):
                identifier = _identifier_value(token, prefix)
                if identifier is not None:
                    values.add(identifier)
    return values


def validate() -> tuple[list[dict], list[dict], dict]:
    """Executa GX em lotes por regra, mantendo na RAM apenas o alvo atual."""
    started_all = time.perf_counter()
    context = gx.get_context(mode="ephemeral")
    datasource = context.data_sources.add_pandas(name="brcris_relations_quality")
    scores, errors, audits = [], [], []

    with common.connect() as con:
        if not common.view_exists(con, "relation"):
            raise ValueError("A view 'relation' não existe no DuckDB.")
        relation_count = con.execute('SELECT COUNT(*) FROM "relation"').fetchone()[0]

        indexed_rules: dict[str, list[tuple[int, str, str, tuple[str, ...]]]] = {}
        for number, (relation_type, side, target, aliases) in enumerate(RELATION_ENDPOINTS, start=1):
            _check_schema(con, target, side)
            indexed_rules.setdefault(target, []).append((number, relation_type, side, aliases))

        for target, target_rules in indexed_rules.items():
            identifier_columns = _identifier_columns(con, target)
            valid_ids_by_prefix: dict[str, set[str]] = {}

            for number, relation_type, side, aliases in target_rules:
                rule = common.Rule(
                    id=f"REL-CON-SEM-{number:03d}",
                    dimension="consistência",
                    validation="consistência referencial",
                    column=f"relation.{relation_type}.{side}",
                    description=(
                        f"{side} da relação {relation_type} deve corresponder à coluna "
                        f"identifier.* de {target}, conforme o prefixo do semanticIdentifier."
                    ),
                    reason=(
                        f"{side} da relação {relation_type} não corresponde à coluna "
                        f"identifier.* de {target} indicada pelo prefixo."
                    ),
                    expectation=gxe.ExpectColumnValuesToBeInSet(column="value", value_set=set()),
                    data=None,
                )
                rule_started = time.perf_counter()
                element_count = 0
                unexpected_count = 0
                batch_count = 0
                rule_errors = []
                for batch_count, relations in enumerate(_relation_batches(con, aliases, side), start=1):
                    frame = common.relation_rows(relations, side)
                    parsed_values = frame["record_value"].map(_semantic_identifier_parts).tolist()
                    prefixes = {parsed[0] for parsed in parsed_values if parsed is not None}
                    for prefix in prefixes:
                        if prefix not in valid_ids_by_prefix:
                            identifier_column = _identifier_column_for_prefix(identifier_columns, prefix)
                            if identifier_column is None:
                                raise ValueError(
                                    f"O prefixo {prefix!r} das relações não tem coluna "
                                    f"identifier correspondente em {target!r}."
                                )
                            valid_ids_by_prefix[prefix] = _valid_identifier_values(
                                con, target, identifier_column, prefix,
                            )

                    comparison_values = []
                    valid_batch_values = set()
                    for original, parsed in zip(frame["record_value"], parsed_values):
                        if parsed is None:
                            value = common.normalize_text(original) or common.MISSING_REFERENCE
                        else:
                            prefix, identifier = parsed
                            value = f"{prefix}::{identifier}"
                            if identifier in valid_ids_by_prefix[prefix]:
                                valid_batch_values.add(value)
                        comparison_values.append(value)
                    frame["value"] = comparison_values
                    rule.expectation = gxe.ExpectColumnValuesToBeInSet(
                        column="value", value_set=valid_batch_values,
                    )
                    score, batch_errors, _ = common.run_expectation(
                        datasource, frame, rule, entity=ENTITY,
                        asset_suffix=f"batch_{number:03d}_{batch_count:05d}",
                    )
                    element_count += score["evaluated"]
                    unexpected_count += score["failures"]
                    rule_errors.extend(batch_errors)
                    if batch_count % 20 == 0:
                        print(
                            f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [relations] {rule.id}: "
                            f"lotes={batch_count:,}; avaliados={element_count:,}; falhas={unexpected_count:,}",
                            flush=True,
                        )

                errors.extend(rule_errors)
                scores.append(common.score_record(
                    rule.id, rule.validation, rule.dimension, rule.column, rule.description,
                    element_count, unexpected_count, time.perf_counter() - rule_started,
                ))
                audits.append({
                    "rule_id": rule.id,
                    "expectation": "ExpectColumnValuesToBeInSet",
                    "success": unexpected_count == 0,
                    "element_count": element_count,
                    "unexpected_count": unexpected_count,
                    "batch_count": batch_count,
                    "batched": True,
                    "batch_size": BATCH_SIZE,
                    "result_format": "COMPLETE",
                    "target_entity": target,
                    "endpoint_column": side,
                })
                print(
                    f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [relations] {rule.id} concluída: "
                    f"avaliados={element_count:,}; falhas={unexpected_count:,}; lotes={batch_count:,}",
                    flush=True,
                )
            del valid_ids_by_prefix

    # Mantém a ordem das regras conforme a tabela de mapeamento, independente do agrupamento por alvo.
    scores.sort(key=lambda row: int(row["rule_id"].rsplit("-", 1)[-1]))
    audits.sort(key=lambda row: int(row["rule_id"].rsplit("-", 1)[-1]))
    metadata = {
        "entity": ENTITY,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "validation_engine": f"Great Expectations {gx.__version__}",
        "gx_result_format": "COMPLETE",
        "gx_results": audits,
        "score_formula": common.SCORE_FORMULA,
        "record_count": relation_count,
        "relation_types": len({relation_type for relation_type, *_ in RELATION_ENDPOINTS}),
        "referential_rules": len(RELATION_ENDPOINTS),
        "batched_validation": True,
        "batch_size": BATCH_SIZE,
        "semantic_identifier_validation": True,
        "target_identifier_column_validation": True,
        "duration_seconds": round(time.perf_counter() - started_all, 2),
    }
    return scores, errors, metadata

