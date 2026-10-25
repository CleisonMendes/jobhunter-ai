"""Teste + recuperação: grava na planilha as vagas já enviadas ao Telegram (tabela 'enviadas').
Usa o mesmo registrar_na_planilha do robô (não duplica: confere pelo link).
Rodar pelo workflow 'Backfill planilha' (botão Run workflow)."""
import os
import sqlite3
from integracoes import registrar_na_planilha

DB = "vagas_enviadas.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
linhas = conn.execute(
    "SELECT link, titulo, empresa, fonte, local, match_score FROM enviadas "
    "WHERE match_score IS NOT NULL ORDER BY data_envio"
).fetchall()
conn.close()

vagas = [dict(r) for r in linhas]
print(f"[BACKFILL] {len(vagas)} vaga(s) na tabela 'enviadas'.")
registrar_na_planilha(vagas)
