"""Operator CLI for ontology build, authority publication and RDF projection."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .compiler import (
    compile_domain_ontology,
    compile_ontology,
    read_ea_csv_exports,
    read_ea_repository,
    read_standard_zip,
    write_package,
)
from .package_reader import OntologyPackageReader
from .protege_export import export_protege_bundle
from .publisher import publish_package


def _build(args: argparse.Namespace) -> dict:
    database_url = os.environ.get(args.ea_url_env, "").strip()
    if not database_url and os.environ.get(args.ea_password_env) is not None:
        from sqlalchemy import URL

        database_url = URL.create(
            args.ea_driver,
            username=os.environ.get(args.ea_user_env, args.ea_user),
            password=os.environ[args.ea_password_env],
            host=os.environ.get(args.ea_host_env, args.ea_host),
            port=int(os.environ.get(args.ea_port_env, str(args.ea_port))),
            database=os.environ.get(args.ea_database_env, args.ea_database),
        )
    if database_url:
        ea = read_ea_repository(database_url)
    elif args.ea_export_dir:
        ea = read_ea_csv_exports(args.ea_export_dir)
    else:
        raise ValueError(
            f"set {args.ea_url_env} for read-only EA access or provide --ea-export-dir"
        )
    standards = read_standard_zip(
        args.standard_zip,
        legacy_docx_dir=args.legacy_docx_dir,
    )
    compiled = (
        compile_ontology(ea, standards)
        if args.legacy_flat_model
        else compile_domain_ontology(ea, standards)
    )
    output_root = Path(args.output_root).expanduser().resolve()
    package_dir = output_root / args.semantic_version
    manifest = write_package(
        compiled,
        package_dir,
        semantic_version=args.semantic_version,
    )
    if args.activate:
        output_root.mkdir(parents=True, exist_ok=True)
        active_path = output_root / "active.json"
        active_path.write_text(
            json.dumps({
                "ontology_key": manifest.ontology_key,
                "semantic_version": manifest.semantic_version,
                "package_id": manifest.package_id,
                "content_sha256": manifest.content_sha256,
            }, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    return {
        "status": "built",
        "package_dir": str(package_dir),
        "package_id": manifest.package_id,
        "semantic_version": manifest.semantic_version,
        "content_sha256": manifest.content_sha256,
        "stats": manifest.stats,
        "validation": manifest.validation_summary,
        "active_pointer_updated": bool(args.activate),
    }


def _publish(args: argparse.Namespace) -> dict:
    database_url = os.environ.get(args.database_url_env, "").strip()
    engine = None
    if database_url:
        from sqlalchemy import create_engine

        engine = create_engine(database_url, pool_size=1, max_overflow=0, pool_pre_ping=True)
    try:
        return publish_package(
            args.package_dir,
            actor=args.actor,
            package_uri=args.package_uri,
            activate=not args.no_activate,
            engine=engine,
        )
    finally:
        if engine is not None:
            engine.dispose()


def _project(args: argparse.Namespace) -> dict:
    """Replace one Fuseki default graph with a hash-verified package projection."""
    reader = OntologyPackageReader(args.package_dir, verify=True)
    rdf_path = reader.artifact_path("rdf")
    with gzip.open(rdf_path, "rb") as stream:
        turtle = stream.read()
    endpoint = args.graph_store_endpoint.rstrip("/")
    request = urllib.request.Request(
        endpoint,
        data=turtle,
        method="PUT",
        headers={
            "Content-Type": "text/turtle; charset=utf-8",
            "X-GDA-Ontology-Package": reader.manifest.package_id,
            "X-GDA-Content-SHA256": reader.manifest.content_sha256,
        },
    )
    username = os.environ.get(args.username_env, "")
    password = os.environ.get(args.password_env, "")
    if username or password:
        import base64
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", errors="replace")
        raise RuntimeError(f"Fuseki projection failed: HTTP {exc.code}: {detail}") from exc
    return {
        "status": "projected",
        "http_status": status,
        "endpoint": endpoint,
        "package_id": reader.manifest.package_id,
        "content_sha256": reader.manifest.content_sha256,
        "triple_count": reader.manifest.stats.get("rdf_triple_count"),
    }


def _export_protege(args: argparse.Namespace) -> dict:
    return export_protege_bundle(args.package_dir, args.output_dir)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GIS Data Agent ontology operator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="compile EA and standard sources")
    build.add_argument("--standard-zip", required=True)
    build.add_argument("--legacy-docx-dir")
    build.add_argument("--ea-url-env", default="EA_REPOSITORY_URL")
    build.add_argument("--ea-password-env", default="EA_REPOSITORY_PASSWORD")
    build.add_argument("--ea-user-env", default="EA_REPOSITORY_USER")
    build.add_argument("--ea-host-env", default="EA_REPOSITORY_HOST")
    build.add_argument("--ea-port-env", default="EA_REPOSITORY_PORT")
    build.add_argument("--ea-database-env", default="EA_REPOSITORY_DATABASE")
    build.add_argument("--ea-driver", default="postgresql+psycopg2")
    build.add_argument("--ea-user", default="ea_user")
    build.add_argument("--ea-host", default="localhost")
    build.add_argument("--ea-port", type=int, default=5432)
    build.add_argument("--ea-database", default="ea_repository")
    build.add_argument("--ea-export-dir")
    build.add_argument("--output-root", required=True)
    build.add_argument("--semantic-version", required=True)
    build.add_argument("--activate", action="store_true")
    build.add_argument(
        "--legacy-flat-model",
        action="store_true",
        help="build the deprecated v1 source-shaped model",
    )
    build.set_defaults(handler=_build)

    publish = subparsers.add_parser("publish", help="publish package to PostgreSQL authority")
    publish.add_argument("--package-dir", required=True)
    publish.add_argument("--actor", required=True)
    publish.add_argument("--package-uri")
    publish.add_argument("--database-url-env", default="ONTOLOGY_AUTHORITY_URL")
    publish.add_argument("--no-activate", action="store_true")
    publish.set_defaults(handler=_publish)

    project = subparsers.add_parser("project", help="replace a Fuseki graph projection")
    project.add_argument(
        "--package-dir",
        help="immutable package directory; defaults to the version selected by active.json",
    )
    project.add_argument("--graph-store-endpoint", required=True)
    project.add_argument("--username-env", default="FUSEKI_USERNAME")
    project.add_argument("--password-env", default="FUSEKI_PASSWORD")
    project.add_argument("--timeout", type=int, default=120)
    project.set_defaults(handler=_project)

    protege = subparsers.add_parser(
        "export-protege",
        help="export review-oriented core and complete Protege models",
    )
    protege.add_argument("--package-dir", required=True)
    protege.add_argument("--output-dir", required=True)
    protege.set_defaults(handler=_export_protege)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = args.handler(args)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
