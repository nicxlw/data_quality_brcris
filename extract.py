"""Extrator configurável de entidades e relações BrCris a partir de ZIPs XML.

O tipo da entidade e as colunas-base são definidos em config/entities.yaml.
Novos tipos podem ser adicionados à configuração sem alterar o código. Fontes
sem record_type podem ser usadas para coletar apenas relações. O XML é lido em
streaming diretamente do ZIP, sem ser descompactado em disco.

Exemplos:
    python extract.py journal --inspect
    python extract.py journal --limit-members 2 --workers 1
    python extract.py journal --force --workers 2

Arquivos de configuração: config/entities.yaml
Saída: data/parquet/<dataset>/ e data/parquet/relation/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from lxml import etree

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # permite --inspect mesmo antes de instalar PyArrow
    pa = None
    pq = None

try:
    import duckdb
except ImportError:  # permite --inspect mesmo antes de instalar DuckDB
    duckdb = None

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config" / "entities.yaml"
PARQUET_DIR = ROOT / "data" / "parquet"
STATE_DIR = ROOT / "data" / "extraction_state"
REJECTS_DIR = ROOT / "data" / "rejects"
DB_PATH = ROOT / "data" / "tcc.duckdb"
BATCH_SIZE = 25_000
EXTRACTOR_FORMAT_VERSION = "relation-info-v1"

# Os campos das entidades são configurados exclusivamente em config/entities.yaml.
# Relações têm estrutura-base fixa e um campo JSON `info` para atributos opcionais
# específicos de cada tipo de relação. O conteúdo de `info` é JSON válido em texto;
# quando não houver atributos, o valor é NULL.
RELATION_COLUMNS = ["type", "fromEntityRef", "toEntityRef", "info"]
PORTUGUESE_LANGS = {"POR", "PT", "PT-BR", "PT_BR", "PORTUGUESE"}


def require_extraction_dependencies() -> None:
    missing = []
    if pa is None or pq is None:
        missing.append("pyarrow")
    if duckdb is None:
        missing.append("duckdb")
    if missing:
        raise SystemExit(
            "Dependências ausentes: " + ", ".join(missing) + ".\n"
            "Instale-as com: python -m pip install -r requirements.txt"
        )


def load_sources() -> dict[str, dict[str, Any]]:
    if not CONFIG.exists():
        raise SystemExit(
            f"Configuração não encontrada: {CONFIG}\n"
            "Crie config/entities.yaml com, por exemplo:\n"
            "journal:\n  zip: data/raw/journal.zip\n  source_prefix: journal\n"
            "  record_type: Journal\n  dataset: journal\n  fields: [title, publisher]\n"
        )
    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    sources = data.get("sources", data)
    if not isinstance(sources, dict):
        raise SystemExit(f"Formato inválido em {CONFIG}: esperava-se um mapa YAML.")
    return {k: v for k, v in sources.items() if isinstance(v, dict) and "zip" in v}


def load_source(name: str) -> dict[str, Any]:
    sources = load_sources()
    if name not in sources:
        available = ", ".join(sources) if sources else "(nenhuma)"
        raise SystemExit(f"Fonte '{name}' não encontrada em {CONFIG}. Disponíveis: {available}")
    cfg = dict(sources[name])
    zip_value = Path(str(cfg["zip"]))
    cfg["zip_path"] = zip_value if zip_value.is_absolute() else ROOT / zip_value
    cfg["source_prefix"] = str(cfg.get("source_prefix", name)).strip("/\\") or name

    record_type = cfg.get("record_type") or (cfg.get("record_filter") or {}).get("type")
    if not record_type and name.lower() == "person":
        record_type = "Person"  # compatibilidade com a configuração antiga
    # Não há mais lista fechada de record_type. Para um tipo novo, a pessoa
    # configura record_type e fields no YAML; o extrator descobre campos adicionais
    # encontrados nos XMLs e os inclui dinamicamente.
    cfg["record_type"] = record_type
    cfg["dataset"] = cfg.get("dataset") or (name if record_type else None)
    if record_type and not cfg["dataset"]:
        cfg["dataset"] = name
    if not record_type:
        cfg["dataset"] = None  # fonte sem tipo de entidade: extrai somente relações
    if cfg.get("dataset") and not re.fullmatch(r"[A-Za-z0-9_-]+", str(cfg["dataset"])):
        raise SystemExit(f"Nome de dataset inválido em {CONFIG}: {cfg['dataset']!r}")

    # O YAML é a única fonte de configuração dos campos-base. Não há esquemas
    # específicos por tipo no Python. Se fields for omitido, a extração ainda
    # descobre dinamicamente os campos presentes nos XMLs.
    fields = cfg.get("fields", [])
    if fields is None:
        fields = []
    if isinstance(fields, str) or not isinstance(fields, list):
        raise SystemExit(
            f"O campo 'fields' da fonte {name!r} deve ser uma lista YAML de nomes de campos."
        )
    cfg["columns"] = list(dict.fromkeys(str(field) for field in fields))
    return cfg


def local_name(tag: str) -> str:
    try:
        return etree.QName(tag).localname
    except (TypeError, ValueError):
        return str(tag).split("}")[-1]


def is_real_xml_member(member: str) -> bool:
    """Ignora diretórios __MACOSX, ficheiros ._ e entradas não XML."""
    path = member.replace("\\", "/")
    parts = path.split("/")
    basename = parts[-1] if parts else ""
    return (
        path.lower().endswith(".xml")
        and not any(part.casefold() == "__macosx" for part in parts)
        and not basename.startswith("._")
        and basename not in {"", ".", ".."}
    )


def source_value(prefix: str, member: str) -> str:
    """Cria uma origem relativa e estável, ex.: orgunit/50/batch_123.xml."""
    member_path = PurePosixPath(member.replace("\\", "/")).as_posix()
    while member_path.startswith("./"):
        member_path = member_path[2:]
    member_path = member_path.lstrip("/")
    prefix_path = PurePosixPath(prefix.replace("\\", "/")).as_posix().strip("/")
    if member_path == prefix_path or member_path.startswith(prefix_path + "/"):
        return member_path
    return f"{prefix_path}/{member_path}" if prefix_path else member_path


def element_text(el: etree._Element) -> str | None:
    value = "".join(el.itertext()).strip()
    return value or None


def field_value(field: etree._Element) -> str | None:
    value = field.get("value")
    if value is None:
        # Um field que contém outros fields é um contêiner estrutural (ex.: apcCost),
        # não um valor textual próprio. Seus filhos serão extraídos em colunas separadas.
        if any(local_name(child.tag) == "field" for child in field):
            return None
        value = element_text(field)
    if value is None:
        return None
    value = value.strip()
    return value or None


def field_path(field: etree._Element, entity: etree._Element) -> str | None:
    """Nome do campo; preserva hierarquia como apcCost.apcAmount para fields aninhados."""
    parts: list[str] = []
    node: etree._Element | None = field
    while node is not None and node is not entity:
        if local_name(node.tag) == "field":
            name = node.get("name")
            if name:
                parts.append(name)
        node = node.getparent()
    if not parts:
        return None
    return ".".join(reversed(parts))


def relation_info(relation: etree._Element) -> str | None:
    """Serializa atributos específicos da relação como JSON, ou retorna None.

    Aceita campos em elementos <field name="..." value="..."> e campos aninhados.
    Campos repetidos são unidos com '|', seguindo a convenção usada nas entidades.
    Também preserva atributos XML adicionais no próprio elemento <relation>, exceto
    os três atributos estruturais type/fromEntityRef/toEntityRef.
    """
    values: dict[str, list[str]] = {}
    structural_attrs = {"type", "fromEntityRef", "toEntityRef"}

    for name, raw_value in relation.attrib.items():
        if name in structural_attrs:
            continue
        value = str(raw_value).strip()
        if value:
            values.setdefault(name, []).append(value)

    for el in relation.iter():
        if local_name(el.tag) != "field":
            continue
        name = field_path(el, relation)
        if not name:
            continue
        value = field_value(el)
        if value is not None:
            values.setdefault(name, []).append(value)

    info = {name: "|".join(items) for name, items in values.items() if items}
    if not info:
        return None
    return json.dumps(info, ensure_ascii=False, separators=(",", ":"))


def entity_row(entity: etree._Element, record_type: str, columns: list[str], source: str) -> dict[str, Any]:
    """Extrai uma entidade, juntando ocorrências repetidas do mesmo campo com '|'.

    Campos encontrados que não estejam na configuração também são incluídos.
    Para fields XML aninhados, o caminho é mantido, ex.: apcCost.apcAmount.
    """
    values: dict[str, list[str]] = {column: [] for column in columns}
    semantic_fallback: dict[str, list[str]] = {column: [] for column in columns}

    for el in entity.iter():
        tag = local_name(el.tag)
        if tag == "field":
            field_name = field_path(el, entity)
            if not field_name:
                continue
            # Campos adicionais não são descartados silenciosamente.
            if field_name not in values:
                values[field_name] = []
            value = field_value(el)
            if value is None:
                continue
            if field_name == "miniBiography":
                lang = (el.get("lang") or "").strip().upper().replace("_", "-")
                if lang and lang not in PORTUGUESE_LANGS:
                    continue
            values[field_name].append(value)
        elif tag == "semanticIdentifier" and record_type == "Person":
            semantic = element_text(el)
            if not semantic or "::" not in semantic:
                continue
            prefix, value = semantic.split("::", 1)
            prefix, value = prefix.strip().lower(), value.strip()
            if not value:
                continue
            if prefix == "brcris" and "identifier.brcris" in semantic_fallback:
                semantic_fallback["identifier.brcris"].append(value)
            elif prefix == "lattes" and "identifier.lattes" in semantic_fallback:
                semantic_fallback["identifier.lattes"].append(value)

    row: dict[str, Any] = {}
    ordered_columns = list(columns) + [column for column in values if column not in columns]
    for column in ordered_columns:
        vals = values[column]
        # Para Person, os semanticIdentifier são fallback; se existe field explícito,
        # usa-o para não misturar formatos distintos de identificadores.
        if (record_type == "Person" and column in {"identifier.brcris", "identifier.lattes"}
                and not vals):
            vals = semantic_fallback[column]
        row[column] = "|".join(vals) if vals else None

    # ref é o identificador de cluster usado pelas relações fromEntityRef/toEntityRef.
    # source preserva a proveniência: prefixo + caminho interno no ZIP.
    row["ref"] = entity.get("ref")
    row["source"] = source
    return row


def clear_processed_element(el: etree._Element) -> None:
    """Libera a memória da árvore incremental do lxml."""
    el.clear()
    parent = el.getparent()
    if parent is not None:
        while el.getprevious() is not None:
            del parent[0]


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return slug or "source"


def chunk_signature(zip_path: str, members: list[str], config_part: dict[str, Any]) -> str:
    stat = Path(zip_path).stat()
    payload = {
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "members": members,
        "config": config_part,
    }
    seed = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def schema_for(target: str, columns: list[str]):
    require_extraction_dependencies()
    if target == "relation":
        return pa.schema([(c, pa.string()) for c in RELATION_COLUMNS] + [("source", pa.string())])
    # Campos do modelo + metadados para provenance e joins com relation.
    return pa.schema([(c, pa.string()) for c in columns] + [("ref", pa.string()), ("source", pa.string())])


def worker_chunk(args: dict[str, Any]) -> dict[str, Any]:
    source_name = args["source_name"]
    slug = args["slug"]
    worker_idx = args["worker_idx"]
    zip_path = args["zip_path"]
    members = args["members"]
    source_prefix = args["source_prefix"]
    record_type = args.get("record_type")
    dataset = args.get("dataset")
    columns = args["columns"]
    max_records = args.get("max_records")
    state_dir = Path(args["state_dir"])
    relation_dir = Path(args["relation_dir"])
    dataset_dir = Path(args["dataset_dir"]) if args.get("dataset_dir") else None
    target_dirs: dict[str, Path] = {"relation": relation_dir}
    if dataset and dataset_dir:
        target_dirs[dataset] = dataset_dir

    state_file = state_dir / f"worker_{worker_idx:03d}.json"
    config_part = {
        "extractor_format_version": EXTRACTOR_FORMAT_VERSION,
        "source_name": source_name,
        "source_prefix": source_prefix,
        "record_type": record_type,
        "dataset": dataset,
        "columns": columns,
        "batch_size": BATCH_SIZE,
        "max_records": max_records,
    }
    signature = chunk_signature(zip_path, members, config_part)

    if not args["force"] and state_file.exists():
        try:
            old = json.loads(state_file.read_text(encoding="utf-8"))
            output_files = old.get("output_files", {})
            outputs_exist = all(
                (target_dirs[target] / filename).exists()
                for target, filenames in output_files.items()
                if target in target_dirs
                for filename in filenames
            ) and set(output_files).issubset(target_dirs)
            if old.get("signature") == signature and outputs_exist:
                old["skipped"] = True
                return old
        except (OSError, json.JSONDecodeError):
            pass

    state_dir.mkdir(parents=True, exist_ok=True)
    for folder in target_dirs.values():
        folder.mkdir(parents=True, exist_ok=True)
        for old_file in folder.glob(f"{slug}__p{worker_idx:03d}__part_*.parquet"):
            old_file.unlink(missing_ok=True)
        for old_tmp in folder.glob(f"{slug}__p{worker_idx:03d}__part_*.parquet.tmp"):
            old_tmp.unlink(missing_ok=True)

    rows: dict[str, list[dict[str, Any]]] = {target: [] for target in target_dirs}
    output_files: dict[str, list[str]] = {target: [] for target in target_dirs}
    part_counts = {target: 0 for target in target_dirs}
    counts = {"processed_xmls": 0, "entity_rows": 0, "relation_rows": 0}
    errors: list[dict[str, str]] = []
    started = time.time()

    def flush(target: str) -> None:
        nonlocal rows
        pending = rows[target]
        if not pending:
            return
        if target == "relation":
            schema_columns = []
        else:
            # O esquema base garante as colunas esperadas; campos adicionais vistos
            # no lote também viram colunas Parquet (union_by_name=True reúne as partes).
            extra_columns = []
            for row in pending:
                for key in row:
                    if key not in columns and key not in {"ref", "source"} and key not in extra_columns:
                        extra_columns.append(key)
            schema_columns = list(columns) + extra_columns
        schema = schema_for(target, schema_columns)
        part = part_counts[target]
        filename = f"{slug}__p{worker_idx:03d}__part_{part:05d}.parquet"
        final_path = target_dirs[target] / filename
        tmp_path = target_dirs[target] / (filename + ".tmp")
        pq.write_table(pa.Table.from_pylist(pending, schema=schema), tmp_path, compression="zstd")
        tmp_path.replace(final_path)
        output_files[target].append(filename)
        part_counts[target] += 1
        rows[target] = []

    try:
        with zipfile.ZipFile(zip_path) as zf:
            for member_num, member in enumerate(members, start=1):
                entity_count_in_member = 0
                current_source = source_value(source_prefix, member)
                try:
                    with zf.open(member) as xml_stream:
                        parser = etree.iterparse(
                            xml_stream,
                            events=("end",),
                            tag=("{*}entity", "{*}relation"),
                            recover=True,
                            huge_tree=True,
                            resolve_entities=False,
                            no_network=True,
                        )
                        for _, el in parser:
                            tag = local_name(el.tag)
                            if tag == "entity":
                                if record_type and el.get("type") == record_type:
                                    entity_count_in_member += 1
                                    if max_records is None or entity_count_in_member <= max_records:
                                        rows[dataset].append(entity_row(el, record_type, columns, current_source))
                                        counts["entity_rows"] += 1
                            elif tag == "relation":
                                rows["relation"].append({
                                    "type": el.get("type"),
                                    "fromEntityRef": el.get("fromEntityRef"),
                                    "toEntityRef": el.get("toEntityRef"),
                                    "info": relation_info(el),
                                    "source": current_source,
                                })
                                counts["relation_rows"] += 1

                            clear_processed_element(el)
                            if dataset and len(rows[dataset]) >= BATCH_SIZE:
                                flush(dataset)
                            if len(rows["relation"]) >= BATCH_SIZE:
                                flush("relation")
                    counts["processed_xmls"] += 1
                except Exception as exc:
                    errors.append({"member": member, "error": f"{type(exc).__name__}: {exc}"})
                if member_num % 2_000 == 0:
                    print(
                        f"[{source_name} p{worker_idx:03d}] {member_num:,}/{len(members):,} XMLs; "
                        f"entidades={counts['entity_rows']:,}; relações={counts['relation_rows']:,}",
                        flush=True,
                    )
        if dataset:
            flush(dataset)
        flush("relation")
    except Exception:
        # Não marca o worker como concluído se a escrita ou leitura do ZIP falhar.
        raise

    summary = {
        "source_name": source_name,
        "worker_idx": worker_idx,
        "signature": signature,
        "processed_xmls": counts["processed_xmls"],
        "member_count": len(members),
        "entity_rows": counts["entity_rows"],
        "relation_rows": counts["relation_rows"],
        "errors": errors,
        "output_files": output_files,
        "seconds": round(time.time() - started, 1),
        "skipped": False,
    }
    state_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def ensure_empty_schema_parquet(target: str, columns: list[str] | None = None) -> None:
    """Mantém um Parquet vazio com o esquema atual, mesmo junto de partes antigas.

    Isso é importante na migração: Parquets de relações gerados por versões antigas
    ainda podem não ter a coluna `info`. Com union_by_name, o arquivo vazio garante
    que a view já exponha a coluna, preenchendo com NULL nas partes antigas.
    """
    require_extraction_dependencies()
    folder = PARQUET_DIR / target
    folder.mkdir(parents=True, exist_ok=True)
    schema = schema_for(target, columns or [])
    schema_path = folder / "_schema_empty.parquet"
    rewrite = not schema_path.exists()
    if not rewrite:
        try:
            existing = pq.read_schema(schema_path)
            rewrite = existing.names != schema.names or any(
                existing.field(name).type != schema.field(name).type for name in schema.names
            )
        except Exception:
            rewrite = True
    if rewrite:
        tmp_path = folder / "_schema_empty.parquet.tmp"
        pq.write_table(pa.Table.from_pylist([], schema=schema), tmp_path, compression="zstd")
        tmp_path.replace(schema_path)


def configured_columns_for_dataset(dataset_name: str) -> list[str]:
    """Reúne fields do YAML para o dataset, sem manter listas duplicadas no Python."""
    columns: list[str] = []
    for source_name, raw_cfg in load_sources().items():
        record_type = raw_cfg.get("record_type") or (raw_cfg.get("record_filter") or {}).get("type")
        if not record_type and source_name.lower() == "person":
            record_type = "Person"  # compatibilidade com a configuração antiga
        configured_dataset = raw_cfg.get("dataset") or (source_name if record_type else None)
        if configured_dataset != dataset_name:
            continue
        fields = raw_cfg.get("fields", [])
        if fields is None:
            fields = []
        if isinstance(fields, str) or not isinstance(fields, list):
            raise SystemExit(
                f"O campo 'fields' da fonte {source_name!r} deve ser uma lista YAML de nomes de campos."
            )
        columns.extend(str(field) for field in fields)
    return list(dict.fromkeys(columns))


def ensure_view(name: str) -> None:
    require_extraction_dependencies()
    folder = PARQUET_DIR / name
    folder.mkdir(parents=True, exist_ok=True)
    if not list(folder.glob("*.parquet")):
        columns = RELATION_COLUMNS if name == "relation" else configured_columns_for_dataset(name)
        ensure_empty_schema_parquet(name, columns)
    pattern = (folder / "*.parquet").as_posix().replace("'", "''")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    try:
        con.execute(
            f'CREATE OR REPLACE VIEW "{name}" AS '
            f"SELECT * FROM read_parquet('{pattern}', union_by_name=true)"
        )
    finally:
        con.close()


def inspect_source(name: str) -> None:
    cfg = load_source(name)
    zip_path: Path = cfg["zip_path"]
    if not zip_path.exists():
        raise SystemExit(f"ZIP não encontrado: {zip_path}")
    with zipfile.ZipFile(zip_path) as zf:
        infos = sorted(
            (info for info in zf.infolist() if not info.is_dir() and is_real_xml_member(info.filename)),
            key=lambda info: info.filename,
        )
        gib = 1024 ** 3
        print(f"Fonte: {name}")
        print(f"ZIP: {zip_path}")
        print(f"Tipo de entidade: {cfg.get('record_type') or '(somente relações)'}")
        print(f"XMLs válidos: {len(infos):,}")
        print(f"Tamanho compactado: {sum(i.compress_size for i in infos) / gib:.3f} GiB")
        print(f"Tamanho descompactado: {sum(i.file_size for i in infos) / gib:.3f} GiB")
        print(f"Espaço livre em disco: {shutil.disk_usage(ROOT).free / gib:.2f} GiB")
        if not infos:
            return
        print(f"Exemplo de source: {source_value(cfg['source_prefix'], infos[0].filename)}")
        print("Elementos e atributos encontrados no primeiro XML:")
        seen: set[tuple[str, tuple[str, ...]]] = set()
        with zf.open(infos[0]) as stream:
            for _, el in etree.iterparse(
                stream, events=("start",), recover=True, huge_tree=True,
                resolve_entities=False, no_network=True,
            ):
                item = (local_name(el.tag), tuple(el.attrib.keys()))
                if item not in seen:
                    seen.add(item)
                    attrs = ", ".join(f"@{attr}" for attr in item[1])
                    print(f"  {item[0]} {attrs}".rstrip())
                if len(seen) >= 80:
                    break


def extract_source(
    name: str,
    workers: int | None = None,
    force: bool = False,
    limit_members: int | None = None,
    max_records: int | None = None,
) -> dict[str, Any]:
    require_extraction_dependencies()
    cfg = load_source(name)
    zip_path: Path = cfg["zip_path"]
    if not zip_path.exists():
        raise SystemExit(f"ZIP não encontrado: {zip_path}")

    with zipfile.ZipFile(zip_path) as zf:
        members = sorted(
            info.filename for info in zf.infolist()
            if not info.is_dir() and is_real_xml_member(info.filename)
        )
    if limit_members is not None:
        members = members[:limit_members]
    if not members:
        raise SystemExit(f"Nenhum arquivo XML válido encontrado em {zip_path}")

    worker_count = workers if workers is not None else min(2, max(1, os.cpu_count() or 1))
    if worker_count < 1:
        raise SystemExit("--workers precisa ser maior ou igual a 1")
    worker_count = max(1, min(worker_count, len(members)))

    source_slug = safe_slug(name)
    source_state_dir = STATE_DIR / source_slug
    dataset = cfg.get("dataset")
    columns = cfg["columns"]
    dataset_dir = PARQUET_DIR / dataset if dataset else None
    relation_dir = PARQUET_DIR / "relation"
    PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    relation_dir.mkdir(parents=True, exist_ok=True)
    if dataset_dir:
        dataset_dir.mkdir(parents=True, exist_ok=True)

    target_dirs = [relation_dir] + ([dataset_dir] if dataset_dir else [])
    if force:
        for folder in target_dirs:
            for old_file in folder.glob(f"{source_slug}__p*__part_*.parquet"):
                old_file.unlink(missing_ok=True)
            for old_tmp in folder.glob(f"{source_slug}__p*__part_*.parquet.tmp"):
                old_tmp.unlink(missing_ok=True)
        if source_state_dir.exists():
            shutil.rmtree(source_state_dir)
    source_state_dir.mkdir(parents=True, exist_ok=True)

    # Se o número de workers diminuiu, remove partições excedentes desta fonte.
    for folder in target_dirs:
        for old_file in folder.glob(f"{source_slug}__p*__part_*.parquet"):
            match = re.match(re.escape(source_slug) + r"__p(\d{3})__part_", old_file.name)
            if match and int(match.group(1)) >= worker_count:
                old_file.unlink(missing_ok=True)
    for marker in source_state_dir.glob("worker_*.json"):
        match = re.match(r"worker_(\d{3})\.json$", marker.name)
        if match and int(match.group(1)) >= worker_count:
            marker.unlink(missing_ok=True)

    chunks = [members[len(members) * i // worker_count: len(members) * (i + 1) // worker_count]
              for i in range(worker_count)]
    args_list = []
    for idx, chunk in enumerate(chunks):
        args_list.append({
            "source_name": name,
            "slug": source_slug,
            "worker_idx": idx,
            "zip_path": str(zip_path),
            "members": chunk,
            "source_prefix": cfg["source_prefix"],
            "record_type": cfg.get("record_type"),
            "dataset": dataset,
            "columns": columns,
            "max_records": max_records,
            "dataset_dir": str(dataset_dir) if dataset_dir else None,
            "relation_dir": str(relation_dir),
            "state_dir": str(source_state_dir),
            "force": force,
        })

    print(f"Fonte: {name}")
    print(f"ZIP: {zip_path}")
    print(f"Tipo: {cfg.get('record_type') or '(somente relações)'}; dataset: {dataset or '(nenhum)'}")
    print(f"XMLs a processar: {len(members):,}; workers: {worker_count}; lote: {BATCH_SIZE:,}")
    if limit_members is not None or max_records is not None:
        print("ATENÇÃO: execução limitada para teste; o resultado NÃO é a extração completa.")

    summaries: list[dict[str, Any]] = []
    started = time.time()
    with ProcessPoolExecutor(max_workers=worker_count) as pool:
        futures = [pool.submit(worker_chunk, args) for args in args_list]
        for idx, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            summaries.append(result)
            status = "reutilizado" if result.get("skipped") else "concluído"
            print(
                f"[{idx}/{worker_count}] worker {result['worker_idx']:03d} {status}: "
                f"XMLs={result['processed_xmls']:,}/{result['member_count']:,}, "
                f"entidades={result['entity_rows']:,}, relações={result['relation_rows']:,}, "
                f"erros={len(result.get('errors', []))}, tempo={result.get('seconds', 0)}s",
                flush=True,
            )

    # Views sempre incluem todos os Parquets do dataset; relation acumula relações
    # de todas as fontes sem apagar as geradas por outros ZIPs.
    if dataset:
        ensure_empty_schema_parquet(dataset, columns)
        ensure_view(dataset)
    ensure_empty_schema_parquet("relation")
    ensure_view("relation")

    all_errors = []
    for result in summaries:
        all_errors.extend({"worker": result["worker_idx"], **err} for err in result.get("errors", []))
    reject_path = REJECTS_DIR / source_slug / "errors.json"
    reject_path.parent.mkdir(parents=True, exist_ok=True)
    if all_errors:
        reject_path.write_text(json.dumps(all_errors, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        reject_path.unlink(missing_ok=True)

    processed_xmls = sum(result["processed_xmls"] for result in summaries)
    entity_rows = sum(result["entity_rows"] for result in summaries)
    relation_rows = sum(result["relation_rows"] for result in summaries)
    summary = {
        "source": name,
        "zip": str(zip_path),
        "source_prefix": cfg["source_prefix"],
        "record_type_extracted": cfg.get("record_type"),
        "dataset": dataset,
        "xml_files_in_run": len(members),
        "xml_files_processed": processed_xmls,
        "entity_rows_written_or_reused": entity_rows,
        "relation_rows_written_or_reused": relation_rows,
        "xml_errors": len(all_errors),
        "workers": worker_count,
        "limited_test_run": limit_members is not None or max_records is not None,
        "seconds": round(time.time() - started, 1),
        "errors_file": str(reject_path) if all_errors else None,
        "reconciled": processed_xmls == len(members) and not all_errors,
    }
    (source_state_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\nExtração concluída.")
    print(f"  XMLs processados: {processed_xmls:,}/{len(members):,}")
    print(f"  Entidades {cfg.get('record_type') or ''}: {entity_rows:,}")
    print(f"  Relações encontradas: {relation_rows:,}")
    print(f"  XMLs com erro: {len(all_errors):,}")
    if dataset_dir:
        print(f"  Parquet {dataset}: {dataset_dir}")
    print(f"  Parquet relation: {relation_dir}")
    print(f"  DuckDB: {DB_PATH}")
    print(f"  Resumo: {source_state_dir / 'summary.json'}")
    if all_errors:
        print(f"  Lista de erros: {reject_path}")
    if summary["limited_test_run"]:
        print("  AVISO: resultado parcial devido aos parâmetros de teste.")
    return summary


def extract_entity(
    name: str,
    workers: int | None = None,
    force: bool = False,
    limit_members: int | None = None,
    max_records: int | None = None,
) -> dict[str, Any]:
    """Alias de compatibilidade com run.py usado no projeto."""
    return extract_source(name, workers, force, limit_members, max_records)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", help="chave da fonte definida em config/entities.yaml (ex.: orgunit)")
    parser.add_argument("--inspect", action="store_true", help="inspeciona o ZIP sem extrair")
    parser.add_argument("--force", action="store_true", help="refaz os dados desta fonte, sem apagar outras fontes")
    parser.add_argument("--workers", type=int, help="processos em paralelo (padrão: até 2)")
    parser.add_argument("--limit-members", type=int, help="processa apenas os primeiros N XMLs (teste)")
    parser.add_argument("--max-records", type=int, help="limita as entidades por XML (teste; relações continuam completas)")
    args = parser.parse_args()
    if args.workers is not None and args.workers < 1:
        parser.error("--workers precisa ser maior ou igual a 1")
    if args.limit_members is not None and args.limit_members < 1:
        parser.error("--limit-members precisa ser maior ou igual a 1")
    if args.max_records is not None and args.max_records < 1:
        parser.error("--max-records precisa ser maior ou igual a 1")

    if args.inspect:
        inspect_source(args.source)
        return 0
    extract_source(
        args.source,
        workers=args.workers,
        force=args.force,
        limit_members=args.limit_members,
        max_records=args.max_records,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
