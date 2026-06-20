"""Compatibility helpers for ADK 2.x workflow-based agent trees."""

from __future__ import annotations

import os
import sys
import warnings
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any


def install_adk_warning_filters() -> None:
    """Suppress ADK-internal import noise that user code cannot fix."""
    warnings.filterwarnings(
        "ignore",
        message=r"BaseAgentConfig is deprecated.*",
        category=DeprecationWarning,
    )


def configure_proj_data_dir() -> str | None:
    """Configure PROJ data path before pyproj/geopandas are imported."""
    existing = os.environ.get("PROJ_DATA") or os.environ.get("PROJ_LIB")
    if existing and (Path(existing) / "proj.db").exists():
        value = str(Path(existing))
        os.environ["PROJ_DATA"] = value
        os.environ["PROJ_LIB"] = value
        try:
            import pyproj

            pyproj.datadir.set_data_dir(value)
        except Exception:
            pass
        return value

    pyver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    candidates = [
        Path(sys.prefix) / "share" / "proj",
        Path(sys.base_prefix) / "share" / "proj",
        Path(sys.prefix)
        / "lib"
        / pyver
        / "site-packages"
        / "pyproj"
        / "proj_dir"
        / "share"
        / "proj",
        Path(sys.base_prefix)
        / "lib"
        / pyver
        / "site-packages"
        / "pyproj"
        / "proj_dir"
        / "share"
        / "proj",
        Path(sys.prefix) / "lib" / pyver / "site-packages" / "pyogrio" / "proj_data",
        Path(sys.base_prefix)
        / "lib"
        / pyver
        / "site-packages"
        / "pyogrio"
        / "proj_data",
        Path(sys.prefix) / "lib" / pyver / "site-packages" / "rasterio" / "proj_data",
        Path(sys.base_prefix)
        / "lib"
        / pyver
        / "site-packages"
        / "rasterio"
        / "proj_data",
        Path("/usr/local/share/proj"),
        Path("/usr/share/proj"),
    ]

    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        candidates.append(Path(conda_prefix) / "share" / "proj")
    candidates.extend(
        [
            Path.home() / "miniconda3" / "envs" / "farmland-mpc" / "share" / "proj",
            Path.home() / "miniconda3" / "share" / "proj",
        ]
    )

    for candidate in candidates:
        if not (candidate / "proj.db").exists():
            continue
        value = str(candidate)
        os.environ["PROJ_DATA"] = value
        os.environ["PROJ_LIB"] = value
        try:
            import pyproj

            pyproj.datadir.set_data_dir(value)
        except Exception:
            pass
        return value
    return None


install_adk_warning_filters()
configure_proj_data_dir()


_START_NODE_NAMES = {"START", "__START__"}


def _node_name(node: Any) -> str:
    return str(getattr(node, "name", ""))


def _is_start_node(node: Any) -> bool:
    return _node_name(node) in _START_NODE_NAMES


def _is_join_node(node: Any) -> bool:
    return node.__class__.__name__ == "JoinNode"


def workflow_graph_nodes(node: Any, *, include_join: bool = False) -> list[Any]:
    """Return public graph nodes for an ADK Workflow-like object."""
    graph = getattr(node, "graph", None)
    if graph is None:
        return []

    nodes = []
    for child in getattr(graph, "nodes", []) or []:
        if _is_start_node(child):
            continue
        if not include_join and _is_join_node(child):
            continue
        nodes.append(child)
    return nodes


def logical_children(node: Any) -> list[Any]:
    """Return child nodes for both ADK 2 Workflow and legacy sub-agent trees."""
    graph_nodes = workflow_graph_nodes(node)
    if graph_nodes:
        return graph_nodes
    return list(getattr(node, "sub_agents", None) or [])


def node_names(nodes: Iterable[Any]) -> list[str]:
    """Return node names for assertions, topology, and diagnostics."""
    return [_node_name(node) for node in nodes]


def logical_child_names(node: Any) -> list[str]:
    """Return logical child names for a workflow or legacy shell agent."""
    return node_names(logical_children(node))


def find_logical_child(node: Any, name: str) -> Any | None:
    """Find a logical child by name."""
    for child in logical_children(node):
        if _node_name(child) == name:
            return child
    return None


def walk_adk_tree(root: Any) -> Iterator[Any]:
    """Depth-first walk across Workflow graphs and legacy sub-agent trees."""
    seen: set[int] = set()

    def _walk(node: Any) -> Iterator[Any]:
        node_id = id(node)
        if node_id in seen:
            return
        seen.add(node_id)
        yield node
        for child in logical_children(node):
            yield from _walk(child)

    yield from _walk(root)


def set_workflow_compat_attrs(
    workflow: Any,
    *,
    sub_agents: Iterable[Any] | None = None,
    max_iterations: int | None = None,
) -> Any:
    """Attach compatibility attrs used by older local code/tests."""
    if sub_agents is not None:
        object.__setattr__(workflow, "sub_agents", list(sub_agents))
    if max_iterations is not None:
        object.__setattr__(workflow, "max_iterations", max_iterations)
    return workflow
