"""Compatibilidad con importaciones anteriores; la implementación vive en riskmap."""

from riskmap.config import BASE_DATOS
from riskmap.services.importacion import importar_estudiantes, listar_programas

__all__ = ["BASE_DATOS", "importar_estudiantes", "listar_programas"]
