import streamlit as st
import sqlite3
import pandas as pd
import json
import os

# Configuração da página
st.set_page_config(page_title="JobHunter AI", page_icon="🤖", layout="wide")

st.title("🤖 Painel de Controle - JobHunter AI")
st.markdown("Monitoramento em tempo real da sua automação de caça a vagas.")

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
        preferencias = perfil.get("preferencias_vaga", {})
        for area in preferencias.get("areas", []):
            st.write(f"- {area}")
            
    with st.sidebar.expander("🛠️ Habilidades Mapeadas"):
        for hab in perfil.get("habilidades", []):
            st.write(f"- {hab}")
            
    st.sidebar.success("Sincronizado com a IA")
except Exception as e:
    st.sidebar.warning("Aguardando IA processar o perfil.json...")


# ==========================================
# 2. ÁREA PRINCIPAL (ESTATÍSTICAS DO DB)
# ==========================================
db_path = "vagas_enviadas.db"

if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT * FROM enviadas", conn)
    conn.close()

    if not df.empty:
        df['data_envio'] = pd.to_datetime(df['data_envio'])
        
        col1, col2 = st.columns(2)
        col1.metric("🔥 Total de Vagas Inéditas", len(df))
        col2.metric("⏱️ Última Vaga Capturada", df['data_envio'].max().strftime("%d/%m/%Y %H:%M"))

        st.divider()

        st.subheader("📈 Ritmo do Mercado (Vagas por Dia)")
        df['Data'] = df['data_envio'].dt.date
        vagas_por_dia = df.groupby('Data').size()
        st.bar_chart(vagas_por_dia, color="#ff4b4b")

        st.subheader("🔗 Histórico de Links Enviados")
        df_display = df[['data_envio', 'link']].sort_values(by="data_envio", ascending=False)
        df_display.columns = ['Data/Hora do Envio', 'Link da Vaga']
        st.dataframe(df_display, use_container_width=True, hide_index=True)
        
    else:
        st.info("O banco de dados está pronto, mas nenhuma vaga inédita foi salva ainda.")
else:
    st.warning("Banco de dados ainda não foi criado pela automação. Aguarde a próxima execução.")
