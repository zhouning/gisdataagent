import ast
import re
from pathlib import Path

from data_agent import staging_environment_readiness as readiness

ROOT = Path(__file__).resolve().parents[1]
STAGING_MODULE_REFERENCE = re.compile(r"data_agent\.(staging_[a-z0-9_]+)")


def _protected_python_modules() -> set[str]:
    return {
        Path(path).stem
        for path in readiness.PROTECTED_RELEASE_SOURCE_PATHS
        if path.endswith(".py")
    }


def test_protected_staging_relative_imports_stay_inside_source_bundle():
    protected_modules = _protected_python_modules()
    for path_text in readiness.PROTECTED_RELEASE_SOURCE_PATHS:
        if not path_text.endswith(".py"):
            continue
        path = ROOT / path_text
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path_text)
        relative_staging_imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.level == 1
            and isinstance(node.module, str)
            and node.module.startswith("staging_")
        }
        assert relative_staging_imports <= protected_modules, (
            path_text,
            sorted(relative_staging_imports - protected_modules),
        )


def test_every_launched_staging_module_is_in_source_bundle():
    protected_modules = _protected_python_modules()
    contract_paths = [
        *(ROOT / path for path in readiness.WORKFLOW_CONTRACTS),
        *(
            ROOT / path
            for path in readiness.PROTECTED_RELEASE_SOURCE_PATHS
            if path.endswith(".py")
        ),
    ]
    referenced_modules = set()
    for path in contract_paths:
        referenced_modules.update(
            STAGING_MODULE_REFERENCE.findall(path.read_text(encoding="utf-8"))
        )

    assert "staging_platform_snapshot" in referenced_modules
    assert referenced_modules <= protected_modules, sorted(
        referenced_modules - protected_modules
    )
