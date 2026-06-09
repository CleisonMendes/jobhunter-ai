"""
==============================================
  JOBHUNTER AI — leitor_pdf.py
  Bloco 2: Migrado para google-genai (novo SDK)
==============================================
"""

import os
import json
import pypdf
from google import genai

MODELOS_FALLBACK = [
    'gemini-2.0-flash-lite',
    'gemini-2.5-flash',
    'gemini-3.5-flash',
]


def extrair_texto_pdf(caminho_pdf: str) -> str:
    """Lê as páginas do PDF e extrai o texto bruto."""
    texto = ""
    try:
        with open(caminho_pdf, "rb") as f:
            leitor = pypdf.PdfReader(f)
            for pagina in leitor.pages:
                texto_pagina = pagina.extract_text()
                if texto_pagina:
                    texto += texto_pagina + "\n"
    except Exception as e:
        print(f"  ❌ Erro ao ler o arquivo PDF: {e}")
    return texto


def processar_curriculo_com_ia(texto_cv: str) -> dict | None:
    """Envia o texto para o Gemini montar o JSON com fallback automático de modelos."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("  ⚠️  GEMINI_API_KEY não configurada. Pulando extração via IA.")
        return None

    client = genai.Client(api_key=api_key)

    prompt = f"""
    Você é um assistente de recrutamento especializado em dados. Leia o texto de um currículo e transforme-o estritamente em um JSON válido.

    Regras Críticas:
    1. Retorne APENAS o objeto JSON. Nada de formatação markdown (como ```json).
    2. Mantenha EXATAMENTE a estrutura aninhada abaixo. Não crie chaves novas, não mude o nome das chaves.

    Estrutura JSON obrigatória:
    {{
      "nome": "Nome Completo Extraído",
      "cargo_atual": "Cargo mais recente",
      "empresa_atual": "Empresa mais recente",
      "experiencia_anos": 9,
      "habilidades": ["habilidade1", "habilidade2", "python", "sql"],
      "certificacoes": ["certificacao1"],
      "formacao": {{
        "curso": "Nome do curso",
        "instituicao": "Instituição de ensino",
        "conclusao_prevista": 2028,
        "status": "em andamento ou concluído"
      }},
      "idiomas": ["idioma1", "idioma2"],
      "preferencias_vaga": {{
        "modalidade": ["remoto", "híbrido", "presencial"],
        "areas": ["antifraude", "chargeback", "dados"],
        "nivel": ["júnior", "pleno"],
        "salario_minimo": 3200
      }},
      "linkedin": "URL do linkedin se houver"
    }}

    Texto bruto do currículo:
    {texto_cv}
    """

    for nome_modelo in MODELOS_FALLBACK:
        try:
            resposta = client.models.generate_content(
                model=nome_modelo,
                contents=prompt
            )
            json_texto = resposta.text.strip()

            # Remove markdown se a IA colocar mesmo assim
            if json_texto.startswith("```"):
                json_texto = json_texto.split("\n", 1)[1].rsplit("\n", 1)[0]
            if json_texto.startswith("json"):
                json_texto = json_texto.split("\n", 1)[1]

            resultado = json.loads(json_texto.strip())
            print(f"  ✅ Currículo processado com {nome_modelo}")
            return resultado

        except Exception as e:
            print(f"  ⚠️  {nome_modelo} falhou no leitor_pdf: {e}")
            continue

    print("  ❌ Todos os modelos falharam ao processar o currículo.")
    return None


def checar_e_atualizar_perfil() -> None:
    """Procura o PDF na raiz e atualiza o json de perfil se achar."""
    caminho_pdf  = "curriculo.pdf"
    caminho_json = "fase3_perfil/perfil.json"

    if not os.path.exists(caminho_pdf):
        print("\n[FASE 3 - PDF] Nenhum 'curriculo.pdf' encontrado. Mantendo o perfil atual.")
        return

    print(f"\n[FASE 3 - PDF] Detectado '{caminho_pdf}'. Extraindo texto...")
    texto_extraido = extrair_texto_pdf(caminho_pdf)

    if not texto_extraido.strip():
        print("  ⚠️  O arquivo PDF parece ser uma imagem ou está vazio/ilegível.")
        return

    print("  🧠 Processando dados com Inteligência Artificial (Gemini)...")
    novo_perfil = processar_curriculo_com_ia(texto_extraido)

    if not novo_perfil:
        return

    try:
        with open(caminho_json, "w", encoding="utf-8") as f:
            json.dump(novo_perfil, f, ensure_ascii=False, indent=4)
        print("  ✅ perfil.json atualizado com sucesso a partir do PDF!")
    except Exception as e:
        print(f"  ❌ Erro ao salvar o novo perfil.json: {e}")