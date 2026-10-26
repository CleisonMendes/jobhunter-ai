"""Filtro de localização.
Regra: fora do estado de São Paulo, só vagas REMOTAS / home office.
Vagas de SP (qualquer cidade do estado) passam em qualquer modelo.
Vaga sem local identificável (ex.: só "Brasil") passa, para não perder posts sem cidade.

Ajustes por variável de ambiente (opcional, no env: do workflow):
  FILTRO_LOCAL=0        desliga este filtro
"""
import os
import re
import unicodedata


def _norm(txt: str) -> str:
    t = unicodedata.normalize("NFKD", txt or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


_REMOTO = re.compile(r"\b(remoto|remota|remote|home ?office|teletrabalho|trabalho remoto|100% remoto|anywhere)\b")
_SP = re.compile(r"\bsao paulo\b|\bsp\b")
_GENERICO = {"", "brasil", "brazil", "brasil, brasil", "nao informado"}


def _classificar(vaga: dict) -> str:
    """Devolve 'remoto', 'sp', 'indefinido' ou 'fora'."""
    local = _norm(vaga.get("local", ""))
    titulo = _norm(vaga.get("titulo", ""))
    junto = f"{local} {titulo}"
    if _REMOTO.search(junto):
        return "remoto"
    if _SP.search(junto):
        return "sp"
    if local.strip() in _GENERICO:
        return "indefinido"
    return "fora"


def filtrar_por_local(vagas: list[dict]) -> list[dict]:
    if os.environ.get("FILTRO_LOCAL", "1") == "0":
        return vagas
    mantidas, fora = [], []
    for v in vagas:
        (fora if _classificar(v) == "fora" else mantidas).append(v)
    print(f"  📍 Localização: {len(mantidas)} mantida(s) (remoto ou SP) | {len(fora)} fora de SP e não remota(s) descartada(s)")
    for v in fora[:5]:
        print(f"     🚫 {v.get('titulo','')[:45]} | {v.get('local','')}")
    if len(fora) > 5:
        print(f"     … e mais {len(fora) - 5}")
    return mantidas
