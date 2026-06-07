# 🤖 JobHunter AI

Sistema automatizado de busca, análise e candidatura a vagas com Python e IA.

## Estrutura do Projeto

```
jobhunter/
│
├── main.py                  ← Ponto de entrada (integra tudo)
├── requirements.txt         ← Dependências
│
├── fase1_mvp/
│   └── buscador.py          ← Busca vagas (Gupy + Remotive)
│
├── fase2_filtro/
│   └── filtro.py            ← Filtra vagas por palavras-chave
│
├── fase3_perfil/
│   ├── perfil.json          ← Seus dados (edite aqui!)
│   └── perfil.py            ← Lê e valida o perfil
│
└── dados/                   ← Pasta para banco de dados (Fase 6)
```

## Como Rodar

### 1. Instalar dependências
```bash
pip install -r requirements.txt
```

### 2. Editar seu perfil
Abra `fase3_perfil/perfil.json` e atualize com seus dados reais.

### 3. Executar
```bash
python main.py
```

### Rodar uma fase isolada
```bash
python fase1_mvp/buscador.py      # só a busca
python fase2_filtro/filtro.py     # só o filtro (com dados de exemplo)
python fase3_perfil/perfil.py     # só o perfil
```

## Roadmap

| Fase | Status | Descrição |
|------|--------|-----------|
| 0    | ✅ | Planejamento |
| 1    | ✅ | MVP Buscador |
| 2    | ✅ | Filtro Inteligente |
| 3    | ✅ | Perfil do Usuário |
| 4    | 🔜 | Match Score |
| 5    | 🔜 | Relatório |
| 6    | 🔜 | Banco de Dados SQLite |
| 7    | 🔜 | Bot Telegram |
| 8    | 🔜 | Currículo Inteligente |
| 9    | 🔜 | Análise com IA |
| 10   | 🔜 | Dashboard Streamlit |
