"""Regras de qualidade de Publication, processadas em lotes para grandes volumes."""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Iterator

import pandas as pd
import great_expectations.expectations as gxe

from quality import authority, common

ENTITY = "publication"
BATCH_ROWS = 50_000
# Para unicidade, o mesmo valor precisa cair sempre no mesmo lote. Hash-particionar
# impede que duplicatas entre blocos sejam perdidas.
UNIQUE_PARTITIONS = 64
MANDATORY_COLUMNS = ["ref", "title", "author", "type", "identifier.brcris"]
DATE_COLUMNS = ["publicationDate", "defenceDay", "degreeDate"]
URL_REGEX = r"^https?://[^\s./]+(?:\.[^\s./]+)+(?:[/:?#][^\s]*)?$"
NUMBER_REGEX = r"^[+-]?(?:[0-9]+(?:[.,][0-9]*)?|[.,][0-9]+)(?:[eE][+-]?[0-9]+)?$"
CURRENT_YEAR = date.today().year
LOG = logging.getLogger("quality.publication")


def _log(message: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [publication] {message}", flush=True)


def _rule(rule_id: str, dimension: str, validation: str, column: str,
          description: str, reason: str, expectation, batch_data: Callable[[], Iterator[pd.DataFrame]]) -> common.Rule:
    return common.Rule(
        id=rule_id, dimension=dimension, validation=validation, column=column,
        description=description, reason=reason, expectation=expectation,
        data=None, batch_data=batch_data,
    )


def _broken_rule(rule_id: str, dimension: str, validation: str, column: str,
                 description: str, problem: str) -> common.Rule:
    def _raise():
        raise ValueError(problem)
    return common.Rule(
        id=rule_id, dimension=dimension, validation=validation, column=column,
        description=description, reason=problem, expectation=None, data=_raise,
    )


def _sql_batches(query: str, params: list | None = None,
                 prepare: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
                 chunk_rows: int = BATCH_ROWS) -> Iterator[pd.DataFrame]:
    """Executa consulta em blocos pequenos para limitar o pico de memória."""
    # DuckDB fetch_df_chunk usa vetores (normalmente 2.048 linhas por vetor).
    vectors = max(1, (chunk_rows + 2047) // 2048)
    con = common.connect(read_only=True)
    try:
        result = con.execute(query, params or [])
        batch_no = 0
        while True:
            frame = result.fetch_df_chunk(vectors_per_chunk=vectors)
            if frame is None or frame.empty:
                break
            batch_no += 1
            if prepare:
                frame = prepare(frame)
            if not frame.empty:
                _log(f"lote {batch_no}: {len(frame):,} registros preparados")
                yield frame.reset_index(drop=True)
            del frame
    finally:
        con.close()


def _base_prepare(column: str) -> Callable[[pd.DataFrame], pd.DataFrame]:
    def prepare(frame: pd.DataFrame) -> pd.DataFrame:
        return common.base_rows(frame, column)
    return prepare


def _non_null_prepare(column: str) -> Callable[[pd.DataFrame], pd.DataFrame]:
    def prepare(frame: pd.DataFrame) -> pd.DataFrame:
        rows = common.base_rows(frame, column)
        return rows[rows["value"].notna()].reset_index(drop=True)
    return prepare


def _date_year(value) -> int | None:
    normalized = common.normalize_text(value)
    if normalized is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = pd.to_numeric(value, errors="coerce")
        if pd.notna(number) and float(number).is_integer():
            return int(number)
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


def _date_prepare(column: str) -> Callable[[pd.DataFrame], pd.DataFrame]:
    def prepare(frame: pd.DataFrame) -> pd.DataFrame:
        rows = common.base_rows(frame, column)
        years = rows["record_value"].map(_date_year)
        invalid = rows["value"].notna() & years.isna()
        years.loc[invalid] = CURRENT_YEAR + 1
        rows["value"] = years
        return rows
    return prepare



def _sql_partition(query: str, params: list | None = None) -> Iterator[pd.DataFrame]:
    """Carrega uma única partição hash, mantendo duplicatas de um valor juntas."""
    con = common.connect(read_only=True)
    try:
        frame = con.execute(query, params or []).fetchdf()
        if not frame.empty:
            _log(f"partição carregada: {len(frame):,} registros")
            yield frame.reset_index(drop=True)
    finally:
        con.close()


def _unique_token_batches(column: str) -> Iterator[pd.DataFrame]:
    """Particiona por hash do token: duplicatas iguais ficam no mesmo lote GX."""
    quoted = common.quote_ident(column)
    for partition in range(UNIQUE_PARTITIONS):
        query = f'''SELECT "ref", "source", CAST({quoted} AS VARCHAR) AS record_value,
                           trim(token.value) AS value
                    FROM "{ENTITY}",
                         UNNEST(string_split(CAST({quoted} AS VARCHAR), '|')) AS token(value)
                    WHERE {quoted} IS NOT NULL
                      AND trim(token.value) <> ''
                      AND hash(trim(token.value)) % {UNIQUE_PARTITIONS} = ?'''
        _log(f"unicidade de {column}: partição {partition + 1}/{UNIQUE_PARTITIONS}")
        yield from _sql_partition(query, [partition])


def _unique_ref_batches() -> Iterator[pd.DataFrame]:
    quoted = common.quote_ident("ref")
    for partition in range(UNIQUE_PARTITIONS):
        query = f'''SELECT "ref", "source", CAST({quoted} AS VARCHAR) AS record_value,
                           trim(CAST({quoted} AS VARCHAR)) AS value
                    FROM "{ENTITY}"
                    WHERE {quoted} IS NOT NULL AND trim(CAST({quoted} AS VARCHAR)) <> ''
                      AND hash(trim(CAST({quoted} AS VARCHAR))) % {UNIQUE_PARTITIONS} = ?'''
        _log(f"unicidade de ref: partição {partition + 1}/{UNIQUE_PARTITIONS}")
        yield from _sql_partition(query, [partition])


def _authority_language_batches() -> Iterator[pd.DataFrame]:
    values = authority.authority_values(
        "language2026.json", ("sigla", "name_original", "name_pt", "name_en")
    )
    query = '''SELECT "ref", "source", "language" AS record_value
               FROM "publication" WHERE "language" IS NOT NULL
                 AND trim(CAST("language" AS VARCHAR)) <> '' '''

    def prepare(frame: pd.DataFrame) -> pd.DataFrame:
        rows = common.base_rows(frame, "record_value")
        rows["value"] = rows["value"].map(authority.normalize_authority)
        return rows[rows["value"].notna()].reset_index(drop=True)

    yield from _sql_batches(query, prepare=prepare)


def _build_rules(columns: list[str]) -> list[common.Rule]:
    rules: list[common.Rule] = []
    identifier_columns = [c for c in columns if c.startswith("identifier.")]

    for number, column in enumerate(identifier_columns, start=1):
        rules.append(_rule(
            f"PUB-UNI-ID-{number:02d}", "unicidade", "unicidade", column,
            f"Cada valor de {column} deve ser único entre as publicações.",
            f"Valor de {column} duplicado.",
            gxe.ExpectColumnValuesToBeUnique(column="value"),
            lambda column=column: _unique_token_batches(column),
        ))

    for column in MANDATORY_COLUMNS:
        rule_id = f"PUB-COM-{column.replace('.', '-').upper()}"
        description = f"{column} deve estar preenchido."
        if column not in columns:
            rules.append(_broken_rule(rule_id, "completude", "completude", column,
                                      description, f"Coluna obrigatória {column!r} ausente na view {ENTITY!r}."))
            continue
        query = f'''SELECT "ref", "source", {common.quote_ident(column)} AS "{column}"
                    FROM "{ENTITY}"'''
        rules.append(_rule(
            rule_id, "completude", "completude", column, description,
            f"{column} está nulo, vazio ou contém apenas espaços.",
            gxe.ExpectColumnValuesToNotBeNull(column="value"),
            lambda query=query, column=column: _sql_batches(query, prepare=_base_prepare(column)),
        ))

    if "ref" in columns:
        rules.append(_rule(
            "PUB-UNI-REF", "unicidade", "unicidade", "ref",
            "Cada publicação deve ter uma referência ref única.",
            "A referência ref está associada a mais de um registro.",
            gxe.ExpectColumnValuesToBeUnique(column="value"), _unique_ref_batches,
        ))
    else:
        rules.append(_broken_rule("PUB-UNI-REF", "unicidade", "unicidade", "ref",
                                  "Cada publicação deve ter uma referência ref única.",
                                  f"Coluna obrigatória 'ref' ausente na view {ENTITY!r}."))

    for column in DATE_COLUMNS:
        rule_id = f"PUB-VAL-YEAR-{column.upper()}"
        description = f"{column} deve ser menor ou igual ao ano atual ({CURRENT_YEAR})."
        if column not in columns:
            rules.append(_broken_rule(rule_id, "validade", "limite", column, description,
                                      f"Coluna {column!r} ausente na view {ENTITY!r}."))
            continue
        query = f'''SELECT "ref", "source", {common.quote_ident(column)} AS "{column}"
                    FROM "{ENTITY}"'''
        rules.append(_rule(
            rule_id, "validade", "limite", column, description,
            f"{column} é posterior ao ano atual ou não contém um ano/data válida.",
            gxe.ExpectColumnValuesToBeBetween(column="value", max_value=CURRENT_YEAR),
            lambda query=query, column=column: _sql_batches(query, prepare=_date_prepare(column)),
        ))

    for column in ["startPage", "endPage"]:
        rule_id = f"PUB-VAL-NUM-{column.upper()}"
        description = f"{column} deve conter um valor numérico quando preenchido."
        if column not in columns:
            rules.append(_broken_rule(rule_id, "validade", "formato numérico", column, description,
                                      f"Coluna {column!r} ausente na view {ENTITY!r}."))
            continue
        query = f'''SELECT "ref", "source", {common.quote_ident(column)} AS "{column}"
                    FROM "{ENTITY}" WHERE {common.quote_ident(column)} IS NOT NULL
                      AND trim(CAST({common.quote_ident(column)} AS VARCHAR)) <> '' '''
        rules.append(_rule(
            rule_id, "validade", "formato numérico", column, description,
            f"O valor de {column} não é numérico.",
            gxe.ExpectColumnValuesToMatchRegex(column="value", regex=NUMBER_REGEX),
            lambda query=query, column=column: _sql_batches(query, prepare=_base_prepare(column)),
        ))

    # A origem pode preservar a grafia resourceURL/resourceUrl. O alias explícito
    # garante que o DataFrame sempre exponha a chave exata usada por base_rows.
    resource_url_column = next((c for c in columns if c.casefold() == "resourceurl"), None)
    if resource_url_column is None:
        rules.append(_broken_rule("PUB-VAL-RESOURCE-URL", "validade", "formato de URL", "resourceUrl",
                                  "resourceUrl deve conter uma URL HTTP ou HTTPS quando preenchido.",
                                  f"Coluna equivalente a 'resourceUrl' ausente na view {ENTITY!r}."))
    else:
        quoted_url = common.quote_ident(resource_url_column)
        query = (f'SELECT "ref", "source", {quoted_url} AS "resourceUrl" '
                 f'FROM "publication" WHERE {quoted_url} IS NOT NULL '
                 f'AND trim(CAST({quoted_url} AS VARCHAR)) <> ' + "''")
        rules.append(_rule(
            "PUB-VAL-RESOURCE-URL", "validade", "formato de URL", "resourceUrl",
            "resourceUrl deve conter uma URL HTTP ou HTTPS quando preenchido.",
            "O valor de resourceUrl não corresponde ao formato básico de URL HTTP(S).",
            gxe.ExpectColumnValuesToMatchRegex(column="value", regex=URL_REGEX),
            lambda: _sql_batches(query, prepare=_base_prepare("resourceUrl")),
        ))

    if not {"type", "advisor"}.issubset(columns):
        missing = sorted({"type", "advisor"} - set(columns))
        rules.append(_broken_rule("PUB-COM-THESIS-ADVISOR", "completude", "completude", "advisor",
                                  "Publicações do tipo Tese devem ter advisor preenchido.",
                                  f"Validação de advisor impossível: coluna(s) ausente(s) na view {ENTITY!r}: {missing}."))
    else:
        query = '''SELECT "ref", "source", "advisor" FROM "publication"
                   WHERE lower(trim(CAST("type" AS VARCHAR))) = 'tese' '''
        rules.append(_rule(
            "PUB-COM-THESIS-ADVISOR", "completude", "completude", "advisor",
            "Publicações do tipo Tese devem ter advisor preenchido.",
            "advisor está nulo ou vazio em uma publicação do tipo Tese.",
            gxe.ExpectColumnValuesToNotBeNull(column="value"),
            lambda: _sql_batches(query, prepare=_base_prepare("advisor")),
        ))

    if "language" not in columns:
        rules.append(_broken_rule("PUB-AUT-LANGUAGE", "validade", "lista de autoridade", "language",
                                  "language deve corresponder a um código ou nome de idioma aceito.",
                                  f"Coluna 'language' ausente na view {ENTITY!r}."))
    else:
        values = authority.authority_values(
            "language2026.json", ("sigla", "name_original", "name_pt", "name_en")
        )
        rules.append(_rule(
            "PUB-AUT-LANGUAGE", "validade", "lista de autoridade", "language",
            "language deve corresponder a um código ou nome de idioma aceito.",
            "O valor de language não consta na lista de autoridade language2026.json.",
            gxe.ExpectColumnValuesToBeInSet(column="value", value_set=set(values)),
            _authority_language_batches,
        ))

    return rules


GROUPS = ("unicidade", "completude", "validade")
GROUP_RESULTS_DIR = common.RESULTS_DIR / ENTITY / "grupos"


def _group_file(group: str) -> Path:
    return GROUP_RESULTS_DIR / f"{group}.json"


def _save_group(group: str, scores: list[dict], errors: list[dict], metadata: dict) -> None:
    GROUP_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    common.write_json(_group_file(group), {
        "group": group, "scores": scores, "errors": errors, "metadata": metadata,
    })


def _load_group_results() -> tuple[list[dict], list[dict], list[dict], list[str]]:
    """Reúne resultados persistidos; cada grupo é substituído quando executado novamente."""
    scores_by_id: dict[str, dict] = {}
    errors_by_key: dict[tuple, dict] = {}
    audits_by_id: dict[str, dict] = {}
    loaded_groups: list[str] = []
    for group in GROUPS:
        path = _group_file(group)
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Não foi possível ler resultados do grupo {group}: {exc}") from exc
        loaded_groups.append(group)
        for score in payload.get("scores", []):
            scores_by_id[score["rule_id"]] = score
        for error in payload.get("errors", []):
            # A ocorrência é identificada por regra, ref, coluna e valor inesperado.
            key = (error.get("rule_id"), error.get("ref"), error.get("column"),
                   error.get("value"), error.get("reason"))
            errors_by_key[key] = error
        for audit in payload.get("metadata", {}).get("gx_results", []):
            audits_by_id[audit.get("rule_id", str(len(audits_by_id)))] = audit
    scores = sorted(scores_by_id.values(), key=lambda row: row.get("rule_id", ""))
    errors = list(errors_by_key.values())
    audits = list(audits_by_id.values())
    return scores, errors, audits, loaded_groups


def validate(group: str | None = None) -> tuple[list[dict], list[dict], dict]:
    """Executa todas as regras ou um grupo e atualiza o resultado consolidado.

    Grupos disponíveis: unicidade, completude e validade. Os resultados de cada
    grupo ficam em results/publication/grupos/ e o relatório normal continua
    sendo gerado pelo runner a partir da consolidação dos grupos já executados.
    """
    if group is not None and group not in GROUPS:
        raise ValueError(f"Grupo inválido: {group!r}. Use um de: {', '.join(GROUPS)}.")

    started = time.perf_counter()
    _log("iniciando validação de publication em grupos")
    with common.connect() as con:
        columns = common.get_columns(con, ENTITY)
        record_count = con.execute(f'SELECT COUNT(*) FROM "{ENTITY}"').fetchone()[0]
    _log(f"view encontrada: {record_count:,} registros; {len(columns)} colunas")
    rules = _build_rules(columns)
    if group is None:
        selected_groups = GROUPS
        selected_rules = rules
    else:
        selected_groups = (group,)
        selected_rules = [rule for rule in rules if rule.dimension == group]

    _log(f"{len(selected_rules)} regras selecionadas; grupo(s): {', '.join(selected_groups)}; lote alvo: {BATCH_ROWS:,}")
    scores, errors, metadata = common.run_quality_checks(
        ENTITY, selected_rules,
        extra_metadata={"record_count": record_count, "batch_rows": BATCH_ROWS,
                   "executed_groups": list(selected_groups)},
    )

    # Em execução completa, substitui os três grupos; em execução parcial,
    # atualiza somente o grupo solicitado e preserva os demais resultados.
    if group is None:
        for current_group in GROUPS:
            group_scores = [row for row in scores if row.get("dimension") == current_group]
            rule_ids = {row["rule_id"] for row in group_scores}
            group_errors = [row for row in errors if row.get("rule_id") in rule_ids]
            group_audits = [row for row in metadata.get("gx_results", []) if row.get("rule_id") in rule_ids]
            _save_group(current_group, group_scores, group_errors, {**metadata, "gx_results": group_audits})
    else:
        _save_group(group, scores, errors, metadata)

    all_scores, all_errors, all_audits, loaded_groups = _load_group_results()
    consolidated_metadata = {
        "entity": ENTITY,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "validation_engine": metadata.get("validation_engine"),
        "gx_result_format": "COMPLETE",
        "gx_results": all_audits,
        "score_formula": metadata.get("score_formula"),
        "record_count": record_count,
        "batch_rows": BATCH_ROWS,
        "groups_available": loaded_groups,
        "groups_missing": [item for item in GROUPS if item not in loaded_groups],
        "partial_report": len(loaded_groups) < len(GROUPS),
    }
    _log(f"grupo(s) concluído(s) em {time.perf_counter() - started:.1f}s; relatório reúne {len(all_scores)} regras de {len(loaded_groups)}/{len(GROUPS)} grupos")
    return all_scores, all_errors, consolidated_metadata
