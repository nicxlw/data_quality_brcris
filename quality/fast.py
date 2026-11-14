"""Validação de publication e relation: SQL dentro do DuckDB (chamado por run.py).

As duas tabelas têm milhões de linhas; por isso as regras rodam em SQL, sem passar
pelo Pandas. Os erros completos ficam em results/<entidade>/errors/<REGRA>.parquet."""
from __future__ import annotations

import re
import shutil
import time
from datetime import datetime

import pandas as pd

from quality import checks, common

WS = " \t\n\r\f\v\u00a0"
EXAMPLES_PER_RULE = 1000
SAMPLE_SEED = 417


def log(entity, message):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [{entity}] {message}", flush=True)


def q(text):
    return "'" + str(text).replace("'", "''") + "'"


def ident(name):
    return common.quote_ident(name)


def norm(expr):
    return f"NULLIF(trim(CAST({expr} AS VARCHAR), {q(WS)}), '')"


def select_errors(entity, meta, ref="NULL", source="NULL", value="NULL", record_value="NULL",
                  relation_type="NULL", from_ref="NULL", to_ref="NULL", info="NULL"):
    cast = lambda e: f"CAST({e} AS VARCHAR)"
    return (
        f"SELECT {q(meta['id'])} AS rule_id, {q(meta['validation'])} AS validation, "
        f"{q(meta['dimension'])} AS dimension, {q(entity)} AS entity, {q(meta['column'])} AS \"column\", "
        f"{cast(ref)} AS ref, {cast(source)} AS source, {cast(value)} AS value, "
        f"{cast(record_value)} AS record_value, {q(meta['reason'])} AS reason, "
        f"{cast(relation_type)} AS relation_type, {cast(from_ref)} AS \"fromEntityRef\", "
        f"{cast(to_ref)} AS \"toEntityRef\", {cast(info)} AS info"
    )


class Engine:
    def __init__(self, entity, view, sample_size=None, memory_limit=None):
        self.entity, self.view, self.sample_size = entity, view, sample_size
        self.out = common.RESULTS_DIR / entity
        self.err_dir = self.out / "errors"
        if self.err_dir.exists():
            shutil.rmtree(self.err_dir)
        self.err_dir.mkdir(parents=True, exist_ok=True)

        self.con = common.connect(read_only=True)
        tmp = common.ROOT / "data" / "duckdb_tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        self.con.execute(f"SET temp_directory={q(tmp.as_posix())}")
        self.con.execute("SET preserve_insertion_order=false")
        if memory_limit:
            self.con.execute(f"SET memory_limit={q(memory_limit)}")

        self.total_rows = self.con.execute(f"SELECT count(*) FROM {ident(view)}").fetchone()[0]
        if sample_size:
            self.con.execute(
                f"CREATE TEMP TABLE src AS SELECT * FROM {ident(view)} "
                f"USING SAMPLE reservoir({int(sample_size)} ROWS) REPEATABLE ({SAMPLE_SEED})")
            self.src = "src"
            self.rows = self.con.execute("SELECT count(*) FROM src").fetchone()[0]
        else:
            self.src = ident(view)
            self.rows = self.total_rows
        self.scores, self.examples, self.total_failures = [], [], 0

    def run(self, meta, build):
        t0 = time.perf_counter()
        log(self.entity, f"{meta['id']} — iniciando")
        path = self.err_dir / f"{meta['id']}.parquet"
        try:
            evaluated, bad_sql = build()
            if isinstance(evaluated, str):
                evaluated = self.con.execute(evaluated).fetchone()[0]
            evaluated = int(evaluated or 0)
            self.con.execute(f"COPY ({bad_sql}) TO {q(path.as_posix())} (FORMAT PARQUET, COMPRESSION ZSTD)")
            reader = f"read_parquet({q(path.as_posix())})"
            failures = int(self.con.execute(f"SELECT count(*) FROM {reader}").fetchone()[0])
            if failures:
                cur = self.con.execute(f"SELECT * FROM {reader} LIMIT {EXAMPLES_PER_RULE}")
                cols = [d[0] for d in cur.description]
                self.examples.extend(dict(zip(cols, row)) for row in cur.fetchall())
            else:
                path.unlink(missing_ok=True)
            score = common.score_record(meta["id"], meta["validation"], meta["dimension"], meta["column"],
                                        meta["description"], evaluated, failures, time.perf_counter() - t0)
            self.total_failures += failures
        except Exception as exc:   # regra com problema vira ERRO TÉCNICO, nunca "aprovada"
            path.unlink(missing_ok=True)
            score = common.score_record(meta["id"], meta["validation"], meta["dimension"], meta["column"],
                                        meta["description"], 0, 0, time.perf_counter() - t0,
                                        technical_error=f"{type(exc).__name__}: {exc}")
        self.scores.append(score)
        log(self.entity, f"{meta['id']} finalizada em {time.perf_counter() - t0:.1f}s; "
                         f"avaliados={score['evaluated']:,}; falhas={score['failures']:,}; status={score['status']}")

    def save(self, extra):
        self.out.mkdir(parents=True, exist_ok=True)
        paths = {"scores_csv": self.out / "scores.csv", "scores_json": self.out / "scores.json",
                 "summary_json": self.out / "validation_summary.json",
                 "errors_sample_csv": self.out / "errors_sample.csv", "errors_dir": self.err_dir}
        common.write_csv(paths["scores_csv"], self.scores, list(self.scores[0].keys()))
        common.write_json(paths["scores_json"], self.scores)
        common.write_csv(paths["errors_sample_csv"], self.examples, common.ERROR_FIELDS)
        entity_score, dimension_scores = common.average_scores(self.scores)
        valid = [s for s in self.scores if s.get("score_pct") is not None and s.get("status") != "ERRO TÉCNICO"]
        summary = {
            "entity": self.entity, "generated_at": datetime.now().isoformat(timespec="seconds"),
            "record_count": self.total_rows, "entity_score_pct": entity_score,
            "sample_size": self.sample_size, "sampled_records": self.rows,
            "dimension_scores": dimension_scores, "rules_count": len(self.scores),
            "rules_without_score": len(self.scores) - len(valid),
            "technical_errors": sum(1 for s in self.scores if s.get("status") == "ERRO TÉCNICO"),
            "error_occurrences": self.total_failures, "score_formula": common.SCORE_FORMULA,
            "aggregation": "média simples das regras com score definido",
            "validation_engine": "SQL no DuckDB (regras equivalentes às Expectations do Great Expectations)",
            "errors_note": ("Todas as ocorrências estão em results/%s/errors/<REGRA>.parquet; "
                            "errors_sample.csv traz até %d exemplos por regra." % (self.entity, EXAMPLES_PER_RULE)),
            **extra,
        }
        common.write_json(paths["summary_json"], summary)
        by_rule = {}
        for row in self.examples:
            by_rule.setdefault(row["rule_id"], []).append(row)
        html_examples = [r for rows in by_rule.values() for r in rows[:5]]
        paths["report_html"] = common.build_validation_report(self.entity, self.scores, html_examples, summary)
        common.build_global_quality_summary()
        return paths


# ============================ PUBLICATION ============================
def _col(columns, name, alias=""):
    return f"{alias}{ident(name)}" if name in columns else "NULL"


def _plan_singular(eng, meta, columns, column):
    """Singularidade: o campo não pode conter '|' (mais de um valor no mesmo registro)."""
    c = ident(column)
    nonempty = f"{c} IS NOT NULL AND trim(CAST({c} AS VARCHAR)) <> ''"
    bad = (select_errors(eng.entity, meta, ref=_col(columns, "ref"), source=_col(columns, "source"),
                         value=f"trim(CAST({c} AS VARCHAR))", record_value=c)
           + f" FROM {eng.src} WHERE {nonempty} AND position('|' IN CAST({c} AS VARCHAR)) > 0")
    return f"SELECT count(*) FROM {eng.src} WHERE {nonempty}", bad


def _plan_unique(eng, meta, column, split):
    c = ident(column)
    if split:
        base = (f'SELECT s."ref" AS r, s."source" AS sc, CAST(s.{c} AS VARCHAR) AS rv, trim(tok.value) AS v '
                f"FROM {eng.src} AS s, UNNEST(string_split(CAST(s.{c} AS VARCHAR), '|')) AS tok(value) "
                f"WHERE s.{c} IS NOT NULL AND trim(tok.value) <> ''")
    else:
        base = (f'SELECT s."ref" AS r, s."source" AS sc, CAST(s.{c} AS VARCHAR) AS rv, '
                f"trim(CAST(s.{c} AS VARCHAR)) AS v FROM {eng.src} AS s "
                f"WHERE s.{c} IS NOT NULL AND trim(CAST(s.{c} AS VARCHAR)) <> ''")
    bad = (f"WITH t AS ({base}), d AS (SELECT v FROM t GROUP BY v HAVING count(*) > 1) "
           + select_errors(eng.entity, meta, ref="t.r", source="t.sc", value="t.v", record_value="t.rv")
           + " FROM t JOIN d USING (v)")
    return f"SELECT count(*) FROM ({base})", bad


def _plan_not_null(eng, meta, columns, column):
    c = ident(column)
    bad = (select_errors(eng.entity, meta, ref=_col(columns, "ref"), source=_col(columns, "source"),
                         value="NULL", record_value=c)
           + f" FROM {eng.src} WHERE {norm(c)} IS NULL")
    return f"SELECT count(*) FROM {eng.src}", bad


def _plan_thesis_advisor(eng, meta, columns):
    cond = "lower(trim(CAST(\"type\" AS VARCHAR))) = 'tese'"
    advisor = '"advisor"'
    bad = (select_errors(eng.entity, meta, ref=_col(columns, "ref"), source=_col(columns, "source"),
                         value="NULL", record_value=advisor)
           + f" FROM {eng.src} WHERE {cond} AND {norm(advisor)} IS NULL")
    return f"SELECT count(*) FROM {eng.src} WHERE {cond}", bad


def _plan_regex(eng, meta, columns, column, regex):
    c = ident(column)
    nonempty = f"{c} IS NOT NULL AND trim(CAST({c} AS VARCHAR)) <> ''"
    bad = (select_errors(eng.entity, meta, ref=_col(columns, "ref"), source=_col(columns, "source"),
                         value=norm(c), record_value=c)
           + f" FROM {eng.src} WHERE {nonempty} AND {norm(c)} IS NOT NULL "
             f"AND NOT regexp_matches({norm(c)}, {q(regex)})")
    return f"SELECT count(*) FROM {eng.src} WHERE {nonempty}", bad


def _join_bad_values(eng, meta, columns, column, bad, table):
    c = ident(column)
    if not bad:
        return select_errors(eng.entity, meta) + " WHERE false"
    eng.con.register(table, pd.DataFrame({"raw": [b[0] for b in bad], "val": [str(b[1]) for b in bad]}))
    return (select_errors(eng.entity, meta, ref=_col(columns, "ref", "s."), source=_col(columns, "source", "s."),
                          value="b.val", record_value=f"s.{c}")
            + f" FROM {eng.src} AS s JOIN {table} AS b ON CAST(s.{c} AS VARCHAR) = CAST(b.raw AS VARCHAR)")


def _plan_year(eng, meta, columns, column):
    from quality import publication as pub
    c = ident(column)
    bad = []
    for value, _n in eng.con.execute(f"SELECT {c}, count(*) FROM {eng.src} GROUP BY 1").fetchall():
        if value is None or common.normalize_text(value) is None:
            continue
        year = pub.date_year(value)
        if year is None:
            year = pub.CURRENT_YEAR + 1
        if year > pub.CURRENT_YEAR or year < pub.MIN_YEAR:
            bad.append((str(value), year))
    table = "bad_" + re.sub(r"\W", "_", meta["id"])
    return f"SELECT count(*) FROM {eng.src}", _join_bad_values(eng, meta, columns, column, bad, table)


def _plan_language(eng, meta, columns):
    from quality import authority
    allowed = set(authority.authority_values("language2026.json", ("sigla", "name_original", "name_pt", "name_en")))
    evaluated, bad = 0, []
    sql = ('SELECT CAST("language" AS VARCHAR), count(*) FROM ' + eng.src +
           ' WHERE "language" IS NOT NULL AND trim(CAST("language" AS VARCHAR)) <> \'\' GROUP BY 1')
    for raw, n in eng.con.execute(sql).fetchall():
        value = authority.normalize_authority(common.normalize_text(raw))
        if value is None or pd.isna(value):
            continue
        evaluated += n
        if value not in allowed:
            bad.append((raw, value))
    return evaluated, _join_bad_values(eng, meta, columns, "language", bad, "bad_language")


def _plan_token_check(eng, meta, columns, column, predicate):
    """Checagem por função (dígito verificador/formato) sobre cada valor separado por '|'."""
    c = ident(column)
    sql = (f"SELECT trim(tok.value) AS v, count(*) FROM {eng.src} AS s, "
           f"UNNEST(string_split(CAST(s.{c} AS VARCHAR), '|')) AS tok(value) "
           f"WHERE s.{c} IS NOT NULL AND trim(tok.value) <> '' GROUP BY 1")
    evaluated, bad = 0, []
    for v, n in eng.con.execute(sql).fetchall():
        evaluated += n
        if not predicate(v):
            bad.append(v)
    table = "bad_" + re.sub(r"\W", "_", meta["id"])
    if not bad:
        return evaluated, select_errors(eng.entity, meta) + " WHERE false"
    eng.con.register(table, pd.DataFrame({"val": bad}))
    sel = select_errors(eng.entity, meta, ref=_col(columns, "ref", "s."), source=_col(columns, "source", "s."),
                        value="b.val", record_value=f"s.{c}")
    return evaluated, (sel + f" FROM {eng.src} AS s, UNNEST(string_split(CAST(s.{c} AS VARCHAR), '|')) AS tok(value) "
                       f"JOIN {table} AS b ON trim(tok.value) = b.val")


def _plan_regex_tokens(eng, meta, columns, column, regex):
    return _plan_token_check(eng, meta, columns, column, lambda v: re.fullmatch(regex, v) is not None)


def _plan_domain(eng, meta, columns, column, list_name):
    """Valor deve estar numa lista fechada de dominios.json (sem acento/maiúscula)."""
    from quality import authority
    allowed = set(authority.authority_values("dominios.json", (list_name,)))
    c = ident(column)
    sql = (f"SELECT CAST({c} AS VARCHAR), count(*) FROM {eng.src} "
           f"WHERE {c} IS NOT NULL AND trim(CAST({c} AS VARCHAR)) <> '' GROUP BY 1")
    evaluated, bad = 0, []
    for raw, n in eng.con.execute(sql).fetchall():
        value = authority.normalize_authority(common.normalize_text(raw))
        if value is None or pd.isna(value):
            continue
        evaluated += n
        if value not in allowed:
            bad.append((raw, value))
    return evaluated, _join_bad_values(eng, meta, columns, column, bad, "bad_" + re.sub(r"\W", "_", meta["id"]))


def _plan_pages_order(eng, meta, columns):
    num = lambda col: f"TRY_CAST(replace(trim(CAST(s.{ident(col)} AS VARCHAR)), ',', '.') AS DOUBLE)"
    both = f"{num('startPage')} IS NOT NULL AND {num('endPage')} IS NOT NULL"
    bad = (select_errors(eng.entity, meta, ref=_col(columns, "ref", "s."), source=_col(columns, "source", "s."),
                         value="CAST(s.\"startPage\" AS VARCHAR) || ' > ' || CAST(s.\"endPage\" AS VARCHAR)",
                         record_value="s.\"startPage\"")
           + f" FROM {eng.src} AS s WHERE {both} AND {num('startPage')} > {num('endPage')}")
    return f"SELECT count(*) FROM {eng.src} AS s WHERE {both}", bad


def validate_publication(sample_size=None, memory_limit=None):
    from quality import publication as pub
    eng = Engine("publication", "publication", sample_size, memory_limit)
    columns = common.get_columns(eng.con, "publication")
    log("publication", f"{eng.total_rows:,} registros; {len(columns)} colunas")
    started = time.perf_counter()

    for rule in pub.build_rules(columns, sample_size):
        meta = {"id": rule.id, "dimension": rule.dimension, "validation": rule.validation,
                "column": rule.column, "description": rule.description, "reason": rule.reason}

        def build(rule=rule, meta=meta):
            if rule.problem:                  # coluna ausente: vira ERRO TÉCNICO com a explicação
                raise ValueError(rule.problem)
            rid, col = rule.id, rule.column
            if rid.startswith("PUB-SIN-ID-"):
                return _plan_singular(eng, meta, columns, col)
            if rid.startswith("PUB-UNI-ID-"):
                return _plan_unique(eng, meta, col, split=True)
            if rid == "PUB-VAL-PAGES-ORDER":
                return _plan_pages_order(eng, meta, columns)
            if rid == "PUB-VAL-DOI":
                return _plan_regex_tokens(eng, meta, columns, col, pub.DOI_REGEX)
            if rid == "PUB-VAL-ISBN-DV":
                return _plan_token_check(eng, meta, columns, col, checks.isbn)
            if rid == "PUB-AUT-TYPE":
                return _plan_domain(eng, meta, columns, col, "publication_type")
            if rid == "PUB-AUT-ACCESSTYPE":
                return _plan_domain(eng, meta, columns, col, "access_type")
            if rid == "PUB-UNI-REF":
                return _plan_unique(eng, meta, "ref", split=False)
            if rid == "PUB-COM-THESIS-ADVISOR":
                return _plan_thesis_advisor(eng, meta, columns)
            if rid.startswith("PUB-COM-"):
                return _plan_not_null(eng, meta, columns, col)
            if rid.startswith("PUB-VAL-YEAR-"):
                return _plan_year(eng, meta, columns, col)
            if rid.startswith("PUB-VAL-NUM-"):
                return _plan_regex(eng, meta, columns, col, pub.NUMBER_REGEX)
            if rid == "PUB-VAL-RESOURCE-URL":
                actual = next(c for c in columns if c.casefold() == "resourceurl")
                return _plan_regex_tokens(eng, meta, columns, actual, pub.URL_REGEX)
            if rid == "PUB-AUT-LANGUAGE":
                return _plan_language(eng, meta, columns)
            raise NotImplementedError(f"A regra {rid} ainda não tem versão em SQL")

        eng.run(meta, build)

    paths = eng.save({"duration_seconds": round(time.perf_counter() - started, 1)})
    log("publication", f"concluído em {time.perf_counter() - started:.1f}s")
    return paths


# ============================== RELATION ==============================
def _clean_after_prefix(expr):
    """Tira o 'prefixo::' (se houver) e os espaços das pontas."""
    return (f"NULLIF(CASE WHEN position('::' IN {expr}) > 0 "
            f"THEN trim(substr({expr}, position('::' IN {expr}) + 2), {q(WS)}) ELSE {expr} END, '')")


def _docdb_key_exprs(base):
    no_country = f"regexp_replace({base}, '^[A-Z]{{2}}', '')"
    return [base, no_country,
            f"regexp_replace({base}, '[A-Z][0-9]?$', '')",
            f"regexp_replace({no_country}, '[A-Z][0-9]?$', '')"]


def _valid_ids_sql(target, column, prefix, hashed=False):
    """Valores válidos do alvo (separados por '|'). Em docdb, guarda as 4 chaves de cada número.

    hashed=True: o identificador da relação é o MD5 do valor em minúsculas (orgunit/brcris)."""
    c = ident(column)
    tokens = (f"SELECT NULLIF(trim(tok.value, {q(WS)}), '') AS t1 "
              f"FROM {ident(target)} AS s, UNNEST(string_split(CAST(s.{c} AS VARCHAR), '|')) AS tok(value) "
              f"WHERE s.{c} IS NOT NULL AND trim(CAST(s.{c} AS VARCHAR)) <> ''")
    if prefix == "docdb":
        base = f"upper(regexp_replace({_clean_after_prefix('t1')}, '[^0-9A-Za-z]', '', 'g'))"
        keys = ", ".join(_docdb_key_exprs("b"))
        return (f"SELECT DISTINCT {q(prefix)} AS prefix, NULLIF(k.key, '') AS ident FROM "
                f"(SELECT {base} AS b FROM ({tokens}) WHERE t1 IS NOT NULL) AS x, "
                f"UNNEST([{keys}]) AS k(key) WHERE NULLIF(k.key, '') IS NOT NULL")
    ident_expr = _clean_after_prefix('t1')
    if hashed:
        ident_expr = f"md5(lower({ident_expr}))"
    return (f"SELECT DISTINCT {q(prefix)} AS prefix, {ident_expr} AS ident "
            f"FROM ({tokens}) WHERE t1 IS NOT NULL AND {_clean_after_prefix('t1')} IS NOT NULL")


def _parsed_cte(eng, side, aliases, lower_brcris=False):
    """Lê o endpoint: prefix, ident (normalizado, só para checar vazio) e k1..k4 (chaves de comparação)."""
    types = ", ".join(q(a.casefold()) for a in aliases)
    c = ident(side)
    keys = _docdb_key_exprs("b")
    k1_other = "CASE WHEN prefix = 'brcris' THEN lower(i2) ELSE i2 END" if lower_brcris else "i2"
    return f"""
    rel AS (SELECT r."type" AS rtype, r."fromEntityRef" AS fe, r."toEntityRef" AS te, r."info" AS info,
                   r."source" AS source, CAST(r.{c} AS VARCHAR) AS raw, {norm('r.' + c)} AS s
            FROM {eng.src} AS r
            WHERE lower(trim(CAST(r."type" AS VARCHAR))) IN ({types})),
    p1 AS (SELECT *, position('::' IN s) AS sep FROM rel),
    p2 AS (SELECT *, CASE WHEN sep > 0 THEN NULLIF(lower(trim(substr(s, 1, sep - 1), {q(WS)})), '') END AS prefix,
                     CASE WHEN sep > 0 THEN NULLIF(trim(substr(s, sep + 2), {q(WS)}), '') END AS i1 FROM p1),
    parsed AS (SELECT *, {_clean_after_prefix('i1')} AS i2,
                      upper(regexp_replace(i2, '[^0-9A-Za-z]', '', 'g')) AS b FROM p2),
    fin AS (SELECT *,
                   CASE WHEN prefix = 'docdb'
                        THEN NULLIF(regexp_replace(regexp_replace(i2, '(?i)^[A-Z]{{2}}', ''), '(?i)[A-Z][0-9]?$', ''), '')
                        ELSE i2 END AS ident,
                   CASE WHEN prefix = 'docdb' THEN {keys[0]} ELSE {k1_other} END AS k1,
                   CASE WHEN prefix = 'docdb' THEN {keys[1]} END AS k2,
                   CASE WHEN prefix = 'docdb' THEN {keys[2]} END AS k3,
                   CASE WHEN prefix = 'docdb' THEN {keys[3]} END AS k4
            FROM parsed)
    """


def _match_condition():
    """Verdadeiro se alguma das chaves do registro existe entre os valores válidos do alvo.

    COALESCE evita NULL (k2..k4 são nulas fora de docdb), que faria o NOT não marcar o erro.
    """
    parts = [f"COALESCE((f.prefix, f.{k}) IN (SELECT prefix, ident FROM valid), false)"
             for k in ("k1", "k2", "k3", "k4")]
    return " OR ".join(parts)


def validate_relation(sample_size=None, memory_limit=None):
    from quality import relation as rel
    eng = Engine("relations", "relation", sample_size, memory_limit)
    log("relations", f"{eng.total_rows:,} relações")
    started = time.perf_counter()
    sample_scope = f"amostra de até {sample_size:,}" if sample_size else "todas as relações"

    identifier_cols = {}
    for relation_type, side, target, aliases in rel.RELATION_ENDPOINTS:
        rel.check_schema(eng.con, target, side)
        if target not in identifier_cols:
            identifier_cols[target] = rel.identifier_columns(eng.con, target)
    evaluated_cache = {}

    for number, (relation_type, side, target, aliases) in enumerate(rel.RELATION_ENDPOINTS, start=1):
        # nomes reais das colunas identifier.* usadas (conforme os prefixos existentes)
        columns_used = rel.endpoint_columns(eng.con, aliases, side, identifier_cols[target])
        description, reason = rel.endpoint_texts(side, relation_type, target, columns_used, sample_scope)
        meta = {
            "id": f"REL-CON-SEM-{number:03d}", "dimension": "consistência",
            "validation": "consistência referencial", "column": f"relation.{relation_type}.{side}",
            "description": description, "reason": reason,
        }

        def build(side=side, target=target, aliases=aliases, meta=meta):
            ctes = _parsed_cte(eng, side, aliases, lower_brcris=target in rel.HASHED_BRCRIS_TARGETS)
            prefixes = [r[0] for r in eng.con.execute(
                f"WITH {ctes} SELECT DISTINCT prefix FROM fin WHERE prefix IS NOT NULL AND ident IS NOT NULL"
            ).fetchall()]
            valid_parts = []
            for prefix in prefixes:
                column = rel.identifier_column_for_prefix(identifier_cols[target], prefix)
                if column is None:
                    raise ValueError(f"O prefixo {prefix!r} das relações não tem coluna "
                                     f"identifier correspondente em {target!r}.")
                hashed = prefix == "brcris" and target in rel.HASHED_BRCRIS_TARGETS
                valid_parts.append(_valid_ids_sql(target, column, prefix, hashed))
            valid = " UNION ALL ".join(valid_parts) if valid_parts else \
                "SELECT CAST(NULL AS VARCHAR) AS prefix, CAST(NULL AS VARCHAR) AS ident WHERE false"
            # value = texto ORIGINAL (a comparação é feita nas chaves normalizadas k1..k4)
            bad = (f"WITH {ctes}, valid AS ({valid}) "
                   + select_errors(
                       eng.entity, meta, ref="f.raw", source="f.source",
                       value=f"CASE WHEN f.s IS NULL THEN {q(common.MISSING_REFERENCE)} ELSE f.raw END",
                       record_value="f.raw", relation_type="f.rtype", from_ref="f.fe", to_ref="f.te", info="f.info")
                   + " FROM fin AS f WHERE f.prefix IS NULL OR f.ident IS NULL OR NOT (" + _match_condition() + ")")
            key = tuple(a.casefold() for a in aliases)
            if key not in evaluated_cache:
                types = ", ".join(q(a) for a in key)
                evaluated_cache[key] = eng.con.execute(
                    f'SELECT count(*) FROM {eng.src} WHERE lower(trim(CAST("type" AS VARCHAR))) IN ({types})'
                ).fetchone()[0]
            return evaluated_cache[key], bad

        eng.run(meta, build)

    paths = eng.save({"relation_types": len({t for t, *_ in rel.RELATION_ENDPOINTS}),
                      "referential_rules": len(rel.RELATION_ENDPOINTS),
                      "duration_seconds": round(time.perf_counter() - started, 1)})
    log("relations", f"concluído em {time.perf_counter() - started:.1f}s")
    return paths
