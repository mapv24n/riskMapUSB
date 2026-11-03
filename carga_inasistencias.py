import mysql.connector
import pandas as pd

# Conexión con la base de datos
try:
    conexion = mysql.connector.connect(
        host="127.0.0.1",
        port=3307,
        user="root",
        password="",
        database="ejemplo_proyecto"
    )

    if conexion.is_connected():
        print("Conexión exitosa")

except mysql.connector.Error as e:
    print("Error de conexión:", e)
    raise

# Leer el archivo Excel de inasistencias
path = "reporte_inasistencia.xlsx"
df = pd.read_excel(path, header=2, dtype=str)

print(df.columns.tolist())

cursor = conexion.cursor()

# Valores estáticos por ahora
id_grupo = 1

# Relación entre corte y columna de la base de datos
cortes = {
    "P1": ("corte_1", []),
    "P2": ("corte_2", ["corte_1"]),
    "Exa": ("corte_3", ["corte_1", "corte_2"])
}

# Revisar qué cortes ya tienen inasistencias guardadas en este grupo
cursor.execute(
    """
    SELECT COUNT(corte_1), COUNT(corte_2), COUNT(corte_3)
    FROM inasistencia
    WHERE id_grupo = %s
    """,
    (id_grupo,)
)

cargados_1, cargados_2, cargados_3 = cursor.fetchone()

# Elegir automáticamente el corte que sigue
if cargados_1 == 0:
    corte_actual = "P1"

elif cargados_2 == 0:
    corte_actual = "P2"

elif cargados_3 == 0:
    corte_actual = "Exa"

else:
    cursor.close()
    conexion.close()
    raise ValueError("Los tres cortes de este grupo ya fueron cargados")

columna_sql, cortes_anteriores = cortes[corte_actual]

print(f"Corte detectado: {corte_actual} -> {columna_sql}")

try:
    for _, fila in df.iterrows():

        # Extraer el código del estudiante
        if pd.isna(fila["Código"]):
            print("Fila omitida: código vacío")
            continue

        codigo = str(fila["Código"]).strip()

        # Extraer el total acumulado de inasistencias
        if pd.isna(fila["Total"]):
            print(f"Estudiante {codigo}: total vacío")
            continue

        total_excel = float(fila["Total"])

        if total_excel < 0 or not total_excel.is_integer():
            print(f"Estudiante {codigo}: total inválido")
            continue

        total_excel = int(total_excel)

        # 1. Buscar al estudiante por su código
        cursor.execute(
            """
            SELECT id_estudiante
            FROM estudiante
            WHERE cod_estudiante = %s
            """,
            (codigo,)
        )

        resultado = cursor.fetchone()

        if not resultado:
            print(f"Estudiante no encontrado: {codigo}")
            continue

        id_estudiante = resultado[0]

        # 2. Buscar el registro de inasistencias del estudiante
        # para el grupo seleccionado
        cursor.execute(
            """
            SELECT id_inasistencia, corte_1, corte_2, corte_3
            FROM inasistencia
            WHERE id_estudiante = %s
              AND id_grupo = %s
            """,
            (id_estudiante, id_grupo)
        )

        resultado = cursor.fetchone()

        if resultado:

            id_inasistencia = resultado[0]

            inasistencias = {
                "corte_1": resultado[1],
                "corte_2": resultado[2],
                "corte_3": resultado[3]
            }

            # 3. Calcular el acumulado de los cortes anteriores
            total_anterior = sum(
                inasistencias[columna] or 0
                for columna in cortes_anteriores
            )

            # 4. Calcular las inasistencias del corte actual
            inasistencias_actuales = total_excel - total_anterior

            if inasistencias_actuales < 0:
                print(
                    f"Error para {codigo}: el total acumulado "
                    "es menor que el registrado anteriormente"
                )
                continue

            # 5. Actualizar únicamente el corte actual
            consulta_update = f"""
                UPDATE inasistencia
                SET {columna_sql} = %s
                WHERE id_inasistencia = %s
            """

            cursor.execute(
                consulta_update,
                (inasistencias_actuales, id_inasistencia)
            )

            print(
                f"Estudiante {codigo}: "
                f"{columna_sql} = {inasistencias_actuales}"
            )

        else:

            # Solo podemos crear el registro desde P1,
            # porque los demás cortes necesitan el acumulado anterior
            if cortes_anteriores:
                print(
                    f"Estudiante {codigo}: no existe un registro "
                    f"previo para calcular {corte_actual}"
                )
                continue

            # 6. Insertar el registro inicial de inasistencias
            cursor.execute(
                """
                INSERT INTO inasistencia
                    (id_estudiante, id_grupo, corte_1)
                VALUES (%s, %s, %s)
                """,
                (id_estudiante, id_grupo, total_excel)
            )

            print(
                f"Estudiante {codigo}: "
                f"corte_1 = {total_excel}"
            )

    # Confirmar los cambios
    conexion.commit()

    print(f"Carga de inasistencias de {corte_actual} finalizada")

except Exception as e:
    conexion.rollback()
    print("Error durante la carga:", e)
    raise

finally:
    cursor.close()
    conexion.close()
