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
    """Envia o texto para o Gemini montar o JSON perfeitamente estruturado."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("  ⚠️ GEMINI_API_KEY não configurada no ambiente. Pulando extração via IA.")
        return None

    # Configura a IA usando o modelo mais rápido e leve
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')

    prompt = f"""
    Você é um assistente de recrutamento de dados. Leia o texto de um currículo e transforme-o estritamente em um JSON válido.

    Regras:
    1. Retorne APENAS o objeto JSON. Nada de formatação markdown (```json).
    2. Preencha todos os campos da estrutura abaixo baseando-se no currículo.

    Estrutura JSON:
    {{
        "nome": "Nome Completo",
        "cargo_atual": "Cargo mais recente",
        "empresa": "Empresa atual",
        "experiencia_anos": 9,
        "formacao": "Curso superior",
        "instituicao": "Instituição de ensino",
        "conclusao": "Ano",
        "habilidades": ["hab1", "hab2"],
        "certificacoes": ["cert1"],
        "modalidade": ["remoto", "híbrido", "presencial"],
        "areas": ["antifraude", "chargeback", "dados"],
        "nivel": ["júnior", "pleno"],
        "salario_min": 3200
    }}

    Texto bruto do currículo:
    {texto_cv}
    """

    try:
        resposta = model.generate_content(prompt)
        json_texto = resposta.text.strip()
        
        # Remove markdown se a IA colocar por teimosia
        if json_texto.startswith("```"):
            json_texto = json_texto.split("\n", 1)[1].rsplit("\n", 1)[0]
            if json_texto.startswith("json"):
                json_texto = json_texto.split("\n", 1)[1]

        return json.loads(json_texto.strip())
    except Exception as e:
        print(f"  ❌ Falha na interpretação da IA: {e}")
        return None

def checar_e_atualizar_perfil() -> None:
    """Procura o PDF na raiz do projeto e atualiza o json de perfil se achar."""
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
        print("\n[FASE 3 - PDF] Nenhum 'curriculo.pdf' novo encontrado. Mantendo o perfil atual.")
