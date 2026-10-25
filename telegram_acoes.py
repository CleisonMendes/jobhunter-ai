"""
RADAR DE VAGAS — telegram_acoes.py (NOVO)

  • enviar_telegram()      → envio (com botões opcionais)
  • botoes_vaga()          → "✅ Me candidatei" / "🗑️ Descartar"
  • processar_cliques()    → lê os cliques pendentes e atualiza a planilha
  • lembretes_followup()   → avisa quando passaram FOLLOWUP_DIAS da candidatura
  • rotinas_telegram()     → roda as duas rotinas acima (chamada a cada rodada)

Como funciona sem servidor: o robô roda por agendamento (GitHub Actions), então os
cliques ficam na fila do Telegram e são processados na próxima rodada. O Telegram
descarta os cliques já confirmados (offset), então não precisa guardar nada no banco.

Variáveis opcionais:
  STATUS_CANDIDATEI  → texto da coluna Status ao candidatar   (padrão "Em andamento")
  STATUS_DESCARTADA  → texto da coluna Status ao descartar    (padrão "Descartada")
  FOLLOWUP_DIAS      → dias até o lembrete                    (padrão 2)
  Se a coluna Status tiver lista suspensa, use valores que existam nela.
"""

import os
import json
import html
import hashlib
import requests
from datetime import datetime

from integracoes import _abrir_aba, PRIMEIRA_LINHA_DADOS

STATUS_CANDIDATEI = os.environ.get("STATUS_CANDIDATEI", "Em andamento")
STATUS_DESCARTADA = os.environ.get("STATUS_DESCARTADA", "Descartada")
PENDENTE_CURRICULO = "📄 Gerar currículo"  # marcador na coluna L (Qual ação) quando você pede o currículo
FOLLOWUP_DIAS = int(os.environ.get("FOLLOWUP_DIAS", "2"))
# Só lembra de candidaturas com data a partir de (dd/mm/aaaa). Ignora as datas que o robô antigo
# preenchia sozinho ao registrar a vaga. Vazio = sem corte.
FOLLOWUP_DESDE = os.environ.get("FOLLOWUP_DESDE", "").strip()

# colunas da planilha (1 = A)
C_TITULO, C_LINK, C_EMPRESA = 2, 3, 4
C_DATA, C_FASE, C_ACAO_NEC, C_ACAO, C_PRAZO, C_STATUS, C_FEEDBACK = 9, 10, 11, 12, 13, 14, 15


def _esc(txt) -> str:
    return html.escape(str(txt or ""), quote=False)


# ====================================================================
# ── ENVIO ────────────────────────────────────────────────────────────
# ====================================================================

def enviar_telegram(texto: str, token: str, chat_id: str, botoes=None) -> bool:
    if not token or not chat_id:
        print("  ⚠️  Telegram não configurado.")
        return False
    payload = {"chat_id": chat_id, "text": texto, "parse_mode": "HTML",
               "disable_web_page_preview": True}
    if botoes:
        payload["reply_markup"] = {"inline_keyboard": botoes}
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json=payload, timeout=20)
        if not r.ok:
            print(f"  ❌ Telegram respondeu {r.status_code}: {r.text[:120]}")
            return False
        return True
    except Exception as e:
        print(f"  ❌ Erro de conexão com Telegram: {e}")
        return False


def hash_link(link: str) -> str:
    """Identificador curto do link (o callback_data do Telegram aceita só 64 bytes)."""
    return hashlib.sha1((link or "").strip().encode("utf-8")).hexdigest()[:12]


def botoes_vaga(link: str, curriculo: bool = True) -> list:
    h = hash_link(link)
    teclado = [[
        {"text": "✅ Me candidatei", "callback_data": f"c|{h}"},
        {"text": "🗑️ Descartar",      "callback_data": f"d|{h}"},
    ]]
    if curriculo:
        teclado.append([{"text": "📄 Gerar currículo + kit", "callback_data": f"g|{h}"}])
    return teclado


def botoes_vaga_sem_curriculo(h: str) -> list:
    return [[
        {"text": "✅ Me candidatei", "callback_data": f"c|{h}"},
        {"text": "🗑️ Descartar",      "callback_data": f"d|{h}"},
    ]]


def enviar_documento(caminho: str, legenda: str, token: str, chat_id: str) -> bool:
    """Envia um arquivo (ex.: o currículo .docx) ao Telegram."""
    if not token or not chat_id:
        print("  ⚠️  Telegram não configurado.")
        return False
    try:
        with open(caminho, "rb") as f:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendDocument",
                              data={"chat_id": chat_id, "caption": legenda[:1000], "parse_mode": "HTML"},
                              files={"document": (os.path.basename(caminho), f)}, timeout=60)
        if not r.ok:
            print(f"  ❌ Telegram respondeu {r.status_code} ao enviar o arquivo: {r.text[:120]}")
            return False
        return True
    except Exception as e:
        print(f"  ❌ Erro ao enviar o arquivo ao Telegram: {e}")
        return False


def planilha_configurada() -> bool:
    return bool((os.environ.get("GOOGLE_CREDENTIALS") or "").strip()
                and (os.environ.get("SHEET_ID") or "").strip())


def _planilha():
    try:
        return _abrir_aba()
    except Exception as e:
        print(f"  ⚠️  Não foi possível abrir a planilha ({type(e).__name__}): {e}")
        return None


# ====================================================================
# ── CLIQUES DOS BOTÕES ───────────────────────────────────────────────
# ====================================================================

def _responder(base: str, callback_id: str, texto: str) -> None:
    try:
        requests.post(f"{base}/answerCallbackQuery",
                      json={"callback_query_id": callback_id, "text": texto}, timeout=15)
    except Exception:
        pass  # clique antigo demais: tudo bem, a planilha já foi atualizada


def _trocar_botoes(base: str, chat_id: str, message_id, rotulo: str, teclado=None) -> None:
    try:
        requests.post(f"{base}/editMessageReplyMarkup", json={
            "chat_id": chat_id, "message_id": message_id,
            "reply_markup": {"inline_keyboard": teclado or [[{"text": rotulo, "callback_data": "x"}]]},
        }, timeout=15)
    except Exception:
        pass


def processar_cliques(token: str, chat_id: str) -> None:
    print("\n[BOTÕES] Verificando cliques pendentes no Telegram...")
    if not token or not chat_id:
        print("  ⚠️  Telegram não configurado.")
        return
    base = f"https://api.telegram.org/bot{token}"
    try:
        r = requests.get(f"{base}/getUpdates", timeout=20, params={
            "timeout": 0, "allowed_updates": json.dumps(["callback_query"])})
        updates = r.json().get("result") or []
    except Exception as e:
        print(f"  ⚠️  Não consegui ler os cliques: {e}")
        return
    if not updates:
        print("  📭 Nenhum clique pendente.")
        return

    aba = _planilha()
    if aba is None:
        print("  ⚠️  Sem planilha: os cliques continuam na fila e serão processados depois.")
        return

    col_link = aba.col_values(C_LINK)
    linhas = {}
    for i, link in enumerate(col_link, start=1):
        if i >= PRIMEIRA_LINHA_DADOS and link.strip():
            linhas.setdefault(hash_link(link), i)

    hoje = datetime.now().strftime("%d/%m/%Y")
    maior, houve_erro, feitos = 0, False, 0

    for up in updates:
        maior = max(maior, up.get("update_id", 0))
        cq = up.get("callback_query") or {}
        msg = cq.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != str(chat_id):
            continue  # ignora cliques de outros chats
        partes = (cq.get("data") or "").split("|")
        if len(partes) != 2 or partes[0] not in ("c", "d", "g"):
            continue
        acao, h = partes
        linha = linhas.get(h)
        if not linha:
            _responder(base, cq["id"], "Não achei essa vaga na planilha.")
            continue
        try:
            if acao == "c":
                dados = [
                    {"range": f"J{linha}", "values": [["Inscrição"]]},
                    {"range": f"N{linha}", "values": [[STATUS_CANDIDATEI]]},
                ]
                if not (aba.cell(linha, C_DATA).value or "").strip():  # não sobrescreve data
                    dados.append({"range": f"I{linha}", "values": [[hoje]]})
                aba.batch_update(dados, value_input_option="USER_ENTERED")
                _responder(base, cq["id"], "Candidatura registrada na planilha ✅")
                _trocar_botoes(base, chat_id, msg.get("message_id"), "✅ Candidatura registrada")
            elif acao == "g":
                aba.batch_update(
                    [{"range": f"L{linha}", "values": [[PENDENTE_CURRICULO]]}],
                    value_input_option="USER_ENTERED")
                _responder(base, cq["id"], "Pedido registrado: o currículo chega na próxima rodada 📄")
                teclado = botoes_vaga_sem_curriculo(h)
                teclado.append([{"text": "⏳ Currículo na fila", "callback_data": "x"}])
                _trocar_botoes(base, chat_id, msg.get("message_id"), "", teclado=teclado)
            else:
                aba.batch_update(
                    [{"range": f"N{linha}", "values": [[STATUS_DESCARTADA]]}],
                    value_input_option="USER_ENTERED")
                _responder(base, cq["id"], "Vaga descartada 🗑️")
                _trocar_botoes(base, chat_id, msg.get("message_id"), "🗑️ Descartada")
            feitos += 1
        except Exception as e:
            houve_erro = True
            print(f"  ❌ Erro ao atualizar a linha {linha}: {e}")

    if maior and not houve_erro:  # confirma: o Telegram apaga o que já foi lido
        try:
            requests.get(f"{base}/getUpdates", params={"offset": maior + 1, "timeout": 0}, timeout=15)
        except Exception:
            pass
    print(f"  ✅ {feitos} clique(s) aplicado(s) na planilha.")


# ====================================================================
# ── LEMBRETE DE FOLLOW-UP ────────────────────────────────────────────
# ====================================================================

def _parse_data_br(txt: str):
    txt = (txt or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(txt[:10], fmt).date()
        except ValueError:
            pass
    return None


def lembretes_followup(token: str, chat_id: str, max_por_rodada: int = 10) -> None:
    """Avisa das candidaturas com FOLLOWUP_DIAS ou mais, sem resposta, ainda na fase Inscrição.
    Depois do aviso, a própria planilha vira o controle: Ação necessária = "Sim"."""
    print("\n[FOLLOW-UP] Procurando candidaturas para follow-up...")
    aba = _planilha()
    if aba is None:
        return
    hoje = datetime.now().date()
    desde = None
    if FOLLOWUP_DESDE:
        try:
            desde = datetime.strptime(FOLLOWUP_DESDE, "%d/%m/%Y").date()
        except ValueError:
            print(f"  ⚠️  FOLLOWUP_DESDE inválido ({FOLLOWUP_DESDE}). Use dd/mm/aaaa. Sem corte.")
    pendentes = []

    for n, lin in enumerate(aba.get_all_values(), start=1):
        if n < PRIMEIRA_LINHA_DADOS:
            continue
        lin = lin + [""] * (C_FEEDBACK - len(lin))
        titulo, link, empresa = lin[C_TITULO - 1], lin[C_LINK - 1], lin[C_EMPRESA - 1]
        data = _parse_data_br(lin[C_DATA - 1])
        fase, acao = lin[C_FASE - 1].strip(), lin[C_ACAO_NEC - 1].strip().lower()
        status, feedback = lin[C_STATUS - 1].strip().lower(), lin[C_FEEDBACK - 1].strip()
        if not (titulo and data):
            continue
        if desde and data < desde:
            continue
        if (hoje - data).days < FOLLOWUP_DIAS:
            continue
        if fase not in ("", "Inscrição") or feedback or acao == "sim":
            continue
        if status not in ("", STATUS_CANDIDATEI.lower()):
            continue
        pendentes.append((n, titulo, empresa, link, (hoje - data).days))
        if len(pendentes) >= max_por_rodada:
            break

    if not pendentes:
        print("  🤫 Nenhum follow-up pendente.")
        return

    texto = f"⏰ <b>HORA DE FAZER FOLLOW-UP ({len(pendentes)})</b>\n\n"
    for _, titulo, empresa, link, dias in pendentes:
        texto += f"• <b>{_esc(titulo)}</b> — {_esc(empresa)}\n  candidatura há {dias} dia(s)\n"
        if link:
            texto += f"  🔗 <a href='{html.escape(link, quote=True)}'>abrir vaga</a>\n"
        texto += "\n"
    texto += "<i>Dica: mande uma mensagem curta ao recrutador. Depois mude a fase ou o status na planilha.</i>"

    if enviar_telegram(texto, token, chat_id):
        hoje_txt = hoje.strftime("%d/%m/%Y")
        dados = []
        for n, *_ in pendentes:
            dados += [
                {"range": f"K{n}", "values": [["Sim"]]},
                {"range": f"L{n}", "values": [["Fazer follow-up (lembrete enviado)"]]},
                {"range": f"M{n}", "values": [[hoje_txt]]},
            ]
        try:
            aba.batch_update(dados, value_input_option="USER_ENTERED")
            print(f"  ✅ {len(pendentes)} lembrete(s) enviado(s) e marcado(s) na planilha.")
        except Exception as e:
            print(f"  ⚠️  Lembrete enviado, mas não consegui marcar a planilha: {e}")


# ====================================================================
# ── ATALHO ───────────────────────────────────────────────────────────
# ====================================================================

def rotinas_telegram(token: str, chat_id: str) -> None:
    if not planilha_configurada():
        print("\n[BOTÕES/FOLLOW-UP] Planilha não configurada. Pulando.")
        return
    rotinas = [processar_cliques, lembretes_followup]
    try:
        from curriculo import gerar_curriculos_pendentes  # importado aqui para evitar import circular
        rotinas.insert(1, gerar_curriculos_pendentes)       # depois dos cliques, antes do follow-up
    except Exception as e:
        print(f"  ⚠️  Currículo adaptado indisponível: {type(e).__name__}: {e}")
    for rotina in rotinas:
        try:
            rotina(token, chat_id)
        except Exception as e:
            print(f"  ⚠️  {rotina.__name__} falhou: {type(e).__name__}: {e}")


if __name__ == "__main__":  # python telegram_acoes.py  → só processa cliques e lembretes
    rotinas_telegram(os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID"))
