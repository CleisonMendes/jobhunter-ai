"""
==============================================
  RADAR DE VAGAS — validacao.py
  Validação de candidatura por COMPROVANTE
  (print da candidatura OU e-mail de confirmação)
==============================================
Fluxo:
  1. Você clica em "Me candidatei" no Telegram  →  o handler chama
     iniciar_validacao(link, titulo, empresa).
     A vaga fica "⏳ Aguardando comprovação" e o bot pede o comprovante.
  2. Você RESPONDE à mensagem do bot com:
       • um print (imagem) da tela de confirmação / "minhas candidaturas", ou
       • o e-mail de confirmação (cole o texto, ou envie PDF/print do e-mail).
     A IA confere se o material realmente comprova uma candidatura ENVIADA
     para aquela empresa/vaga. Também rejeita o mesmo arquivo reaproveitado
     em outra vaga (hash SHA-256).
  3. Em paralelo, se o Gmail estiver configurado, o robô procura sozinho o
     e-mail de confirmação da empresa e valida a vaga.
  4. Passou do prazo sem comprovante → "⚠️ Sem comprovante".

Planilha "Gestão de Vagas" — crie 2 colunas novas:
  Q = Status da validação      R = Comprovante
  (proteja Q:R no Google Sheets para só a conta de serviço escrever)

Variáveis de ambiente:
  TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, GEMINI_API_KEY, GOOGLE_CREDENTIALS, SHEET_ID  (já existentes)
  VALIDACAO_PRAZO_HORAS   prazo para enviar o comprovante (padrão 48)
  Opcionais (validação automática pelo Gmail, escopo gmail.readonly):
  GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN

Como ligar ao que você já tem:
  • No handler do botão "Me candidatei":      iniciar_validacao(link, titulo, empresa)
  • No loop que já lê os updates do Telegram: processar_update(update)
    (se NENHUM código seu lê getUpdates, rode:  python validacao.py --polling)
  • Em toda rodada do robô:                    python validacao.py
"""

import os
import re
import sys
import json
import sqlite3
import hashlib
import argparse
import requests
from datetime import datetime, timedelta
from pathlib import Path

for _pasta in ("fase1_mvp", "fase2_filtro", "fase3_perfil"):
    sys.path.append(str(Path(__file__).parent / _pasta))

from google import genai
from google.genai import types
from integracoes import _abrir_aba, _normalizar, PRIMEIRA_LINHA_DADOS


# ====================================================================
# ── CONFIGURAÇÃO ─────────────────────────────────────────────────────
# ====================================================================

DB           = "vagas_enviadas.db"
PASTA        = Path("comprovantes")
MODELO       = "gemini-2.5-flash"
HORAS_PRAZO  = int(os.environ.get("VALIDACAO_PRAZO_HORAS", "48"))
COL_LINK     = 3                      # C
PENDENTES    = ("aguardando", "recusada")

STATUS_TXT = {
    "aguardando": "⏳ Aguardando comprovação",
    "print":      "✅ Validada (print)",
    "email":      "✅ Validada (e-mail)",
    "recusada":   "❌ Comprovante recusado",
    "expirada":   "⚠️ Sem comprovante",
}

CONFIRMACAO = r"candidatura|application|inscri[cç][aã]o|recebemos|thank you for applying|obrigad"


def _agora() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


# ====================================================================
# ── BANCO ────────────────────────────────────────────────────────────
# ====================================================================

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS validacoes (
            link        TEXT PRIMARY KEY,
            titulo      TEXT,
            empresa     TEXT,
            status      TEXT DEFAULT 'aguardando',
            metodo      TEXT,
            hash        TEXT,
            msg_id      INTEGER,
            criada_em   TEXT,
            validada_em TEXT,
            detalhe     TEXT
        )
    """)
    conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
    conn.commit()
    return conn


# ====================================================================
# ── TELEGRAM ─────────────────────────────────────────────────────────
# ====================================================================

def _tg(metodo: str, **dados) -> dict:
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        return {}
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/{metodo}", json=dados, timeout=30)
        return r.json()
    except Exception as e:
        print(f"  ❌ Telegram ({metodo}): {e}")
        return {}


def _enviar(texto: str, reply_to: int = None):
    dados = {"chat_id": os.environ.get("TELEGRAM_CHAT_ID"), "text": texto,
             "disable_web_page_preview": True}
    if reply_to:
        dados["reply_to_message_id"] = reply_to
    resp = _tg("sendMessage", **dados)
    return (resp.get("result") or {}).get("message_id")


def _baixar(file_id: str):
    info = _tg("getFile", file_id=file_id)
    caminho = (info.get("result") or {}).get("file_path")
    if not caminho:
        return None
    try:
        r = requests.get(f"https://api.telegram.org/file/bot{os.environ.get('TELEGRAM_TOKEN')}/{caminho}",
                         timeout=60)
        return r.content if r.ok else None
    except Exception:
        return None


# ====================================================================
# ── PLANILHA ─────────────────────────────────────────────────────────
# ====================================================================

def _atualizar_planilha(link: str, status: str, comprovante: str = "") -> None:
    try:
        aba = _abrir_aba()
        if aba is None:
            return
        for i, valor in enumerate(aba.col_values(COL_LINK), start=1):
            if i >= PRIMEIRA_LINHA_DADOS and valor.strip() == link.strip():
                aba.update(range_name=f"P{i}:Q{i}",
                           values=[[STATUS_TXT[status], comprovante]])
                return
        print("  ⚠️  Vaga não encontrada na planilha para atualizar a validação.")
    except Exception as e:
        print(f"  ❌ Erro ao atualizar a planilha: {e}")


# ====================================================================
# ── IA: CONFERE SE O MATERIAL REALMENTE COMPROVA ─────────────────────
# ====================================================================

def _analisar_comprovante(conteudo, mime: str, titulo: str, empresa: str) -> dict:
    """conteudo: bytes (imagem/PDF) ou str (texto de e-mail).
    Retorna dict com 'comprova' = True/False, ou None se a IA estiver indisponível."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"comprova": None, "motivo": "GEMINI_API_KEY ausente"}

    prompt = f"""Você valida comprovantes de candidatura a vagas de emprego.
Vaga esperada: "{titulo}" na empresa "{empresa}".

Analise o material e responda APENAS com um JSON válido:
{{"comprova": true, "empresa_visivel": "", "vaga_visivel": "", "data_visivel": "", "motivo": "frase curta"}}

Regras:
- "comprova" só é true se o material mostrar claramente uma candidatura ENVIADA ou RECEBIDA
  (tela de confirmação, e-mail de confirmação ou lista de 'minhas candidaturas')
  E a empresa OU o cargo corresponderem à vaga esperada.
- Página da vaga, formulário em branco ou botão 'Candidatar-se' NÃO comprovam.
- Material ilegível, cortado demais ou com sinais de edição: false."""

    if isinstance(conteudo, bytes):
        partes = [types.Part.from_bytes(data=conteudo, mime_type=mime), prompt]
    else:
        partes = [prompt + "\n\nMATERIAL (texto do e-mail):\n" + conteudo[:6000]]

    try:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(model=MODELO, contents=partes)
        achado = re.search(r"\{.*\}", resp.text or "", re.DOTALL)
        if not achado:
            return {"comprova": None, "motivo": "resposta da IA inválida"}
        return json.loads(achado.group(0))
    except Exception as e:
        print(f"  ⚠️  IA indisponível: {str(e)[:80]}")
        return {"comprova": None, "motivo": "IA indisponível"}


# ====================================================================
# ── PASSO 1: "ME CANDIDATEI" → PEDE O COMPROVANTE ────────────────────
# ====================================================================

def iniciar_validacao(link: str, titulo: str, empresa: str) -> None:
    """Chame no handler do botão 'Me candidatei'."""
    conn = _db()
    ja = conn.execute("SELECT status FROM validacoes WHERE link = ?", (link,)).fetchone()
    if ja and ja[0] in ("print", "email"):
        conn.close()
        return

    msg_id = _enviar(
        f"📎 Comprovante pendente\n{titulo} — {empresa}\n\n"
        "Responda a ESTA mensagem com o print da candidatura (tela de confirmação) "
        "ou com o e-mail de confirmação (cole o texto, PDF ou print).\n"
        f"Prazo: {HORAS_PRAZO}h."
    )
    conn.execute("""INSERT OR REPLACE INTO validacoes
                    (link, titulo, empresa, status, msg_id, criada_em)
                    VALUES (?, ?, ?, 'aguardando', ?, ?)""",
                 (link, titulo, empresa, msg_id, _agora()))
    conn.commit()
    conn.close()
    _atualizar_planilha(link, "aguardando")


# ====================================================================
# ── PASSO 2: RECEBE O COMPROVANTE PELO TELEGRAM ──────────────────────
# ====================================================================

def _vaga_alvo(conn, msg: dict):
    """Descobre a qual vaga o comprovante pertence."""
    resp_a = (msg.get("reply_to_message") or {}).get("message_id")
    if resp_a:
        linha = conn.execute("SELECT link, titulo, empresa FROM validacoes WHERE msg_id = ?",
                             (resp_a,)).fetchone()
        if linha:
            return linha
    marcas = ",".join("?" * len(PENDENTES))
    pend = conn.execute(f"SELECT link, titulo, empresa FROM validacoes WHERE status IN ({marcas})",
                        PENDENTES).fetchall()
    return pend[0] if len(pend) == 1 else None


def _salvar_arquivo(link: str, dados, mime: str) -> str:
    PASTA.mkdir(exist_ok=True)
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}.get(mime, ".txt")
    slug = re.sub(r"\W+", "-", link)[-40:].strip("-")
    caminho = PASTA / f"{datetime.utcnow():%Y%m%d}_{slug}{ext}"
    caminho.write_bytes(dados if isinstance(dados, bytes) else dados.encode())
    return str(caminho)


def processar_update(update: dict) -> bool:
    """Trata uma mensagem com comprovante. Retorna True se o update era um comprovante."""
    msg = update.get("message") or {}
    if not msg or str(msg.get("chat", {}).get("id")) != str(os.environ.get("TELEGRAM_CHAT_ID")):
        return False

    foto, doc = msg.get("photo"), msg.get("document")
    texto = (msg.get("text") or msg.get("caption") or "").strip()
    eh_texto_email = bool(texto) and not texto.startswith("/") and len(texto) > 80
    if not (foto or doc or eh_texto_email):
        return False

    msg_id = msg["message_id"]
    conn = _db()
    try:
        alvo = _vaga_alvo(conn, msg)
        if not alvo:
            _enviar("Não sei a qual vaga esse comprovante pertence. Responda diretamente à "
                    "mensagem '📎 Comprovante pendente' da vaga.", msg_id)
            return True
        link, titulo, empresa = alvo

        # ── Obtém o conteúdo ──
        if foto or doc:
            if foto:
                file_id, mime = foto[-1]["file_id"], "image/jpeg"
            else:
                mime = doc.get("mime_type", "")
                if not (mime.startswith("image/") or mime == "application/pdf"):
                    _enviar("Formato não aceito. Envie imagem, PDF ou cole o texto do e-mail.", msg_id)
                    return True
                file_id = doc["file_id"]
            conteudo = _baixar(file_id)
            if not conteudo:
                _enviar("Não consegui baixar o arquivo. Tente enviar de novo.", msg_id)
                return True
        else:
            conteudo, mime = texto, "text/plain"

        # ── Anti-reaproveitamento ──
        bruto = conteudo if isinstance(conteudo, bytes) else conteudo.encode()
        digest = hashlib.sha256(bruto).hexdigest()
        outro = conn.execute("SELECT titulo FROM validacoes WHERE hash = ? AND link <> ?",
                             (digest, link)).fetchone()
        if outro:
            _enviar(f"❌ Esse comprovante já foi usado na vaga '{outro[0]}'. "
                    "Cada candidatura precisa do seu próprio comprovante.", msg_id)
            return True

        # ── IA confere ──
        analise = _analisar_comprovante(conteudo, mime, titulo, empresa)
        if analise.get("comprova") is None:
            _enviar("⚠️ Não consegui analisar agora. Reenvie o comprovante em alguns minutos.", msg_id)
            return True

        if not analise.get("comprova"):
            motivo = analise.get("motivo", "não comprova a candidatura")
            conn.execute("UPDATE validacoes SET status='recusada', detalhe=? WHERE link=?",
                         (motivo, link))
            conn.commit()
            _atualizar_planilha(link, "recusada", motivo[:120])
            _enviar(f"❌ Comprovante recusado: {motivo}\nEnvie outro (tela de confirmação ou "
                    "e-mail da empresa).", msg_id)
            return True

        # ── Validada ──
        metodo = "print" if mime.startswith("image/") else "email"
        arquivo = _salvar_arquivo(link, conteudo, mime)
        conn.execute("""UPDATE validacoes SET status=?, metodo=?, hash=?, validada_em=?, detalhe=?
                        WHERE link=?""",
                     (metodo, metodo, digest, _agora(), arquivo, link))
        conn.commit()
        comprovante = f"{metodo} · {datetime.utcnow():%d/%m/%Y} · sha:{digest[:10]}"
        _atualizar_planilha(link, metodo, comprovante)
        _enviar(f"✅ Candidatura validada ({metodo})!\n{titulo} — {empresa}", msg_id)
        return True
    finally:
        conn.close()


def coletar_updates() -> None:
    """Modo --polling: lê as mensagens novas do Telegram.
    Use SÓ se nenhum outro código seu consome getUpdates (o offset é confirmado aqui)."""
    conn = _db()
    linha = conn.execute("SELECT v FROM kv WHERE k = 'offset'").fetchone()
    offset = int(linha[0]) if linha else 0
    resp = _tg("getUpdates", offset=offset, timeout=0)
    for u in resp.get("result", []):
        processar_update(u)
        offset = u["update_id"] + 1
    conn.execute("INSERT OR REPLACE INTO kv (k, v) VALUES ('offset', ?)", (str(offset),))
    conn.commit()
    conn.close()


# ====================================================================
# ── PASSO 3: VALIDAÇÃO AUTOMÁTICA PELO GMAIL ─────────────────────────
# ====================================================================

def _token_gmail():
    cid, sec, ref = (os.environ.get(k) for k in
                     ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"))
    if not (cid and sec and ref):
        return None
    try:
        r = requests.post("https://oauth2.googleapis.com/token", timeout=20, data={
            "client_id": cid, "client_secret": sec,
            "refresh_token": ref, "grant_type": "refresh_token"})
        return r.json().get("access_token") if r.ok else None
    except Exception:
        return None


def _buscar_email(token: str, empresa: str, titulo: str):
    termo = (empresa or titulo or "").replace('"', "").strip()
    if not termo:
        return None
    cab = {"Authorization": f"Bearer {token}"}
    base = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
    q = (f'newer_than:14d "{termo}" '
         '(candidatura OR application OR inscrição OR "thank you for applying")')
    try:
        r = requests.get(base, headers=cab, params={"q": q, "maxResults": 5}, timeout=20)
        if not r.ok:
            return None
        for item in r.json().get("messages", []):
            m = requests.get(f"{base}/{item['id']}", headers=cab, timeout=20,
                             params={"format": "metadata", "metadataHeaders": ["Subject", "From"]})
            if not m.ok:
                continue
            dados = m.json()
            cabs = {h["name"]: h["value"] for h in dados.get("payload", {}).get("headers", [])}
            texto = f"{cabs.get('Subject', '')} {dados.get('snippet', '')}"
            alvo = _normalizar(texto + " " + cabs.get("From", ""))
            if re.search(CONFIRMACAO, texto, re.IGNORECASE) and _normalizar(termo)[:12] in alvo:
                return {"id": item["id"], "assunto": cabs.get("Subject", ""),
                        "de": cabs.get("From", "")}
    except Exception as e:
        print(f"  ⚠️  Gmail: {e}")
    return None


def verificar_emails_pendentes() -> None:
    token = _token_gmail()
    if not token:
        print("  ℹ️  Gmail não configurado — validação automática por e-mail ignorada.")
        return

    conn = _db()
    marcas = ",".join("?" * len(PENDENTES))
    pend = conn.execute(f"SELECT link, titulo, empresa FROM validacoes WHERE status IN ({marcas})",
                        PENDENTES).fetchall()
    for link, titulo, empresa in pend:
        achou = _buscar_email(token, empresa, titulo)
        if not achou:
            continue
        comprovante = f"e-mail · {datetime.utcnow():%d/%m/%Y} · Gmail:{achou['id']}"
        conn.execute("""UPDATE validacoes SET status='email', metodo='gmail', validada_em=?, detalhe=?
                        WHERE link=?""", (_agora(), f"{achou['assunto']} | {achou['de']}", link))
        conn.commit()
        _atualizar_planilha(link, "email", comprovante)
        _enviar(f"✅ Validada automaticamente pelo e-mail de confirmação:\n{titulo} — {empresa}")
        print(f"  ✅ Gmail validou: {titulo[:40]}")
    conn.close()


# ====================================================================
# ── PASSO 4: PRAZO ───────────────────────────────────────────────────
# ====================================================================

def expirar_pendentes() -> None:
    limite = datetime.utcnow() - timedelta(hours=HORAS_PRAZO)
    conn = _db()
    marcas = ",".join("?" * len(PENDENTES))
    pend = conn.execute(f"""SELECT link, titulo, empresa, criada_em FROM validacoes
                            WHERE status IN ({marcas})""", PENDENTES).fetchall()
    for link, titulo, empresa, criada in pend:
        if criada and datetime.fromisoformat(criada) < limite:
            conn.execute("UPDATE validacoes SET status='expirada' WHERE link=?", (link,))
            conn.commit()
            _atualizar_planilha(link, "expirada")
            _enviar(f"⚠️ Prazo do comprovante encerrado:\n{titulo} — {empresa}")
            print(f"  ⚠️  Expirou: {titulo[:40]}")
    conn.close()


# ====================================================================
# ── EXECUÇÃO ─────────────────────────────────────────────────────────
# ====================================================================

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--polling", action="store_true",
                        help="lê mensagens do Telegram (use só se nenhum outro código lê getUpdates)")
    args = parser.parse_args()

    print("\n[VALIDAÇÃO] Conferindo comprovantes pendentes...")
    if args.polling:
        coletar_updates()
    verificar_emails_pendentes()
    expirar_pendentes()


if __name__ == "__main__":
    main()
