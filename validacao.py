"""
==============================================
  RADAR DE VAGAS — validacao.py
  Validação de candidatura por COMPROVANTE
  (print da candidatura OU e-mail da empresa)
==============================================
Todo o estado da validação fica NA PLANILHA (nada de banco SQLite), então funciona
em qualquer workflow do GitHub Actions, mesmo os que não salvam o banco.

Fluxo:
  1. Você clica em "Me candidatei" no Telegram  →  o telegram_acoes.py chama
     iniciar_validacao(link, titulo, empresa).
     A vaga fica "⏳ Aguardando comprovação" e o bot pede o comprovante.
  2. Você RESPONDE à mensagem do bot com:
       • um print (imagem) da tela de confirmação / "minhas candidaturas", ou
       • o e-mail da empresa (cole o texto, ou envie PDF/print do e-mail).
     A IA classifica o material e só aceita se ele provar que a candidatura
     existe para AQUELA vaga:
       ✅ candidatura_enviada   → "recebemos sua candidatura", "agradecemos por se candidatar"
       ✅ retorno_do_processo   → avanço de fase, testes, entrevista, ou encerramento da vaga
       ❌ cadastro_conta, ativacao_pendente, vaga_ou_formulario, ilegivel, outro
     Também rejeita o mesmo comprovante reaproveitado em outra vaga (hash SHA-256).
  3. Em paralelo, se o Gmail estiver configurado, o robô procura sozinho o
     e-mail da empresa e valida a vaga.
  4. Passou do prazo sem comprovante → "⚠️ Sem comprovante".
  5. Só quando validada, a data de inscrição (coluna I) é preenchida.

Planilha "Gestão de Vagas":
  P = Status da validação
  Q = Comprovante (método · data · tipo · hash)
  R = Controle (uso interno: "id da mensagem do bot|data do pedido") → NÃO EDITE; pode ocultar a coluna
  (proteja P:R no Google Sheets para só a conta de serviço escrever)

O arquivo do print não é guardado no servidor: o comprovante continua na conversa do
Telegram e a planilha guarda o hash dele.

Variáveis de ambiente:
  TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, GEMINI_API_KEY, GOOGLE_CREDENTIALS, SHEET_ID
  VALIDACAO_PRAZO_HORAS   prazo para enviar o comprovante (padrão 48)
  Opcionais (validação automática pelo Gmail, escopo gmail.readonly):
  GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN

Ligações (feitas no telegram_acoes.py):
  • botão "Me candidatei"                →  iniciar_validacao(link, titulo, empresa)
  • mensagens recebidas no Telegram      →  processar_update(update)
  • a cada rodada                        →  verificar_emails_pendentes() e expirar_pendentes()
"""

import os
import re
import sys
import json
import hashlib
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

MODELO       = "gemini-2.5-flash"
HORAS_PRAZO  = int(os.environ.get("VALIDACAO_PRAZO_HORAS", "48"))
PENDENTES    = ("aguardando", "recusada")

# Colunas da planilha (A = 1)
COL_TITULO, COL_LINK, COL_EMPRESA = 2, 3, 4      # B, C, D
COL_STATUS, COL_COMPROVANTE, COL_CONTROLE = 16, 17, 18   # P, Q, R

# Tipos de material que a IA pode devolver e que PROVAM a candidatura.
# Para aceitar só confirmações de envio, deixe apenas "candidatura_enviada".
TIPOS_VALIDOS = ("candidatura_enviada", "retorno_do_processo")

STATUS_TXT = {
    "aguardando": "⏳ Aguardando comprovação",
    "print":      "✅ Validada (print)",
    "email":      "✅ Validada (e-mail)",
    "recusada":   "❌ Comprovante recusado",
    "expirada":   "⚠️ Sem comprovante",
}
ROTULO_CHAVE = {texto: chave for chave, texto in STATUS_TXT.items()}

# Assuntos/trechos de e-mails da empresa que indicam candidatura ou andamento do processo
CONFIRMACAO = (r"recebemos (a )?sua candidatura|candidatura (enviada|recebida|realizada)|"
               r"application (received|submitted)|we received your application|thank you for applying|"
               r"agradecemos por se candidatar|obrigad[oa] por se candidatar|"
               r"pr[oó]xima fase|processo seletivo|vaga finalizada|n[aã]o daremos continuidade")


def _agora() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def _hoje_br() -> str:
    """Data de hoje no horário de Brasília (o GitHub Actions roda em UTC)."""
    return (datetime.utcnow() - timedelta(hours=3)).strftime("%d/%m/%Y")


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
# ── PLANILHA (É AQUI QUE FICA O ESTADO) ──────────────────────────────
# ====================================================================

def _aba_ou_none():
    try:
        return _abrir_aba()
    except Exception as e:
        print(f"  ❌ Não foi possível abrir a planilha: {e}")
        return None


def _celula(linha: list, col: int) -> str:
    return linha[col - 1].strip() if len(linha) >= col else ""


def _ler_linhas(aba) -> list:
    """Lê as vagas da planilha com o estado da validação (colunas P, Q e R)."""
    valores = aba.get_all_values()
    saida = []
    for n in range(PRIMEIRA_LINHA_DADOS, len(valores) + 1):
        l = valores[n - 1]
        link = _celula(l, COL_LINK)
        if not link:
            continue
        saida.append({
            "linha":       n,
            "link":        link,
            "titulo":      _celula(l, COL_TITULO),
            "empresa":     _celula(l, COL_EMPRESA),
            "status":      ROTULO_CHAVE.get(_celula(l, COL_STATUS), ""),
            "comprovante": _celula(l, COL_COMPROVANTE),
            "controle":    _celula(l, COL_CONTROLE),
        })
    return saida


def _gravar(aba, linha: int, status: str, comprovante: str = "",
            controle: str = None, data: bool = False) -> None:
    """Atualiza P e Q (e R, se informado). Com data=True, preenche a coluna I (inscrição)."""
    dados = [{"range": f"P{linha}:Q{linha}", "values": [[STATUS_TXT[status], comprovante]]}]
    if controle is not None:
        dados.append({"range": f"R{linha}", "values": [[controle]]})
    if data:
        dados.append({"range": f"I{linha}", "values": [[_hoje_br()]]})
    try:
        aba.batch_update(dados, value_input_option="USER_ENTERED")
    except Exception as e:
        print(f"  ❌ Erro ao atualizar a planilha (linha {linha}): {e}")


# ====================================================================
# ── IA: CLASSIFICA O MATERIAL E CONFERE SE COMPROVA ──────────────────
# ====================================================================

def _analisar_comprovante(conteudo, mime: str, titulo: str, empresa: str) -> dict:
    """conteudo: bytes (imagem/PDF) ou str (texto de e-mail).
    Retorna dict com 'comprova' = True/False, ou None se a IA estiver indisponível."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"comprova": None, "motivo": "GEMINI_API_KEY ausente"}

    motivos = {
        "cadastro_conta":     "É confirmação de cadastro/conta, não de candidatura enviada.",
        "ativacao_pendente":  "A candidatura ainda precisa ser ativada ou concluída.",
        "vaga_ou_formulario": "É a página da vaga ou um formulário, sem candidatura enviada.",
        "ilegivel":           "Material ilegível, cortado ou com sinais de edição.",
        "outro":              "O material não trata de uma candidatura sua a essa vaga.",
    }

    prompt = f"""Você valida comprovantes de candidatura a vagas de emprego.
Vaga esperada: "{titulo}" na empresa "{empresa}".

Classifique o material e responda APENAS com um JSON válido:
{{"tipo": "candidatura_enviada", "corresponde_vaga": true, "empresa_visivel": "", "vaga_visivel": "", "data_visivel": "", "motivo": "frase curta"}}

Valores permitidos para "tipo":
- "candidatura_enviada": o material afirma de forma explícita que a candidatura a uma vaga
  foi ENVIADA ou RECEBIDA (ex.: "recebemos sua candidatura", "agradecemos por se candidatar",
  "application received", ou a vaga listada em 'minhas candidaturas' com status de candidatura).
- "retorno_do_processo": mensagem da empresa sobre o processo seletivo DO CANDIDATO nessa vaga:
  avanço de fase, testes ou entrevista agendada, ou encerramento da vaga / retorno negativo
  ("não daremos continuidade ao seu processo"). Prova que a candidatura existiu.
- "cadastro_conta": confirmação de cadastro, criação de conta, verificação de e-mail ou login.
- "ativacao_pendente": pede para o candidato concluir, ativar ou completar a candidatura.
- "vaga_ou_formulario": página da vaga, formulário em branco ou botão 'Candidatar-se'.
- "ilegivel": ilegível, cortado demais ou com sinais de edição.
- "outro": newsletter, alerta de vagas, propaganda ou qualquer e-mail que não trate da
  candidatura ou do processo do candidato.

Seja rigoroso: se houver qualquer sinal de que a candidatura ainda precisa ser ativada,
concluída ou confirmada pelo candidato, NÃO use "candidatura_enviada".

"corresponde_vaga": true somente se a empresa OU o cargo do material corresponderem à vaga esperada.
Quando o e-mail vem de uma plataforma de recrutamento (inHire, Gupy, Greenhouse, Lever etc.),
a empresa pode não aparecer no texto: nesse caso confira o cargo e o remetente."""

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
        analise = json.loads(achado.group(0))
    except Exception as e:
        print(f"  ⚠️  IA indisponível: {str(e)[:80]}")
        return {"comprova": None, "motivo": "IA indisponível"}

    tipo = analise.get("tipo")
    corresponde = bool(analise.get("corresponde_vaga"))
    analise["comprova"] = (tipo in TIPOS_VALIDOS) and corresponde

    if not analise["comprova"]:
        if tipo in TIPOS_VALIDOS:
            analise["motivo"] = "O comprovante parece ser de outra vaga ou empresa."
        else:
            analise["motivo"] = (motivos.get(tipo) or analise.get("motivo")
                                 or "Não comprova uma candidatura enviada.")
    return analise


# ====================================================================
# ── PASSO 1: "ME CANDIDATEI" → PEDE O COMPROVANTE ────────────────────
# ====================================================================

def iniciar_validacao(link: str, titulo: str, empresa: str) -> None:
    """Chame no handler do botão 'Me candidatei'."""
    aba = _aba_ou_none()
    if aba is None:
        return
    alvo = next((x for x in _ler_linhas(aba) if x["link"].strip() == link.strip()), None)
    if alvo is None:
        print("  ⚠️  Vaga não encontrada na planilha para iniciar a validação.")
        return
    if alvo["status"] in ("print", "email"):
        return  # já validada

    msg_id = _enviar(
        f"📎 Comprovante pendente\n{titulo} — {empresa}\n\n"
        "Responda a ESTA mensagem com o print da candidatura (tela de confirmação) "
        "ou com o e-mail da empresa (cole o texto, PDF ou print).\n"
        f"Prazo: {HORAS_PRAZO}h."
    )
    _gravar(aba, alvo["linha"], "aguardando", "", controle=f"{msg_id}|{_agora()}")


# ====================================================================
# ── PASSO 2: RECEBE O COMPROVANTE PELO TELEGRAM ──────────────────────
# ====================================================================

def _vaga_alvo(linhas: list, msg: dict):
    """Descobre a qual vaga o comprovante pertence."""
    resp_a = (msg.get("reply_to_message") or {}).get("message_id")
    if resp_a:
        for x in linhas:
            if x["controle"].split("|")[0] == str(resp_a):
                return x
    pend = [x for x in linhas if x["status"] in PENDENTES]
    return pend[0] if len(pend) == 1 else None


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
    aba = _aba_ou_none()
    if aba is None:
        _enviar("⚠️ Não consegui acessar a planilha agora. Reenvie o comprovante mais tarde.", msg_id)
        return True

    linhas = _ler_linhas(aba)
    alvo = _vaga_alvo(linhas, msg)
    if not alvo:
        _enviar("Não sei a qual vaga esse comprovante pertence. Responda diretamente à "
                "mensagem '📎 Comprovante pendente' da vaga.", msg_id)
        return True
    linha, titulo, empresa = alvo["linha"], alvo["titulo"], alvo["empresa"]

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

    # ── Anti-reaproveitamento (o hash fica na coluna Q das vagas já validadas) ──
    bruto = conteudo if isinstance(conteudo, bytes) else conteudo.encode()
    digest = hashlib.sha256(bruto).hexdigest()
    marca = f"sha:{digest[:16]}"
    outro = next((x for x in linhas if marca in x["comprovante"] and x["linha"] != linha), None)
    if outro:
        _enviar(f"❌ Esse comprovante já foi usado na vaga '{outro['titulo']}'. "
                "Cada candidatura precisa do seu próprio comprovante.", msg_id)
        return True

    # ── IA confere ──
    analise = _analisar_comprovante(conteudo, mime, titulo, empresa)
    if analise.get("comprova") is None:
        _enviar("⚠️ Não consegui analisar agora. Reenvie o comprovante em alguns minutos.", msg_id)
        return True

    if not analise.get("comprova"):
        motivo = analise.get("motivo", "não comprova a candidatura")
        _gravar(aba, linha, "recusada", motivo[:120])
        _enviar(f"❌ Comprovante recusado: {motivo}\nEnvie outro (tela de confirmação ou "
                "e-mail da empresa).", msg_id)
        return True

    # ── Validada ──
    metodo = "print" if mime.startswith("image/") else "email"
    comprovante = f"{metodo} · {_hoje_br()} · {analise.get('tipo', '')} · {marca}"
    _gravar(aba, linha, metodo, comprovante, data=True)
    _enviar(f"✅ Candidatura validada ({metodo})!\n{titulo} — {empresa}", msg_id)
    return True


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
    q = (f'newer_than:30d "{termo}" '
         '(candidatura OR application OR inscrição OR processo OR "próxima fase" '
         'OR "thank you for applying")')
    try:
        r = requests.get(base, headers=cab, params={"q": q, "maxResults": 8}, timeout=20)
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
    aba = _aba_ou_none()
    if aba is None:
        return

    for x in _ler_linhas(aba):
        if x["status"] not in PENDENTES:
            continue
        achou = _buscar_email(token, x["empresa"], x["titulo"])
        if not achou:
            continue
        _gravar(aba, x["linha"], "email", f"e-mail · {_hoje_br()} · Gmail:{achou['id']}", data=True)
        _enviar(f"✅ Validada automaticamente pelo e-mail da empresa:\n{x['titulo']} — {x['empresa']}")
        print(f"  ✅ Gmail validou: {x['titulo'][:40]}")


# ====================================================================
# ── PASSO 4: PRAZO ───────────────────────────────────────────────────
# ====================================================================

def expirar_pendentes() -> None:
    limite = datetime.utcnow() - timedelta(hours=HORAS_PRAZO)
    aba = _aba_ou_none()
    if aba is None:
        return

    for x in _ler_linhas(aba):
        if x["status"] not in PENDENTES:
            continue
        partes = x["controle"].split("|")
        if len(partes) < 2:
            continue
        try:
            criada = datetime.fromisoformat(partes[1])
        except ValueError:
            continue
        if criada < limite:
            _gravar(aba, x["linha"], "expirada")
            _enviar(f"⚠️ Prazo do comprovante encerrado:\n{x['titulo']} — {x['empresa']}")
            print(f"  ⚠️  Expirou: {x['titulo'][:40]}")


# ====================================================================
# ── EXECUÇÃO ─────────────────────────────────────────────────────────
# ====================================================================

def main() -> None:
    print("\n[VALIDAÇÃO] Conferindo comprovantes pendentes...")
    verificar_emails_pendentes()
    expirar_pendentes()


if __name__ == "__main__":
    main()
