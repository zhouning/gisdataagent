"""Command line entry point for GDA semantic standards interchange."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runtime import (
    export_ontology_to_jsonld,
    export_ontology_to_turtle,
    export_semantic_layer_to_jsonld,
    export_semantic_layer_to_ossie_yaml,
    export_semantic_layer_to_turtle,
    export_semantic_layer_to_yaml,
    import_ontology_from_jsonld,
    import_ontology_from_turtle,
    import_semantic_layer_from_jsonld,
    import_semantic_layer_from_ossie_yaml,
    import_semantic_layer_from_turtle,
    validate_roundtrip,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GDA ontology/semantic-layer standards interchange")
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser("export", help="project a runtime JSON asset")
    export.add_argument("--kind", choices=("ontology", "semantic-layer"), required=True)
    export.add_argument("--format", choices=("turtle", "json-ld", "yaml", "ossie-yaml"), required=True)
    export.add_argument("--input", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--no-shapes", action="store_true")

    imp = sub.add_parser("import", help="read a standards projection")
    imp.add_argument("--kind", choices=("ontology", "semantic-layer"), required=True)
    imp.add_argument("--format", choices=("turtle", "json-ld", "ossie-yaml"), required=True)
    imp.add_argument("--input", type=Path, required=True)
    imp.add_argument("--output", type=Path, required=True)
    imp.add_argument("--mode", choices=("strict", "lossless-extension", "projection-only"), default="strict")

    check = sub.add_parser("validate", help="export and verify lossless round-trip")
    check.add_argument("--input", type=Path, required=True)
    check.add_argument("--format", action="append", choices=("turtle", "json-ld"), dest="formats")

    args = parser.parse_args(argv)
    if args.command == "export":
        if args.kind == "ontology":
            if args.format == "ossie-yaml":
                parser.error("ossie-yaml export is only available for semantic-layer assets")
            fn = export_ontology_to_turtle if args.format == "turtle" else export_ontology_to_jsonld
        else:
            if args.format == "yaml":
                fn = export_semantic_layer_to_yaml
            elif args.format == "ossie-yaml":
                fn = export_semantic_layer_to_ossie_yaml
            elif args.format == "turtle":
                fn = export_semantic_layer_to_turtle
            else:
                fn = export_semantic_layer_to_jsonld
        kwargs = {"include_shapes": not args.no_shapes} if args.format in {"turtle", "json-ld"} else {}
        path = fn(args.input, args.output, **kwargs)
        print(json.dumps({"status": "exported", "path": path, "kind": args.kind, "format": args.format}, ensure_ascii=False))
        return 0
    if args.command == "import":
        if args.kind == "ontology":
            if args.format == "ossie-yaml":
                parser.error("ossie-yaml import is only available for semantic-layer assets")
            fn = import_ontology_from_turtle if args.format == "turtle" else import_ontology_from_jsonld
        else:
            if args.format == "ossie-yaml":
                fn = import_semantic_layer_from_ossie_yaml
            else:
                fn = import_semantic_layer_from_turtle if args.format == "turtle" else import_semantic_layer_from_jsonld
        payload = fn(args.input, mode=args.mode)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "imported", "path": str(args.output.resolve()), "mode": args.mode}, ensure_ascii=False))
        return 0
    result = validate_roundtrip(args.input, formats=tuple(args.formats or ("turtle", "json-ld")))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["lossless"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
