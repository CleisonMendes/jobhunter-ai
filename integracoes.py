"""
RADAR DE VAGAS — integracoes.py
  • buscar_vagas_gupy(): endpoint atualizado (o antigo retorna 404)
  • registrar_na_planilha(): grava vagas aderentes na planilha Gestão de Vagas (PDA)

Variáveis de ambiente (segredos do GitHub):
  GOOGLE_CREDENTIALS  → conteúdo inteiro do JSON da conta de serviço
  SHEET_ID            → ID da planilha (trecho do link entre /d/ e /edit)
  SHEET_ABA           → (opcional) nome da aba, padrão "Vagas"
  SCORE_MIN_PLANILHA  → (opcional) score mínimo para entrar na planilha, padrão 60
Se GOOGLE_CREDENTIALS ou SHEET_ID não existirem, a planilha é simplesmente ignorada.
"""

import os
import re
import json
import unicodedata
import requests


# ====================================================================
# ── GUPY (endpoint novo) ─────────────────────────────────────────────
# ====================================================================

def buscar_vagas_gupy(termo: str, limite: int = 20) -> list[dict]:
    """Endpoint público do portal.gupy.io (o domínio portal.api.gupy.io não responde mais)."""
    print(f"\n🔍 [Gupy] Buscando: '{termo}'...")
    url = "https://employability-portal.gupy.io/api/v1/jobs"
    params = {"jobName": termo, "limit": limite, "offset": 0}
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=20)
        resp.raise_for_status()
        corpo = resp.json()
        itens = corpo.get("data") or corpo.get("results") or []
    except Exception as e:
        print(f"   ⚠️  Erro Gupy: {e}")
        return []

    vagas = []
    for item in itens:
        remoto = item.get("isRemoteWork") or item.get("workplaceType") == "remote"
        cidade_estado = ", ".join(filter(None, [item.get("city"), item.get("state")]))
        vagas.append({
            "titulo":  item.get("name", ""),
            "empresa": item.get("careerPageName") or item.get("companyName", ""),
            "local":   "Remoto" if remoto else (cidade_estado or "Brasil"),
            "fonte":   "Gupy",
            "link":    item.get("applyUrl") or item.get("jobUrl", ""),
        })
    print(f"   ✅ {len(vagas)} vaga(s) encontrada(s)")
    return vagas


# ====================================================================
# ── GOOGLE SHEETS ────────────────────────────────────────────────────
# ====================================================================

PRIMEIRA_LINHA_DADOS = 5  # cabeçalho na linha 4


def _normalizar(txt: str) -> str:
    txt = unicodedata.normalize("NFD", (txt or "").lower())
    return "".join(c for c in txt if unicodedata.category(c) != "Mn")


def _aderencia(score: int) -> str:
    """Regra das 3 cores do PDA aplicada ao score da IA."""
    if score >= 60:
        return f"🟢 {score}%"
    if score >= 40:
        return f"🟡 {score}%"
    return f"🔴 {score}%"


def _modelo(vaga: dict) -> str:
    texto = _normalizar(vaga.get("local", "")) + " " + _normalizar(vaga.get("titulo", ""))
    if "remoto" in texto or "remote" in texto or "home office" in texto:
        return "Remoto"
    if "hibrido" in texto or "hybrid" in texto:
        return "Híbrido"
    return "Presencial"


def _eh_post(vaga: dict) -> bool:
    return ("post" in _normalizar(vaga.get("fonte", ""))
            or "postagem" in _normalizar(vaga.get("empresa", "")))


_CARGO = re.compile(
    r"\b(analista|assistente|auxiliar|especialista|coordenador(?:a)?|gerente|consultor(?:a)?|"
    r"desenvolvedor(?:a)?|engenheiro(?:a)?|tecnico|estagiario(?:a)?|supervisor(?:a)?)\b[^.\n|!•–-]{0,60}",
    re.IGNORECASE,
)


def _limpar_texto(txt: str) -> str:
    """Tira '[POST]', hashtags, emojis e espaços sobrando."""
    t = re.sub(r"^\s*\[post\]\s*", "", txt or "", flags=re.IGNORECASE)
    t = re.sub(r"#\w+", " ", t)
    t = "".join(c for c in t if unicodedata.category(c) not in ("So", "Sk", "Cs", "Cn"))
    return re.sub(r"\s+", " ", t).strip(" -–|:•")


def _titulo_planilha(vaga: dict) -> str:
    """Só o nome da vaga. Posts do LinkedIn trazem o texto da postagem, então são limpos."""
    ia = (vaga.get("titulo_limpo") or "").strip()
    if ia:
        return ia[:90]
    titulo = vaga.get("titulo", "")
    if not _eh_post(vaga):
        return titulo
    limpo = _limpar_texto(titulo)
    achado = _CARGO.search(limpo)
    cargo = achado.group(0) if achado else limpo
    cargo = re.split(r"\s+(?:na|no|em|para|pela|pelo|pra)\s+", cargo, maxsplit=1, flags=re.IGNORECASE)[0]
    cargo = cargo.strip(" -–|:•")[:80]
    letras = [c for c in cargo if c.isalpha()]
    if letras and sum(c.isupper() for c in letras) / len(letras) > 0.8:  # caixa alta -> Título
        cargo = cargo.title()
    return cargo or "Vaga divulgada no LinkedIn (ver link)"


def _empresa_planilha(vaga: dict) -> str:
    """Nunca grava 'Postagem do LinkedIn' como empresa: usa a citada no texto ou deixa em branco."""
    citada = (vaga.get("empresa_citada") or "").strip()
    if citada:
        return citada
    empresa = vaga.get("empresa", "")
    return "" if "postagem" in _normalizar(empresa) else empresa


def _fonte_planilha(vaga: dict) -> str:
    fonte = vaga.get("fonte", "Radar de Vagas")
    return "LinkedIn" if "linkedin" in _normalizar(fonte) else fonte


def _linha_planilha(vaga: dict) -> list:
    """14 colunas, de B a O, na ordem da planilha Gestão de Vagas."""
    try:
        score = int(vaga.get("match_score", 0))
    except (TypeError, ValueError):
        score = 0
    return [
        _titulo_planilha(vaga),                    # B  Título da Vaga
        vaga.get("link", ""),                      # C  Link da vaga
        _empresa_planilha(vaga),                   # D  Nome da Empresa
        _aderencia(score),                         # E  Aderência Vaga
        "Prevenção a Fraude / Backoffice",         # F  Área/Ramo de atuação
        _modelo(vaga),                             # G  Modelo de Trabalho
        _fonte_planilha(vaga),                     # H  Onde encontrei essa vaga?
        "",                                        # I  Quando me inscrevi (preencha ao aplicar)
        "Inscrição",                               # J  Fase do processo
        "Não",                                     # K  Alguma ação é necessária?
        "",                                        # L  Qual ação
        "",                                        # M  Prazo
        "Em andamento",                            # N  Status
        "",                                        # O  Feedback
    ]


def _abrir_aba():
    cred = (os.environ.get("GOOGLE_CREDENTIALS") or "").strip()
    sheet_id = (os.environ.get("SHEET_ID") or "").strip()
    if not cred or not sheet_id:
        return None
    import gspread
    from google.oauth2.service_account import Credentials

    escopos = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(json.loads(cred), scopes=escopos)
    gc = gspread.authorize(creds)
    return gc.open_by_key(sheet_id).worksheet(os.environ.get("SHEET_ABA", "Vagas").strip())


def _email_conta_servico() -> str:
    """E-mail da conta de serviço (não é segredo) para facilitar a conferência do compartilhamento."""
    try:
        return json.loads(os.environ.get("GOOGLE_CREDENTIALS", "")).get("client_email", "")
    except Exception:
        return ""


def registrar_na_planilha(vagas: list[dict]) -> None:
    """Acrescenta vagas aderentes e inéditas abaixo da última linha preenchida da coluna B.
    Nunca mexe na coluna A (numeração) nem nas linhas existentes."""
    print("\n[PLANILHA] Registrando vagas aderentes no Google Sheets...")

    try:
        aba = _abrir_aba()
    except Exception as e:
        print(f"  ❌ Não foi possível abrir a planilha ({type(e).__name__}): {e!r}")
        email = _email_conta_servico()
        if email:
            print(f"     → Compartilhe a planilha como Editor com: {email}")
        print("     → Confira também se o SHEET_ID está correto e se a aba se chama 'Vagas'.")
        return
    if aba is None:
        print("  ⚠️  GOOGLE_CREDENTIALS / SHEET_ID não definidos. Planilha ignorada.")
        return

    try:
        score_min = int(os.environ.get("SCORE_MIN_PLANILHA", "60"))
    except ValueError:
        score_min = 60

    candidatas = [v for v in vagas if (v.get("match_score") or 0) >= score_min and v.get("link")]
    if not candidatas:
        print(f"  🤫 Nenhuma vaga com score >= {score_min}. Nada a registrar.")
        return

    try:
        col_b = aba.col_values(2)  # índice 0 = linha 1
        col_c = aba.col_values(3)
        links_existentes = {c.strip() for c in col_c[PRIMEIRA_LINHA_DADOS - 1:] if c.strip()}

        novas = [v for v in candidatas if v["link"].strip() not in links_existentes]
        if not novas:
            print("  🤫 Todas as vagas já estão na planilha.")
            return

        ultima_preenchida = PRIMEIRA_LINHA_DADOS - 1
        for i, valor in enumerate(col_b, start=1):
            if i >= PRIMEIRA_LINHA_DADOS and valor.strip():
                ultima_preenchida = i
        proxima = ultima_preenchida + 1

        linhas = [_linha_planilha(v) for v in novas]
        fim = proxima + len(linhas) - 1
        if fim > aba.row_count:
            aba.add_rows(fim - aba.row_count)

        aba.update(range_name=f"B{proxima}:O{fim}", values=linhas,
                   value_input_option="USER_ENTERED")
        print(f"  ✅ {len(linhas)} vaga(s) registrada(s) nas linhas {proxima} a {fim}")
    except Exception as e:
        print(f"  ❌ Erro ao gravar na planilha: {e}")
