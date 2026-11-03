# riskMapUSB

Aplicación Flask con inicio de sesión para Profesor, Director de Programa y
Administrador. El logo y la paleta verde y blanca se basan en el archivo
`images/Logo.png` proporcionado para el proyecto.

## Ejecutar localmente

Desde la carpeta del proyecto:

```sh
python3 -m pip install -r requirements.txt
python3 app.py
```

Al ejecutar `python3 app.py`, se abre automáticamente el navegador en
<http://127.0.0.1:5001/login>. El puerto predeterminado es 5001 para
evitar el conflicto con el servicio de macOS que ocupa el 5000. Se puede cambiar
con `PORT=5002 python3 app.py`.

## Base de datos y primera cuenta

1. Iniciar MySQL o MariaDB y comprobar los parámetros de `BASE_DATOS` en
   `riskmap/config.py`: servidor `127.0.0.1`, puerto `3306`, usuario `root`, contraseña
   vacía y base `uni_alert`. Ajustarlos si la instalación local usa otros valores.
2. Solo en una base nueva, importar `uni_alert.sql` mediante phpMyAdmin o el
   cliente de MySQL. Si las tablas ya existen, conservarlas: no volver a importar
   el archivo sobre ellas. La aplicación crea la tabla `usuario` si falta.
3. Si todavía no existe una cuenta administradora, crearla desde la terminal:

   ```sh
   python3 -m flask --app app crear-admin
   ```

4. Iniciar sesión con ese correo y contraseña y pulsar **Abrir módulo
   Administrador**, o abrir <http://127.0.0.1:5001/admin>.

El administrador puede crear, consultar, editar y eliminar registros de las diez
tablas, incluidas las cuentas de usuario y sus roles. Los demás roles no tienen
acceso al CRUD. El rol se obtiene de la cuenta al iniciar sesión.

### Carga masiva de estudiantes a un grupo

En **Administrador → Cargar estudiantes a un grupo**, selecciona el grupo de
destino, el programa para los estudiantes nuevos y un archivo `.xlsx` con los
encabezados exactos **Código**, **Estudiante** y **Correo**. Completa las tres
columnas por fila; guarda los códigos como texto para conservar ceros iniciales.

La carga busca cada estudiante por `cod_estudiante`. Si no existe, lo crea en
`estudiante` con el programa seleccionado; luego lo vincula mediante
`grupo_estudiante`. Los datos de estudiantes existentes se conservan y los
vínculos repetidos se omiten, incluso si se vuelve a subir el mismo archivo.
Al terminar se muestra el número de estudiantes creados, vinculados y filas
omitidas. Si ocurre un error, se revierte toda la carga. La opción también está
disponible desde las tablas `grupo`, `estudiante` y `grupo_estudiante`.

### Calificaciones del docente

El profesor puede abrir **Calificaciones** desde el menú o desde su página de
inicio. Solo aparecen los grupos cuyo `id_docente` corresponde a un registro de
`docente` con el mismo correo de su cuenta `usuario`. El administrador debe
mantener esos correos coincidentes y asignar el docente al grupo. La asignación y
el rol se verifican contra la base de datos al consultar y al guardar.

Selecciona el grupo para ver el detalle de notas y cargar un `.xlsx` con las
columnas **#**, **Código**, **Estudiante**, **Correo**, **P1**, **P2** y **Exa**.
Se usa **Código** para identificar al estudiante y **P1**, **P2** y **Exa** para
guardar `corte_1`, `corte_2` y `corte_3`. Las columnas **#**, **Estudiante** y
**Correo** son informativas y no modifican los datos del estudiante; también se
admiten archivos con solo **Código** y una o más columnas de notas.
Se detectan encabezados en las primeras tres filas. Los
códigos deben guardarse como texto si tienen ceros iniciales. Las notas admiten
coma o punto decimal, hasta dos decimales y valores entre 0 y 9,99, según la
capacidad de las columnas `DECIMAL(3,2)` del esquema actual; no se infiere una
escala académica distinta.

Cada nota presente reemplaza la del mismo corte; las celdas vacías conservan las
notas anteriores. Las filas sin notas se omiten. Solo se aceptan estudiantes ya
vinculados al grupo: esta operación no crea estudiantes ni matrículas. Un código
repetido, una nota inválida, un estudiante ajeno al grupo o un error de base de
datos cancela toda la carga. El resultado muestra los registros creados y
actualizados y el detalle guardado.

La carga guarda los cortes que tengan nota y conserva los demás; no calcula
notas acumuladas ni selecciona automáticamente el siguiente corte.

Si aparece el formulario con un error de conexión, verificar que MySQL esté
iniciado y que su puerto coincida con `riskmap/config.py`. El encabezado del volcado SQL
menciona el puerto 3307; la configuración actual de la aplicación usa 3306.


## Estructura del proyecto

```text
app.py                         # Entrada, puerto y apertura del navegador
riskmap/
├── __init__.py                # Factoría create_app y registro de módulos
├── config.py                  # Parámetros de conexión a MySQL
├── constants.py               # Tablas permitidas y roles
├── database.py                # Conexión y tabla de cuentas
├── auth.py                    # Decoradores de permisos
├── cli.py                     # Comando crear-admin
├── routes/                    # Rutas Flask por módulo
│   ├── auth.py                # Inicio y cierre de sesión
│   ├── main.py                # Inicio e importación
│   └── admin.py               # Administración y CRUD
├── services/
│   ├── importacion.py         # Importación de estudiantes desde Excel
│   └── schema.py              # Metadatos para formularios CRUD
├── templates/
│   ├── base.html              # Encabezado, logo, favicon y estructura común
│   ├── auth/login.html
│   ├── main/inicio.html
│   └── admin/                 # Panel y formulario/listado CRUD
└── static/
    ├── css/main.css           # Estilos y colores institucionales
    └── images/                # Logo servido por Flask y usado como favicon
images/Logo.png                # Imagen original conservada
uni_alert.sql                  # Esquema SQL original
extract.py                     # Compatibilidad con importaciones anteriores
tests/test_app.py              # Comprobaciones con base de datos simulada
```

El comando para crear el administrador y las direcciones de las páginas se
mantienen. `extract.py` reexporta los servicios para conservar compatibilidad;
la configuración de MySQL se modifica ahora en `riskmap/config.py`.

Para ejecutar las comprobaciones sin modificar la base de datos:

```sh
python3 -m unittest discover -s tests -v
```
