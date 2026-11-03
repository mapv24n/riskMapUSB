"""Protección de vistas según la sesión y el rol."""

from functools import wraps
from flask import abort, redirect, request, session, url_for


def requiere_login(funcion):
    @wraps(funcion)
    def envoltura(*args, **kwargs):
        if "usuario" not in session:
            return redirect(url_for("auth.login", siguiente=request.path))
        return funcion(*args, **kwargs)
    return envoltura


def requiere_admin(funcion):
    @wraps(funcion)
    @requiere_login
    def envoltura(*args, **kwargs):
        if session["usuario"].get("rol") != "administrador":
            abort(403)
        return funcion(*args, **kwargs)
    return envoltura


def requiere_profesor(funcion):
    @wraps(funcion)
    @requiere_login
    def envoltura(*args, **kwargs):
        if session["usuario"].get("rol") != "profesor":
            abort(403)
        return funcion(*args, **kwargs)
    return envoltura


