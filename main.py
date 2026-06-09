"""
==============================================
  JOBHUNTER AI — main.py (OTIMIZADO)
  Fases 1 a 7 — Execução Paralela + Timers
==============================================
"""

import sys
import time
import json
import re
import os
import sqlite3
import requests
import google.generativeai as genai
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.append(str(Path(__file__).parent / "fase1_mvp"))
sys.path.append(str(Path(__file__).parent / "fase2_filtro"))
sys.path.append(str(Path(__file__).parent / "fase3_perfil"))

from filtro     import filtrar_vagas, exibir_resultado_filtro
from perfil     import carregar_perfil, exibir_perfil
from buscador   import buscar_vagas_gupy, buscar_todas_greenhouse, buscar_vagas_indeed, buscar_linkedin_rss, buscar_linkedin_posts
from leitor_pdf import checar_e_atualizar_perfil


# ====================================================================
# ── UTILITÁRIO: TIMER ────────────────────────────────────────────────
# ====================================================================

class Timer:
    def __init__(self, nome):
        self.nome = nome

    def __enter__(self):
        self.inicio = time.time()
        return self

    def __exit__(self, *args):
        elapsed = time.time() - self.inicio
        print(f"  ⏱️  [{self.nome}] concluído em {elapsed:.1f}s")


# ====================================================================
# ── FASE 1: BUSCA PARALELA ───────────────────────────────────────────
# ====================================================================

def buscar_todas_vagas_paralelo() -> list:
    print("\n[FASE 1] Buscando vagas em paralelo...")
    todas_vagas = []

    tarefas = []

    # Gupy
    termos_gupy = [
        "analista antifraude",
        "analista chargeback",
        "prevenção de fraudes",
        "analista financeiro",
        "backoffice financeiro",
        "analista de dados",
    ]
    for termo in termos_gupy:
        tarefas.append(("gupy", termo))

    # Indeed
    termos_indeed = [
        "analista antifraude",
        "analista chargeback",
        "prevenção de fraudes",
    ]
    for termo in termos_indeed:
        tarefas.append(("indeed", termo))

    # LinkedIn RSS
    termos_linkedin = [
        "analista antifraude",
        "analista chargeback",
        "prevenção de fraudes",
    ]
    for termo in termos_linkedin:
        tarefas.append(("linkedin_rss", termo))

    # LinkedIn Posts
    termos_ocultos = ["antifraude", "chargeback"]
    for termo in termos_ocultos:
        tarefas.append(("linkedin_posts", termo))

    def executar_tarefa(args):
        fonte, termo = args
        try:
            if fonte == "gupy":
                return buscar_vagas_gupy(termo)
            elif fonte == "indeed":
                return buscar_vagas_indeed(termo, "Brasil")
            elif fonte == "linkedin_rss":
                return buscar_linkedin_rss(termo)
            elif fonte == "linkedin_posts":
                return buscar_linkedin_posts(termo)
        except Exception as e:
            print(f"  ⚠️  Erro em {fonte} ({termo}): {e}")
            return []

    with Timer("Buscas paralelas (Gupy + Indeed + LinkedIn)"):
        with ThreadPoolExecutor(max_workers=8) as executor:
            futuros = {executor.submit(executar_tarefa, t): t for t in tarefas}
            for futuro in as_completed(futuros):
                resultado = futuro.result()
                if resultado:
                    todas_vagas.extend(resultado)

    # Greenhouse roda separado (já busca várias empresas internamente)
    with Timer("Greenhouse"):
        print("  📡 Buscando nas empresas financeiras via Greenhouse...")
        try:
            vagas_gh = buscar_todas_greenhouse()
            todas_vagas.extend(vagas_gh)
        except Exception as e:
            print(f"  ⚠️  Erro no Greenhouse: {e}")

    print(f"\n  📥 Total bruto coletado: {len(todas_vagas)} vaga(s)")
    return todas_vagas


# ====================================================================
# ── FASE 4: MATCH SCORE ──────────────────────────────────────────────
# ====================================================================

# Lista de modelos em ordem de preferência — tenta o primeiro,
# se falhar (cota, erro etc.) cai automaticamente para o próximo
MODELOS_FALLBACK = [
    'gemini-2.0-flash-lite',
    'gemini-2.5-flash',
    'gemini-3.5-flash',
]


def calcular_match(vagas_filtradas: list[dict], perfil: dict) -> list[dict]:
    print("\n[FASE 4] Triagem Híbrida e Inteligência Analítica (Match 2.0)...")

    termos_chave  = ["antifraude", "chargeback", "fraude", "risco", "dados", "data", "python", "sql", "backoffice"]
    termos_barrar = ["sênior", "senior", "lead", "staff", "coordenador", "gerente", "manager"]

    vagas_pre_aprovadas = [
        v for v in vagas_filtradas
        if any(t in v.get('titulo', '').lower() for t in termos_chave)
        and not any(t in v.get('titulo', '').lower() for t in termos_barrar)
    ]

    if not vagas_pre_aprovadas:
        return []

    api_key = os.environ.get("GEMINI_API_KEY")
    genai.configure(api_key=api_key)

    perfil_resumido = {
        "cargo": perfil.get("cargo_atual"),
        "habilidades": perfil.get("habilidades"),
        "areas": perfil.get("preferencias_vaga", {}).get("areas")
    }

    limite_analise = 5
    vagas_pontuadas = []

def analisar_vaga(vaga):
    prompt = f"""
    Você é um consultor. Analise esta vaga para o candidato: {json.dumps(perfil_resumido, ensure_ascii=False)}
    Vaga: "{vaga['titulo']}" na empresa "{vaga['empresa']}"

    Avalie a aderência de 0 a 100.
    Retorne APENAS um objeto JSON válido (começando com {{ e terminando com }}):
    {{
        "score": 85,
        "resumo": "Explicação curta.",
        "perguntas_entrevista": ["p1", "p2"],
        "mensagem_linkedin": "abordagem curta."
    }}
    """
    for nome_modelo in MODELOS_FALLBACK:
        tentativas = 2  # tenta 2x no mesmo modelo antes de trocar
        for tentativa in range(tentativas):
            try:
                model = genai.GenerativeModel(nome_modelo)
                resposta = model.generate_content(prompt)
                texto_bruto = resposta.text.strip()
                match = re.search(r'\{.*\}', texto_bruto, re.DOTALL)
                if match:
                    analise = json.loads(match.group(0))
                    vaga['match_score']       = analise.get('score', 0)
                    vaga['resumo_ia']         = analise.get('resumo', '')
                    vaga['perguntas']         = analise.get('perguntas_entrevista', [])
                    vaga['mensagem_linkedin'] = analise.get('mensagem_linkedin', '')
                    print(f"  ✅ '{vaga['titulo'][:30]}' analisado com {nome_modelo}")
                    return vaga
                else:
                    raise ValueError("JSON não encontrado na resposta")

            except Exception as e:
                erro_str = str(e)
                # Extrai o tempo de espera sugerido pela API (retry_delay)
                espera = 15  # padrão se não encontrar
                match_delay = re.search(r'retry_delay\s*\{\s*seconds:\s*(\d+)', erro_str)
                if match_delay:
                    espera = int(match_delay.group(1)) + 2  # +2s de margem

                if '429' in erro_str and tentativa < tentativas - 1:
                    print(f"  ⏳ {nome_modelo} — rate limit, aguardando {espera}s e tentando novamente...")
                    time.sleep(espera)
                else:
                    print(f"  ⚠️  {nome_modelo} falhou para '{vaga['titulo'][:25]}': 429 rate limit")
                    break  # passa para o próximo modelo

    print(f"  ❌ Todos os modelos falharam para '{vaga['titulo'][:30]}'")
    vaga['match_score'] = 10
    return vaga

    with Timer("Análise IA (Gemini)"):
        with ThreadPoolExecutor(max_workers=3) as executor:
            futuros = [executor.submit(analisar_vaga, v) for v in vagas_pre_aprovadas[:limite_analise]]
            for futuro in as_completed(futuros):
                vagas_pontuadas.append(futuro.result())

    vagas_pontuadas.sort(key=lambda x: x.get('match_score', 0), reverse=True)
    return vagas_pontuadas


def exibir_ranking(vagas_pontuadas: list[dict], limite: int = 15) -> None:
    print(f"\n{'='*60}")
    print(f"  🏆 TOP {limite} VAGAS MAIS ALINHADAS COM O SEU PERFIL")
    print(f"{'='*60}")

    melhores_vagas = [v for v in vagas_pontuadas if v['match_score'] > 0][:limite]

    if not melhores_vagas:
        print("\n❌ Nenhuma vaga obteve pontuação alta o suficiente nesta execução.")
        return

    for numero, vaga in enumerate(melhores_vagas, start=1):
        print(f"\n[{numero:02d}] {vaga['titulo']}")
        print(f"     Match Score : {vaga['match_score']} pts ⭐")
        print(f"     Empresa     : {vaga['empresa']}")
        print(f"     Local       : {vaga['local']}")
        print(f"     Fonte       : {vaga['fonte']}")
        print(f"     Link        : {vaga['link']}")
        print(f"     {'-'*52}")


# ====================================================================
# ── FASE 5: TELEGRAM ─────────────────────────────────────────────────
# ====================================================================

def enviar_para_telegram(vagas_pontuadas: list[dict], limite: int = 15) -> None:
    print("\n[FASE 5] Verificando vagas inéditas no Banco de Dados...")

    conn   = sqlite3.connect("vagas_enviadas.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS enviadas (
            link TEXT PRIMARY KEY,
            data_envio TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    TOKEN   = os.environ.get("TELEGRAM_TOKEN")
    CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

    melhores_vagas = [v for v in vagas_pontuadas if v['match_score'] > 0]
    vagas_ineditas = []

    for vaga in melhores_vagas:
        cursor.execute("SELECT 1 FROM enviadas WHERE link = ?", (vaga['link'],))
        if cursor.fetchone() is None:
            vagas_ineditas.append(vaga)
            if len(vagas_ineditas) >= limite:
                break

    if not vagas_ineditas:
        print("  🤫 Nenhuma vaga nova nesta rodada. Nada foi enviado.")
        conn.close()
        return

    print(f"  🔥 {len(vagas_ineditas)} vaga(s) inédita(s)! Enviando...")

    mensagem = f"🚀 <b>NOVAS VAGAS INÉDITAS ({len(vagas_ineditas)})</b> 🚀\n\n"

    for numero, vaga in enumerate(vagas_ineditas, start=1):
        link    = vaga['link']
        titulo  = vaga['titulo'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        empresa = vaga['empresa'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        score   = vaga.get('match_score', 0)

        mensagem += f"<b>[{numero:02d}] {titulo}</b>\n"
        mensagem += f"🏢 {empresa} | 📍 {vaga['local']}\n"
        mensagem += f"⭐ <b>Match Score: {score}%</b>\n"

        if vaga.get('resumo_ia'):
            mensagem += f"🤖 <i>{vaga['resumo_ia']}</i>\n"

        mensagem += f"🔗 <a href='{link}'>Acessar Vaga</a>\n\n"

        if score >= 75 and vaga.get('perguntas'):
            mensagem += f"<b>💡 DOSSIÊ DE ENTREVISTA</b>\n"
            for p in vaga['perguntas']:
                mensagem += f"❓ {p}\n"
            mensagem += f"💬 <b>Abordagem LinkedIn:</b>\n<i>{vaga['mensagem_linkedin']}</i>\n"

        mensagem += "───────────────────\n\n"
        cursor.execute("INSERT OR IGNORE INTO enviadas (link) VALUES (?)", (link,))

    conn.commit()
    conn.close()

    url     = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mensagem,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        resposta = requests.post(url, json=payload)
        if resposta.status_code == 200:
            print("  📱 ✅ Enviado com sucesso!")
        else:
            print(f"  ❌ Erro Telegram: {resposta.text}")
    except Exception as e:
        print(f"  ❌ Erro de conexão: {e}")


# ====================================================================
# ── MAIN ─────────────────────────────────────────────────────────────
# ====================================================================

def main():
    inicio_total = time.time()

    print("\n" + "=" * 60)
    print("          🤖 JOBHUNTER AI — Sistema Completo")
    print("     Gupy · Greenhouse · Indeed · LinkedIn · PDF Reader")
    print("=" * 60)

    # Fase 3: Perfil
    print("\n[FASE 3] Carregando perfil do candidato...")
    try:
        checar_e_atualizar_perfil()
    except Exception as e:
        print(f"  ⚠️  Aviso: Erro no leitor de PDF. Usando perfil atual. Detalhes: {e}")

    perfil = carregar_perfil()
    exibir_perfil(perfil)

    # Fase 1: Busca (paralela)
    with Timer("FASE 1 — Busca total"):
        todas_vagas = buscar_todas_vagas_paralelo()

    # Fase 2: Filtro
    with Timer("FASE 2 — Filtro"):
        print("\n[FASE 2] Aplicando filtro — removendo fora do Brasil...")
        vagas_filtradas = filtrar_vagas(todas_vagas)
        exibir_resultado_filtro(todas_vagas, vagas_filtradas)

    # Fase 4: Match Score
    with Timer("FASE 4 — Match Score"):
        vagas_com_score = calcular_match(vagas_filtradas, perfil)
        exibir_ranking(vagas_com_score, limite=15)

    # Fase 5: Telegram
    with Timer("FASE 5 — Telegram"):
        enviar_para_telegram(vagas_com_score, limite=15)

    # Resumo final com tempo total
    tempo_total = time.time() - inicio_total
    print(f"\n{'='*60}")
    print(f"  ✅ Pipeline completo em {tempo_total:.1f}s ({tempo_total/60:.1f} min)")
    print(f"  → {len(todas_vagas)} vagas brutas coletadas")
    print(f"  → {len(vagas_filtradas)} vagas relevantes após filtro")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
