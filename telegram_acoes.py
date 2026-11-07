"""
RADAR DE VAGAS — telegram_acoes.py

  • enviar_telegram()      → envio (com botões opcionais)
  • botoes_vaga()          → 6 botões: candidatei, descartar, salvar, lembrar, entrevista, currículo
  • processar_cliques()    → lê os cliques e os comprovantes pendentes (prints/e-mails)
  • validar_comprovantes() → valida por e-mail (Gmail) e encerra pendências fora do prazo
  • lembretes_followup()   → avisa quando passaram FOLLOWUP_DIAS da candidatura
  • lembretes_agendados()  → reenvia as vagas marcadas com "⏰ Lembrar amanhã" / "⭐ Salvar para depois"
  • rotinas_telegram()     → roda as rotinas acima (chamada a cada rodada)

Como funciona sem servidor: o robô roda por agendamento (GitHub Actions), então os
cliques e as mensagens ficam na fila do Telegram e são processados na próxima rodada.
O Telegram descarta os itens já confirmados (offset), então não precisa guardar nada no banco.

BOTÕES NOVOS (gravam na planilha, usando as colunas que já existem):
  🎤 Entrevista          → coluna Fase (J) = FASE_ENTREVISTA
  ⭐ Salvar para depois  → K = "Sim", L = "⭐ Salva para depois", M = hoje + SALVAS_DIAS
  ⏰ Lembrar amanhã      → K = "Sim", L = "⏰ Lembrar amanhã",     M = amanhã
  Quando a data da coluna M chega, a vaga é reenviada ao Telegram (com os botões) na
  primeira rodada do dia, e a coluna L passa a indicar que o lembrete foi enviado.

VALIDAÇÃO DE CANDIDATURA:
  "✅ Me candidatei" NÃO grava mais a data na planilha. Ele pede o comprovante
  (print ou e-mail de confirmação). A data de inscrição (coluna I) só entra depois
  que o comprovante for validado (veja validacao.py).

Variáveis opcionais:
  STATUS_CANDIDATEI  → texto da coluna Status ao candidatar   (padrão "Em andamento")
  STATUS_DESCARTADA  → texto da coluna Status ao descartar    (padrão "Descartada")
  FASE_ENTREVISTA    → texto da coluna Fase ao marcar entrevista (padrão "Entrevista")
  SALVAS_DIAS        → dias até lembrar de uma vaga salva      (padrão 3)
  FOLLOWUP_DIAS      → dias até o lembrete                    (padrão 2)
  Se a coluna Status ou Fase tiver lista suspensa, use valores que existam nela.
"""

import os
import json
import html
import hashlib
import requests
from datetime import datetime, timedelta

from integracoes import _abrir_aba, PRIMEIRA_LINHA_DADOS
from validacao import iniciar_validacao, processar_update as processar_comprovante

STATUS_CANDIDATEI = os.environ.get("STATUS_CANDIDATEI", "Em andamento")
STATUS_DESCARTADA = os.environ.get("STATUS_DESCARTADA", "Descartada")
FASE_ENTREVISTA = os.environ.get("FASE_ENTREVISTA", "Entrevista")
try:
    SALVAS_DIAS = int(os.environ.get("SALVAS_DIAS", "3"))
except ValueError:
    SALVAS_DIAS = 3
PENDENTE_CURRICULO = "📄 Gerar currículo"  # marcador na coluna L (Qual ação) quando você pede o currículo
MARC_LEMBRAR = "⏰ Lembrar amanhã"           # marcador na coluna L (botão ⏰)
MARC_SALVA = "⭐ Salva para depois"          # marcador na coluna L (botão ⭐)
FOLLOWUP_DIAS = int(os.environ.get("FOLLOWUP_DIAS", "2"))
# Só lembra de candidaturas com data a partir de (dd/mm/aaaa). Ignora as datas que o robô antigo
# preenchia sozinho ao registrar a vaga. Vazio = sem corte.
FOLLOWUP_DESDE = os.environ.get("FOLLOWUP_DESDE", "").strip()

# colunas da planilha (1 = A)
C_TITULO, C_LINK, C_EMPRESA = 2, 3, 4
C_DATA, C_FASE, C_ACAO_NEC, C_ACAO, C_PRAZO, C_STATUS, C_FEEDBACK = 9, 10, 11, 12, 13, 14, 15


def _esc(txt) -> str:
    return html.escape(str(txt or ""), quote=False)


def _hoje_brt():
    """Data de hoje no horário de Brasília (o robô roda em UTC)."""
    return (datetime.utcnow() - timedelta(hours=3)).date()


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


def _teclado(h: str, curriculo: bool = True) -> list:
    """Layout dos botões (3 linhas de 2):
         ✅ Me candidatei       | 🗑️ Descartar
         ⭐ Salvar para depois  | ⏰ Lembrar amanhã
         🎤 Entrevista          | 📄 Currículo + kit
    """
    teclado = [
        [{"text": "✅ Me candidatei",      "callback_data": f"c|{h}"},
         {"text": "🗑️ Descartar",          "callback_data": f"d|{h}"}],
        [{"text": "⭐ Salvar para depois", "callback_data": f"s|{h}"},
         {"text": "⏰ Lembrar amanhã",     "callback_data": f"l|{h}"}],
    ]
    ultima = [{"text": "🎤 Entrevista", "callback_data": f"e|{h}"}]
    if curriculo:
        ultima.append({"text": "📄 Currículo + kit", "callback_data": f"g|{h}"})
    teclado.append(ultima)
    return teclado


def botoes_vaga(link: str, curriculo: bool = True) -> list:
    return _teclado(hash_link(link), curriculo)


def botoes_vaga_sem_curriculo(h: str) -> list:
    return _teclado(h, curriculo=False)


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
# ── CLIQUES DOS BOTÕES E COMPROVANTES ────────────────────────────────
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
    print("\n[BOTÕES] Verificando cliques e comprovantes pendentes no Telegram...")
    if not token or not chat_id:
        print("  ⚠️  Telegram não configurado.")
        return
    base = f"https://api.telegram.org/bot{token}"
    try:
        # "message" entra na lista para chegarem os prints/e-mails enviados como comprovante
        r = requests.get(f"{base}/getUpdates", timeout=20, params={
            "timeout": 0, "allowed_updates": json.dumps(["callback_query", "message"])})
        updates = r.json().get("result") or []
    except Exception as e:
        print(f"  ⚠️  Não consegui ler os cliques: {e}")
        return
    if not updates:
        print("  📭 Nenhum clique ou comprovante pendente.")
        return

    aba = _planilha()
    if aba is None:
        print("  ⚠️  Sem planilha: os itens continuam na fila e serão processados depois.")
        return

    col_link = aba.col_values(C_LINK)
    linhas = {}
    for i, link in enumerate(col_link, start=1):
        if i >= PRIMEIRA_LINHA_DADOS and link.strip():
            linhas.setdefault(hash_link(link), i)

    maior, houve_erro, feitos, comprovantes = 0, False, 0, 0

    for up in updates:
        maior = max(maior, up.get("update_id", 0))

        # ── Mensagem com comprovante (print, PDF ou texto do e-mail) ──
        if up.get("message"):
            try:
                if processar_comprovante(up):
                    comprovantes += 1
            except Exception as e:
                print(f"  ⚠️  Erro ao processar comprovante: {type(e).__name__}: {e}")
            continue

        cq = up.get("callback_query") or {}
        msg = cq.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != str(chat_id):
            continue  # ignora cliques de outros chats
        partes = (cq.get("data") or "").split("|")
        if len(partes) != 2 or partes[0] not in ("c", "d", "g", "e", "s", "l"):
            continue
        acao, h = partes
        linha = linhas.get(h)
        if not linha:
            _responder(base, cq["id"], "Não achei essa vaga na planilha.")
            continue
        try:
            if acao == "c":
                # Não grava a data aqui: só pede o comprovante.
                # A data (coluna I) entra quando o comprovante for validado.
                dados_linha = aba.row_values(linha)
                dados_linha += [""] * (C_EMPRESA - len(dados_linha))
                iniciar_validacao(
                    link=dados_linha[C_LINK - 1].strip(),
                    titulo=dados_linha[C_TITULO - 1],
                    empresa=dados_linha[C_EMPRESA - 1],
                )
                _responder(base, cq["id"], "Agora envie o comprovante 📎")
                _trocar_botoes(base, chat_id, msg.get("message_id"), "📎 Aguardando comprovante")
            elif acao == "g":
                aba.batch_update(
                    [{"range": f"L{linha}", "values": [[PENDENTE_CURRICULO]]}],
                    value_input_option="USER_ENTERED")
                _responder(base, cq["id"], "Pedido registrado: o currículo chega na próxima rodada 📄")
                teclado = botoes_vaga_sem_curriculo(h)
                teclado.append([{"text": "⏳ Currículo na fila", "callback_data": "x"}])
                _trocar_botoes(base, chat_id, msg.get("message_id"), "", teclado=teclado)
            elif acao == "e":
                # Entrevista: muda só a coluna Fase. (O follow-up ignora vagas fora da fase Inscrição.)
                aba.batch_update(
                    [{"range": f"J{linha}", "values": [[FASE_ENTREVISTA]]}],
                    value_input_option="USER_ENTERED")
                _responder(base, cq["id"], "Entrevista marcada 🎤 Boa sorte!")
                _trocar_botoes(base, chat_id, msg.get("message_id"), "🎤 Entrevista marcada")
            elif acao in ("s", "l"):
                dias = 1 if acao == "l" else SALVAS_DIAS
                marcador = MARC_LEMBRAR if acao == "l" else MARC_SALVA
                quando = (_hoje_brt() + timedelta(days=dias)).strftime("%d/%m/%Y")
                aba.batch_update([
                    {"range": f"K{linha}", "values": [["Sim"]]},
                    {"range": f"L{linha}", "values": [[marcador]]},
                    {"range": f"M{linha}", "values": [[quando]]},
                ], value_input_option="USER_ENTERED")
                if acao == "l":
                    _responder(base, cq["id"], "Combinado: te lembro amanhã ⏰")
                    _trocar_botoes(base, chat_id, msg.get("message_id"), f"⏰ Lembro em {quando[:5]}")
                else:
                    _responder(base, cq["id"], f"Vaga salva ⭐ Te lembro em {dias} dias")
                    _trocar_botoes(base, chat_id, msg.get("message_id"), f"⭐ Salva, lembro em {quando[:5]}")
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
    print(f"  ✅ {feitos} clique(s) aplicado(s) e {comprovantes} comprovante(s) processado(s).")


# ====================================================================
# ── VALIDAÇÃO: GMAIL + PRAZO ─────────────────────────────────────────
# ====================================================================

def validar_comprovantes(token: str, chat_id: str) -> None:
    """Procura o e-mail de confirmação no Gmail (se configurado) e encerra as pendências
    que passaram do prazo."""
    from validacao import verificar_emails_pendentes, expirar_pendentes
    print("\n[VALIDAÇÃO] Conferindo comprovantes pendentes...")
    verificar_emails_pendentes()
    expirar_pendentes()


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
# ── LEMBRETES AGENDADOS: ⏰ LEMBRAR AMANHÃ / ⭐ SALVAR PARA DEPOIS ────
# ====================================================================

def lembretes_agendados(token: str, chat_id: str, max_por_rodada: int = 10) -> None:
    """Reenvia (com os botões) as vagas marcadas com ⏰ ou ⭐ cuja data da coluna M já chegou.
    Depois do envio, a coluna L indica que o lembrete foi enviado e a coluna K é limpa."""
    print("\n[LEMBRETES] Procurando vagas salvas ou adiadas...")
    aba = _planilha()
    if aba is None:
        return
    hoje = _hoje_brt()
    devidos = []

    for n, lin in enumerate(aba.get_all_values(), start=1):
        if n < PRIMEIRA_LINHA_DADOS:
            continue
        lin = lin + [""] * (C_FEEDBACK - len(lin))
        marcador = lin[C_ACAO - 1].strip()
        if marcador not in (MARC_LEMBRAR, MARC_SALVA):
            continue
        prazo = _parse_data_br(lin[C_PRAZO - 1])
        if not prazo or prazo > hoje:
            continue
        titulo, link, empresa = lin[C_TITULO - 1], lin[C_LINK - 1].strip(), lin[C_EMPRESA - 1]
        if not (titulo and link):
            continue
        devidos.append((n, marcador, titulo, empresa, link))
        if len(devidos) >= max_por_rodada:
            break

    if not devidos:
        print("  🤫 Nenhum lembrete agendado para hoje.")
        return

    dados = []
    for n, marcador, titulo, empresa, link in devidos:
        rotulo = "⏰ <b>LEMBRETE</b>" if marcador == MARC_LEMBRAR else "⭐ <b>VAGA SALVA</b>"
        texto = (f"{rotulo}\n\n<b>{_esc(titulo)}</b> — {_esc(empresa)}\n"
                 f"🔗 <a href='{html.escape(link, quote=True)}'>abrir vaga</a>")
        if enviar_telegram(texto, token, chat_id, botoes=botoes_vaga(link)):
            enviado = "⏰ Lembrete enviado" if marcador == MARC_LEMBRAR else "⭐ Salva (lembrete enviado)"
            dados += [
                {"range": f"K{n}", "values": [[""]]},
                {"range": f"L{n}", "values": [[enviado]]},
            ]
    if dados:
        try:
            aba.batch_update(dados, value_input_option="USER_ENTERED")
            print(f"  ✅ {len(dados) // 2} lembrete(s) enviado(s) e marcado(s) na planilha.")
        except Exception as e:
            print(f"  ⚠️  Lembrete enviado, mas não consegui marcar a planilha: {e}")


# ====================================================================
# ── ATALHO ───────────────────────────────────────────────────────────
# ====================================================================

def rotinas_telegram(token: str, chat_id: str) -> None:
    if not planilha_configurada():
        print("\n[BOTÕES/FOLLOW-UP] Planilha não configurada. Pulando.")
        return
    rotinas = [processar_cliques, validar_comprovantes, lembretes_followup, lembretes_agendados]
    try:
        from curriculo import gerar_curriculos_pendentes  # importado aqui para evitar import circular
        rotinas.insert(1, gerar_curriculos_pendentes)       # depois dos cliques, antes da validação
    except Exception as e:
        print(f"  ⚠️  Currículo adaptado indisponível: {type(e).__name__}: {e}")
    for rotina in rotinas:
        try:
            rotina(token, chat_id)
        except Exception as e:
            print(f"  ⚠️  {rotina.__name__} falhou: {type(e).__name__}: {e}")


if __name__ == "__main__":  # python telegram_acoes.py  → só processa cliques, comprovantes e lembretes
    rotinas_telegram(os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID"))
