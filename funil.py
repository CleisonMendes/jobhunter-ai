"""
RADAR DE VAGAS — funil.py (NOVO)

Lê a planilha Gestão de Vagas e manda no Telegram o funil: candidaturas, respostas e
conversão por canal ("Onde encontrei essa vaga?").

Definições (ajuste aqui se o seu uso da planilha for diferente):
  • candidatura = linha com a coluna I (Quando me inscrevi) preenchida
  • resposta    = candidatura cuja Fase (J) saiu de "Inscrição" ou com Feedback (O) preenchido
  • descartada  = Status (N) igual a STATUS_DESCARTADA

Uso:
  from funil import enviar_relatorio_funil; enviar_relatorio_funil()
  ou, em um agendamento semanal:  python funil.py
"""

import os
from collections import defaultdict
from datetime import datetime, timedelta

from integracoes import _abrir_aba, PRIMEIRA_LINHA_DADOS
from telegram_acoes import enviar_telegram, _esc, _parse_data_br, STATUS_DESCARTADA


def montar_relatorio(linhas: list[list[str]]) -> str:
    hoje = datetime.now().date()
    por_canal = defaultdict(lambda: {"vagas": 0, "cand": 0, "resp": 0})
    total = descartadas = cand = resp = ult7 = 0

    for n, lin in enumerate(linhas, start=1):
        if n < PRIMEIRA_LINHA_DADOS:
            continue
        lin = lin + [""] * (15 - len(lin))
        if not lin[1].strip():          # sem título = linha vazia
            continue
        canal = lin[7].strip() or "—"   # H
        data = _parse_data_br(lin[8])   # I
        fase, status, feedback = lin[9].strip(), lin[13].strip(), lin[14].strip()  # J, N, O

        total += 1
        por_canal[canal]["vagas"] += 1
        if status.lower() == STATUS_DESCARTADA.lower():
            descartadas += 1
        if data:
            cand += 1
            por_canal[canal]["cand"] += 1
            if (hoje - data).days <= 7:
                ult7 += 1
            if fase not in ("", "Inscrição") or feedback:
                resp += 1
                por_canal[canal]["resp"] += 1

    if not cand:
        return ("📊 <b>FUNIL DE CANDIDATURAS</b>\n\n"
                f"Vagas na planilha: {total} | Descartadas: {descartadas}\n"
                "Ainda não há candidaturas registradas (use o botão ✅ Me candidatei).")

    taxa = lambda r, c: f"{(100 * r / c):.0f}%" if c else "—"
    texto = (f"📊 <b>FUNIL DE CANDIDATURAS</b>\n\n"
             f"Vagas na planilha: {total} | Descartadas: {descartadas}\n"
             f"Candidaturas: <b>{cand}</b> (últimos 7 dias: {ult7})\n"
             f"Respostas: <b>{resp}</b> | Taxa de resposta: <b>{taxa(resp, cand)}</b>\n\n"
             f"<b>Por canal</b>\n<pre>{'canal':<14}{'cand':>5}{'resp':>5}{'conv':>6}\n")
    for canal, d in sorted(por_canal.items(), key=lambda kv: -kv[1]["cand"]):
        if d["cand"]:
            texto += f"{_esc(canal)[:13]:<14}{d['cand']:>5}{d['resp']:>5}{taxa(d['resp'], d['cand']):>6}\n"
    return texto + "</pre>"


def enviar_relatorio_funil() -> None:
    print("\n[FUNIL] Montando relatório do funil...")
    aba = _abrir_aba()
    if aba is None:
        print("  ⚠️  Planilha não configurada.")
        return
    texto = montar_relatorio(aba.get_all_values())
    enviar_telegram(texto, os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID"))


if __name__ == "__main__":
    enviar_relatorio_funil()
