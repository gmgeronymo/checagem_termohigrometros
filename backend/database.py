import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "calibracoes.db")


def _get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS calibracoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL UNIQUE,
            certificado TEXT NOT NULL DEFAULT '',
            data_calibracao TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS pontos_calibracao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            calibracao_id INTEGER NOT NULL,
            tipo TEXT NOT NULL CHECK(tipo IN ('temperatura', 'umidade')),
            indicacao TEXT NOT NULL,
            correcao TEXT NOT NULL,
            incerteza_u TEXT NOT NULL,
            FOREIGN KEY (calibracao_id) REFERENCES calibracoes(id) ON DELETE CASCADE
        );
    """)
    conn.commit()
    conn.close()


def get_calibracao(label: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, label, certificado, data_calibracao FROM calibracoes WHERE label = ?",
        (label,),
    ).fetchone()
    if not row:
        conn.close()
        return None

    pontos = conn.execute(
        "SELECT tipo, indicacao, correcao, incerteza_u FROM pontos_calibracao WHERE calibracao_id = ? ORDER BY tipo, id",
        (row["id"],),
    ).fetchall()

    conn.close()

    result = {
        "label": row["label"],
        "certificado": row["certificado"],
        "data_calibracao": row["data_calibracao"],
        "temperatura": [],
        "umidade": [],
    }
    for p in pontos:
        ponto = {
            "indicacao": p["indicacao"],
            "correcao": p["correcao"],
            "incerteza_u": p["incerteza_u"],
        }
        result[p["tipo"]].append(ponto)

    return result


def save_calibracao(label: str, certificado: str, data_calibracao: str,
                    temperatura: list[dict], umidade: list[dict]):
    conn = _get_conn()

    existing = conn.execute(
        "SELECT id FROM calibracoes WHERE label = ?", (label,)
    ).fetchone()

    if existing:
        cal_id = existing["id"]
        conn.execute(
            "UPDATE calibracoes SET certificado = ?, data_calibracao = ? WHERE id = ?",
            (certificado, data_calibracao, cal_id),
        )
        conn.execute("DELETE FROM pontos_calibracao WHERE calibracao_id = ?", (cal_id,))
    else:
        cur = conn.execute(
            "INSERT INTO calibracoes (label, certificado, data_calibracao) VALUES (?, ?, ?)",
            (label, certificado, data_calibracao),
        )
        cal_id = cur.lastrowid

    for ponto in temperatura:
        conn.execute(
            "INSERT INTO pontos_calibracao (calibracao_id, tipo, indicacao, correcao, incerteza_u) VALUES (?, 'temperatura', ?, ?, ?)",
            (cal_id, ponto["indicacao"], ponto["correcao"], ponto["incerteza_u"]),
        )

    for ponto in umidade:
        conn.execute(
            "INSERT INTO pontos_calibracao (calibracao_id, tipo, indicacao, correcao, incerteza_u) VALUES (?, 'umidade', ?, ?, ?)",
            (cal_id, ponto["indicacao"], ponto["correcao"], ponto["incerteza_u"]),
        )

    conn.commit()
    conn.close()


def delete_calibracao(label: str) -> bool:
    conn = _get_conn()
    cur = conn.execute("DELETE FROM calibracoes WHERE label = ?", (label,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def list_calibracoes() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT label, certificado, data_calibracao FROM calibracoes ORDER BY label"
    ).fetchall()
    conn.close()
    return [{"label": r["label"], "certificado": r["certificado"], "data_calibracao": r["data_calibracao"]} for r in rows]
