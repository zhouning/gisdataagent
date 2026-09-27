"""Minimal package marker for the standalone GIS preprocessing image.

The full application package initializer imports optional document, solver and
ML adapters.  Those dependencies are intentionally absent from this focused
source-data compiler image, so importing a preprocessing submodule must not
execute the full application initializer.
"""
