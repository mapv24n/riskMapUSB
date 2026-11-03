"""Consulta e importación de calificaciones de los grupos asignados al docente."""

from decimal import Decimal, InvalidOperation

import pandas as pd

from ..database import conectar

CORTES = {"P1": "corte_1", "P2": "corte_2", "Exa": "corte_3"}


def leer_calificaciones(archivo):
    # Admite encabezados en la primera fila y reportes con dos filas de título.
    datos = pd.read_excel(archivo, header=None, dtype=str, keep_default_na=False)
    encabezado = None
    for indice in range(min(3, len(datos))):
        nombres = [valor.strip() for valor in datos.iloc[indice]]
        if "Código" in nombres and any(corte in nombres for corte in CORTES):
            encabezado = indice
            break
    if encabezado is None:
        raise ValueError("El Excel debe incluir Código y al menos una columna P1, P2 o Exa "
                         "en la fila 1, 2 o 3.")
    relevantes = ["Código"] + [corte for corte in CORTES if corte in nombres]
    if any(nombres.count(columna) != 1 for columna in relevantes):
        raise ValueError("Los encabezados Código, P1, P2 y Exa no deben repetirse.")
    posiciones = {columna: nombres.index(columna) for columna in relevantes}
    registros, codigos = [], set()
    omitidos = 0
    for numero, fila in enumerate(datos.iloc[encabezado + 1:].itertuples(index=False, name=None), start=encabezado + 2):
        notas = {}
        for corte in relevantes[1:]:
            valor = fila[posiciones[corte]].strip()
            if not valor:
                continue
            try:
                nota = Decimal(valor.replace(",", "."))
            except InvalidOperation:
                raise ValueError(f"Nota inválida en la fila {numero}, columna {corte}.") from None
            if not nota.is_finite() or not Decimal("0") <= nota <= Decimal("9.99"):
                raise ValueError(f"La nota de {corte} en la fila {numero} debe estar entre 0 y 9,99.")
            if nota != nota.quantize(Decimal("0.01")):
                raise ValueError(f"La nota de {corte} en la fila {numero} debe tener como máximo dos decimales.")
            notas[CORTES[corte]] = nota
        if not notas:
            omitidos += 1
            continue
        codigo = fila[posiciones["Código"]].strip()
        if not codigo:
            raise ValueError(f"Falta el código del estudiante en la fila {numero}.")
        if codigo.casefold() in codigos:
            raise ValueError(f"El código {codigo} está repetido en el archivo (fila {numero}).")
        codigos.add(codigo.casefold())
        registros.append((numero, codigo, notas))
    if not registros:
        raise ValueError("El archivo no contiene calificaciones para cargar.")
    return registros, omitidos


def importar_calificaciones(archivo, id_usuario, id_grupo):
    registros, omitidos = leer_calificaciones(archivo)
    conexion = conectar()
    cursor = None
    resumen = {"creados": 0, "actualizados": 0, "notas": 0, "omitidos": omitidos}
    try:
        cursor = conexion.cursor(dictionary=True)
        obtener_grupo_docente(cursor, id_usuario, id_grupo, bloquear=True)
        for numero, codigo, notas in registros:
            cursor.execute("""SELECT e.id_estudiante FROM estudiante e
                              WHERE e.cod_estudiante = %s AND EXISTS (
                                  SELECT 1 FROM grupo_estudiante ge
                                  WHERE ge.id_estudiante = e.id_estudiante AND ge.id_grupo = %s)""",
                           (codigo, id_grupo))
            estudiante = cursor.fetchone()
            if estudiante is None:
                raise ValueError(f"El estudiante {codigo} de la fila {numero} no está vinculado al grupo.")
            cursor.execute("SELECT id_calificacion FROM calificacion WHERE id_estudiante = %s AND id_grupo = %s",
                           (estudiante["id_estudiante"], id_grupo))
            existentes = cursor.fetchall()
            if len(existentes) > 1:
                raise ValueError(f"El estudiante {codigo} tiene registros de calificación duplicados; "
                                 "solicita al administrador que los revise.")
            if existentes:
                asignaciones = ", ".join(f"{columna} = %s" for columna in notas)
                cursor.execute(f"UPDATE calificacion SET {asignaciones} WHERE id_calificacion = %s",
                               (*notas.values(), existentes[0]["id_calificacion"]))
                resumen["actualizados"] += 1
            else:
                columnas = ", ".join(notas)
                parametros = ", ".join(["%s"] * (2 + len(notas)))
                cursor.execute(f"INSERT INTO calificacion (id_estudiante, id_grupo, {columnas}) "
                               f"VALUES ({parametros})", (estudiante["id_estudiante"], id_grupo, *notas.values()))
                resumen["creados"] += 1
            resumen["notas"] += len(notas)
        conexion.commit()
        return resumen
    except Exception:
        conexion.rollback()
        raise
    finally:
        if cursor is not None:
            cursor.close()
        conexion.close()


# El esquema actual relaciona la cuenta con el docente mediante su correo.
GRUPOS_DOCENTE = """
    FROM grupo g
    JOIN docente d ON d.id_docente = g.id_docente
    JOIN usuario u ON LOWER(TRIM(u.correo)) = LOWER(TRIM(d.correo))
    JOIN asignatura a ON a.id_asignatura = g.id_asignatura
    JOIN periodo p ON p.id_periodo = g.id_periodo
    WHERE u.id_usuario = %s AND u.rol = 'profesor'
"""


def listar_grupos_docente(id_usuario):
    conexion = conectar()
    cursor = None
    try:
        cursor = conexion.cursor(dictionary=True)
        cursor.execute("SELECT g.id_grupo, g.cod_grupo, g.nombre, "
                       "a.nombre AS asignatura, p.nombre AS periodo "
                       + GRUPOS_DOCENTE + " ORDER BY p.nombre DESC, g.cod_grupo", (id_usuario,))
        return cursor.fetchall()
    finally:
        if cursor is not None:
            cursor.close()
        conexion.close()


def obtener_grupo_docente(cursor, id_usuario, id_grupo, bloquear=False):
    cursor.execute("SELECT g.id_grupo, g.cod_grupo, g.nombre, "
                   "a.nombre AS asignatura, p.nombre AS periodo "
                   + GRUPOS_DOCENTE + " AND g.id_grupo = %s"
                   + (" FOR UPDATE" if bloquear else ""), (id_usuario, id_grupo))
    grupo = cursor.fetchone()
    if grupo is None:
        raise PermissionError("El grupo no está asignado a tu cuenta docente.")
    return grupo


def consultar_calificaciones(id_usuario, id_grupo):
    conexion = conectar()
    cursor = None
    try:
        cursor = conexion.cursor(dictionary=True)
        grupo = obtener_grupo_docente(cursor, id_usuario, id_grupo)
        cursor.execute("""SELECT e.cod_estudiante, e.nombre, c.corte_1, c.corte_2, c.corte_3
                          FROM estudiante e
                          LEFT JOIN calificacion c ON c.id_estudiante = e.id_estudiante AND c.id_grupo = %s
                          WHERE EXISTS (SELECT 1 FROM grupo_estudiante ge
                                        WHERE ge.id_estudiante = e.id_estudiante AND ge.id_grupo = %s)
                          ORDER BY e.nombre, e.cod_estudiante""", (id_grupo, id_grupo))
        return grupo, cursor.fetchall()
    finally:
        if cursor is not None:
            cursor.close()
        conexion.close()
