"""
RADAR DE VAGAS — saude_fontes.py (NOVO)

Avisa no Telegram quando uma fonte (Gupy, LinkedIn, Greenhouse, Lever...) para de funcionar:
  • trouxe 0 vagas por ALERTA_FONTE_RODADAS rodadas seguidas (padrão 3), ou
  • deu erro por ALERTA_FONTE_RODADAS_ERRO rodadas seguidas (padrão 2).
Depois do alerta, só repete a cada 24h. Quando a fonte volta, manda um aviso de recuperação.

O contador fica no mesmo banco vagas_enviadas.db (tabela saude_fontes).
"""

import os
import sqlite3
from datetime import datetime, timedelta

from telegram_acoes import enviar_telegram, _esc

DB = "vagas_enviadas.db"
LIMITE_ZERO = int(os.environ.get("ALERTA_FONTE_RODADAS", "3"))
LIMITE_ERRO = int(os.environ.get("ALERTA_FONTE_RODADAS_ERRO", "2"))
REALERTA_HORAS = 24


def verificar_e_alertar(resultados: dict, token: str, chat_id: str, db: str = DB) -> list:
    """resultados = {"Gupy": (qtd_vagas, erro_ou_vazio), ...}. Devolve os avisos enviados."""
    agora = datetime.utcnow()
    avisos = []

    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE IF NOT EXISTS saude_fontes (
        fonte TEXT PRIMARY KEY, zeros_seguidos INTEGER DEFAULT 0,
        ultimo_motivo TEXT, ultimo_alerta TEXT)""")

    for fonte, (qtd, erro) in resultados.items():
        linha = conn.execute(
            "SELECT zeros_seguidos, ultimo_alerta FROM saude_fontes WHERE fonte = ?",
            (fonte,)).fetchone()
        zeros, ultimo = linha if linha else (0, None)

        if qtd > 0 and not erro:
            if ultimo:
                avisos.append(f"✅ A fonte <b>{_esc(fonte)}</b> voltou a trazer vagas ({qtd}).")
            conn.execute("INSERT OR REPLACE INTO saude_fontes VALUES (?, 0, '', NULL)", (fonte,))
            continue

        zeros += 1
        limite = LIMITE_ERRO if erro else LIMITE_ZERO
        passou_prazo = (not ultimo) or (agora - datetime.fromisoformat(ultimo)) > timedelta(hours=REALERTA_HORAS)
        if zeros >= limite and passou_prazo:
            motivo = f"erro: {_esc(erro)}" if erro else "0 vagas"
            avisos.append(f"⚠️ A fonte <b>{_esc(fonte)}</b> está com problema há {zeros} rodada(s) seguidas ({motivo}).")
            ultimo = agora.isoformat()
        conn.execute("INSERT OR REPLACE INTO saude_fontes VALUES (?, ?, ?, ?)",
                     (fonte, zeros, erro or "0 vagas", ultimo))

    conn.commit()
    conn.close()

    if avisos:
        print(f"  🚨 {len(avisos)} aviso(s) sobre fontes. Enviando ao Telegram...")
        enviar_telegram("🛠️ <b>SAÚDE DAS FONTES</b>\n\n" + "\n".join(avisos), token, chat_id)
    return avisos
