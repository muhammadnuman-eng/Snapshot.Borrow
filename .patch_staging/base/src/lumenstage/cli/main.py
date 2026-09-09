"""Command-line entry point for catalog and reporting operations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from lumenstage import __version__
from lumenstage.config.settings import load_settings
from lumenstage.errors import LumenStageError, ValidationError
from lumenstage.reporting.dashboard import DashboardReport
from lumenstage.reporting.exports import export_collection_csv
from lumenstage.reporting.metrics import MetricsCollector
from lumenstage.services.registry import registry
from lumenstage.storage.store import JsonDocumentStore


def _json_object(value: str) -> dict[str, Any]:
    try:
        result = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError("must be valid JSON") from exc
    if not isinstance(result, dict):
        raise argparse.ArgumentTypeError("must be a JSON object")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lumenstage", description="LumenStage production toolkit")
    parser.add_argument("--version", action="version", version=f"lumenstage {__version__}")
    parser.add_argument("--data-dir", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)

    catalog = sub.add_parser("catalog", help="manage any LumenStage catalog resource")
    catalog.add_argument("resource", choices=registry.resources)
    actions = catalog.add_subparsers(dest="action", required=True)
    listing = actions.add_parser("list")
    listing.add_argument("--status")
    listing.add_argument("--query")
    listing.add_argument("--tag", action="append", default=[])
    show = actions.add_parser("get")
    show.add_argument("item_id")
    create = actions.add_parser("create")
    create.add_argument("name")
    create.add_argument("slug")
    create.add_argument("--tag", action="append", default=[])
    create.add_argument("--metadata", type=_json_object, default={})
    update = actions.add_parser("update")
    update.add_argument("item_id")
    update.add_argument("--name")
    update.add_argument("--status")
    update.add_argument("--tag", action="append")
    update.add_argument("--metadata", type=_json_object)
    update.add_argument("--note")
    archive = actions.add_parser("archive")
    archive.add_argument("item_id")
    archive.add_argument("--note")
    delete = actions.add_parser("delete")
    delete.add_argument("item_id")

    sub.add_parser("resources", help="list available resource types")
    sub.add_parser("metrics")
    sub.add_parser("dashboard")
    export = sub.add_parser("export")
    export.add_argument("collection")

    return parser


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def _run_catalog(args: argparse.Namespace, store: JsonDocumentStore) -> int:
    service = registry.service(args.resource, store)
    if args.action == "list":
        rows = service.list(status=args.status, query=args.query, tags=args.tag or None)
        _print_json([row.to_dict() for row in rows])
    elif args.action == "get":
        _print_json(service.get(args.item_id).to_dict())
    elif args.action == "create":
        _print_json(
            service.create(
                args.name,
                args.slug,
                tags=args.tag,
                metadata=args.metadata,
            ).to_dict()
        )
    elif args.action == "update":
        changes = {
            key: value
            for key, value in {
                "name": args.name,
                "status": args.status,
                "tags": args.tag,
                "metadata": args.metadata,
                "note": args.note,
            }.items()
            if value is not None
        }
        if not changes:
            raise ValidationError("at least one update option is required")
        _print_json(service.update(args.item_id, **changes).to_dict())
    elif args.action == "archive":
        _print_json(service.archive(args.item_id, note=args.note).to_dict())
    elif args.action == "delete":
        service.get(args.item_id)
        service.delete(args.item_id)
        _print_json({"deleted": args.item_id})
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    if args.data_dir:
        settings.data_dir = args.data_dir
    settings.ensure_dirs()
    store = JsonDocumentStore(settings.data_dir / "store.json")
    try:
        if args.command == "catalog":
            return _run_catalog(args, store)
        if args.command == "resources":
            _print_json(
                [
                    {
                        "name": definition.resource,
                        "collection": definition.collection,
                        "label": definition.label,
                    }
                    for definition in registry
                ]
            )
            return 0
        if args.command == "metrics":
            _print_json(MetricsCollector(store).collect().to_dict())
            return 0
        if args.command == "dashboard":
            _print_json(DashboardReport(store).build())
            return 0
        if args.command == "export":
            print(export_collection_csv(store, args.collection))
            return 0
    except LumenStageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
