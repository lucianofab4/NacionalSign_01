import psycopg2

try:
    conn = psycopg2.connect(
        dbname="nacionalsign",
        user="postgres",
        password="postgres123",
        host="localhost",
        port=5432
    )
    print("Conexão OK")
    conn.close()
except Exception as e:
    print(f"Erro na conexão: {e}")
