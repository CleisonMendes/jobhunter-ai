"""
RADAR DE VAGAS — paginas_vaga.py (NOVO)

  • obter_descricao(vaga)  → texto da descrição completa (Greenhouse, Gupy, Lever) ou "".
  • vaga_aberta(vaga)      → True (aberta) | False (encerrada) | None (não deu para saber).

Regra de ouro: na dúvida, devolve None e a vaga segue normalmente.
Só descarta quando tem certeza (404/410, redirecionamento de erro ou aviso de encerrada).
"""

import re
import json
import html
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; RadarDeVagas/1.0)",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}
TIMEOUT = 15
MAX_DESC = 6000  # caracteres enviados ao Gemini

_GH = re.compile(r"greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)", re.I)

MARCAS_ENCERRADA = (
    "vaga encerrada", "vaga não está mais", "vaga nao esta mais",
    "não está mais disponível", "nao esta mais disponivel",
    "inscrições encerradas", "inscricoes encerradas",
    "não aceita mais candidaturas", "nao aceita mais candidaturas",
    "no longer available", "no longer accepting", "position has been filled",
    "job is no longer", "this job has expired",
)


def _texto(htm: str) -> str:
    """HTML (ou HTML escapado) → texto simples."""
    t = html.unescape(htm or "")
    t = re.sub(r"(?is)<(script|style)\b.*?>.*?</\1>", " ", t)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</div>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t\xa0]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


def _eh_post(vaga: dict) -> bool:
    return "post" in (vaga.get("fonte") or "").lower()


# ── Greenhouse ───────────────────────────────────────────────────────
def _greenhouse(board: str, job_id: str) -> str:
    url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    if not r.ok:
        return ""
    return _texto(r.json().get("content", ""))


# ── Gupy (a página é Next.js: a vaga vem em JSON dentro de __NEXT_DATA__) ─
_CHAVES_GUPY = {"description", "responsibilities", "prerequisites",
                "additionalInformation", "relevantInformation", "benefits"}


def _achar(obj, achados: list) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _CHAVES_GUPY and isinstance(v, str) and v.strip():
                achados.append(v)
            else:
                _achar(v, achados)
    elif isinstance(obj, list):
        for item in obj:
            _achar(item, achados)


def _gupy(link: str) -> str:
    r = requests.get(link, headers=HEADERS, timeout=TIMEOUT)
    if not r.ok:
        return ""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
    if m:
        try:
            achados: list = []
            _achar(json.loads(m.group(1)), achados)
            if achados:
                return "\n\n".join(_texto(a) for a in achados)
        except Exception:
            pass
    return ""


# ── ProgramaThor (tenta o JSON-LD "JobPosting"; senão, o texto da página) ──
def _jsonld_descricao(htm: str) -> str:
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', htm, re.S | re.I):
        try:
            dados = json.loads(m.group(1))
        except Exception:
            continue
        for d in (dados if isinstance(dados, list) else [dados]):
            if isinstance(d, dict) and d.get("@type") == "JobPosting" and d.get("description"):
                return _texto(d["description"])
    return ""


def _programathor(link: str) -> str:
    r = requests.get(link, headers=HEADERS, timeout=TIMEOUT)
    if not r.ok:
        return ""
    return _jsonld_descricao(r.text) or _texto(r.text)


# ── API pública ──────────────────────────────────────────────────────
def obter_descricao(vaga: dict) -> str:
    """Descrição completa da vaga (até MAX_DESC caracteres) ou '' se não achar."""
    pronta = (vaga.get("descricao") or "").strip()  # ex.: Lever já traz
    if pronta:
        return pronta[:MAX_DESC]

    link = (vaga.get("link") or "").strip()
    if not link or _eh_post(vaga):
        return ""
    try:
        m = _GH.search(link)
        if m:
            return _greenhouse(m.group(1), m.group(2))[:MAX_DESC]
        if "gupy.io" in link:
            return _gupy(link)[:MAX_DESC]
        if "linkedin.com/jobs/view" in link:
            from linkedin_vagas import descricao_linkedin
            return descricao_linkedin(link)[:MAX_DESC]
    except Exception as e:
        print(f"     ⚠️  Descrição indisponível ({type(e).__name__}): {str(e)[:80]}")
    return ""


def vaga_aberta(vaga: dict):
    """True = aberta, False = encerrada (com certeza), None = não deu para saber."""
    link = (vaga.get("link") or "").strip()
    if not link or _eh_post(vaga):
        return None
    try:
        m = _GH.search(link)
        if m:
            r = requests.get(
                f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs/{m.group(2)}",
                headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 404:
                return False
            return True if r.ok else None

        r = requests.get(link, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    except Exception:
        return None

    if r.status_code in (404, 410):
        return False
    if not r.ok:
        return None
    if "error=true" in r.url:  # Greenhouse manda vaga fechada para ?error=true
        return False
    visivel = _texto(r.text[:300000]).lower()  # sem <script>, para não ler textos de interface
    if any(marca in visivel for marca in MARCAS_ENCERRADA):
        return False
    return True
