"""
RADAR DE VAGAS — analise_envio.py (NOVO)
Substitui no main.py tudo de "FASE 4: MATCH SCORE" até o fim de _enviar_alerta_urgencia.

O que mudou em relação ao main.py antigo:
  1. Vagas já vistas (tabelas enviadas/descartadas) são puladas ANTES de chamar o Gemini.
     Se a análise falhar, a vaga NÃO é marcada como vista: tenta de novo na próxima rodada.
  2. A nota usa a descrição completa (Greenhouse, Gupy, Lever) e devolve % de aderência,
     requisitos atendidos e gaps. Sem descrição, avalia só pelo título e avisa.
  3. Vagas encerradas (confirmado) são descartadas antes de gastar cota.
  4. Cada vaga vai em uma mensagem própria, com botões "Me candidatei" / "Descartar"
     (os botões só aparecem se a vaga entra na planilha: score >= SCORE_MIN_PLANILHA).
     Vagas com score >= 85 ganham o selo "VAGA OURO" na própria mensagem.

Variáveis opcionais: MAX_ANALISES_POR_RODADA (padrão 5), SCORE_MIN_PLANILHA (padrão 60).
"""

import os
import re
import json
import time
import html
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed

from integracoes import registrar_na_planilha
from paginas_vaga import obter_descricao, vaga_aberta
from telegram_acoes import enviar_telegram, botoes_vaga, planilha_configurada

DB = "vagas_enviadas.db"
MAX_ANALISES = int(os.environ.get("MAX_ANALISES_POR_RODADA", "5"))
MODELOS_FALLBACK = ['gemini-2.5-flash', 'gemini-3.5-flash']

# compatibilidade com o nome antigo
_enviar_mensagem_telegram = enviar_telegram


class Timer:
    def __init__(self, nome):
        self.nome = nome

    def __enter__(self):
        self.inicio = time.time()
        return self

    def __exit__(self, *args):
        print(f"  ⏱️  [{self.nome}] concluído em {time.time() - self.inicio:.1f}s")


def _esc(txt) -> str:
    return html.escape(str(txt or ""), quote=False)


def _prioridade(v: dict):
    """Recentes (até 7 dias) primeiro; depois, as mais novas."""
    return (0 if v.get('recente') else 1, v.get('dias_desde_publicacao', 9999))


def _rotulo_idade(v: dict) -> str:
    d = v.get('dias_desde_publicacao')
    if d is None:
        return ''
    quando = 'hoje' if d == 0 else f'há {d} dia(s)'
    origem = 'Publicada' if v.get('data_origem') == 'publicada' else 'Detectada'
    return f"🗓️ {origem} {quando}\n"


# ====================================================================
# ── VAGAS JÁ VISTAS ──────────────────────────────────────────────────
# ====================================================================

def _links_ja_vistos(db: str = DB) -> set:
    vistos = set()
    try:
        conn = sqlite3.connect(db)
        for tabela in ("enviadas", "descartadas"):
            try:
                vistos.update((r[0] or "").strip() for r in conn.execute(f"SELECT link FROM {tabela}"))
            except sqlite3.OperationalError:
                pass  # tabela ainda não existe
        conn.close()
    except Exception as e:
        print(f"  ⚠️  Não consegui ler o banco de vagas vistas: {e}")
    return vistos


def _registrar_encerrada(v: dict, db: str = DB) -> None:
    try:
        conn = sqlite3.connect(db)
        conn.execute("""CREATE TABLE IF NOT EXISTS descartadas (
            link TEXT PRIMARY KEY, titulo TEXT, empresa TEXT, fonte TEXT, local TEXT,
            motivo TEXT, data_descarte TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute(
            "INSERT OR IGNORE INTO descartadas (link, titulo, empresa, fonte, local, motivo) VALUES (?,?,?,?,?,?)",
            (v.get('link', ''), v.get('titulo', '—'), v.get('empresa', '—'),
             v.get('fonte', '—'), v.get('local', '—'), "Vaga encerrada"))
        conn.commit()
        conn.close()
    except Exception:
        pass


# ====================================================================
# ── FASE 4: MATCH SCORE ──────────────────────────────────────────────
# ====================================================================

def _sem_analise(vagas: list[dict]) -> list[dict]:
    for v in vagas:
        v.setdefault('match_score', 0)
        v.setdefault('resumo_ia', '')
        v.setdefault('perguntas', [])
        v.setdefault('mensagem_linkedin', '')
    return vagas


def calcular_match(vagas_filtradas: list[dict], perfil: dict) -> list[dict]:
    print("\n[FASE 4] Triagem Híbrida e Inteligência Analítica (Match 3.0)...")

    termos_chave  = ["antifraude","chargeback","fraude","risco","dados","data","python","sql","backoffice",
                     "desenvolvedor","desenvolvedora","developer","full stack","fullstack","full-stack",
                     "javascript","react","node","qa","teste","automação","automacao","rpa","sistemas",
                     "suporte técnico","suporte tecnico","integração","integracao",
                     "programador","programadora","software","backend","back-end","back end",
                     "frontend","front-end","front end","typescript","java","php"]
    termos_barrar = ["sênior","senior","lead","staff","coordenador","gerente","manager"]

    pre = [
        v for v in vagas_filtradas
        if any(t in v.get('titulo','').lower() for t in termos_chave)
        and not any(t in v.get('titulo','').lower() for t in termos_barrar)
    ]
    pre.sort(key=_prioridade)

    vistos = _links_ja_vistos()
    novas = [v for v in pre if (v.get('link') or '').strip() not in vistos]
    print(f"  🔎 {len(pre)} pré-aprovada(s) | ♻️ {len(pre) - len(novas)} já vista(s) puladas | 🆕 {len(novas)} nova(s)")

    if not pre:
        print("  ⚠️  Nenhuma vaga passou pelo pré-filtro. Usando as 5 primeiras ainda não vistas.")
        return _sem_analise([v for v in vagas_filtradas
                             if (v.get('link') or '').strip() not in vistos][:5])
    if not novas:
        print("  🤫 Nada novo para analisar nesta rodada.")
        return []

    # confere se ainda está aberta, até juntar MAX_ANALISES vagas
    selecionadas, encerradas = [], 0
    for v in novas:
        if len(selecionadas) >= MAX_ANALISES:
            break
        if vaga_aberta(v) is False:
            encerradas += 1
            _registrar_encerrada(v)
            continue
        selecionadas.append(v)
    if encerradas:
        print(f"  🚫 {encerradas} vaga(s) encerrada(s) descartada(s)")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("  ⚠️  GEMINI_API_KEY não encontrada.")
        return _sem_analise(selecionadas)

    from google import genai
    client = genai.Client(api_key=api_key)

    perfil_resumido = {
        "cargo":       perfil.get("cargo_atual"),
        "habilidades": perfil.get("habilidades"),
        "areas":       perfil.get("preferencias_vaga", {}).get("areas"),
        "objetivo":    ("Transição de carreira para tecnologia (desenvolvimento web, automação, dados, QA). "
                        "Mais de 10 anos em meios de pagamento, chargeback e antifraude; formação full-stack "
                        "em JavaScript (Node.js, React, SQL, APIs REST) e ADS em andamento. "
                        "Busca vagas júnior ou pleno; vagas de tecnologia e de operações de pagamentos são aderentes."),
    }

    def analisar_vaga(vaga):
        descricao = obter_descricao(vaga)
        vaga['base_analise'] = 'descrição' if descricao else 'título'
        print(f"  📄 '{vaga['titulo'][:30]}': "
              + (f"descrição obtida ({len(descricao)} caracteres)" if descricao else "sem descrição (só título)"))

        prompt = f"""Você é um consultor de carreira. Compare a vaga com o perfil do candidato.

PERFIL DO CANDIDATO:
{json.dumps(perfil_resumido, ensure_ascii=False)}

VAGA
Título: {vaga.get('titulo', '')}
Empresa: {vaga.get('empresa', '')}
Local: {vaga.get('local', '')}
Descrição completa:
{descricao if descricao else '(indisponível: avalie só pelo título e deixe requisitos_atendidos e gaps vazios)'}

TAREFA
1. "score": aderência de 0 a 100. Requisitos obrigatórios pesam mais que os desejáveis.
2. "requisitos_atendidos": até 5 requisitos da vaga que o perfil atende (frases curtas).
3. "gaps": até 5 requisitos da vaga que o perfil não cobre ou cobre pouco (frases curtas).
4. "resumo": 2 a 4 frases explicando POR QUE a aderência é essa, citando experiências e habilidades concretas do candidato que casam com a vaga.
5. "perguntas_entrevista": 5 perguntas específicas desta vaga (não genéricas), ligadas às experiências do candidato.
6. "mensagem_linkedin": mensagem pronta de abordagem ao recrutador (até 450 caracteres), citando a vaga e a empresa; use [Nome do Recrutador].
Use somente requisitos escritos na descrição. Nunca invente.
Se a "vaga" for o texto de uma postagem do LinkedIn, extraia também o nome do cargo
(sem hashtags, emojis ou a palavra [POST]) e o nome da empresa, somente se aparecer no texto.
Se a empresa não aparecer, deixe vazio.
Retorne APENAS um objeto JSON válido (começando com {{ e terminando com }}):
{{
    "score": 85,
    "resumo": "Explicação de 2 a 4 frases.",
    "requisitos_atendidos": ["..."],
    "gaps": ["..."],
    "perguntas_entrevista": ["p1", "p2", "p3", "p4", "p5"],
    "mensagem_linkedin": "Olá [Nome do Recrutador], ...",
    "titulo_limpo": "Analista de Cobrança",
    "empresa_citada": "Nome da Empresa ou vazio"
}}"""
        for nome_modelo in MODELOS_FALLBACK:
            for tentativa in range(2):
                try:
                    resposta = client.models.generate_content(model=nome_modelo, contents=prompt)
                    achado = re.search(r'\{.*\}', resposta.text.strip(), re.DOTALL)
                    if not achado:
                        raise ValueError("JSON não encontrado")
                    a = json.loads(achado.group(0))
                    try:
                        vaga['match_score'] = int(a.get('score', 0))
                    except (TypeError, ValueError):
                        vaga['match_score'] = 0
                    vaga['resumo_ia']            = a.get('resumo', '') or ''
                    vaga['requisitos_atendidos'] = a.get('requisitos_atendidos') or []
                    vaga['gaps']                 = a.get('gaps') or []
                    vaga['perguntas']            = a.get('perguntas_entrevista') or []
                    vaga['mensagem_linkedin']    = a.get('mensagem_linkedin', '') or ''
                    vaga['titulo_limpo']         = a.get('titulo_limpo', '') or ''
                    vaga['empresa_citada']       = a.get('empresa_citada', '') or ''
                    vaga['analise_ok'] = True
                    print(f"  ✅ '{vaga['titulo'][:30]}' analisado com {nome_modelo}")
                    return vaga
                except Exception as e:
                    erro_str = str(e)
                    espera = 15
                    m = re.search(r'retry_delay\s*\{\s*seconds:\s*(\d+)', erro_str)
                    if m:
                        espera = int(m.group(1)) + 2
                    if '429' in erro_str and tentativa == 0:
                        print(f"  ⏳ {nome_modelo} — rate limit, aguardando {espera}s...")
                        time.sleep(espera)
                    else:
                        print(f"  ⚠️  {nome_modelo} falhou: {erro_str[:80]}")
                        break

        print(f"  ❌ Todos os modelos falharam para '{vaga['titulo'][:30]}' (tenta de novo na próxima rodada)")
        vaga['match_score'] = 10
        vaga['analise_ok'] = False
        for chave, padrao in (('resumo_ia', ''), ('perguntas', []), ('mensagem_linkedin', '')):
            vaga.setdefault(chave, padrao)
        return vaga

    pontuadas = []
    with Timer("Análise IA (Gemini)"):
        with ThreadPoolExecutor(max_workers=1) as executor:
            futuros = [executor.submit(analisar_vaga, v) for v in selecionadas]
            for futuro in as_completed(futuros):
                pontuadas.append(futuro.result())

    pontuadas.sort(key=lambda x: (x.get('recente', False), x.get('match_score', 0)), reverse=True)
    return pontuadas


def exibir_ranking(vagas_pontuadas: list[dict], limite: int = 15) -> None:
    if not vagas_pontuadas:
        print("\n❌ Nenhuma vaga para exibir no ranking.")
        return

    print(f"\n{'='*60}")
    print(f"  🏆 TOP {limite} VAGAS MAIS ALINHADAS COM O SEU PERFIL")
    print(f"{'='*60}")

    for numero, vaga in enumerate(vagas_pontuadas[:limite], start=1):
        print(f"\n[{numero:02d}] {vaga['titulo']}")
        print(f"     Match Score : {vaga.get('match_score', 0)} pts ⭐")
        print(f"     Empresa     : {vaga['empresa']}")
        print(f"     Local       : {vaga['local']}")
        print(f"     Fonte       : {vaga['fonte']}")
        print(f"     Link        : {vaga['link']}")
        print(f"     {'-'*52}")


# ====================================================================
# ── FASE 5: TELEGRAM + BANCO + PLANILHA ──────────────────────────────
# ====================================================================

SEP = "━━━━━━━━━━━━━━━━━━━━━━━━━"


def _mensagens_vaga(vaga: dict, numero: int) -> list[str]:
    """Formato do alerta que você já conhecia (OURO e normal), com 'Atende' e 'Gaps' a mais.
    Se passar do limite do Telegram, o dossiê vai em uma segunda mensagem."""
    score = vaga.get('match_score', 0)
    ouro = score >= 85
    titulo  = _esc(vaga.get('titulo', '—'))[:200]
    empresa = _esc(vaga.get('empresa', '—'))
    link    = html.escape(vaga.get('link', ''), quote=True)

    if ouro:
        t = f"🚨🚨 <b>ALERTA DE VAGA OURO!</b> 🚨🚨\n{SEP}\n\n🥇 <b>{titulo}</b>\n🏢 {empresa}\n"
        t += f"⭐ Match Score: <b>{score}%</b>\n"
    else:
        t = f"<b>[{numero:02d}] {titulo}</b>\n🏢 {empresa} | 📍 {_esc(vaga.get('local', '—'))}\n"
        t += f"⭐ <b>Match Score: {score}%</b>\n"
    if vaga.get('base_analise') == 'título':
        t += "⚠️ <i>Análise só pelo título (descrição da vaga indisponível)</i>\n"
    t += _rotulo_idade(vaga)
    if vaga.get('resumo_ia'):
        t += f"🤖 <i>{_esc(vaga['resumo_ia'])[:1200]}</i>\n"
    if vaga.get('requisitos_atendidos'):
        t += "✅ <b>Atende:</b> " + "; ".join(_esc(r)[:220] for r in vaga['requisitos_atendidos'][:5]) + "\n"
    if vaga.get('gaps'):
        t += "🔸 <b>Gaps:</b> " + "; ".join(_esc(g)[:220] for g in vaga['gaps'][:5]) + "\n"
    t += f"🔗 <a href='{link}'>{'👉 CANDIDATAR AGORA' if ouro else 'Acessar Vaga'}</a>\n"

    dossie = ""
    if (ouro or score >= 75) and vaga.get('perguntas'):
        dossie = "\n<b>💡 DOSSIÊ DE ENTREVISTA</b>\n"
        for p in vaga['perguntas'][:5]:
            dossie += f"❓ {_esc(p)[:300]}\n"
        if vaga.get('mensagem_linkedin'):
            titulo_msg = "💬 <b>Mensagem LinkedIn pronta:</b>" if ouro else "💬 <b>Abordagem LinkedIn:</b>"
            dossie += f"\n{titulo_msg}\n<i>{_esc(vaga['mensagem_linkedin'])[:800]}</i>\n"
    if ouro:
        dossie += SEP

    if len(t) + len(dossie) <= 3900:
        return [t + dossie]
    return [t, dossie.strip()] if dossie.strip() else [t[:3900]]


def enviar_para_telegram(vagas_pontuadas: list[dict], limite: int = 15) -> None:
    if not vagas_pontuadas:
        print("\n[FASE 5] Nenhuma vaga para enviar.")
        return

    # planilha primeiro (ela mesma evita duplicatas pelo link)
    registrar_na_planilha(vagas_pontuadas)

    print("\n[FASE 5] Salvando vagas enriquecidas no Banco de Dados...")
    conn = sqlite3.connect(DB)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS enviadas (
            link TEXT PRIMARY KEY, data_envio TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            titulo TEXT, empresa TEXT, fonte TEXT, local TEXT, match_score INTEGER
        )
    """)
    cursor.execute("PRAGMA table_info(enviadas)")
    colunas_existentes = {row[1] for row in cursor.fetchall()}
    for col in ['titulo', 'empresa', 'fonte', 'local', 'match_score']:
        if col not in colunas_existentes:
            cursor.execute(f"ALTER TABLE enviadas ADD COLUMN {col} {'INTEGER' if col == 'match_score' else 'TEXT'}")
    conn.commit()

    TOKEN   = os.environ.get("TELEGRAM_TOKEN")
    CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

    ineditas = []
    for vaga in vagas_pontuadas:
        if vaga.get('analise_ok') is False:   # falhou na IA: não marca como vista
            continue
        cursor.execute("SELECT 1 FROM enviadas WHERE link = ?", (vaga['link'],))
        if cursor.fetchone() is None:
            try:
                cursor.execute(
                    "INSERT INTO enviadas (link, titulo, empresa, fonte, local, match_score) VALUES (?,?,?,?,?,?)",
                    (vaga['link'], vaga.get('titulo', '—'), vaga.get('empresa', '—'),
                     vaga.get('fonte', '—'), vaga.get('local', '—'), vaga.get('match_score', 0)))
                ineditas.append(vaga)
            except Exception as e:
                print(f"  ⚠️  Erro ao salvar vaga: {e}")
        if len(ineditas) >= limite:
            break
    conn.commit()
    conn.close()

    if not ineditas:
        print("  🤫 Nenhuma vaga nova nesta rodada. Nada foi enviado.")
        return

    print(f"  🔥 {len(ineditas)} vaga(s) inédita(s)! Enviando...")
    try:
        score_min = int(os.environ.get("SCORE_MIN_PLANILHA", "60"))
    except ValueError:
        score_min = 60
    usar_botoes = planilha_configurada()

    enviar_telegram(f"🚀 <b>NOVAS VAGAS INÉDITAS ({len(ineditas)})</b> 🚀", TOKEN, CHAT_ID)
    for numero, vaga in enumerate(ineditas, start=1):
        botoes = botoes_vaga(vaga['link']) if usar_botoes and vaga.get('match_score', 0) >= score_min else None
        partes = _mensagens_vaga(vaga, numero)
        enviar_telegram(partes[0], TOKEN, CHAT_ID, botoes=botoes)  # botões na primeira mensagem
        for extra in partes[1:]:
            enviar_telegram(extra, TOKEN, CHAT_ID)
    print("  📱 ✅ Enviado com sucesso!")
