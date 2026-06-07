"""
==============================================
  JOBHUNTER AI — Fase 3: Perfil do Usuário
==============================================
Objetivo: Carregar e validar o perfil do
          candidato a partir do arquivo JSON.

Conceitos aprendidos nessa fase:
  - JSON (leitura de arquivos)
  - Dicionários aninhados
  - Funções com retorno tipado
  - Tratamento de erros (try/except)
  - Módulo pathlib (caminhos de arquivo)
"""

import json
from pathlib import Path


# ── Caminho do arquivo de perfil ──────────────────────────────────────────────

# Path(__file__) = caminho desse script
# .parent        = pasta onde ele está
# / "perfil.json"= arquivo na mesma pasta
ARQUIVO_PERFIL = Path(__file__).parent / "perfil.json"


# ── Funções ───────────────────────────────────────────────────────────────────

def carregar_perfil() -> dict:
    """
    Lê o arquivo perfil.json e retorna como dicionário Python.

    Retorna:
        dict: perfil completo do candidato

    Lança:
        FileNotFoundError: se o arquivo não existir
        json.JSONDecodeError: se o JSON estiver malformado
    """
    try:
        with open(ARQUIVO_PERFIL, "r", encoding="utf-8") as arquivo:
            perfil = json.load(arquivo)

        print(f"✅ Perfil carregado: {perfil['nome']}")
        return perfil

    except FileNotFoundError:
        print(f"❌ Arquivo não encontrado: {ARQUIVO_PERFIL}")
        print("💡 Crie o arquivo perfil.json na pasta fase3_perfil/")
        raise

    except json.JSONDecodeError as erro:
        print(f"❌ Erro no formato do JSON: {erro}")
        print("💡 Verifique vírgulas e chaves no perfil.json")
        raise


def exibir_perfil(perfil: dict) -> None:
    """
    Exibe o perfil de forma organizada no terminal.

    Parâmetros:
        perfil (dict): dicionário com os dados do candidato
    """
    print(f"\n{'='*60}")
    print(f"  👤 PERFIL: {perfil['nome']}")
    print(f"{'='*60}")

    print(f"\n  Cargo atual  : {perfil['cargo_atual']}")
    print(f"  Empresa      : {perfil['empresa_atual']}")
    print(f"  Experiência  : {perfil['experiencia_anos']} anos")

    # Formação
    f = perfil["formacao"]
    print(f"\n  Formação     : {f['curso']}")
    print(f"  Instituição  : {f['instituicao']} ({f['status']})")
    print(f"  Conclusão    : {f['conclusao_prevista']}")

    # Habilidades
    print(f"\n  Habilidades  :")
    for skill in perfil["habilidades"]:
        print(f"    • {skill}")

    # Certificações
    print(f"\n  Certificações:")
    for cert in perfil["certificacoes"]:
        print(f"    • {cert}")

    # Preferências
    prefs = perfil["preferencias_vaga"]
    print(f"\n  Modalidade   : {', '.join(prefs['modalidade'])}")
    print(f"  Áreas        : {', '.join(prefs['areas'])}")
    print(f"  Nível        : {', '.join(prefs['nivel'])}")
    print(f"  Salário mín. : R$ {prefs['salario_minimo']:,.0f}")


def get_habilidades(perfil: dict) -> list[str]:
    """
    Retorna lista de habilidades em minúsculo (para comparação).
    Usado pela Fase 4 (Match Score).

    Parâmetros:
        perfil (dict): perfil do candidato

    Retorna:
        list[str]: habilidades normalizadas
    """
    return [skill.lower() for skill in perfil["habilidades"]]


# ── Uso direto ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    perfil = carregar_perfil()
    exibir_perfil(perfil)

    print(f"\n\n📦 Habilidades prontas para o Match Score:")
    print(get_habilidades(perfil))
