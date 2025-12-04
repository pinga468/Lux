import sqlite3

conn = sqlite3.connect("Lux.db")  # substitua se seu DB tiver outro nome
c = conn.cursor()

try:
    c.execute("ALTER TABLE company ADD COLUMN ai_score FLOAT DEFAULT 0")
    print("Coluna ai_score adicionada!")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e):
        print("A coluna ai_score já existe.")
    else:
        raise e

conn.commit()
conn.close()
