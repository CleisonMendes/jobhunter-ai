"""
==============================================
  JOBHUNTER AI — main.py (OTIMIZADO)
  Fases 1 a 7 — Execução Paralela + Timers
  Bloco 1: Deduplicação + DB Enriquecido + Descartadas
==============================================
"""

import sys
import time
import json
import re
import os
import sqlite3
import requests
from google import genai
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
# ── ITEM 2: DEDUPLICAÇÃO ─────────────────────────────────────────────
# ====================================================================

def deduplicar_vagas(vagas: list[dict]) -> list[dict]:
    """
    Remove duplicatas com base no link (exato) e por similaridade
    de título + empresa (evita a mesma vaga de fontes diferentes).
    """
    print("\n[DEDUP] Removendo duplicatas...")
    vistas_por_link = set()
    vistas_por_chave = set()
    unicas = []

    for vaga in vagas:
        link = vaga.get('link', '').strip()
        titulo = vaga.get('titulo', '').lower().strip()
        empresa = vaga.get('empresa', '').lower().strip()

        # Normaliza título removendo sufixos comuns de fontes
        titulo_norm = re.sub(r'\s*[-|]\s*(linkedin|gupy|greenhouse|indeed).*$', '', titulo)

        chave = f"{titulo_norm[:40]}|{empresa[:30]}"

        if link and link in vistas_por_link:
            continue
        if chave in vistas_por_chave:
            continue

        if link:
            vistas_por_link.add(link)
        vistas_por_chave.add(chave)
        unicas.append(vaga)

    removidas = len(vagas) - len(unicas)
    print(f"  🧹 {removidas} duplicata(s) removida(s) → {len(unicas)} vagas únicas")
    return unicas


# ====================================================================
# ── ITEM 3: BANCO DE DESCARTADAS ─────────────────────────────────────
# ====================================================================

def salvar_descartadas(todas_vagas: list[dict], vagas_filtradas: list[dict]) -> None:
    """
    Salva as vagas que não passaram no filtro em uma tabela separada,
    com o motivo do descarte para análise futura.
    """
    links_aprovados = {v.get('link') for v in vagas_filtradas}
    descartadas = [v for v in todas_vagas if v.get('link') not in links_aprovados]

    if not descartadas:
        return

    conn = sqlite3.connect("vagas_enviadas.db")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS descartadas (
            link        TEXT PRIMARY KEY,
            titulo      TEXT,
            empresa     TEXT,
            fonte       TEXT,
            local       TEXT,
            motivo      TEXT,
            data_descarte TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    inseridas = 0
    for vaga in descartadas:
        link   = vaga.get('link', '')
        titulo = vaga.get('titulo', '—')
        local  = vaga.get('local', '').lower()

        # Tenta inferir o motivo do descarte
        if any(pais in local for pais in ['united', 'mexico', 'colombia', 'argentina', 'usa', 'us', 'uk']):
            motivo = "Fora do Brasil"
        elif not link:
            motivo = "Link inválido"
        else:
            motivo = "Não passou no filtro de relevância"

        try:
            cursor.execute("""
                INSERT OR IGNORE INTO descartadas (link, titulo, empresa, fonte, local, motivo)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                link,
                titulo,
                vaga.get('empresa', '—'),
                vaga.get('fonte', '—'),
                vaga.get('local', '—'),
                motivo
            ))
            if cursor.rowcount > 0:
                inseridas += 1
        except Exception:
            pass

    conn.commit()
    conn.close()
    print(f"  🗃️  {inseridas} vaga(s) nova(s) registrada(s) em 'descartadas'")


# ====================================================================
# ── FASE 1: BUSCA PARALELA ───────────────────────────────────────────
# ====================================================================

def buscar_todas_vagas_paralelo() -> list:
    print("\n[FASE 1] Buscando vagas em paralelo...")
    todas_vagas = []
    tarefas = []

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

    termos_indeed = [
        "analista antifraude",
        "analista chargeback",
        "prevenção de fraudes",
    ]
    for termo in termos_indeed:
        tarefas.append(("indeed", termo))

    termos_linkedin = [
        "analista antifraude",
        "analista chargeback",
        "prevenção de fraudes",
    ]
    for termo in termos_linkedin:
        tarefas.append(("linkedin_rss", termo))

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

    print(f"  🔎 {len(vagas_pre_aprovadas)} vaga(s) pré-aprovadas para análise da IA")

    if not vagas_pre_aprovadas:
        print("  ⚠️  Nenhuma vaga passou pelo pré-filtro. Retornando top 5 por score de filtro.")
        for v in vagas_filtradas[:5]:
            v.setdefault('match_score', 0)
            v.setdefault('resumo_ia', '')
            v.setdefault('perguntas', [])
            v.setdefault('mensagem_linkedin', '')
        return vagas_filtradas[:5]

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("  ⚠️  GEMINI_API_KEY não encontrada. Retornando vagas sem score IA.")
        for v in vagas_pre_aprovadas:
            v.setdefault('match_score', 0)
            v.setdefault('resumo_ia', '')
            v.setdefault('perguntas', [])
            v.setdefault('mensagem_linkedin', '')
        return vagas_pre_aprovadas

    client = genai.Client(api_key=api_key)

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
            for tentativa in range(2):
                try:
                    resposta = client.models.generate_content(
                        model=nome_modelo,
                        contents=prompt
                    )
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
                    espera = 15
                    match_delay = re.search(r'retry_delay\s*\{\s*seconds:\s*(\d+)', erro_str)
                    if match_delay:
                        espera = int(match_delay.group(1)) + 2

                    if '429' in erro_str and tentativa == 0:
                        print(f"  ⏳ {nome_modelo} — rate limit, aguardando {espera}s...")
                        time.sleep(espera)
                    else:
                        print(f"  ⚠️  {nome_modelo} falhou para '{vaga['titulo'][:25]}': {erro_str[:80]}")
                        break

        print(f"  ❌ Todos os modelos falharam para '{vaga['titulo'][:30]}'")
        vaga['match_score'] = 10
        vaga.setdefault('resumo_ia', '')
        vaga.setdefault('perguntas', [])
        vaga.setdefault('mensagem_linkedin', '')
        return vaga

    with Timer("Análise IA (Gemini)"):
        with ThreadPoolExecutor(max_workers=1) as executor:
            futuros = [executor.submit(analisar_vaga, v) for v in vagas_pre_aprovadas[:limite_analise]]
            for futuro in as_completed(futuros):
                vagas_pontuadas.append(futuro.result())

    vagas_pontuadas.sort(key=lambda x: x.get('match_score', 0), reverse=True)
    return vagas_pontuadas


def exibir_ranking(vagas_pontuadas: list[dict], limite: int = 15) -> None:
    if not vagas_pontuadas:
        print("\n❌ Nenhuma vaga para exibir no ranking.")
        return

    print(f"\n{'='*60}")
    print(f"  🏆 TOP {limite} VAGAS MAIS ALINHADAS COM O SEU PERFIL")
    print(f"{'='*60}")

    melhores_vagas = [v for v in vagas_pontuadas if v.get('match_score', 0) >= 0][:limite]

    if not melhores_vagas:
        print("\n❌ Nenhuma vaga obteve pontuação nesta execução.")
        return

    for numero, vaga in enumerate(melhores_vagas, start=1):
        print(f"\n[{numero:02d}] {vaga['titulo']}")
        print(f"     Match Score : {vaga.get('match_score', 0)} pts ⭐")
        print(f"     Empresa     : {vaga['empresa']}")
        print(f"     Local       : {vaga['local']}")
        print(f"     Fonte       : {vaga['fonte']}")
        print(f"     Link        : {vaga['link']}")
        print(f"     {'-'*52}")


# ====================================================================
# ── FASE 5: TELEGRAM + BANCO ENRIQUECIDO ─────────────────────────────
# ====================================================================

def enviar_para_telegram(vagas_pontuadas: list[dict], limite: int = 15) -> None:
    if not vagas_pontuadas:
        print("\n[FASE 5] Nenhuma vaga para enviar.")
        return

    print("\n[FASE 5] Salvando vagas enriquecidas no Banco de Dados...")

    conn = sqlite3.connect("vagas_enviadas.db")
    cursor = conn.cursor()

    # ── ITEM 1: Tabela com colunas completas ─────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS enviadas (
            link        TEXT PRIMARY KEY,
            data_envio  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            titulo      TEXT,
            empresa     TEXT,
            fonte       TEXT,
            local       TEXT,
            match_score INTEGER
        )
    """)

    # Migração silenciosa: adiciona colunas se o banco já existia sem elas
    colunas_novas = ['titulo', 'empresa', 'fonte', 'local', 'match_score']
    cursor.execute("PRAGMA table_info(enviadas)")
    colunas_existentes = {row[1] for row in cursor.fetchall()}
    for col in colunas_novas:
        if col not in colunas_existentes:
            tipo = 'INTEGER' if col == 'match_score' else 'TEXT'
            cursor.execute(f"ALTER TABLE enviadas ADD COLUMN {col} {tipo}")

    conn.commit()

    TOKEN   = os.environ.get("TELEGRAM_TOKEN")
    CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

    vagas_ineditas = []
    for vaga in vagas_pontuadas:
        cursor.execute("SELECT 1 FROM enviadas WHERE link = ?", (vaga['link'],))
        if cursor.fetchone() is None:
            try:
                cursor.execute("""
                    INSERT INTO enviadas (link, titulo, empresa, fonte, local, match_score)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    vaga['link'],
                    vaga.get('titulo', '—'),
                    vaga.get('empresa', '—'),
                    vaga.get('fonte', '—'),
                    vaga.get('local', '—'),
                    vaga.get('match_score', 0)
                ))
                vagas_ineditas.append(vaga)
            except Exception as e:
                print(f"  ⚠️  Erro ao salvar vaga: {e}")

            if len(vagas_ineditas) >= limite:
                break

    conn.commit()
    conn.close()

    if not vagas_ineditas:
        print("  🤫 Nenhuma vaga nova nesta rodada. Nada foi enviado.")
        return

    print(f"  🔥 {len(vagas_ineditas)} vaga(s) inédita(s)! Enviando...")

    mensagem = f"🚀 <b>NOVAS VAGAS INÉDITAS ({len(vagas_ineditas)})</b> 🚀\n\n"
    for numero, vaga in enumerate(vagas_ineditas, start=1):
        link    = vaga['link']
        titulo  = str(vaga.get('titulo', '—')).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        empresa = str(vaga.get('empresa', '—')).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        score   = vaga.get('match_score', 0)

        mensagem += f"<b>[{numero:02d}] {titulo}</b>\n"
        mensagem += f"🏢 {empresa} | 📍 {vaga.get('local', '—')}\n"
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

    url     = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": mensagem, "parse_mode": "HTML", "disable_web_page_preview": True}

    try:
        requests.post(url, json=payload)
        print("  📱 ✅ Enviado com sucesso!")
    except Exception as e:
        print(f"  ❌ Erro de conexão com Telegram: {e}")


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

    # Fase 1: Busca paralela
    with Timer("FASE 1 — Busca total"):
        todas_vagas = buscar_todas_vagas_paralelo()

    # ── ITEM 2: Deduplicação ─────────────────────────────────────────
    with Timer("DEDUP — Deduplicação"):
        todas_vagas = deduplicar_vagas(todas_vagas)

    # Fase 2: Filtro
    with Timer("FASE 2 — Filtro"):
        print("\n[FASE 2] Aplicando filtro — removendo fora do Brasil...")
        vagas_filtradas = filtrar_vagas(todas_vagas)
        exibir_resultado_filtro(todas_vagas, vagas_filtradas)

    # ── ITEM 3: Salvar descartadas ───────────────────────────────────
    with Timer("DEDUP — Salvando descartadas"):
        salvar_descartadas(todas_vagas, vagas_filtradas)

    # Fase 4: Match Score
    with Timer("FASE 4 — Match Score"):
        vagas_com_score = calcular_match(vagas_filtradas, perfil)
        exibir_ranking(vagas_com_score, limite=15)

    # Fase 5: Telegram + banco enriquecido
    with Timer("FASE 5 — Telegram"):
        enviar_para_telegram(vagas_com_score, limite=15)

    # Resumo final
    tempo_total = time.time() - inicio_total
    print(f"\n{'='*60}")
    print(f"  ✅ Pipeline completo em {tempo_total:.1f}s ({tempo_total/60:.1f} min)")
    print(f"  → {len(todas_vagas)} vagas únicas após deduplicação")
    print(f"  → {len(vagas_filtradas)} vagas relevantes após filtro")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()