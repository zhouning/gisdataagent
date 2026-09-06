"""Standards interchange for the Abu Dhabi runtime ontology and semantic layer.

The JSON files used by the NL2SQL runtime remain authoritative.  This package
provides explicit, auditable projections to RDF/OWL, JSON-LD, SKOS and SHACL,
and imports them back only through a declared mode.  A standards projection is
therefore useful to Protege, RDF stores and catalog tooling without being
mistaken for an executable semantic layer by itself.
"""

from .runtime import (
    InteropError,
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

__all__ = [
    "InteropError",
    "export_ontology_to_jsonld",
    "export_ontology_to_turtle",
    "export_semantic_layer_to_jsonld",
    "export_semantic_layer_to_ossie_yaml",
    "export_semantic_layer_to_turtle",
    "export_semantic_layer_to_yaml",
    "import_ontology_from_jsonld",
    "import_ontology_from_turtle",
    "import_semantic_layer_from_jsonld",
    "import_semantic_layer_from_ossie_yaml",
    "import_semantic_layer_from_turtle",
    "validate_roundtrip",
]
