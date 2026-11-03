"""Interfaz del docente para los grupos que tiene asignados."""

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException

from ..auth import requiere_profesor
from ..services.calificaciones import consultar_calificaciones, importar_calificaciones, listar_grupos_docente

bp = Blueprint("docente", __name__)


@bp.get("/docente/calificaciones")
@requiere_profesor
def calificaciones():
    grupos, grupo, estudiantes = [], None, []
    try:
        grupos = listar_grupos_docente(session["usuario"]["id_usuario"])
        if request.args.get("id_grupo"):
            try:
                id_grupo = int(request.args["id_grupo"])
            except ValueError:
                abort(400)
            try:
                grupo, estudiantes = consultar_calificaciones(session["usuario"]["id_usuario"], id_grupo)
            except PermissionError:
                abort(403)
    except HTTPException:
        raise
    except Exception:
        current_app.logger.exception("No se pudieron consultar las calificaciones")
        flash("No se pudieron consultar las calificaciones. Verifica la conexión a la base de datos.", "error")
        return render_template("docente/calificaciones.html", titulo="Calificaciones", grupos=[],
                               grupo=None, estudiantes=[]), 503
    return render_template("docente/calificaciones.html", titulo="Calificaciones", grupos=grupos,
                           grupo=grupo, estudiantes=estudiantes)


@bp.post("/docente/grupos/<int:id_grupo>/calificaciones")
@requiere_profesor
def cargar_calificaciones(id_grupo):
    try:
        # Comprueba la asignación antes de aceptar el archivo; se verifica de nuevo al guardar.
        consultar_calificaciones(session["usuario"]["id_usuario"], id_grupo)
        archivo = request.files.get("archivo")
        if not archivo or not archivo.filename.lower().endswith(".xlsx"):
            raise ValueError("Selecciona un archivo .xlsx.")
        resumen = importar_calificaciones(archivo, session["usuario"]["id_usuario"], id_grupo)
        flash(f"Carga completada: {resumen['notas']} notas guardadas, {resumen['creados']} registros creados, "
              f"{resumen['actualizados']} actualizados y {resumen['omitidos']} filas sin notas omitidas.")
    except PermissionError:
        abort(403)
    except ValueError as error:
        flash(f"No se pudo completar la carga: {error} No se guardaron cambios.", "error")
    except Exception:
        current_app.logger.exception("No se pudo cargar el archivo de calificaciones")
        flash("No se pudo procesar el archivo. Comprueba que sea un Excel válido y que la base de datos "
              "esté disponible. No se guardaron cambios.", "error")
    return redirect(url_for("docente.calificaciones", id_grupo=id_grupo))
