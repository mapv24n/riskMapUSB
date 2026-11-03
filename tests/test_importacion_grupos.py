"""Carga de Excel y transacciones sobre una base temporal, sin tocar MySQL."""

from io import BytesIO
import sqlite3
import unittest
from unittest.mock import patch

import pandas as pd

from riskmap import create_app
from riskmap.services.importacion import importar_estudiantes_grupo


def excel(filas, columnas=None):
    archivo = BytesIO()
    pd.DataFrame(filas, columns=columnas or ["Código", "Estudiante", "Correo"]).to_excel(archivo, index=False)
    archivo.seek(0)
    return archivo


class CursorSQLite:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, sql, params=()):
        return self.cursor.execute(sql.replace("%s", "?").replace(" FOR UPDATE", ""), params)

    def fetchone(self):
        return self.cursor.fetchone()

    @property
    def lastrowid(self):
        return self.cursor.lastrowid

    def close(self):
        self.cursor.close()


class ConexionSQLite:
    def __init__(self, db):
        self.db = db

    def cursor(self):
        return CursorSQLite(self.db.cursor())

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()

    def close(self):
        pass  # Conserva la base temporal para comprobar el resultado.


class ImportacionGrupoTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript("""
            CREATE TABLE grupo (id_grupo INTEGER PRIMARY KEY);
            CREATE TABLE programa (id_programa INTEGER PRIMARY KEY);
            CREATE TABLE estudiante (id_estudiante INTEGER PRIMARY KEY,
                cod_estudiante TEXT UNIQUE, id_programa INTEGER, nombre TEXT, correo TEXT);
            CREATE TABLE grupo_estudiante (id_grupo_estudiante INTEGER PRIMARY KEY,
                id_grupo INTEGER, id_estudiante INTEGER);
            INSERT INTO grupo VALUES (1);
            INSERT INTO programa VALUES (2);
            INSERT INTO estudiante VALUES (10, '001', 3, 'Existente', 'original@test.co');
            INSERT INTO estudiante VALUES (11, '002', 3, 'Miembro', 'miembro@test.co');
            INSERT INTO grupo_estudiante VALUES (1, 1, 11);
        """)
        self.addCleanup(self.db.close)
        patcher = patch("riskmap.services.importacion.conectar", return_value=ConexionSQLite(self.db))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_creates_links_and_skips_existing_and_repeated_members(self):
        filas = [["001", "Otro nombre", "otro@test.co"], ["002", "Miembro", "m@test.co"],
                 ["003", "Nuevo", "nuevo@test.co"], ["003", "Nuevo", "nuevo@test.co"]]
        resumen = importar_estudiantes_grupo(excel(filas), 1, 2)
        self.assertEqual(resumen, {"procesados": 4, "nuevos": 1, "vinculados": 2, "omitidos": 2})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM grupo_estudiante").fetchone()[0], 3)
        self.assertEqual(self.db.execute("SELECT cod_estudiante, id_programa, nombre FROM estudiante ORDER BY id_estudiante").fetchall(),
                         [('001', 3, 'Existente'), ('002', 3, 'Miembro'), ('003', 2, 'Nuevo')])
        resumen = importar_estudiantes_grupo(excel(filas), 1, 2)
        self.assertEqual(resumen["vinculados"], 0)
        self.assertEqual(resumen["nuevos"], 0)

    def test_invalid_workbooks_leave_database_unchanged(self):
        casos = [(excel([], ["Código", "Estudiante", "Correo"]), "no contiene"),
                 (excel([["001"]], ["Código"]), "Faltan columnas"),
                 (excel([["003", "Nuevo", ""]]), "fila 2"),
                 (excel([["003", "x" * 101, "n@test.co"]]), "longitud")]
        for archivo, mensaje in casos:
            with self.subTest(mensaje=mensaje), self.assertRaisesRegex(ValueError, mensaje):
                importar_estudiantes_grupo(archivo, 1, 2)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM estudiante").fetchone()[0], 2)

    def test_missing_group_or_program_is_rejected(self):
        for grupo, programa, mensaje in [(99, 2, "grupo"), (1, 99, "programa")]:
            with self.subTest(mensaje=mensaje), self.assertRaisesRegex(ValueError, mensaje):
                importar_estudiantes_grupo(excel([["003", "Nuevo", "n@test.co"]]), grupo, programa)

    def test_database_failure_rolls_back_students_and_memberships(self):
        self.db.executescript("""CREATE TRIGGER rechazar BEFORE INSERT ON grupo_estudiante
            WHEN NEW.id_estudiante > 12 BEGIN SELECT RAISE(ABORT, 'Error de prueba'); END;""")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "Error de prueba"):
            importar_estudiantes_grupo(excel([["003", "Nuevo", "n@test.co"],
                                              ["004", "Otro", "o@test.co"]]), 1, 2)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM estudiante").fetchone()[0], 2)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM grupo_estudiante").fetchone()[0], 1)


class CargaGrupoRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, SECRET_KEY="pruebas")
        self.client = self.app.test_client()

    def login(self, rol):
        with self.client.session_transaction() as session:
            session["usuario"] = {"rol": rol, "nombre": "Prueba"}

    def test_requires_admin_for_read_and_upload(self):
        for rol, estado in [(None, 302), ("profesor", 403), ("director_programa", 403)]:
            if rol:
                self.login(rol)
            for metodo in (self.client.get, self.client.post):
                self.assertEqual(metodo("/admin/carga-estudiantes").status_code, estado)

    @patch("riskmap.routes.admin.conectar")
    def test_form_and_admin_entry(self, conectar):
        self.login("administrador")
        conectar.return_value.cursor.return_value.fetchall.side_effect = [
            [(1, "G01", "Grupo A", "2026-2")], [(2, "Ingeniería")]]
        html = self.client.get("/admin/carga-estudiantes").get_data(as_text=True)
        for texto in ('multipart/form-data', 'G01', '2026-2', 'Ingeniería', 'Código'):
            self.assertIn(texto, html)
        self.assertIn('/admin/carga-estudiantes', self.client.get('/admin').get_data(as_text=True))

    @patch("riskmap.routes.admin.importar_estudiantes_grupo")
    def test_upload_success_and_errors(self, importar):
        self.login("administrador")
        importar.return_value = {"nuevos": 1, "vinculados": 2, "omitidos": 1}
        respuesta = self.client.post("/admin/carga-estudiantes", data={
            "id_grupo": "1", "id_programa": "2", "archivo": (BytesIO(b"excel"), "lista.xlsx")})
        self.assertEqual(respuesta.location, "/admin/carga-estudiantes")
        self.assertEqual(importar.call_args.args[1:], (1, 2))
        with self.client.session_transaction() as session:
            self.assertIn("1 estudiantes creados", session["_flashes"][-1][1])
        importar.reset_mock()
        for datos in ({}, {"id_grupo": "mal", "id_programa": "2", "archivo": (BytesIO(b"x"), "lista.xlsx")},
                      {"archivo": (BytesIO(b"x"), "lista.csv")}):
            self.client.post("/admin/carga-estudiantes", data=datos)
            importar.assert_not_called()
        importar.side_effect = ValueError("Faltan columnas requeridas: Correo")
        self.client.post("/admin/carga-estudiantes", data={"id_grupo": "1", "id_programa": "2",
                         "archivo": (BytesIO(b"x"), "lista.xlsx")})
        with self.client.session_transaction() as session:
            self.assertIn("Faltan columnas", session["_flashes"][-1][1])
