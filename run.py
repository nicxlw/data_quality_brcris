"""CLI para análise exploratória genérica e validações por classe.

Uso:
    python run.py explore person
    python run.py validate person --skip-extract
    python run.py validate person --force-extract --workers 2

Compatibilidade: `python run.py person --skip-extract` equivale a `validate`.
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

import extract
from quality import common, exploration


def _ensure_view_from_parquet(entity: str) -> None:
    """Ensure the view exists without rewriting an existing DuckDB database."""
    entity = common.validate_name(entity)
    parquet_dir = extract.PARQUET_DIR / entity
    if common.DB_PATH.exists():
        with common.connect(read_only=True) as con:
            if common.view_exists(con, entity):
                return

    if list(parquet_dir.glob("*.parquet")):
        extract.ensure_view(entity)
        return

    raise SystemExit(
        f"Não há Parquets nem view DuckDB para {entity!r}. Execute a extração primeiro."
    )


def _ensure_relation_view_if_available() -> None:
    parquet_dir = extract.PARQUET_DIR / "relation"
    if not list(parquet_dir.glob("*.parquet")):
        return
    if common.DB_PATH.exists():
        with common.connect(read_only=True) as con:
            if common.view_exists(con, "relation"):
                return
    extract.ensure_view("relation")


def _run_explore(entity: str) -> int:
    _ensure_view_from_parquet(entity)
    paths = exploration.generate_report(entity)
    print("\nAnálise exploratória concluída:")
    for label, path in paths.items():
        print(f"  {label}: {path}")
    return 0


def _run_validate(entity: str, skip_extract: bool, force_extract: bool, workers: int | None) -> int:
    try:
        module = importlib.import_module(f"quality.{entity}")
    except ModuleNotFoundError as exc:
        if exc.name == f"quality.{entity}":
            raise SystemExit(f"Não existe quality/{entity}.py com as validações dessa classe.") from exc
        raise
    validator = getattr(module, "validate", None)
    if not callable(validator):
        raise SystemExit(f"quality/{entity}.py deve expor a função validate().")

    if skip_extract:
        _ensure_view_from_parquet(entity)
        _ensure_relation_view_if_available()
    else:
        info = extract.extract_entity(entity, workers=workers, force=force_extract)
        if not info.get("reconciled", False):
            raise SystemExit("Contagens XML x Parquet não batem ou houve erro de parse; corrija a extração antes de validar.")
        _ensure_relation_view_if_available()

    print(f"\n[{entity}] executando as validações configuradas...")
    scores, errors, metadata = validator()
    paths = common.save_validation_results(entity, scores, errors, metadata)
    paths.update({f"global_{k}": v for k, v in common.build_global_quality_summary().items()})
    print("\nValidação concluída:")
    for label, path in paths.items():
        print(f"  {label}: {path}")
    print(f"  Regras avaliadas: {len(scores)}")
    print(f"  Ocorrências de erro exportadas: {len(errors):,}")
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    # Compatibility with the previous CLI: `run.py person --skip-extract`.
    if argv and argv[0] not in {"explore", "validate", "-h", "--help"}:
        argv = ["validate", *argv]

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    explore_parser = commands.add_parser("explore", help="Gerar análise exploratória HTML de qualquer dataset")
    explore_parser.add_argument("entity", help="Nome da view/dataset no DuckDB, ex.: person, journal")

    validate_parser = commands.add_parser("validate", help="Executar as validações definidas para uma entidade")
    validate_parser.add_argument("entity", help="Classe com módulo quality/<entity>.py")
    validate_parser.add_argument("--skip-extract", action="store_true", help="Validar Parquets/views já existentes")
    validate_parser.add_argument("--force-extract", action="store_true", help="Refazer extração antes de validar")
    validate_parser.add_argument("--workers", type=int, default=None, help="Quantidade de workers na extração")

    args = parser.parse_args(argv)
    if args.command == "explore":
        try:
            return _run_explore(args.entity)
        except Exception as exc:
            raise SystemExit(f"Falha na análise exploratória: {type(exc).__name__}: {exc}") from exc
    try:
        return _run_validate(args.entity, args.skip_extract, args.force_extract, args.workers)
    except Exception as exc:
        raise SystemExit(f"Falha na validação: {type(exc).__name__}: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
