#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API Agro — Painel do Produtor
Precisão Inova / André CTO

Endpoints unificados para o chatbot WhatsApp:
  /cotacao/{produto}       — preço atual + variação
  /cotacoes/todas          — todas as cotações atuais
  /clima/{cidade}          — previsão 7 dias + atual
  /noticias                — últimas notícias agro
  /eventos                 — próximos eventos agro
  /webhook                 — recebe mensagens do WhatsApp (Evolution API)

Rodar:
  cd /opt/painel-produtor
  python3 api_agro.py

  Ou com uvicorn:
  uvicorn api_agro:app --host 0.0.0.0 --port 5056 --reload

Cron (garantir que está rodando):
  */5 * * * * pgrep -f api_agro || cd /opt/painel-produtor && python3 api_agro.py >> /var/log/painel-produtor/api.log 2>&1 &
"""

import os
import json
import logging
import hashlib
import math
from datetime import datetime, date
from typing import Optional

# Carregar config.env
from pathlib import Path
_env_file = Path(__file__).parent / 'config.env'
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

import pymysql
import pymysql.cursors
import requests
import anthropic
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────
DB = {
    'host':     '199.167.147.66',
    'port':     3306,
    'user':     'techobco_agropecuaria',
    'password': '@precisao2203',
    'database': 'techobco_agropecuaria',
    'charset':  'utf8mb4',
}

# Evolution API (ajustar após instalar)
EVOLUTION_URL  = os.getenv('EVOLUTION_URL', 'http://localhost:8080')
EVOLUTION_KEY  = os.getenv('EVOLUTION_KEY', 'inova-secret-key')
EVOLUTION_INST = os.getenv('EVOLUTION_INSTANCE', 'agro-bot')

# Claude API (mesmo .env do agente de apostas)
ANTHROPIC_KEY  = os.getenv('ANTHROPIC_API_KEY', '')

# Anti-duplicata (mesmo padrão do WhatsApp v2 de apostas)
_msg_seen = set()
MAX_SEEN  = 500

# ── FastAPI ───────────────────────────────────────────────────
app = FastAPI(title='API Agro — Painel do Produtor', version='1.1')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])


def get_conn():
    return pymysql.connect(**DB, cursorclass=pymysql.cursors.DictCursor, connect_timeout=10)


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS DE DADOS (o agente Claude chama estes via tool-use)
# ═══════════════════════════════════════════════════════════════

@app.get('/cotacao/{produto}')
def cotacao(produto: str):
    """Preço atual de um produto. Ex: /cotacao/soja"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            busca = produto.lower().replace('é', 'e').replace('á', 'a').replace('ã', 'a').replace('ú', 'u').replace('í', 'i').replace('ó', 'o').replace('ô', 'o').replace('ç', 'c')
            cur.execute(
                'SELECT * FROM cotacoes_atual WHERE produto LIKE %s ORDER BY atualizado_em DESC',
                (f'%{busca}%',)
            )
            rows = cur.fetchall()
            if not rows:
                return {'encontrado': False, 'produto': produto, 'mensagem': f'Produto "{produto}" não encontrado'}

            for r in rows:
                for k, v in r.items():
                    if hasattr(v, 'isoformat'):
                        r[k] = v.isoformat()
                    elif hasattr(v, '__float__'):
                        r[k] = float(v)

            return {'encontrado': True, 'quantidade': len(rows), 'cotacoes': rows}
    finally:
        conn.close()


@app.get('/cotacoes/todas')
def cotacoes_todas():
    """Todas as cotações atuais (commodities + hortifruti + câmbio)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM cotacoes_atual ORDER BY produto')
            cotacoes = cur.fetchall()
            cur.execute('SELECT * FROM cambio_atual ORDER BY par')
            cambio = cur.fetchall()

            for lst in [cotacoes, cambio]:
                for r in lst:
                    for k, v in r.items():
                        if hasattr(v, 'isoformat'): r[k] = v.isoformat()
                        elif hasattr(v, '__float__'): r[k] = float(v)

            return {'cotacoes': cotacoes, 'cambio': cambio}
    finally:
        conn.close()


@app.get('/clima/{cidade}')
def clima(cidade: str):
    """Clima atual + previsão 7 dias. Ex: /clima/pitangui"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            busca = cidade.lower().replace('á','a').replace('ã','a').replace('â','a').replace('é','e').replace('ê','e').replace('í','i').replace('ó','o').replace('õ','o').replace('ô','o').replace('ú','u').replace('ç','c')
            cur.execute(
                'SELECT * FROM municipios WHERE nome_busca LIKE %s LIMIT 1',
                (f'%{busca}%',)
            )
            mun = cur.fetchone()
            if not mun:
                return {'encontrado': False, 'cidade': cidade, 'mensagem': f'Município "{cidade}" não cadastrado'}

            mun_id = mun['id']

            cur.execute('SELECT * FROM clima_atual WHERE municipio_id = %s', (mun_id,))
            atual = cur.fetchone()

            cur.execute(
                'SELECT * FROM clima_previsao WHERE municipio_id = %s AND data_prev >= CURDATE() ORDER BY data_prev LIMIT 7',
                (mun_id,)
            )
            previsao = cur.fetchall()

            for obj in [atual] + previsao:
                if not obj: continue
                for k, v in obj.items():
                    if hasattr(v, 'isoformat'): obj[k] = v.isoformat()
                    elif hasattr(v, '__float__'): obj[k] = float(v)

            for k, v in mun.items():
                if hasattr(v, 'isoformat'): mun[k] = v.isoformat()
                elif hasattr(v, '__float__'): mun[k] = float(v)

            return {
                'encontrado': True,
                'municipio': mun,
                'atual': atual,
                'previsao': previsao,
            }
    finally:
        conn.close()


@app.get('/noticias')
def noticias(limite: int = 5, categoria: Optional[str] = None):
    """Últimas notícias agro. Ex: /noticias?limite=5&categoria=mercado"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if categoria:
                cur.execute(
                    'SELECT titulo, resumo, emoji, categoria, criado_em FROM agro_noticias WHERE categoria = %s ORDER BY criado_em DESC LIMIT %s',
                    (categoria, limite)
                )
            else:
                cur.execute(
                    'SELECT titulo, resumo, emoji, categoria, criado_em FROM agro_noticias ORDER BY criado_em DESC LIMIT %s',
                    (limite,)
                )
            rows = cur.fetchall()
            for r in rows:
                for k, v in r.items():
                    if hasattr(v, 'isoformat'): r[k] = v.isoformat()
            return {'noticias': rows, 'total': len(rows)}
    finally:
        conn.close()


@app.get('/eventos')
def eventos(limite: int = 5, uf: Optional[str] = None):
    """Próximos eventos agro. Ex: /eventos?uf=MG&limite=5"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if uf:
                cur.execute(
                    'SELECT titulo, local_evento, uf, data_inicio, data_fim, tipo, emoji FROM agro_eventos WHERE data_inicio >= CURDATE() AND uf = %s ORDER BY data_inicio LIMIT %s',
                    (uf.upper(), limite)
                )
            else:
                cur.execute(
                    'SELECT titulo, local_evento, uf, data_inicio, data_fim, tipo, emoji FROM agro_eventos WHERE data_inicio >= CURDATE() ORDER BY data_inicio LIMIT %s',
                    (limite,)
                )
            rows = cur.fetchall()
            for r in rows:
                for k, v in r.items():
                    if hasattr(v, 'isoformat'): r[k] = v.isoformat()
            return {'eventos': rows, 'total': len(rows)}
    finally:
        conn.close()


@app.get('/saude')
def saude():
    """Health check."""
    return {'status': 'ok', 'timestamp': datetime.now().isoformat(), 'versao': '1.1'}


# ═══════════════════════════════════════════════════════════════
# AGENTE CLAUDE — Processa mensagens do WhatsApp
# ═══════════════════════════════════════════════════════════════

def _normalizar(texto):
    """Remove acentos para busca flexível."""
    t = texto.lower()
    for a, b in [('á','a'),('ã','a'),('â','a'),('é','e'),('ê','e'),('í','i'),('ó','o'),('õ','o'),('ô','o'),('ú','u'),('ç','c')]:
        t = t.replace(a, b)
    return t


def _serializar(rows):
    """Serializa Decimal/datetime em lista de dicts."""
    if not rows:
        return rows
    if isinstance(rows, dict):
        rows = [rows]
    for r in rows:
        for k, v in r.items():
            if hasattr(v, 'isoformat'):
                r[k] = v.isoformat()
            elif hasattr(v, '__float__'):
                fv = float(v)
                r[k] = None if (math.isnan(fv) or math.isinf(fv)) else fv
    return rows


# Definição das tools que o Claude pode chamar
TOOLS_AGENTE = [
    # ── 5 tools originais ──
    {
        'name': 'consultar_cotacao',
        'description': 'Consulta o preço atual de um produto agrícola (soja, milho, café, boi, etc). Retorna preço, variação e data.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'produto': {
                    'type': 'string',
                    'description': 'Nome do produto. Ex: soja, milho, cafe, boi, frango, leite, algodao, trigo, acucar, etanol'
                }
            },
            'required': ['produto']
        }
    },
    {
        'name': 'consultar_clima',
        'description': 'Consulta clima atual e previsão 7 dias de um município. Retorna temperatura, chuva, umidade, vento, ET₀.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'cidade': {
                    'type': 'string',
                    'description': 'Nome da cidade/município. Ex: Pitangui, Uberlândia, Sorriso, Londrina'
                }
            },
            'required': ['cidade']
        }
    },
    {
        'name': 'consultar_noticias',
        'description': 'Busca as últimas notícias agropecuárias. Pode filtrar por categoria: mercado, clima, tecnologia, sustentabilidade, inovacao.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'categoria': {
                    'type': 'string',
                    'description': 'Categoria (opcional): mercado, clima, tecnologia, sustentabilidade, inovacao',
                    'enum': ['mercado', 'clima', 'tecnologia', 'sustentabilidade', 'inovacao']
                },
                'limite': {
                    'type': 'integer',
                    'description': 'Quantidade de notícias (padrão 5)',
                    'default': 5
                }
            }
        }
    },
    {
        'name': 'consultar_eventos',
        'description': 'Busca próximos eventos agropecuários (feiras, exposições, cursos). Pode filtrar por estado (UF).',
        'input_schema': {
            'type': 'object',
            'properties': {
                'uf': {
                    'type': 'string',
                    'description': 'Estado (UF) para filtrar. Ex: MG, SP, MT, GO'
                },
                'limite': {
                    'type': 'integer',
                    'description': 'Quantidade de eventos (padrão 5)',
                    'default': 5
                }
            }
        }
    },
    {
        'name': 'consultar_todas_cotacoes',
        'description': 'Lista TODAS as cotações atuais disponíveis (commodities + hortifruti + câmbio). Use quando o usuário quer um panorama geral.',
        'input_schema': {
            'type': 'object',
            'properties': {}
        }
    },

    # ── 5 tools novas (agrobr) ──
    {
        'name': 'consultar_safra',
        'description': (
            'Consulta a estimativa de safra CONAB para um produto agrícola. '
            'Retorna dados por UF: área plantada (mil ha), área colhida (mil ha), '
            'produtividade (kg/ha) e produção (mil ton). Safra 2025/26. '
            'Produtos: soja, milho, arroz, feijao, trigo, algodao, sorgo, amendoim.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'produto': {
                    'type': 'string',
                    'description': 'Nome do produto (ex: soja, milho, trigo)'
                },
                'uf': {
                    'type': 'string',
                    'description': 'Sigla do estado (ex: MG, MT, PR). Opcional.'
                },
            },
            'required': ['produto'],
        },
    },
    {
        'name': 'consultar_producao',
        'description': (
            'Consulta produção anual de um produto agrícola (IBGE/PAM). '
            'Retorna dados históricos por UF: área colhida, quantidade, rendimento e valor. '
            'Produtos: soja, milho, cafe, arroz, feijao, trigo, algodao, cana-de-acucar, laranja.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'produto': {
                    'type': 'string',
                    'description': 'Nome do produto (ex: soja, milho, cafe)'
                },
                'uf': {
                    'type': 'string',
                    'description': 'Sigla do estado. Opcional.'
                },
                'ano': {
                    'type': 'integer',
                    'description': 'Ano específico. Sem filtro retorna últimos 5 anos.'
                },
            },
            'required': ['produto'],
        },
    },
    {
        'name': 'consultar_historico_preco',
        'description': (
            'Consulta histórico de preços diários de um produto (CEPEA). '
            'Retorna série temporal com data, valor, praça e tendência. '
            'Útil para ver se o preço subiu ou caiu nos últimos dias/semanas. '
            'Produtos: soja, milho, cafe, boi, trigo, algodao.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'produto': {
                    'type': 'string',
                    'description': 'Nome do produto (ex: soja, cafe, boi)'
                },
                'dias': {
                    'type': 'integer',
                    'description': 'Dias pra trás. Padrão 15, máximo 90.'
                },
            },
            'required': ['produto'],
        },
    },
    {
        'name': 'consultar_exportacao',
        'description': (
            'Consulta exportações brasileiras de produtos agrícolas (ComexStat). '
            'Retorna volume (kg) e valor (USD) por ano/mês. '
            'Produtos: soja, milho, cafe, algodao, acucar, carne bovina, carne de frango.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'produto': {
                    'type': 'string',
                    'description': 'Nome do produto (ex: soja, cafe)'
                },
                'ano': {
                    'type': 'integer',
                    'description': 'Ano específico. Sem filtro retorna últimos 3 anos.'
                },
            },
            'required': ['produto'],
        },
    },
    {
        'name': 'consultar_credito_rural',
        'description': (
            'Consulta dados de crédito rural do Banco Central (SICOR). '
            'Retorna valor total e quantidade de contratos por UF e ano. '
            'Produtos: soja, milho, cafe, arroz, feijao, trigo.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'produto': {
                    'type': 'string',
                    'description': 'Nome do produto (ex: soja, milho)'
                },
                'uf': {
                    'type': 'string',
                    'description': 'Sigla do estado. Opcional.'
                },
            },
            'required': ['produto'],
        },
    },
]

SYSTEM_PROMPT = """Você é o assistente agrícola do Painel do Produtor — Precisão Inova.

Você ajuda agricultores brasileiros via WhatsApp com:
- Cotações de commodities (soja, milho, café, boi, etc) e hortifruti (CEASA-MG)
- Previsão do tempo e clima atual por município
- Notícias agropecuárias atualizadas
- Eventos agrícolas (feiras, exposições, cursos)
- Câmbio (dólar, euro)
- Estimativa de safra CONAB (área, produtividade, produção por UF)
- Produção anual IBGE por estado
- Histórico e tendência de preços (últimos dias/semanas)
- Exportações brasileiras por produto
- Crédito rural (contratos e valores por UF)

REGRAS:
- Responda SEMPRE em português brasileiro, tom amigável e direto
- Use emojis com moderação (🌾 🐂 ☕ 🌽 📊 📈 etc)
- Seja BREVE — o agricultor está no celular, mensagens curtas
- Quando mostrar preços, inclua a variação se disponível
- Para clima, destaque CHUVA (o produtor quer saber se vai chover)
- Para histórico de preço, destaque a TENDÊNCIA (subindo/caindo/estável)
- Para safra, destaque produção total e os maiores estados produtores
- Se não tiver dados de um município, diga e sugira cidades próximas
- Quando não souber, diga "não tenho essa informação agora"
- NÃO invente dados — use APENAS o que as tools retornarem
- Para perguntas fora do agro, responda educadamente que é um assistente agrícola

FORMATO:
- Sem markdown (WhatsApp não renderiza)
- Use linhas simples, emojis como separadores
- Máximo ~500 caracteres por resposta (SMS-friendly)
"""


def executar_tool(tool_name: str, tool_input: dict) -> str:
    """Executa a tool consultando o banco diretamente (evita deadlock single-worker)."""
    try:
        conn = get_conn()
        with conn.cursor() as cur:

            # ── Tools originais ──

            if tool_name == 'consultar_cotacao':
                produto = tool_input.get('produto', '')
                busca = _normalizar(produto)
                cur.execute('SELECT * FROM cotacoes_atual WHERE produto LIKE %s', (f'%{busca}%',))
                rows = cur.fetchall()
                _serializar(rows)
                # Se não achou em cotacoes, tentar cambio
                if not rows:
                    # Mapear nomes comuns pra par
                    cambio_map = {'dolar': 'USD', 'dollar': 'USD', 'usd': 'USD', 'euro': 'EUR', 'eur': 'EUR', 'libra': 'GBP', 'gbp': 'GBP'}
                    busca_cambio = cambio_map.get(busca, busca.upper())
                    cur.execute('SELECT * FROM cambio_atual WHERE par LIKE %s', (f'%{busca_cambio}%',))
                    cambio = cur.fetchall()
                    _serializar(cambio)
                    if cambio:
                        result = {'encontrado': True, 'cotacoes': cambio}
                    else:
                        result = {'encontrado': False, 'cotacoes': []}
                else:
                    result = {'encontrado': True, 'cotacoes': rows}

            elif tool_name == 'consultar_clima':
                cidade = tool_input.get('cidade', '')
                busca = _normalizar(cidade)
                cur.execute('SELECT * FROM municipios WHERE nome_busca LIKE %s LIMIT 1', (f'%{busca}%',))
                mun = cur.fetchone()
                if not mun:
                    result = {'encontrado': False, 'mensagem': f'Município "{cidade}" não cadastrado'}
                else:
                    mun_id = mun['id']
                    cur.execute('SELECT * FROM clima_atual WHERE municipio_id = %s', (mun_id,))
                    atual = cur.fetchone()
                    cur.execute('SELECT * FROM clima_previsao WHERE municipio_id = %s AND data_prev >= CURDATE() ORDER BY data_prev LIMIT 7', (mun_id,))
                    previsao = cur.fetchall()
                    _serializar([mun])
                    if atual:
                        _serializar([atual])
                    _serializar(previsao)
                    result = {'encontrado': True, 'municipio': mun, 'atual': atual, 'previsao': previsao}

            elif tool_name == 'consultar_noticias':
                limite = tool_input.get('limite', 5)
                categoria = tool_input.get('categoria')
                if categoria:
                    cur.execute('SELECT titulo, resumo, emoji, categoria, criado_em FROM agro_noticias WHERE categoria = %s ORDER BY criado_em DESC LIMIT %s', (categoria, limite))
                else:
                    cur.execute('SELECT titulo, resumo, emoji, categoria, criado_em FROM agro_noticias ORDER BY criado_em DESC LIMIT %s', (limite,))
                rows = cur.fetchall()
                _serializar(rows)
                result = {'noticias': rows, 'total': len(rows)}

            elif tool_name == 'consultar_eventos':
                limite = tool_input.get('limite', 5)
                uf = tool_input.get('uf')
                if uf:
                    cur.execute('SELECT titulo, local_evento, uf, data_inicio, data_fim, tipo, emoji FROM agro_eventos WHERE data_inicio >= CURDATE() AND uf = %s ORDER BY data_inicio LIMIT %s', (uf.upper(), limite))
                else:
                    cur.execute('SELECT titulo, local_evento, uf, data_inicio, data_fim, tipo, emoji FROM agro_eventos WHERE data_inicio >= CURDATE() ORDER BY data_inicio LIMIT %s', (limite,))
                rows = cur.fetchall()
                _serializar(rows)
                result = {'eventos': rows, 'total': len(rows)}

            elif tool_name == 'consultar_todas_cotacoes':
                cur.execute('SELECT * FROM cotacoes_atual ORDER BY produto')
                cotacoes = cur.fetchall()
                cur.execute('SELECT * FROM cambio_atual ORDER BY par')
                cambio = cur.fetchall()
                _serializar(cotacoes)
                _serializar(cambio)
                result = {'cotacoes': cotacoes, 'cambio': cambio}

            # ── Tools novas (agrobr) ──

            elif tool_name == 'consultar_safra':
                produto = _normalizar(tool_input.get('produto', ''))
                uf = tool_input.get('uf')
                query = "SELECT produto, safra, uf, area_plantada, area_colhida, produtividade, producao, levantamento, fonte, atualizado_em FROM safra_conab WHERE produto LIKE %s"
                params = [f'%{produto}%']
                if uf:
                    query += " AND uf = %s"
                    params.append(uf.upper())
                query += " ORDER BY safra DESC, producao DESC LIMIT 30"
                cur.execute(query, params)
                rows = cur.fetchall()
                _serializar(rows)
                if rows:
                    result = {'encontrado': True, 'total_ufs': len(rows), 'safra': rows[0].get('safra'), 'dados': rows}
                else:
                    result = {'encontrado': False, 'mensagem': f'Sem dados de safra para "{produto}". Tente: soja, milho, arroz, feijao, trigo, algodao.'}

            elif tool_name == 'consultar_producao':
                produto = _normalizar(tool_input.get('produto', ''))
                uf = tool_input.get('uf')
                ano = tool_input.get('ano')
                query = "SELECT produto, ano, uf, area_colhida, quantidade, rendimento, valor_producao, fonte, atualizado_em FROM producao_ibge WHERE produto LIKE %s"
                params = [f'%{produto}%']
                if uf:
                    query += " AND uf = %s"
                    params.append(uf.upper())
                if ano:
                    query += " AND ano = %s"
                    params.append(ano)
                else:
                    query += " AND ano >= YEAR(CURDATE()) - 5"
                query += " ORDER BY ano DESC, quantidade DESC LIMIT 30"
                cur.execute(query, params)
                rows = cur.fetchall()
                _serializar(rows)
                if rows:
                    result = {'encontrado': True, 'total': len(rows), 'dados': rows}
                else:
                    result = {'encontrado': False, 'mensagem': f'Sem dados de produção para "{produto}". Tente: soja, milho, cafe, arroz, trigo.'}

            elif tool_name == 'consultar_historico_preco':
                produto = _normalizar(tool_input.get('produto', ''))
                dias = min(max(tool_input.get('dias', 15), 5), 90)
                cur.execute(
                    "SELECT produto, praca, data_ref, valor, unidade, fonte FROM preco_historico WHERE produto LIKE %s AND data_ref >= DATE_SUB(CURDATE(), INTERVAL %s DAY) ORDER BY data_ref DESC LIMIT 60",
                    (f'%{produto}%', dias)
                )
                rows = cur.fetchall()
                _serializar(rows)
                if rows:
                    primeiro = float(rows[-1]['valor'])
                    ultimo = float(rows[0]['valor'])
                    variacao = ((ultimo - primeiro) / primeiro * 100) if primeiro else 0
                    tendencia = 'alta' if variacao > 1 else ('queda' if variacao < -1 else 'estavel')
                    result = {
                        'encontrado': True,
                        'produto': rows[0].get('produto'),
                        'praca': rows[0].get('praca'),
                        'preco_atual': ultimo,
                        'preco_inicio': primeiro,
                        'variacao_pct': round(variacao, 2),
                        'tendencia': tendencia,
                        'dias': len(rows),
                        'unidade': rows[0].get('unidade'),
                        'historico': rows[:15],
                    }
                else:
                    result = {'encontrado': False, 'mensagem': f'Sem histórico de preço para "{produto}". Tente: soja, milho, cafe, boi, trigo, algodao.'}

            elif tool_name == 'consultar_exportacao':
                produto = _normalizar(tool_input.get('produto', ''))
                ano = tool_input.get('ano')
                query = "SELECT produto, ano, mes, peso_kg, valor_usd, pais_destino, fonte FROM exportacao WHERE produto LIKE %s"
                params = [f'%{produto}%']
                if ano:
                    query += " AND ano = %s"
                    params.append(ano)
                else:
                    query += " AND ano >= YEAR(CURDATE()) - 3"
                query += " ORDER BY ano DESC, mes DESC LIMIT 50"
                cur.execute(query, params)
                rows = cur.fetchall()
                _serializar(rows)
                if rows:
                    result = {'encontrado': True, 'total': len(rows), 'dados': rows}
                else:
                    result = {'encontrado': False, 'mensagem': f'Sem dados de exportação para "{produto}". Tente: soja, milho, cafe, algodao, acucar.'}

            elif tool_name == 'consultar_credito_rural':
                produto = _normalizar(tool_input.get('produto', ''))
                uf = tool_input.get('uf')
                query = "SELECT produto, ano, uf, valor, qtd_contratos, fonte FROM credito_rural WHERE produto LIKE %s"
                params = [f'%{produto}%']
                if uf:
                    query += " AND uf = %s"
                    params.append(uf.upper())
                query += " ORDER BY ano DESC, valor DESC LIMIT 30"
                cur.execute(query, params)
                rows = cur.fetchall()
                _serializar(rows)
                if rows:
                    result = {'encontrado': True, 'total': len(rows), 'dados': rows}
                else:
                    result = {'encontrado': False, 'mensagem': f'Sem dados de crédito rural para "{produto}". Tente: soja, milho, cafe.'}

            else:
                result = {'erro': f'Tool desconhecida: {tool_name}'}

        conn.close()
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({'erro': str(e)})


def processar_com_agente(mensagem: str) -> str:
    """Envia mensagem pro Claude com tool-use e retorna resposta final."""
    if not ANTHROPIC_KEY:
        return '⚠️ Chave da API não configurada. Contate o suporte.'

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    messages = [{'role': 'user', 'content': mensagem}]

    # Loop de tool-use (máximo 5 iterações)
    for _ in range(5):
        response = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=800,
            system=SYSTEM_PROMPT,
            tools=TOOLS_AGENTE,
            messages=messages,
        )

        if response.stop_reason == 'end_turn':
            textos = [b.text for b in response.content if hasattr(b, 'text')]
            return '\n'.join(textos) if textos else '🌾 Não consegui processar. Tente novamente.'

        if response.stop_reason == 'tool_use':
            messages.append({'role': 'assistant', 'content': response.content})

            tool_results = []
            for block in response.content:
                if block.type == 'tool_use':
                    log.info(f'  🔧 Tool: {block.name}({block.input})')
                    resultado = executar_tool(block.name, block.input)
                    tool_results.append({
                        'type': 'tool_result',
                        'tool_use_id': block.id,
                        'content': resultado,
                    })

            messages.append({'role': 'user', 'content': tool_results})
        else:
            break

    return '🌾 Desculpe, tive um problema. Tente novamente em instantes.'


# ═══════════════════════════════════════════════════════════════
# WEBHOOK WHATSAPP (Evolution API)
# ═══════════════════════════════════════════════════════════════

def enviar_whatsapp(numero: str, texto: str):
    """Envia mensagem via Evolution API. Aceita jid completo ou numero."""
    url = f"{EVOLUTION_URL}/message/sendText/{EVOLUTION_INST}"
    if '@' in numero:
        payload = {'number': numero, 'textMessage': {'text': texto}}
    else:
        payload = {'number': numero, 'textMessage': {'text': texto}}
    try:
        r = requests.post(url, json=payload, headers={'apikey': EVOLUTION_KEY}, timeout=10)
        log.info(f'  📤 Enviado para {numero[:15]}... ({r.status_code})')
        if r.status_code != 201:
            log.warning(f'  ⚠️ Resposta: {r.text[:200]}')
    except Exception as e:
        log.error(f'  ✗ Erro envio WhatsApp: {e}')


@app.post('/webhook')
async def webhook_whatsapp(request: Request):
    """Recebe mensagens do WhatsApp via Evolution API webhook."""
    try:
        body = await request.json()
    except Exception:
        return {'status': 'ignored'}

    event = body.get('event', '')

    # Só processa mensagens recebidas
    if event not in ('messages.upsert', 'MESSAGES_UPSERT'):
        return {'status': 'ignored', 'event': event}

    data = body.get('data', {})
    key = data.get('key', {})

    # Ignora mensagens enviadas por nós (EXCETO comandos !add)
    msg_preview = ''
    msg_data_tmp = data.get('message', {})
    msg_preview = (msg_data_tmp.get('conversation') or (msg_data_tmp.get('extendedTextMessage', {}) or {}).get('text') or '').strip()
    if key.get('fromMe', False):
        if not msg_preview.startswith('!add'):
            return {'status': 'ignored', 'reason': 'fromMe'}

    # Extrai número e mensagem
    remote_jid = key.get('remoteJid', '')
    numero_log = remote_jid.replace('@s.whatsapp.net', '').replace('@g.us', '').replace('@lid', '')

    # Fix LID: se o jid é @lid, buscar número real no banco
    if '@lid' in remote_jid:
        lid_key = remote_jid.replace('@lid', '')
        try:
            conn_wp = get_conn()
            with conn_wp.cursor() as cur:
                cur.execute('SELECT numero, status FROM whatsapp_contatos WHERE lid = %s', (lid_key,))
                row = cur.fetchone()
                if row:
                    if row.get('status') == 'bloqueado':
                        log.info(f'  🚫 LID {lid_key} BLOQUEADO')
                        conn_wp.close()
                        return {'status': 'blocked'}
                    if row.get('status') == 'pendente' or not row.get('numero'):
                        log.info(f'  ⏳ LID {lid_key} ainda PENDENTE')
                        conn_wp.close()
                        return {'status': 'pending'}
                    numero = row['numero']
                    log.info(f'  🔗 LID {lid_key} -> {numero}')
                else:
                    numero = None
                    log.info(f'  ❓ LID {lid_key} sem mapeamento direto')
            conn_wp.close()
        except Exception as e:
            log.warning(f'  Erro busca LID: {e}')
            numero = None
    else:
        numero = remote_jid.replace('@s.whatsapp.net', '')

    # Ignora grupos
    if '@g.us' in remote_jid:
        return {'status': 'ignored', 'reason': 'group'}

    # Extrai texto da mensagem
    msg_data = data.get('message', {})
    mensagem = (
        msg_data.get('conversation')
        or (msg_data.get('extendedTextMessage', {}) or {}).get('text')
        or ''
    ).strip()

    # Mídia sem texto: ignorar silenciosamente (não gastar tokens)
    media_types = ['audioMessage', 'imageMessage', 'videoMessage', 'stickerMessage', 'documentMessage']
    is_media = any(mt in msg_data for mt in media_types)
    if is_media and not mensagem:
        return {'status': 'ignored', 'reason': 'media_no_text'}

    if not mensagem:
        return {'status': 'ignored', 'reason': 'empty'}

    # Só responde se começar com !
    if not mensagem.startswith('!'):
        return {'status': 'ignored', 'reason': 'no_prefix'}
    mensagem = mensagem[1:].strip()
    if not mensagem:
        # Menu de opções
        menu = (
            "🌾 *Painel do Produtor* — O que posso ajudar?\n\n"
            "📊 Cotações:\n"
            "  ! preço da soja\n"
            "  ! cotação do café\n"
            "  ! todas as cotações\n\n"
            "🌧️ Clima:\n"
            "  ! clima em Pitangui\n"
            "  ! vai chover em Sorriso?\n\n"
            "📰 Informações:\n"
            "  ! notícias do agro\n"
            "  ! eventos em MG\n\n"
            "📈 Análises:\n"
            "  ! safra da soja\n"
            "  ! tendência do milho\n"
            "  ! exportações de café\n\n"
            "🍇 Frutas (4 CEASAs):\n"
            "  ! preço da pitaya\n"
            "  ! abacate em SP e BH\n\n"
            "💵 Câmbio:\n"
            "  ! dólar hoje\n"
        )
        if numero:
            enviar_whatsapp(numero, menu)
        return {'status': 'menu_sent'}

    # Anti-duplicata
    msg_id = data.get('key', {}).get('id', '')
    msg_hash = hashlib.md5(f'{numero}:{msg_id}'.encode()).hexdigest()
    if msg_hash in _msg_seen:
        return {'status': 'duplicate'}
    _msg_seen.add(msg_hash)
    if len(_msg_seen) > MAX_SEEN:
        _msg_seen.clear()

    log.info(f'📩 {numero_log[:8]}...: "{mensagem[:60]}"')

    # Comando admin: !add NUMERO NOME
    if mensagem.lower().startswith('add '):
        parts = mensagem[4:].strip().split(' ', 1)
        if len(parts) >= 1:
            import re as _re
            tel_add = _re.sub(r'[^0-9]', '', parts[0])
            nome_add = parts[1] if len(parts) > 1 else 'Contato'
            if not tel_add.startswith('55'):
                tel_add = '55' + tel_add
            if len(tel_add) >= 12:
                try:
                    conn_add = get_conn()
                    with conn_add.cursor() as cur_add:
                        cur_add.execute('SELECT lid FROM whatsapp_contatos WHERE numero = %s', (tel_add,))
                        exists = cur_add.fetchone()
                        if exists:
                            log.info(f'  ℹ️ Número {tel_add} já cadastrado com LID {exists["lid"]}')
                        else:
                            cur_add.execute(
                                'INSERT INTO whatsapp_contatos (lid, numero, nome) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE numero=VALUES(numero), nome=VALUES(nome)',
                                (f'pending_{tel_add}', tel_add, nome_add)
                            )
                            conn_add.commit()
                            log.info(f'  ✅ Admin add: {tel_add} ({nome_add})')
                    conn_add.close()
                    if numero:
                        enviar_whatsapp(numero, f'✅ Cadastrado: {tel_add} ({nome_add})')
                        enviar_whatsapp(tel_add, f'🌾 Olá {nome_add}! Você foi cadastrado no Painel do Produtor.\n\nDigite ! seguido da sua pergunta:\n\n! Preço da soja?\n! Vai chover em Pitangui?\n! Últimas notícias do agro')
                except Exception as e:
                    log.error(f'  Erro admin add: {e}')
                return {'status': 'admin_add'}
        return {'status': 'invalid_add'}

    # Se não tem número mapeado, pedir registro
    if numero is None:
        import re as _re
        tel = _re.sub(r'[^0-9]', '', mensagem)
        if len(tel) >= 10 and len(tel) <= 13:
            if not tel.startswith('55'):
                tel = '55' + tel
            lid_key = remote_jid.replace('@lid', '')
            push_name = data.get('pushName', '')
            try:
                conn_wp = get_conn()
                with conn_wp.cursor() as cur:
                    cur.execute(
                        'INSERT INTO whatsapp_contatos (lid, numero, nome) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE numero=VALUES(numero), nome=VALUES(nome)',
                        (lid_key, tel, push_name)
                    )
                conn_wp.commit()
                conn_wp.close()
                log.info(f'  ✅ Registrado: {lid_key} -> {tel} ({push_name})')
                enviar_whatsapp(tel, f'✅ Cadastro confirmado, {push_name or "amigo"}! Agora pode perguntar:\n\n🌾 Preço da soja?\n🌧️ Vai chover em Pitangui?\n📰 Últimas notícias do agro')
            except Exception as e:
                log.error(f'  Erro registro: {e}')
            return {'status': 'registered'}
        else:
            push_name = data.get('pushName', 'Desconhecido')
            lid_key = remote_jid.replace('@lid', '')

            # Auto-cadastro: "cadastro NUMERO"
            match_cadastro = _re.match(r'(?:cadastro|registro|meu numero)\s+(\d[\d\s\-()]+)', mensagem.lower())
            if match_cadastro:
                tel_auto = _re.sub(r'[^0-9]', '', match_cadastro.group(1))
                if not tel_auto.startswith('55'):
                    tel_auto = '55' + tel_auto
                if len(tel_auto) >= 12:
                    try:
                        conn_auto = get_conn()
                        with conn_auto.cursor() as cur_auto:
                            cur_auto.execute(
                                "INSERT INTO whatsapp_contatos (lid, numero, nome, push_name, status) VALUES (%s, %s, %s, %s, 'aprovado') ON DUPLICATE KEY UPDATE numero=VALUES(numero), nome=VALUES(nome), push_name=VALUES(push_name), status='aprovado'",
                                (lid_key, tel_auto, push_name, push_name)
                            )
                        conn_auto.commit()
                        conn_auto.close()
                        log.info(f'  ✅ Auto-cadastro: {lid_key} -> {tel_auto} ({push_name})')
                        enviar_whatsapp(tel_auto, f'✅ Cadastro confirmado, {push_name}! Agora pode perguntar:\n\n! Preço da soja?\n! Vai chover em Pitangui?\n! Últimas notícias do agro')
                        return {'status': 'auto_registered'}
                    except Exception as e:
                        log.warning(f'  Erro auto-cadastro: {e}')

            # Senão, salvar como pendente
            try:
                conn_pend = get_conn()
                with conn_pend.cursor() as cur_pend:
                    cur_pend.execute(
                        "INSERT IGNORE INTO whatsapp_contatos (lid, numero, nome, push_name, status) VALUES (%s, '', %s, %s, 'pendente')",
                        (lid_key, push_name, push_name)
                    )
                conn_pend.commit()
                conn_pend.close()
                log.info(f'  📋 LID {lid_key} salvo como PENDENTE ({push_name})')
            except Exception as e:
                log.warning(f'  Erro save pendente: {e}')
            return {'status': 'pending_approval'}

    # Processa com o agente Claude
    try:
        resposta = processar_com_agente(mensagem)
    except Exception as e:
        log.error(f'  ✗ Erro agente: {e}')
        resposta = '⚠️ Desculpe, estou com dificuldades técnicas. Tente novamente em alguns minutos.'

    enviar_whatsapp(numero, resposta)

    return {'status': 'ok', 'numero': numero_log[:8]}


# ═══════════════════════════════════════════════════════════════
# ADMIN — Painel de gerenciamento de contatos
# ═══════════════════════════════════════════════════════════════

@app.get('/admin/contatos')
def admin_contatos(status: Optional[str] = None):
    """Lista todos os contatos WhatsApp."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if status:
                cur.execute('SELECT * FROM whatsapp_contatos WHERE status = %s ORDER BY criado_em DESC', (status,))
            else:
                cur.execute('SELECT * FROM whatsapp_contatos ORDER BY FIELD(status, "pendente", "aprovado", "bloqueado"), criado_em DESC')
            rows = cur.fetchall()
            _serializar(rows)
            return {'contatos': rows, 'total': len(rows)}
    finally:
        conn.close()


@app.post('/admin/aprovar')
async def admin_aprovar(request: Request):
    """Aprova um contato: {lid, numero, nome}"""
    body = await request.json()
    lid = body.get('lid', '')
    numero = body.get('numero', '')
    nome = body.get('nome', '')
    if not lid or not numero:
        return {'error': 'lid e numero obrigatórios'}
    import re as _re
    numero = _re.sub(r'[^0-9]', '', numero)
    if not numero.startswith('55'):
        numero = '55' + numero
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE whatsapp_contatos SET numero=%s, nome=%s, status='aprovado' WHERE lid=%s",
                (numero, nome, lid)
            )
        conn.commit()
        try:
            enviar_whatsapp(numero, f'🌾 Olá {nome}! Você foi aprovado no Painel do Produtor.\n\nDigite ! seguido da sua pergunta:\n\n! Preço da soja?\n! Vai chover em Pitangui?\n! Últimas notícias do agro')
        except:
            pass
        return {'status': 'ok', 'lid': lid, 'numero': numero}
    finally:
        conn.close()


@app.post('/admin/bloquear')
async def admin_bloquear(request: Request):
    """Bloqueia um contato: {lid}"""
    body = await request.json()
    lid = body.get('lid', '')
    if not lid:
        return {'error': 'lid obrigatório'}
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE whatsapp_contatos SET status='bloqueado' WHERE lid=%s", (lid,))
        conn.commit()
        return {'status': 'ok', 'lid': lid}
    finally:
        conn.close()


@app.post('/admin/desbloquear')
async def admin_desbloquear(request: Request):
    """Desbloqueia um contato: {lid}"""
    body = await request.json()
    lid = body.get('lid', '')
    if not lid:
        return {'error': 'lid obrigatório'}
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE whatsapp_contatos SET status='aprovado' WHERE lid=%s", (lid,))
        conn.commit()
        return {'status': 'ok', 'lid': lid}
    finally:
        conn.close()


@app.post('/admin/remover')
async def admin_remover(request: Request):
    """Remove um contato: {lid}"""
    body = await request.json()
    lid = body.get('lid', '')
    if not lid:
        return {'error': 'lid obrigatório'}
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM whatsapp_contatos WHERE lid=%s", (lid,))
        conn.commit()
        return {'status': 'ok', 'lid': lid}
    finally:
        conn.close()



@app.post('/admin/toggle_alertas')
async def admin_toggle_alertas(request: Request):
    """Liga/desliga alertas para um contato: {lid}"""
    body = await request.json()
    lid = body.get('lid', '')
    if not lid:
        return {'error': 'lid obrigatorio'}
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT recebe_alertas FROM whatsapp_contatos WHERE lid=%s', (lid,))
            row = cur.fetchone()
            if not row:
                return {'error': 'contato nao encontrado'}
            novo = 0 if row.get('recebe_alertas', 0) else 1
            cur.execute('UPDATE whatsapp_contatos SET recebe_alertas=%s WHERE lid=%s', (novo, lid))
        conn.commit()
        return {'status': 'ok', 'lid': lid, 'recebe_alertas': novo}
    finally:
        conn.close()


ADMIN_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Painel Admin — Bot Agro</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f1117; color: #e0e0e0; padding: 20px; }
h1 { color: #4ade80; margin-bottom: 5px; font-size: 24px; }
.subtitle { color: #888; margin-bottom: 20px; font-size: 14px; }
.stats { display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }
.stat { background: #1a1d27; padding: 12px 20px; border-radius: 10px; text-align: center; min-width: 100px; }
.stat .num { font-size: 28px; font-weight: 700; }
.stat .label { font-size: 11px; color: #888; margin-top: 4px; }
.stat.pending .num { color: #f59e0b; }
.stat.approved .num { color: #4ade80; }
.stat.blocked .num { color: #ef4444; }
.filters { margin-bottom: 15px; }
.filters button { background: #1a1d27; border: 1px solid #333; color: #ccc; padding: 6px 16px; border-radius: 6px; cursor: pointer; margin-right: 6px; font-size: 13px; }
.filters button.active { background: #4ade80; color: #000; border-color: #4ade80; }
.card { background: #1a1d27; border-radius: 10px; padding: 16px; margin-bottom: 10px; border-left: 4px solid #333; }
.card.pendente { border-left-color: #f59e0b; }
.card.aprovado { border-left-color: #4ade80; }
.card.bloqueado { border-left-color: #ef4444; }
.card .name { font-size: 16px; font-weight: 600; }
.card .lid { font-size: 11px; color: #666; margin-top: 2px; }
.card .info { font-size: 13px; color: #aaa; margin-top: 6px; }
.card .actions { margin-top: 10px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.card input { background: #0f1117; border: 1px solid #444; color: #fff; padding: 6px 10px; border-radius: 6px; font-size: 13px; width: 180px; }
.btn { padding: 6px 14px; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 500; }
.btn-approve { background: #4ade80; color: #000; }
.btn-block { background: #ef4444; color: #fff; }
.btn-remove { background: #333; color: #aaa; }
.btn:hover { opacity: 0.85; }
.empty { text-align: center; padding: 40px; color: #555; }
.toast { position: fixed; bottom: 20px; right: 20px; background: #4ade80; color: #000; padding: 12px 20px; border-radius: 8px; font-weight: 500; display: none; z-index: 99; }
</style>
</head>
<body>
<h1>🌾 Painel Admin — Bot Agro</h1>
<p class="subtitle">Gerenciamento de contatos WhatsApp</p>

<div class="stats" id="stats"></div>
<div class="filters" id="filters"></div>
<div id="list"></div>
<div class="toast" id="toast"></div>

<script>
const API = '';
let contatos = [];
let filtro = 'todos';

async function load() {
    const r = await fetch(API + '/admin/contatos');
    const d = await r.json();
    contatos = d.contatos || [];
    render();
}

function render() {
    const pending = contatos.filter(c => c.status === 'pendente').length;
    const approved = contatos.filter(c => c.status === 'aprovado').length;
    const blocked = contatos.filter(c => c.status === 'bloqueado').length;

    document.getElementById('stats').innerHTML = `
        <div class="stat pending"><div class="num">${pending}</div><div class="label">PENDENTES</div></div>
        <div class="stat approved"><div class="num">${approved}</div><div class="label">APROVADOS</div></div>
        <div class="stat blocked"><div class="num">${blocked}</div><div class="label">BLOQUEADOS</div></div>
        <div class="stat"><div class="num">${contatos.filter(c => c.recebe_alertas).length}</div><div class="label">🔔 ALERTAS</div></div>
        <div class="stat"><div class="num">${contatos.length}</div><div class="label">TOTAL</div></div>
    `;

    const filters = ['todos', 'pendente', 'aprovado', 'bloqueado'];
    document.getElementById('filters').innerHTML = filters.map(f =>
        `<button class="${filtro === f ? 'active' : ''}" onclick="setFiltro('${f}')">${f.charAt(0).toUpperCase() + f.slice(1)}${f !== 'todos' ? ` (${f === 'pendente' ? pending : f === 'aprovado' ? approved : blocked})` : ''}</button>`
    ).join('');

    const filtered = filtro === 'todos' ? contatos : contatos.filter(c => c.status === filtro);

    if (filtered.length === 0) {
        document.getElementById('list').innerHTML = '<div class="empty">Nenhum contato encontrado</div>';
        return;
    }

    document.getElementById('list').innerHTML = filtered.map(c => `
        <div class="card ${c.status}">
            <div class="name">${c.push_name || c.nome || 'Sem nome'}</div>
            <div class="lid">LID: ${c.lid}</div>
            <div class="info">
                ${c.numero ? '📱 ' + c.numero : '📱 Sem número'}
                ${c.nome ? ' · ' + c.nome : ''}
                · ${c.status.toUpperCase()}
                · ${c.criado_em ? new Date(c.criado_em).toLocaleString('pt-BR') : ''}
            </div>
            <div class="actions">
                ${c.status === 'pendente' ? `
                    <input type="text" id="num_${c.lid}" placeholder="5537999999999" />
                    <button class="btn btn-approve" onclick="aprovar('${c.lid}')">✓ Aprovar</button>
                    <button class="btn btn-block" onclick="bloquear('${c.lid}')">✗ Bloquear</button>
                ` : ''}
                ${c.status === 'aprovado' ? `
                    <span style="color:#4ade80">✓ Ativo — ${c.numero}</span>
                    <button class="btn ${c.recebe_alertas ? 'btn-approve' : 'btn-remove'}" onclick="toggleAlertas('${c.lid}')">${c.recebe_alertas ? '🔔 Alertas ON' : '🔕 Alertas OFF'}</button>
                    <button class="btn btn-block" onclick="bloquear('${c.lid}')">Bloquear</button>
                ` : ''}
                ${c.status === 'bloqueado' ? `
                    <span style="color:#ef4444">✗ Bloqueado</span>
                    <button class="btn btn-approve" onclick="desbloquear('${c.lid}')">Desbloquear</button>
                    <button class="btn btn-remove" onclick="remover('${c.lid}')">Remover</button>
                ` : ''}
            </div>
        </div>
    `).join('');
}

function setFiltro(f) { filtro = f; render(); }

async function aprovar(lid) {
    const input = document.getElementById('num_' + lid);
    const numero = input ? input.value.trim() : '';
    if (!numero || numero.length < 10) {
        toast('Digite o número com DDD', '#ef4444');
        return;
    }
    const nome = contatos.find(c => c.lid === lid)?.push_name || '';
    const r = await fetch(API + '/admin/aprovar', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({lid, numero, nome})
    });
    if (r.ok) { toast('✓ Aprovado! Boas-vindas enviada'); load(); }
}

async function bloquear(lid) {
    if (!confirm('Bloquear este contato?')) return;
    await fetch(API + '/admin/bloquear', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({lid})
    });
    toast('✗ Bloqueado', '#ef4444'); load();
}

async function remover(lid) {
    if (!confirm('Remover permanentemente?')) return;
    await fetch(API + '/admin/remover', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({lid})
    });
    toast('Removido'); load();
}

async function desbloquear(lid) {
    await fetch(API + '/admin/desbloquear', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({lid})
    });
    toast('✓ Desbloqueado'); load();
}

async function toggleAlertas(lid) {
    const r = await fetch(API + '/admin/toggle_alertas', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({lid})
    });
    if (r.ok) {
        const d = await r.json();
        toast(d.recebe_alertas ? '🔔 Alertas ativados' : '🔕 Alertas desativados');
        load();
    }
}

function toast(msg, color) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.style.background = color || '#4ade80';
    t.style.color = color === '#ef4444' ? '#fff' : '#000';
    t.style.display = 'block';
    setTimeout(() => t.style.display = 'none', 3000);
}

load();
setInterval(load, 15000);
</script>
</body>
</html>"""

from fastapi.responses import HTMLResponse

@app.get('/admin', response_class=HTMLResponse)
def admin_page():
    return ADMIN_HTML


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    log.info('='*55)
    log.info('API AGRO — Painel do Produtor v1.1')
    log.info('10 tools: cotacao, clima, noticias, eventos, cambio,')
    log.info('          safra, producao, historico, exportacao, credito')
    log.info('Porta: 5056 | Docs: http://localhost:5056/docs')
    log.info('='*55)
    uvicorn.run(app, host='0.0.0.0', port=5056, log_level='info')
