"""Análise exploratória genérica para qualquer view/dataset do DuckDB.

Uso: python run.py explore person
Colunas categóricas configuráveis em config/exploration.yaml.
"""
from __future__ import annotations

import csv
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from quality import common

CONFIG_PATH = common.ROOT / "config" / "exploration.yaml"


def load_exploration_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {"datasets": {}}
    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    datasets = data.get("datasets", data)
    return {"datasets": datasets if isinstance(datasets, dict) else {}}


def _query_profile(con, entity: str, columns: list[str]) -> tuple[int, list[dict[str, Any]]]:
    qtable = common.quote_ident(entity)
    row_count = int(con.execute(f"SELECT COUNT(*) FROM {qtable}").fetchone()[0])
    if not columns:
        return row_count, []

    expressions = []
    aliases: list[tuple[str, str]] = []
    for idx, column in enumerate(columns):
        qcol = common.quote_ident(column)
        filled_alias = f"filled_{idx}"
        distinct_alias = f"distinct_{idx}"
        expressions.append(
            f"COUNT(*) FILTER (WHERE NULLIF(TRIM(CAST({qcol} AS VARCHAR)), '') IS NOT NULL) AS {common.quote_ident(filled_alias)}"
        )
        expressions.append(
            f"COUNT(DISTINCT NULLIF(TRIM(CAST({qcol} AS VARCHAR)), '')) AS {common.quote_ident(distinct_alias)}"
        )
        aliases.append((filled_alias, distinct_alias))

    metrics = con.execute(f"SELECT {', '.join(expressions)} FROM {qtable}").fetchone()
    profiles: list[dict[str, Any]] = []
    for idx, column in enumerate(columns):
        filled_alias, distinct_alias = aliases[idx]
        filled = int(metrics[idx * 2] or 0)
        distinct = int(metrics[idx * 2 + 1] or 0)
        completeness = round(filled * 100.0 / row_count, 3) if row_count else None
        profiles.append({
            "column": column,
            "filled": filled,
            "missing": row_count - filled,
            "completeness_pct": completeness,
            "distinct_values": distinct,
        })
    profiles.sort(key=lambda item: (
        item["completeness_pct"] is not None,
        item["completeness_pct"] if item["completeness_pct"] is not None else -1,
        item["column"].lower(),
    ))
    return row_count, profiles


def _category_distribution(con, entity: str, column: str, limit: int = 10) -> dict[str, Any]:
    qtable = common.quote_ident(entity)
    qcol = common.quote_ident(column)
    from_sql = (
        f"FROM {qtable} AS t, "
        f"UNNEST(string_split(CAST(t.{qcol} AS VARCHAR), '|')) AS u(category) "
        f"WHERE t.{qcol} IS NOT NULL AND TRIM(u.category) <> ''"
    )
    total = int(con.execute(f"SELECT COUNT(*) {from_sql}").fetchone()[0])
    distinct = int(con.execute(f"SELECT COUNT(DISTINCT TRIM(u.category)) {from_sql}").fetchone()[0])
    top = con.execute(
        f"SELECT TRIM(u.category) AS category, COUNT(*) AS occurrences {from_sql} "
        "GROUP BY TRIM(u.category) ORDER BY occurrences DESC, category ASC LIMIT ?",
        [limit],
    ).fetchall()
    entries = [{"value": str(value), "count": int(count)} for value, count in top]
    top_total = sum(x["count"] for x in entries)
    other_count = max(0, total - top_total)
    if other_count:
        entries.append({"value": "Outras", "count": other_count, "is_other": True})
    for item in entries:
        item["pct"] = round(item["count"] * 100.0 / total, 3) if total else 0.0
    return {
        "column": column,
        "total_values": total,
        "distinct_categories": distinct,
        "entries": entries,
    }


def _chart_bar_rows(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "<p class='muted'>Não há valores preenchidos para esta coluna.</p>"
    max_count = max((int(entry["count"]) for entry in entries), default=0) or 1
    rows = []
    for entry in entries:
        width = max(0, min(100, float(entry["count"]) * 100.0 / max_count))
        raw_name = str(entry["value"])
        label = html.escape(raw_name if len(raw_name) <= 95 else raw_name[:92] + "…")
        rows.append(
            "<div class='category-row'>"
            f"<div class='category-label' title='{html.escape(raw_name, quote=True)}'>{label}</div>"
            f"<div class='category-track'><span style='width:{width:.2f}%'></span></div>"
            f"<div class='category-count'>{int(entry['count']):,} <small>({float(entry['pct']):.1f}%)</small></div>"
            "</div>"
        )
    return "".join(rows)


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def generate_report(entity: str) -> dict[str, Path]:
    """Profile the complete view and write CSV/JSON statistics and HTML report."""
    entity = common.validate_name(entity)
    with common.connect(read_only=True) as con:
        if not common.view_exists(con, entity):
            raise RuntimeError(
                f"A view {entity!r} não existe no DuckDB. Extraia a classe ou atualize a view antes de explorar."
            )
        columns = common.get_columns(con, entity)
        row_count, profiles = _query_profile(con, entity, columns)
        cfg = load_exploration_config()
        dataset_cfg = cfg.get("datasets", {}).get(entity, {}) or {}
        categorical = dataset_cfg.get("categorical_columns", []) or []
        categorical = list(dict.fromkeys(str(col) for col in categorical))
        missing_configured = [col for col in categorical if col not in columns]
        available_categorical = [col for col in categorical if col in columns]
        categories = [_category_distribution(con, entity, col) for col in available_categorical]

    complete_values = [item["completeness_pct"] for item in profiles if item["completeness_pct"] is not None]
    avg_completeness = round(sum(complete_values) / len(complete_values), 3) if complete_values else None
    empty_columns = [item["column"] for item in profiles if item["filled"] == 0]
    timestamp = datetime.now().isoformat(timespec="seconds")
    profile_json = {
        "entity": entity,
        "generated_at": timestamp,
        "row_count": row_count,
        "column_count": len(columns),
        "average_column_completeness_pct": avg_completeness,
        "all_null_columns": empty_columns,
        "categorical_columns_configured": categorical,
        "categorical_columns_missing_from_dataset": missing_configured,
        "columns": profiles,
        "categories": categories,
    }

    results_dir = common.RESULTS_DIR / "exploration" / entity
    reports_dir = common.REPORTS_DIR / "exploration"
    results_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    profile_csv = results_dir / "profile.csv"
    profile_json_path = results_dir / "profile.json"
    category_csv = results_dir / "category_counts.csv"
    html_path = reports_dir / f"{entity}.html"

    _write_csv(profile_csv, profiles, ["column", "filled", "missing", "completeness_pct", "distinct_values"])
    common.write_json(profile_json_path, profile_json)
    category_rows: list[dict[str, Any]] = []
    for category in categories:
        for entry in category["entries"]:
            category_rows.append({
                "column": category["column"],
                "value": entry["value"],
                "count": entry["count"],
                "pct_of_value_occurrences": entry["pct"],
                "is_other": bool(entry.get("is_other", False)),
            })
    _write_csv(category_csv, category_rows, ["column", "value", "count", "pct_of_value_occurrences", "is_other"])

    completeness_rows = []
    for item in profiles:
        pct = item["completeness_pct"]
        width = 0 if pct is None else max(0, min(100, float(pct)))
        pct_label = "n/d" if pct is None else f"{pct:.1f}%"
        column_label = html.escape(item["column"])
        color = "#17875d" if pct is not None and pct >= 90 else "#c18a2a" if pct is not None and pct >= 60 else "#c04b43"
        completeness_rows.append(
            "<tr>"
            f"<td><code>{column_label}</code></td><td>{item['filled']:,}</td><td>{item['missing']:,}</td>"
            f"<td><div class='bar'><span style='width:{width}%;background:{color}'></span></div><b style='color:{color}'>{pct_label}</b></td>"
            f"<td>{item['distinct_values']:,}</td></tr>"
        )

    category_sections = []
    for category in categories:
        column = category["column"]
        distribution_note = (
            "<p class='muted note'>Distribuição calculada sobre os valores individuais; células com valores separados por '|' são divididas em categorias. Exibidas até 10 categorias e o agregado 'Outras'.</p>"
            if category["total_values"] > 0 else ""
        )
        category_sections.append(
            "<section class='category-card'>"
            f"<h3>{html.escape(column)}</h3>"
            f"<p class='muted'>{category['total_values']:,} ocorrências de valores · {category['distinct_categories']:,} categorias distintas</p>"
            f"{_chart_bar_rows(category['entries'])}"
            f"{distribution_note}"
            "</section>"
        )

    warnings = []
    if empty_columns:
        warnings.append("Colunas sem nenhum valor: " + ", ".join(empty_columns))
    if missing_configured:
        warnings.append("Colunas categóricas configuradas, mas não encontradas no dataset: " + ", ".join(missing_configured))
    warnings_html = "".join(f"<li>{html.escape(warning)}</li>" for warning in warnings)
    warning_section = f"<div class='warning'><strong>Atenção aos dados</strong><ul>{warnings_html}</ul></div>" if warnings else ""
    mean_text = "n/d" if avg_completeness is None else f"{avg_completeness:.1f}%"
    categories_section = "".join(category_sections) if category_sections else "<p class='muted'>Nenhuma coluna categórica foi configurada para este dataset. Edite config/exploration.yaml para incluir as colunas desejadas.</p>"

    page = f"""<!doctype html>
<html lang='pt-BR'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Análise exploratória — {html.escape(entity)}</title>
<style>
:root{{--ink:#172033;--muted:#64748b;--line:#e2e8f0;--paper:#f8fafc;--navy:#315a7d;--bar:#6488a8}}
*{{box-sizing:border-box}}body{{font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;max-width:1300px;margin:0 auto;padding:28px;color:var(--ink);background:#fff}}
h1{{font-size:2rem;margin-bottom:.25rem}}h2{{margin-top:2.2rem;font-size:1.35rem}}h3{{margin:.2rem 0 .4rem;font-size:1.05rem}}.muted{{color:var(--muted);font-size:.9rem}}.subtitle{{margin-top:0;color:var(--muted)}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:24px 0}}.card{{border:1px solid var(--line);border-radius:14px;padding:18px;background:var(--paper)}}.label{{font-size:.86rem;color:var(--muted)}}.value{{font-size:1.8rem;font-weight:750;margin-top:5px}}
table{{border-collapse:collapse;width:100%;font-size:.9rem}}th,td{{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}}th{{background:var(--paper);position:sticky;top:0}}tr:hover td{{background:#fbfdff}}.table-scroll{{overflow-x:auto}}.bar{{height:9px;width:145px;max-width:100%;border-radius:100px;background:#e8edf2;overflow:hidden;margin:0 0 5px}}.bar span{{display:block;height:100%;border-radius:100px}}
.category-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,510px),1fr));gap:14px;margin-top:15px}}.category-card{{border:1px solid var(--line);border-radius:14px;padding:16px;min-width:0}}.category-row{{display:grid;grid-template-columns:minmax(100px,1.25fr) minmax(80px,2fr) minmax(105px,.8fr);gap:10px;align-items:center;margin:12px 0}}.category-label{{font-size:.86rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.category-track{{background:#edf2f7;height:10px;border-radius:50px;overflow:hidden}}.category-track span{{display:block;height:100%;background:var(--bar);border-radius:50px}}.category-count{{font-size:.82rem;text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}.category-count small{{color:var(--muted)}}.warning{{margin:20px 0;padding:12px 16px;border-left:4px solid #d99b35;background:#fff9e9;border-radius:8px}}.warning ul{{margin-bottom:0}}.note{{font-size:.8rem;margin-top:14px}}code{{background:#f1f5f9;padding:2px 5px;border-radius:4px;overflow-wrap:anywhere}}footer{{margin-top:32px;border-top:1px solid var(--line);padding-top:12px;color:var(--muted);font-size:.82rem}}
</style></head><body>
<h1>Análise exploratória — {html.escape(entity)}</h1>
<p class='subtitle'>Perfil da classe gerado em {datetime.now():%d/%m/%Y às %H:%M}. Este relatório descreve os dados disponíveis; não representa, por si só, aprovação nas regras de qualidade.</p>
<div class='cards'>
 <div class='card'><div class='label'>Total de registros</div><div class='value'>{row_count:,}</div></div>
 <div class='card'><div class='label'>Colunas disponíveis</div><div class='value'>{len(columns):,}</div></div>
 <div class='card'><div class='label'>Completude média por coluna</div><div class='value'>{mean_text}</div></div>
 <div class='card'><div class='label'>Colunas 100% vazias</div><div class='value'>{len(empty_columns):,}</div></div>
</div>
{warning_section}
<h2>Completude e diversidade por coluna</h2>
<p class='muted'>Completude = registros com valor não nulo/não vazio dividido pelo total de registros. Valores distintos são contados após trim; células com valores multivalorados continuam sendo uma única string nesta tabela.</p>
<div class='table-scroll'><table><thead><tr><th>Coluna</th><th>Preenchidos</th><th>Ausentes</th><th>Completude</th><th>Valores distintos</th></tr></thead><tbody>
{''.join(completeness_rows)}
</tbody></table></div>
<h2>Distribuição de variáveis categóricas</h2>
<p class='muted'>As categorias são configuradas em config/exploration.yaml. Para facilitar a apresentação, cada gráfico mostra no máximo as 10 categorias mais frequentes e agrupa as demais em “Outras”.</p>
<div class='category-grid'>{categories_section}</div>
<footer>Saídas técnicas: results/exploration/{html.escape(entity)}/profile.csv, profile.json e category_counts.csv.</footer>
</body></html>"""
    html_path.write_text(page, encoding="utf-8")
    return {
        "html": html_path,
        "profile_csv": profile_csv,
        "profile_json": profile_json_path,
        "category_counts_csv": category_csv,
    }
