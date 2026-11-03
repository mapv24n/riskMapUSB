from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash
from ..auth import requiere_admin
from ..constants import TABLAS
from ..database import conectar
from ..services.schema import obtener_campos
from ..services.importacion import importar_estudiantes_grupo

bp = Blueprint("admin", __name__)


@bp.route("/admin")
@requiere_admin
def admin_inicio():
    return render_template("admin/index.html", titulo="Administrador", tablas=TABLAS)


@bp.route("/admin/carga-estudiantes", methods=["GET", "POST"])
@requiere_admin
def cargar_estudiantes_grupo():
    if request.method == "POST":
        try:
            archivo = request.files.get("archivo")
            if not archivo or not archivo.filename.lower().endswith(".xlsx"):
                raise ValueError("Selecciona un archivo .xlsx.")
            try:
                id_grupo = int(request.form.get("id_grupo", ""))
                id_programa = int(request.form.get("id_programa", ""))
            except ValueError:
                raise ValueError("Selecciona un grupo y un programa válidos.") from None
            resumen = importar_estudiantes_grupo(archivo, id_grupo, id_programa)
            flash(f"Carga completada: {resumen['nuevos']} estudiantes creados, "
                  f"{resumen['vinculados']} vinculados al grupo y "
                  f"{resumen['omitidos']} filas omitidas por pertenecer ya al grupo.")
        except Exception as error:
            flash(f"No se pudo completar la carga: {error}", "error")
        return redirect(url_for("admin.cargar_estudiantes_grupo"))

    grupos, programas = [], []
    conexion = None
    cursor = None
    estado = 200
    try:
        conexion = conectar()
        cursor = conexion.cursor()
        cursor.execute("""SELECT g.id_grupo, g.cod_grupo, g.nombre, p.nombre
                          FROM grupo g JOIN periodo p ON p.id_periodo = g.id_periodo
                          ORDER BY g.cod_grupo, p.nombre""")
        grupos = cursor.fetchall()
        cursor.execute("SELECT id_programa, nombre FROM programa ORDER BY nombre")
        programas = cursor.fetchall()
    except Exception:
        flash("No se pudieron consultar los grupos y programas. Verifica la conexión a la base de datos.", "error")
        estado = 503
    finally:
        if cursor is not None:
            cursor.close()
        if conexion is not None:
            conexion.close()
    return render_template("admin/carga_estudiantes.html", titulo="Carga masiva de estudiantes",
                           grupos=grupos, programas=programas), estado


@bp.route("/admin/<tabla>")
@requiere_admin
def admin_tabla(tabla):
    if tabla not in TABLAS:
        abort(404)
    conexion = conectar()
    try:
        campos, pk = obtener_campos(tabla, conexion)
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(f"SELECT * FROM `{tabla}` ORDER BY `{pk}` DESC LIMIT 500")
        filas = cursor.fetchall()
        registro = None
        if request.args.get("editar"):
            cursor.execute(f"SELECT * FROM `{tabla}` WHERE `{pk}`=%s", (request.args["editar"],))
            registro = cursor.fetchone()
        cursor.close()
    finally:
        conexion.close()
    return render_template("admin/tabla.html", titulo=tabla, tabla=tabla, campos=campos, pk=pk, filas=filas, registro=registro)


@bp.post("/admin/<tabla>/guardar")
@requiere_admin
def guardar_registro(tabla):
    if tabla not in TABLAS:
        abort(404)
    conexion = conectar()
    cursor = None
    try:
        campos, pk = obtener_campos(tabla, conexion)
        cursor = conexion.cursor()
        accion = request.form.get("accion")
        if accion == "eliminar":
            cursor.execute(f"DELETE FROM `{tabla}` WHERE `{pk}`=%s", (request.form["pk_value"],))
        elif accion in ("crear", "actualizar"):
            values = {}
            for campo in campos:
                nombre = campo["name"]
                if campo["auto"]:
                    continue
                valor = request.form.get(nombre, "").strip()
                if tabla == "usuario" and nombre == "clave":
                    if valor:
                        values["password_hash"] = generate_password_hash(valor)
                    elif accion == "crear":
                        raise ValueError("La contraseña es obligatoria para crear una cuenta.")
                    continue
                values[nombre] = valor if valor != "" else None
            if accion == "crear":
                columnas = list(values)
                sql_cols = ", ".join(f"`{c}`" for c in columnas)
                placeholders = ", ".join(["%s"] * len(columnas))
                cursor.execute(f"INSERT INTO `{tabla}` ({sql_cols}) VALUES ({placeholders})", tuple(values[c] for c in columnas))
            else:
                if not values:
                    raise ValueError("No hay campos para actualizar.")
                asignaciones = ", ".join(f"`{c}`=%s" for c in values)
                cursor.execute(f"UPDATE `{tabla}` SET {asignaciones} WHERE `{pk}`=%s", (*values.values(), request.form["pk_value"]))
        else:
            abort(400)
        conexion.commit()
        flash("Registro guardado correctamente." if accion != "eliminar" else "Registro eliminado.")
    except Exception as error:
        conexion.rollback()
        flash(f"No se pudo guardar el registro: {error}", "error")
    finally:
        if cursor:
            cursor.close()
        conexion.close()
    return redirect(url_for("admin.admin_tabla", tabla=tabla))


