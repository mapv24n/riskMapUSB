"""Permisos, carga de Excel y persistencia de notas sin modificar MySQL."""

from decimal import Decimal
from io import BytesIO
import sqlite3
import unittest
from unittest.mock import patch

import pandas as pd

from riskmap import create_app
from riskmap.services.calificaciones import (
    consultar_calificaciones, importar_calificaciones, leer_calificaciones, listar_grupos_docente,
)


def excel(filas, columnas=("Código", "P1", "P2", "Exa"), fila_encabezado=0):
    archivo = BytesIO()
    pd.DataFrame(filas, columns=columnas).to_excel(archivo, index=False, startrow=fila_encabezado)
    archivo.seek(0)
    return archivo


class CursorTemporal:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, sql, parametros=()):
        self.cursor.execute(sql.replace("%s", "?").replace(" FOR UPDATE", ""),
                            tuple(str(p) if isinstance(p, Decimal) else p for p in parametros))

    def fetchone(self):
        fila = self.cursor.fetchone()
        return dict(fila) if fila is not None else None

    def fetchall(self):
        return [dict(fila) for fila in self.cursor.fetchall()]

    def close(self):
        self.cursor.close()


class ConexionTemporal:
    def __init__(self, db):
        self.db = db

    def cursor(self, dictionary=False):
        return CursorTemporal(self.db.cursor())

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()

    def close(self):
        pass


class CalificacionesTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE usuario (id_usuario INTEGER PRIMARY KEY, correo TEXT, rol TEXT);
            CREATE TABLE docente (id_docente INTEGER PRIMARY KEY, correo TEXT);
            CREATE TABLE asignatura (id_asignatura INTEGER PRIMARY KEY, nombre TEXT);
            CREATE TABLE periodo (id_periodo INTEGER PRIMARY KEY, nombre TEXT);
            CREATE TABLE grupo (id_grupo INTEGER PRIMARY KEY, cod_grupo TEXT, nombre TEXT,
                                id_docente INTEGER, id_asignatura INTEGER, id_periodo INTEGER);
            CREATE TABLE estudiante (id_estudiante INTEGER PRIMARY KEY, cod_estudiante TEXT, nombre TEXT);
            CREATE TABLE grupo_estudiante (id_grupo INTEGER, id_estudiante INTEGER);
            CREATE TABLE calificacion (id_calificacion INTEGER PRIMARY KEY, id_estudiante INTEGER,
                                      id_grupo INTEGER, corte_1 NUMERIC, corte_2 NUMERIC, corte_3 NUMERIC);
            INSERT INTO usuario VALUES (1, ' docente@test.co ', 'profesor'), (2, 'otro@test.co', 'profesor');
            INSERT INTO docente VALUES (1, 'DOCENTE@test.co'), (2, 'otro@test.co');
            INSERT INTO asignatura VALUES (1, 'Matemáticas');
            INSERT INTO periodo VALUES (1, '2026-2');
            INSERT INTO grupo VALUES (1, 'G01', 'Grupo A', 1, 1, 1), (2, 'G02', 'Grupo B', 2, 1, 1);
            INSERT INTO estudiante VALUES (10, '001', 'Ana'), (11, '002', 'Luis'), (12, '003', 'Pedro');
            INSERT INTO grupo_estudiante VALUES (1, 10), (1, 11), (2, 12), (1, 10);
            INSERT INTO calificacion VALUES (1, 10, 1, 3.5, 4, NULL);
        """)
        self.addCleanup(self.db.close)
        parche = patch("riskmap.services.calificaciones.conectar", return_value=ConexionTemporal(self.db))
        parche.start()
        self.addCleanup(parche.stop)
        self.app = create_app()
        self.app.config.update(TESTING=True, SECRET_KEY="pruebas")
        self.client = self.app.test_client()

    def login(self, rol="profesor"):
        with self.client.session_transaction() as session:
            session["usuario"] = {"id_usuario": 1, "rol": rol, "nombre": "Docente", "correo": "no-confiar@test.co"}

    def notas(self):
        return [tuple(fila) for fila in self.db.execute(
            "SELECT id_estudiante, id_grupo, corte_1, corte_2, corte_3 FROM calificacion ORDER BY id_estudiante")]

    def test_only_assigned_groups_and_students_are_visible(self):
        self.assertEqual([g["id_grupo"] for g in listar_grupos_docente(1)], [1])
        grupo, estudiantes = consultar_calificaciones(1, 1)
        self.assertEqual(grupo["asignatura"], "Matemáticas")
        self.assertEqual([e["cod_estudiante"] for e in estudiantes], ["001", "002"])
        with self.assertRaises(PermissionError):
            consultar_calificaciones(1, 2)

    def test_inserts_updates_preserves_blanks_and_zero_and_is_repeatable(self):
        filas = [["001", "", "4,25", 0], ["002", 3.8, "", ""]]
        resumen = importar_calificaciones(excel(filas, fila_encabezado=2), 1, 1)
        self.assertEqual(resumen, {"creados": 1, "actualizados": 1, "notas": 3, "omitidos": 0})
        self.assertEqual(self.notas(), [(10, 1, 3.5, 4.25, 0), (11, 1, 3.8, None, None)])
        resumen = importar_calificaciones(excel(filas), 1, 1)
        self.assertEqual(resumen["creados"], 0)
        self.assertEqual(len(self.notas()), 2)

    def test_rejects_nonmembers_and_rolls_back_previous_rows(self):
        anteriores = self.notas()
        for codigo in ("003", "999"):
            with self.subTest(codigo=codigo), self.assertRaisesRegex(ValueError, "no está vinculado"):
                importar_calificaciones(excel([["001", 5, "", ""], [codigo, 4, "", ""]]), 1, 1)
            self.assertEqual(self.notas(), anteriores)

    def test_denies_upload_after_assignment_or_role_changes(self):
        with self.assertRaises(PermissionError):
            importar_calificaciones(excel([["003", 5, "", ""]]), 1, 2)
        self.db.execute("UPDATE usuario SET rol = 'administrador' WHERE id_usuario = 1")
        self.db.commit()
        with self.assertRaises(PermissionError):
            importar_calificaciones(excel([["001", 5, "", ""]]), 1, 1)

    def test_rejects_duplicate_grade_records(self):
        self.db.execute("INSERT INTO calificacion (id_estudiante, id_grupo) VALUES (10, 1)")
        self.db.commit()
        with self.assertRaisesRegex(ValueError, "duplicados"):
            importar_calificaciones(excel([["001", 5, "", ""]]), 1, 1)

    def test_database_error_rolls_back_created_and_updated_records(self):
        self.db.executescript("""CREATE TRIGGER rechazar BEFORE INSERT ON calificacion
                                BEGIN SELECT RAISE(ABORT, 'Error de prueba'); END;""")
        with self.assertRaises(sqlite3.IntegrityError):
            importar_calificaciones(excel([["001", 5, "", ""], ["002", 4, "", ""]]), 1, 1)
        self.assertEqual(self.notas(), [(10, 1, 3.5, 4, None)])

    def test_bad_headers_empty_duplicates_and_invalid_numbers(self):
        casos = [excel([], ("Código", "P1")), excel([["001", 4]], ("Código", "Nota")),
                 excel([["001", 4, 5]], ("Código", "P1", "P1")),
                 excel([["001", 4], ["001", 5]], ("Código", "P1")),
                 excel([["", 4]], ("Código", "P1"))]
        casos += [excel([["001", valor]], ("Código", "P1"))
                  for valor in ("texto", "NaN", "Infinity", "-1", "10", "4.123")]
        for archivo in casos:
            with self.subTest(archivo=archivo), self.assertRaises(ValueError):
                leer_calificaciones(archivo)
        registros, omitidos = leer_calificaciones(excel([["001", ""], ["002", "0"]], ("Código", "P1")))
        self.assertEqual(omitidos, 1)
        self.assertEqual(registros[0][1:], ("002", {"corte_1": Decimal("0")}))

    def test_pages_and_successful_upload_show_saved_detail(self):
        self.login()
        html = self.client.get("/docente/calificaciones?id_grupo=1").get_data(as_text=True)
        for texto in ("G01", "Matemáticas", "2026-2", "Ana", "Pendiente", "multipart/form-data"):
            self.assertIn(texto, html)
        self.assertNotIn("G02", html)
        respuesta = self.client.post("/docente/grupos/1/calificaciones", data={
            "archivo": (excel([[1, "001", "Nombre informativo", "otro@test.co", "", "4,25", 0],
                               [2, "002", "Luis", "luis@test.co", 4.75, "", ""]],
                              ("#", "Código", "Estudiante", "Correo", "P1", "P2", "Exa"),
                              fila_encabezado=2), "notas.xlsx")}, follow_redirects=True)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("Carga completada", respuesta.get_data(as_text=True))
        self.assertIn("4.75", respuesta.get_data(as_text=True))
        self.assertEqual(self.notas(), [(10, 1, 3.5, 4.25, 0), (11, 1, 4.75, None, None)])
        self.assertEqual(self.db.execute("SELECT nombre FROM estudiante WHERE id_estudiante = 10").fetchone()[0], "Ana")

    def test_routes_deny_other_groups_and_roles(self):
        for rol, estado in [(None, 302), ("administrador", 403), ("director_programa", 403)]:
            if rol:
                self.login(rol)
            self.assertEqual(self.client.get("/docente/calificaciones").status_code, estado)
            self.assertEqual(self.client.post("/docente/grupos/1/calificaciones").status_code, estado)
        self.login()
        self.assertEqual(self.client.get("/docente/calificaciones?id_grupo=2").status_code, 403)
        self.assertEqual(self.client.post("/docente/grupos/2/calificaciones").status_code, 403)
        self.assertEqual(self.client.get("/docente/calificaciones?id_grupo=mal").status_code, 400)

    def test_empty_assignment_and_bad_uploads(self):
        self.login()
        for datos in ({}, {"archivo": (BytesIO(b"x"), "notas.csv")},
                      {"archivo": (BytesIO(b"archivo corrupto"), "notas.xlsx")}):
            with self.subTest(datos=datos):
                respuesta = self.client.post("/docente/grupos/1/calificaciones", data=datos, follow_redirects=True)
            self.assertIn("No se pudo", respuesta.get_data(as_text=True))
            self.assertEqual(self.notas(), [(10, 1, 3.5, 4, None)])
        self.db.execute("UPDATE docente SET correo = 'cambiado@test.co' WHERE id_docente = 1")
        self.db.commit()
        self.assertIn("No tienes grupos asignados", self.client.get("/docente/calificaciones").get_data(as_text=True))
