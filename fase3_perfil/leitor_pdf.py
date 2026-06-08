import os
import json
import pypdf
import google.generativeai as genai

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
    """Envia o texto para o Gemini montar o JSON mantendo a estrutura aninhada original."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("  ⚠️ GEMINI_API_KEY não configurada no ambiente. Pulando extração via IA.")
        return None

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')

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

    try:
        resposta = model.generate_content(prompt)
        json_texto = resposta.text.strip()
        
        # Remove markdown se a IA colocar
        if json_texto.startswith("```"):
            json_texto = json_texto.split("\n", 1)[1].rsplit("\n", 1)[0]
            if json_texto.startswith("json"):
                json_texto = json_texto.split("\n", 1)[1]

        return json.loads(json_texto.strip())
    except Exception as e:
        print(f"  ❌ Falha na interpretação da IA: {e}")
        return None

def checar_e_atualizar_perfil() -> None:
    """Procura o PDF na raiz e atualiza o json de perfil se achar."""
    caminho_pdf = "curriculo.pdf"
    caminho_json = "fase3_perfil/perfil.json"

    if os.path.exists(caminho_pdf):
        print(f"\n[FASE 3 - PDF] Detectado '{caminho_pdf}'. Extraindo texto...")
        texto_extraido = extrair_texto_pdf(caminho_pdf)
        
        if texto_extraido.strip():
            print("  🧠 Processando dados com Inteligência Artificial (Gemini)...")
            novo_perfil = processar_curriculo_com_ia(texto_extraido)
            
            if novo_perfil:
                try:
                    with open(caminho_json, "w", encoding="utf-8") as f:
                        json.dump(novo_perfil, f, ensure_ascii=False, indent=4)
                    print(f"  ✅ O arquivo perfil.json foi atualizado com sucesso usando o seu PDF!")
                except Exception as e:
                    print(f"  ❌ Erro ao salvar o novo perfil.json: {e}")
        else:
            print("  ⚠️ O arquivo PDF parece ser uma imagem ou está vazio/ilegível.")
    else:
        print("\n[FASE 3 - PDF] Nenhum 'curriculo.pdf' encontrado. Mantendo o perfil atual.")
