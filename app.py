import hashlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

st.set_page_config(page_title="JobHunter AI", page_icon="🤖", layout="wide")

st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size: 1.8rem !important; }
[data-testid="stMetricDelta"] { font-size: 0.8rem !important; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# CONFIGURAÇÕES
# ==========================================
DB_VAGAS = "vagas_enviadas.db"
DB_STATUS = "status_vagas.db"   # banco separado: o robô não é afetado
STATUS_OPCOES = ["Nova", "Candidatei", "Entrevista", "Descartei"]
STATUS_PADRAO_VISIVEL = ["Nova", "Candidatei", "Entrevista"]
META_PADRAO = 5
PAGINA = 10


def agora_brt():
    return (datetime.now(timezone.utc) - timedelta(hours=3)).replace(tzinfo=None)


def limpar(txt):
    """Evita que o $ vire fórmula no markdown do Streamlit."""
    return str(txt).replace("$", "\\$")


# ==========================================
# STATUS POR VAGA (banco separado)
# ==========================================
def init_status_db():
    with closing(sqlite3.connect(DB_STATUS)) as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS status_vagas (
                link TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                data_candidatura TEXT,
                atualizado_em TEXT NOT NULL
            )"""
        )
        con.commit()


def carregar_status():
    try:
        with closing(sqlite3.connect(DB_STATUS)) as con:
            return pd.read_sql_query("SELECT * FROM status_vagas", con)
    except Exception:
        return pd.DataFrame(columns=["link", "status", "data_candidatura", "atualizado_em"])


def salvar_status(link, chave):
    """Callback do selectbox: grava o novo status da vaga."""
    novo = st.session_state[chave]
    agora = agora_brt().strftime("%Y-%m-%d %H:%M:%S")
    with closing(sqlite3.connect(DB_STATUS)) as con:
        atual = con.execute(
            "SELECT data_candidatura FROM status_vagas WHERE link = ?", (link,)
        ).fetchone()
        data_cand = atual[0] if atual else None
        if novo in ("Candidatei", "Entrevista"):
            data_cand = data_cand or agora
        else:
            data_cand = None
        con.execute(
            """INSERT INTO status_vagas (link, status, data_candidatura, atualizado_em)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(link) DO UPDATE SET
                   status = excluded.status,
                   data_candidatura = excluded.data_candidatura,
                   atualizado_em = excluded.atualizado_em""",
            (link, novo, data_cand, agora),
        )
        con.commit()


init_status_db()

# ==========================================
# 1. BARRA LATERAL (PERFIL)
# ==========================================
try:
    with open("fase3_perfil/perfil.json", "r", encoding="utf-8") as f:
        perfil = json.load(f)

    st.sidebar.header("👤 Perfil Ativo")
    st.sidebar.write(f"**Nome:** {perfil.get('nome', 'N/A')}")
    st.sidebar.write(f"**Cargo:** {perfil.get('cargo_atual', 'N/A')}")
    st.sidebar.write(f"**Empresa:** {perfil.get('empresa_atual', 'N/A')}")

    with st.sidebar.expander("🎓 Formação Acadêmica"):
        formacao = perfil.get("formacao", {})
        if isinstance(formacao, dict):
            st.write(f"**Curso:** {formacao.get('curso', 'N/A')}")
            st.write(f"**Local:** {formacao.get('instituicao', 'N/A')}")
            st.write(f"**Status:** {formacao.get('status', 'N/A')} ({formacao.get('conclusao_prevista', '')})")
        else:
            st.write(formacao)

    with st.sidebar.expander("📜 Cursos e Certificações"):
        for cert in perfil.get("certificacoes", []):
            st.write(f"- {cert}")

    with st.sidebar.expander("🎯 Áreas Alvo"):
        for area in perfil.get("preferencias_vaga", {}).get("areas", []):
            st.write(f"- {area}")

    with st.sidebar.expander("🛠️ Habilidades Mapeadas"):
        for hab in perfil.get("habilidades", []):
            st.write(f"- {hab}")

    st.sidebar.success("✅ Sincronizado com a IA")

except Exception:
    st.sidebar.warning("⏳ Aguardando IA processar o perfil.json...")

# ==========================================
# CABEÇALHO
# ==========================================
st.title("🤖 JobHunter AI — Painel de Controle")
st.caption("Monitoramento em tempo real da sua automação de caça a vagas.")

# ==========================================
# 2. LEITURA DO BANCO
# ==========================================
if not os.path.exists(DB_VAGAS):
    st.warning("⏳ Banco de dados ainda não foi criado. Aguarde a próxima execução.")
    st.stop()

conn = sqlite3.connect(DB_VAGAS)

try:
    df = pd.read_sql_query("SELECT * FROM enviadas", conn)
except Exception as e:
    st.error(f"Erro ao ler o banco: {e}")
    conn.close()
    st.stop()

try:
    df_desc = pd.read_sql_query("SELECT * FROM descartadas", conn)
except Exception:
    df_desc = pd.DataFrame()

conn.close()

if df.empty:
    st.info("Banco pronto, mas nenhuma vaga inédita foi salva ainda.")
    st.stop()

# Normaliza
df["data_envio"] = pd.to_datetime(df["data_envio"]) - pd.Timedelta(hours=3)
df["Data"] = df["data_envio"].dt.date

for col, fallback in [("match_score", 0), ("titulo", "—"), ("empresa", "—"),
                      ("fonte", "—"), ("local", "—"), ("link", "")]:
    if col not in df.columns:
        df[col] = fallback

df["match_score"] = pd.to_numeric(df["match_score"], errors="coerce").fillna(0).astype(int)

# Status por vaga
df_status = carregar_status()
status_map = dict(zip(df_status["link"], df_status["status"]))
df["status"] = df["link"].map(status_map).fillna("Nova")

# ==========================================
# FILTROS (BARRA LATERAL)
# ==========================================
st.sidebar.divider()
st.sidebar.header("🎚️ Filtros")
score_min = st.sidebar.slider("Score mínimo de match", 0, 100, 0, step=5)
fontes_disp = ["Todas"] + sorted(df["fonte"].dropna().astype(str).unique().tolist())
fonte_filtro = st.sidebar.selectbox("Filtrar por fonte", fontes_disp)
busca = st.sidebar.text_input("Buscar por cargo ou empresa")
status_sel = st.sidebar.multiselect("Status da vaga", STATUS_OPCOES, default=STATUS_PADRAO_VISIVEL)
meta_semanal = st.sidebar.number_input("Meta semanal de candidaturas", 1, 50, META_PADRAO)

df_filtrado = df[df["match_score"] >= score_min].copy()
if fonte_filtro != "Todas":
    df_filtrado = df_filtrado[df_filtrado["fonte"] == fonte_filtro]
if busca.strip():
    termo = busca.strip()
    mask = (
        df_filtrado["titulo"].astype(str).str.contains(termo, case=False, regex=False, na=False)
        | df_filtrado["empresa"].astype(str).str.contains(termo, case=False, regex=False, na=False)
    )
    df_filtrado = df_filtrado[mask]
if status_sel:
    df_filtrado = df_filtrado[df_filtrado["status"].isin(status_sel)]

# ==========================================
# 3. KPIs
# ==========================================
st.subheader("📊 Resumo da Execução")

hoje = agora_brt().date()
inicio_semana = hoje - timedelta(days=hoje.weekday())
vagas_hoje = int((df["Data"] == hoje).sum())

vagas_ouro = int((df_filtrado["match_score"] >= 85).sum())
score_medio = int(df_filtrado["match_score"].mean()) if not df_filtrado.empty else 0
ultima_captura = df["data_envio"].max().strftime("%d/%m %H:%M")
total_desc = len(df_desc) if not df_desc.empty else 0

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("🔥 Vagas inéditas", len(df), delta=f"{vagas_hoje} hoje", delta_color="off")
c2.metric("🎯 Após filtros", len(df_filtrado))
c3.metric("⭐ Score médio", f"{score_medio}%")
c4.metric("🚨 Vagas ouro (≥85)", vagas_ouro)
c5.metric("🗃️ Descartadas", total_desc)
c6.metric("⏱️ Última captura", ultima_captura)

if vagas_ouro > 0:
    st.success(f"🚨 **{vagas_ouro} vaga(s) OURO com score ≥ 85%!** Confira o ranking abaixo.")

# ---- Progresso de candidaturas ----
df_cand = df_status[df_status["status"].isin(["Candidatei", "Entrevista"])].copy()
total_cand = len(df_cand)
total_entrev = int((df_status["status"] == "Entrevista").sum())
if not df_cand.empty:
    df_cand["data_candidatura"] = pd.to_datetime(df_cand["data_candidatura"], errors="coerce")
    cand_semana = int((df_cand["data_candidatura"].dt.date >= inicio_semana).sum())
else:
    cand_semana = 0

st.markdown("##### 🎯 Meta da semana")
p1, p2, p3 = st.columns(3)
p1.metric("📨 Candidaturas na semana", f"{cand_semana}/{meta_semanal}")
p2.metric("✅ Candidaturas no total", total_cand)
p3.metric("🎤 Entrevistas", total_entrev)
st.progress(min(cand_semana / meta_semanal, 1.0), text=f"{cand_semana} de {meta_semanal} candidaturas esta semana")

st.divider()

# ==========================================
# 4. RANKING DE VAGAS (cards com status)
# ==========================================
st.subheader("🏆 Ranking de Vagas")

if "n_mostrar" not in st.session_state:
    st.session_state.n_mostrar = PAGINA

if df_filtrado.empty:
    st.info("Nenhuma vaga encontrada com os filtros selecionados.")
else:
    def badge_status(val):
        if val >= 85:
            return "🚨 Ouro"
        elif val >= 50:
            return "🥈 Prata"
        return "🔴 Atenção"

    df_rank = df_filtrado.sort_values(["match_score", "data_envio"], ascending=[False, False]).reset_index(drop=True)
    total = len(df_rank)
    n = st.session_state.n_mostrar
    st.caption(f"Mostrando {min(n, total)} de {total} vagas. Mude o status na caixa de cada vaga.")

    for _, row in df_rank.head(n).iterrows():
        score = int(row["match_score"])
        link = str(row["link"])
        chave = "st_" + hashlib.md5(link.encode("utf-8")).hexdigest()[:12]
        status_atual = row["status"] if row["status"] in STATUS_OPCOES else "Nova"

        with st.container(border=True):
            c_info, c_status, c_btn = st.columns([6, 2, 2])
            with c_info:
                st.markdown(f"**{badge_status(score)} · {limpar(row['titulo'])}**")
                st.caption(
                    f"🏢 {limpar(row['empresa'])} | 📍 {limpar(row['local'])} | "
                    f"🔖 {limpar(row['fonte'])} | 🗓️ {row['data_envio'].strftime('%d/%m')}"
                )
                st.progress(min(max(score, 0), 100) / 100, text=f"Match {score}%")
            with c_status:
                st.selectbox(
                    "Status",
                    STATUS_OPCOES,
                    index=STATUS_OPCOES.index(status_atual),
                    key=chave,
                    label_visibility="collapsed",
                    on_change=salvar_status,
                    args=(link, chave),
                )
            with c_btn:
                st.link_button("👉 Candidatar", link, use_container_width=True)

    if total > n:
        if st.button(f"Mostrar mais {PAGINA} vagas"):
            st.session_state.n_mostrar += PAGINA
            st.rerun()

st.divider()

# ==========================================
# 5. GRÁFICOS
# ==========================================
st.subheader("🔻 Funil de Candidaturas")
funil = pd.DataFrame(
    {
        "Vagas": [
            len(df),
            int((df["match_score"] >= 85).sum()),
            total_cand,
            total_entrev,
        ]
    },
    index=["1. Inéditas", "2. Ouro (≥85)", "3. Candidatei", "4. Entrevista"],
)
st.bar_chart(funil, color="#00C48C")

st.subheader("📈 Tendência do Mercado (Vagas por Dia)")

vagas_por_dia = df.groupby("Data").size().reset_index(name="Vagas")
vagas_por_dia["Data"] = pd.to_datetime(vagas_por_dia["Data"])
vagas_por_dia = vagas_por_dia.set_index("Data")

if not vagas_por_dia.empty:
    vagas_por_dia = vagas_por_dia.reindex(
        pd.date_range(vagas_por_dia.index.min(), vagas_por_dia.index.max(), freq="D"),
        fill_value=0,
    )
    vagas_por_dia.index.name = "Data"
    st.area_chart(vagas_por_dia, color="#378ADD")
else:
    st.info("Dados insuficientes para o gráfico.")

if df["match_score"].sum() > 0:
    score_por_dia = (
        df[df["match_score"] > 0]
        .groupby("Data")["match_score"]
        .mean().round(1).reset_index()
    )
    score_por_dia.columns = ["Data", "Score Médio"]
    score_por_dia["Data"] = pd.to_datetime(score_por_dia["Data"])
    score_por_dia = score_por_dia.set_index("Data")
    st.caption("Score médio de aderência por dia")
    st.line_chart(score_por_dia, color="#639922")

st.subheader("🔖 Vagas por Fonte")
vagas_por_fonte = df["fonte"].astype(str).value_counts()
st.bar_chart(vagas_por_fonte, color="#FAC775")

st.divider()

# ==========================================
# 6. ABA DE DESCARTADAS
# ==========================================
if not df_desc.empty:
    with st.expander(f"🗃️ Vagas Descartadas ({len(df_desc)}) — clique para analisar"):
        st.caption("Vagas que não passaram no filtro. Use para ajustar os critérios.")

        motivos = df_desc["motivo"].value_counts().reset_index()
        motivos.columns = ["Motivo", "Qtd"]
        col_a, col_b = st.columns([1, 2])
        with col_a:
            st.dataframe(motivos, use_container_width=True, hide_index=True)
        with col_b:
            st.bar_chart(motivos.set_index("Motivo"), color="#E24B4A")

        df_desc_display = df_desc[["titulo", "empresa", "fonte", "local", "motivo"]].copy()
        df_desc_display.columns = ["Cargo", "Empresa", "Fonte", "Local", "Motivo do Descarte"]
        st.dataframe(df_desc_display, use_container_width=True, hide_index=True)

st.divider()

# ==========================================
# 7. HISTÓRICO COMPLETO
# ==========================================
with st.expander("🔗 Histórico completo de links enviados"):
    df_hist = df[["data_envio", "link"]].sort_values("data_envio", ascending=False).copy()
    df_hist["data_envio"] = df_hist["data_envio"].dt.strftime("%d/%m/%Y %H:%M")
    df_hist.columns = ["Data/Hora", "Link"]
    st.dataframe(df_hist, use_container_width=True, hide_index=True)
