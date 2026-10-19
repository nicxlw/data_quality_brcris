"""Infraestrutura compartilhada de qualidade de dados (DuckDB + Great Expectations).

Papel deste módulo (padrão "cadoc", sem DORC):
- declaração de regras: dataclass Rule (Expectation do GX + dados preparados);
- execução centralizada: run_quality_checks roda todas as regras com um único
  contexto GX efêmero e recupera TODOS os registros que falharam;
- consolidação: score por regra, médias simples por dimensão e por entidade;
- persistência: CSV/JSON em results/<entidade>/ e reports/<entidade>/report.html.

SQL e Pandas apenas preparam os dados; quem decide o que é erro é a Expectation.
"""
from __future__ import annotations

import csv
import html
import json
import math
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
# TCC_DUCKDB_PATH permite apontar para um banco sintético em verificações locais.
DB_PATH = Path(os.environ["TCC_DUCKDB_PATH"]) if os.environ.get("TCC_DUCKDB_PATH") else ROOT / "data" / "tcc.duckdb"
RESULTS_DIR = ROOT / "results"
REPORTS_DIR = ROOT / "reports"

SCORE_FORMULA = "((element_count - unexpected_count) / element_count) * 100"
# Sentinela para endpoints nulos em validações referenciais: o valor original é
# preservado em record_value e a sentinela faz a Expectation de conjunto falhar.
MISSING_REFERENCE = "__REFERENCIA_AUSENTE__"

ERROR_FIELDS = [
    "rule_id", "validation", "dimension", "entity", "column", "ref",
    "source", "value", "record_value", "reason", "relation_type",
    "fromEntityRef", "toEntityRef", "info",
]


# ------------------------------------------------------------------ DuckDB --
def validate_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(name)):
        raise ValueError(f"Nome de entidade inválido: {name!r}")
    return str(name)


def quote_ident(name: str) -> str:
    """Protege nomes de coluna, inclusive os que contêm pontos."""
    return '"' + str(name).replace('"', '""') + '"'


def connect(read_only: bool = True):
    import duckdb
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Banco DuckDB não encontrado: {DB_PATH}")
    return duckdb.connect(str(DB_PATH), read_only=read_only)


def view_exists(con, name: str) -> bool:
    validate_name(name)
    return con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema='main' AND table_name=?", [name]
    ).fetchone()[0] > 0


def get_columns(con, entity: str) -> list[str]:
    validate_name(entity)
    if not view_exists(con, entity):
        raise ValueError(f"A view {entity!r} não existe no DuckDB.")
    return [row[0] for row in con.execute(f"DESCRIBE SELECT * FROM {quote_ident(entity)}").fetchall()]


# ------------------------------------------------------------ serialização --
def _plain(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if type(value).__name__ in {"NAType", "NaTType"}:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return str(value)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_plain(data), ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows([{k: _plain(row.get(k)) for k in fields} for row in rows])


# ------------------------------------------------- declaração e preparação --
@dataclass
class Rule:
    """Uma regra de qualidade: a Expectation do GX e os dados preparados para ela.

    `data` pode ser um DataFrame ou um callable sem argumentos que o produza.
    O callable é executado pelo engine imediatamente antes da validação, e o
    frame pode ser liberado da memória logo depois — útil em entidades grandes.
    """
    id: str
    dimension: str
    validation: str
    column: str
    description: str
    reason: str
    expectation: Any
    data: Any


def normalize_text(value: Any) -> str | None:
    """Texto vazio ou só com espaços vira None (ausente); demais valores, strip."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text if text else None


def base_rows(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """Uma linha por registro, com `value` normalizado (vazio vira nulo)."""
    rows = pd.DataFrame({
        "__dq_row_id": range(len(df)),
        "ref": df["ref"] if "ref" in df.columns else None,
        "source": df["source"] if "source" in df.columns else None,
        "record_value": df[column],
    })
    rows["value"] = rows["record_value"].map(normalize_text)
    return rows


def split_tokens(df: pd.DataFrame, column: str, separator: str = "|") -> pd.DataFrame:
    """Uma linha por identificador: campos repetidos vêm concatenados com '|'.

    Preserva ref/source/record_value para rastrear a pessoa de origem. Registros
    sem valor não entram (ausência é medida pela regra de completude, não aqui).
    """
    rows = []
    refs = df["ref"] if "ref" in df.columns else [None] * len(df)
    sources = df["source"] if "source" in df.columns else [None] * len(df)
    for ref, source, original in zip(refs, sources, df[column]):
        if normalize_text(original) is None:
            continue
        for token in str(original).split(separator):
            token = token.strip()
            if token:
                rows.append({
                    "__dq_row_id": len(rows), "ref": ref, "source": source,
                    "record_value": original, "value": token,
                })
    return pd.DataFrame(rows, columns=["__dq_row_id", "ref", "source", "record_value", "value"])


def relation_rows(relations: pd.DataFrame, side: str) -> pd.DataFrame:
    """Frame para validar se o endpoint `side` das relações pertence a um conjunto válido.

    Endpoint nulo vira a sentinela MISSING_REFERENCE para a Expectation de
    conjunto falhar; o valor original permanece em record_value e nos endpoints.
    """
    columns = ["__dq_row_id", "ref", "source", "value", "record_value",
               "relation_type", "fromEntityRef", "toEntityRef", "info"]
    if relations.empty:
        return pd.DataFrame(columns=columns)
    rows = pd.DataFrame({
        "__dq_row_id": range(len(relations)),
        "ref": relations[side],
        "source": relations["source"] if "source" in relations.columns else None,
        "record_value": relations[side],
        "relation_type": relations["type"],
        "fromEntityRef": relations["fromEntityRef"] if "fromEntityRef" in relations.columns else None,
        "toEntityRef": relations["toEntityRef"] if "toEntityRef" in relations.columns else None,
        "info": relations["info"] if "info" in relations.columns else None,
    })
    normalized = rows["record_value"].map(normalize_text)
    rows["value"] = normalized.where(normalized.notna(), MISSING_REFERENCE)
    return rows


# ------------------------------------------------------------------ engine --
def run_quality_checks(entity: str, rules: list[Rule], *,
                       extra_metadata: dict[str, Any] | None = None
                       ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Executa todas as regras de uma entidade com um único contexto GX efêmero.

    Regra que quebra por incompatibilidade de schema, configuração ou API vira
    status ERRO TÉCNICO com score indefinido — nunca é contada como aprovada
    nem derruba as demais regras.
    """
    entity = validate_name(entity)
    import great_expectations as gx
    context = gx.get_context(mode="ephemeral")
    datasource = context.data_sources.add_pandas(name="brcris_quality")

    scores, errors, audits = [], [], []
    for rule in rules:
        try:
            frame = rule.data() if callable(rule.data) else rule.data
            score, rule_errors, audit = run_expectation(datasource, frame, rule, entity=entity)
        except Exception as exc:
            score = score_record(rule.id, rule.validation, rule.dimension, rule.column,
                                 rule.description, 0, 0,
                                 technical_error=f"{type(exc).__name__}: {exc}")
            rule_errors = []
            audit = {"rule_id": rule.id, "expectation": type(rule.expectation).__name__,
                     "technical_error": f"{type(exc).__name__}: {exc}"}
        scores.append(score)
        errors.extend(rule_errors)
        audits.append(audit)

    metadata = {
        "entity": entity,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "validation_engine": f"Great Expectations {gx.__version__}",
        "gx_result_format": "COMPLETE",
        "gx_results": audits,
        "score_formula": SCORE_FORMULA,
        **(extra_metadata or {}),
    }
    return scores, errors, metadata


def run_expectation(datasource, dataframe: pd.DataFrame, rule: Rule, *, entity: str
                    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Executa a Expectation de uma regra e recupera todas as linhas que o GX marcou."""
    started = time.perf_counter()
    df = dataframe.reset_index(drop=True).copy()
    if "__dq_row_id" not in df.columns:
        df.insert(0, "__dq_row_id", range(len(df)))
    if df["__dq_row_id"].duplicated().any():
        raise ValueError("__dq_row_id precisa ser único.")

    asset_name = re.sub(r"[^A-Za-z0-9_]", "_", f"asset_{entity}_{rule.id}")
    asset = datasource.add_dataframe_asset(name=asset_name)
    batch = asset.add_batch_definition_whole_dataframe("all_rows").get_batch(
        batch_parameters={"dataframe": df}
    )
    result = batch.validate(
        rule.expectation,
        result_format={
            "result_format": "COMPLETE",
            "unexpected_index_column_names": ["__dq_row_id"],
            "exclude_unexpected_values": True,
        },
    )
    details = result.result or {}
    total = int(details.get("element_count") or 0)
    bad_count = int(details.get("unexpected_count") or 0)
    bad_rows = _unexpected_rows(df, details, bad_count, rule.id)

    score = score_record(rule.id, rule.validation, rule.dimension, rule.column,
                         rule.description, total, bad_count, time.perf_counter() - started)
    audit = {
        "rule_id": rule.id,
        "expectation": type(rule.expectation).__name__,
        "success": bool(result.success),
        "element_count": total,
        "unexpected_count": bad_count,
        "result_format": "COMPLETE",
    }
    errors = [_error_record(rule, entity, row) for row in bad_rows]
    return score, errors, audit


def _unexpected_row_ids(details: dict[str, Any]) -> list[Any]:
    """Lê os identificadores de linha inesperada do resultado COMPLETE do GX.

    O formato varia por Expectation: pode vir um escalar por item
    ({"__dq_row_id": 3}) ou um único item com a lista completa de valores
    ({"__dq_row_id": ["0", "2"]}), como no ExpectColumnValuesToBeUnique.
    """
    row_ids = []
    for item in details.get("unexpected_index_list") or []:
        if isinstance(item, dict):
            value = item.get("__dq_row_id")
            if value is None and len(item) == 1:
                value = next(iter(item.values()))
        else:
            value = item
        if isinstance(value, (list, tuple)):
            row_ids.extend(v for v in value if v is not None)
        elif value is not None:
            row_ids.append(value)
    return row_ids


def _unexpected_rows(df: pd.DataFrame, details: dict[str, Any], bad_count: int, rule_id: str) -> list[dict[str, Any]]:
    """Recupera as linhas completas a partir dos índices que o GX apontou.

    Se a API não devolver os índices necessários, falha explicitamente em vez
    de exportar uma contagem de erros sem os registros correspondentes.
    """
    if not bad_count:
        return []
    wanted = {str(value) for value in _unexpected_row_ids(details)}
    bad_rows = df[df["__dq_row_id"].map(str).isin(wanted)].to_dict("records")
    if len(bad_rows) != bad_count:
        raise RuntimeError(
            f"GX informou {bad_count} falhas em {rule_id}, mas só foi possível recuperar "
            f"{len(bad_rows)} linhas. Confira o result_format COMPLETE."
        )
    return bad_rows


def _error_record(rule: Rule, entity: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": rule.id, "validation": rule.validation, "dimension": rule.dimension,
        "entity": entity, "column": rule.column,
        "ref": row.get("ref"),
        "source": row.get("source"),
        "value": row.get("value"),
        "record_value": row.get("record_value"), "reason": rule.reason,
        "relation_type": row.get("relation_type"),
        "fromEntityRef": row.get("fromEntityRef"),
        "toEntityRef": row.get("toEntityRef"), "info": row.get("info"),
    }


# ------------------------------------------------------------------ scores --
def score_record(rule_id: str, validation: str, dimension: str, column: str,
                 description: str, element_count: int, unexpected_count: int,
                 seconds: float = 0, technical_error: str = "") -> dict[str, Any]:
    # Fórmula definida para o projeto. Para zero elementos, o score é indefinido.
    score = ((element_count - unexpected_count) / element_count * 100) if element_count else None
    status = "ERRO TÉCNICO" if technical_error else (
        "SEM DADOS" if not element_count else "APROVADA" if not unexpected_count else "FALHOU"
    )
    return {
        "rule_id": rule_id, "validation": validation, "dimension": dimension,
        "column": column, "description": description, "evaluated": element_count,
        "failures": unexpected_count, "score_pct": round(score, 3) if score is not None else None,
        "status": status, "duration_seconds": round(seconds, 2),
        "technical_error": technical_error,
    }


def average_scores(scores: list[dict[str, Any]]) -> tuple[float | None, list[dict[str, Any]]]:
    """Média simples das regras com score definido, por entidade e por dimensão."""
    valid = [s for s in scores if s.get("score_pct") is not None and s.get("status") != "ERRO TÉCNICO"]
    entity_score = sum(s["score_pct"] for s in valid) / len(valid) if valid else None
    grouped: dict[str, list[float]] = {}
    for row in valid:
        grouped.setdefault(row["dimension"], []).append(row["score_pct"])
    dimensions = [
        {"dimension": name, "score_pct": round(sum(values) / len(values), 3), "rules": len(values)}
        for name, values in sorted(grouped.items())
    ]
    return (round(entity_score, 3) if entity_score is not None else None), dimensions


# ------------------------------------------------------------- persistência --
def save_validation_results(entity: str, scores: list[dict[str, Any]], errors: list[dict[str, Any]],
                            metadata: dict[str, Any]) -> dict[str, Path]:
    out = RESULTS_DIR / entity
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "scores_csv": out / "scores.csv", "scores_json": out / "scores.json",
        "errors_csv": out / "errors.csv", "errors_json": out / "errors.json",
        "summary_json": out / "validation_summary.json", "gx_results_json": out / "gx_results.json",
    }
    score_fields = list(scores[0].keys()) if scores else [
        "rule_id", "validation", "dimension", "column", "description", "evaluated",
        "failures", "score_pct", "status", "duration_seconds", "technical_error",
    ]
    write_csv(paths["scores_csv"], scores, score_fields)
    write_json(paths["scores_json"], scores)
    write_csv(paths["errors_csv"], errors, ERROR_FIELDS)
    write_json(paths["errors_json"], errors)
    write_json(paths["gx_results_json"], metadata.get("gx_results", []))
    entity_score, dimension_scores = average_scores(scores)
    valid_rules = [s for s in scores if s.get("score_pct") is not None and s.get("status") != "ERRO TÉCNICO"]
    summary = {
        "entity": entity, "generated_at": datetime.now().isoformat(timespec="seconds"),
        "record_count": metadata.get("record_count"), "entity_score_pct": entity_score,
        "dimension_scores": dimension_scores, "rules_count": len(scores),
        "rules_without_score": len(scores) - len(valid_rules),
        "technical_errors": sum(1 for s in scores if s.get("status") == "ERRO TÉCNICO"),
        "error_occurrences": len(errors),
        "score_formula": SCORE_FORMULA,
        "aggregation": "média simples das regras com score definido",
    }
    write_json(paths["summary_json"], summary)
    paths["report_html"] = build_validation_report(entity, scores, errors, summary)
    if entity == "person":
        _remove_empty_legacy_person_dirs()
    return paths


def _remove_empty_legacy_person_dirs() -> None:
    """Remove empty plural output directories left by older runs."""
    for directory in (RESULTS_DIR / "persons", REPORTS_DIR / "persons"):
        if directory.is_dir() and next(directory.iterdir(), None) is None:
            directory.rmdir()


def _example_text(error: dict[str, Any]) -> str:
    """Mostra no HTML o valor avaliado; ref continua disponível nos CSV/JSON."""
    value = error.get("value")
    record_value = error.get("record_value")
    if value == MISSING_REFERENCE and (record_value is None or not str(record_value).strip()):
        return "(referência vazia)"
    if value is not None:
        return str(value) if str(value).strip() else "(vazio)"
    if record_value is not None and str(record_value).strip():
        return f"(item vazio; valor original: {record_value})"
    return str(error.get("ref") or error.get("reason") or "(vazio)")


def build_validation_report(entity: str, scores: list[dict[str, Any]], errors: list[dict[str, Any]], summary: dict[str, Any]) -> Path:
    """Gera relatório HTML simples, com score por regra/dimensão/entidade e exemplos."""
    entity_score = summary.get("entity_score_pct")
    entity_text = "N/D" if entity_score is None else f"{entity_score:.2f}%"
    dim_rows = "".join(
        f"<tr><td>{html.escape(d['dimension'])}</td><td>{d['score_pct']:.2f}%</td><td>{d['rules']}</td></tr>"
        for d in summary.get("dimension_scores", [])
    ) or "<tr><td colspan='3'>Sem scores disponíveis</td></tr>"

    error_by_rule: dict[str, list[dict[str, Any]]] = {}
    for error in errors:
        error_by_rule.setdefault(error["rule_id"], []).append(error)

    rule_rows = []
    for score in scores:
        # O HTML mostra no máximo 5 exemplos; os arquivos CSV/JSON têm todos.
        examples = error_by_rule.get(score["rule_id"], [])[:5]
        example_html = "<br>".join(html.escape(_example_text(e)) for e in examples)
        if score.get("technical_error"):
            example_html = f"<span class='err'>{html.escape(score['technical_error'])}</span>"
        pct = score.get("score_pct")
        cells = [
            html.escape(str(score.get("rule_id") or "")),
            html.escape(str(score.get("dimension") or "")),
            html.escape(str(score.get("description") or "")),
            "N/D" if pct is None else f"{pct:.2f}%",
            str(score.get("evaluated", 0)),
            str(score.get("failures", 0)),
            html.escape(str(score.get("status") or "")),
            example_html,
        ]
        rule_rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")

    without_score = summary.get("rules_without_score", 0)
    note = f" {without_score} regra(s) sem avaliação (SEM DADOS ou ERRO TÉCNICO) ficaram fora da média." if without_score else ""
    page = f"""<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Qualidade — {html.escape(entity)}</title><style>
body{{font-family:Arial,sans-serif;max-width:1200px;margin:32px auto;padding:0 18px;color:#202938}}table{{border-collapse:collapse;width:100%;margin:16px 0}}th,td{{border-bottom:1px solid #ddd;padding:9px;text-align:left;vertical-align:top}}th{{background:#f1f4f8}}.score{{font-size:2rem;font-weight:bold}}.muted{{color:#687386}}.err{{color:#b3261e}}
</style></head><body><h1>Qualidade dos dados: {html.escape(entity)}</h1>
<p class='muted'>Gerado em {datetime.now():%d/%m/%Y %H:%M}. Score = ((element_count - unexpected_count) / element_count) × 100.{html.escape(note)}</p>
<h2>Score da entidade</h2><div class='score'>{entity_text}</div>
<h2>Score por dimensão</h2><table><thead><tr><th>Dimensão</th><th>Score médio</th><th>Regras na média</th></tr></thead><tbody>{dim_rows}</tbody></table>
<h2>Detalhes por validação</h2><table><thead><tr><th>Regra</th><th>Dimensão</th><th>Descrição</th><th>Score</th><th>Avaliados</th><th>Falhas</th><th>Status</th><th>Exemplos (máx. 5)</th></tr></thead><tbody>{''.join(rule_rows)}</tbody></table>
<p class='muted'>Todas as ocorrências estão nos arquivos errors.csv e errors.json.</p></body></html>"""
    path = REPORTS_DIR / entity / "report.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path


def build_global_quality_summary() -> dict[str, Path]:
    """Resume médias simples a partir dos scores salvos por entidade."""
    rows = []
    for file in sorted(RESULTS_DIR.glob("*/scores.json")):
        try:
            scores = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entity_score, dimensions = average_scores(scores)
        rows.append({"entity": file.parent.name, "score_pct": entity_score, "dimensions": dimensions})
    result = {"generated_at": datetime.now().isoformat(timespec="seconds"), "entities": rows}
    json_path = RESULTS_DIR / "quality_summary.json"
    write_json(json_path, result)
    body_rows = []
    for row in rows:
        pct = row["score_pct"]
        pct_text = "N/D" if pct is None else f"{pct:.2f}%"
        body_rows.append(f"<tr><td>{html.escape(row['entity'])}</td><td>{pct_text}</td></tr>")
    report_path = REPORTS_DIR / "quality_summary.html"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "<!doctype html><html lang='pt-BR'><meta charset='utf-8'><title>Resumo da qualidade</title>"
        f"<h1>Scores por entidade</h1><table><tr><th>Entidade</th><th>Score médio</th></tr>{''.join(body_rows)}</table></html>",
        encoding="utf-8",
    )
    return {"summary_json": json_path, "report_html": report_path}
