#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper de Clima Agrícola — Painel do Produtor
Precisão Inova / André CTO

Fonte: Open-Meteo (gratuita, sem API key)
  - Previsão 7 dias: temp, chuva, umidade, vento, radiação, ET₀
  - Clima atual: temperatura, umidade, vento, chuva 1h

Salva em: clima_previsao, clima_atual (techobco_agropecuaria)

Cron (a cada 3h):
  0 */3 * * * /opt/painel-produtor/venv/bin/python3 /opt/painel-produtor/scraper_clima.py >> /var/log/painel-produtor/clima.log 2>&1

Uso:
  python3 scraper_clima.py              # roda todos os municípios
  python3 scraper_clima.py --test       # testa sem salvar no banco
  python3 scraper_clima.py --cidade pitangui   # só um município
"""

import sys
import logging
import argparse
import time as t
from datetime import datetime

import requests
import pymysql
import pymysql.cursors

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)

# ── Banco (mesmo padrão do scraper_cepea.py) ──────────────────
DB = {
    'host':        '199.167.147.66',
    'port':        3306,
    'user':        'techobco_agropecuaria',
    'password':    '@precisao2203',
    'database':    'techobco_agropecuaria',
    'charset':     'utf8mb4',
}

SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'PainelProdutor/1.0 (scraper_clima)',
    'Accept': 'application/json',
})

# ── Open-Meteo API (gratuita, sem key) ────────────────────────
# Docs: https://open-meteo.com/en/docs
OPENMETEO_FORECAST = 'https://api.open-meteo.com/v1/forecast'

# Variáveis diárias (previsão 7 dias)
DAILY_VARS = [
    'temperature_2m_max',
    'temperature_2m_min',
    'precipitation_sum',
    'precipitation_probability_max',
    'relative_humidity_2m_mean',       # umidade média do dia (útil pra doenças/pragas)
    'wind_speed_10m_max',
    'shortwave_radiation_sum',         # radiação solar total MJ/m² (fotossíntese)
    'et0_fao_evapotranspiration',      # ET₀ FAO Penman-Monteith (irrigação)
    'weather_code',
]

# Variáveis atuais (tempo agora)
CURRENT_VARS = [
    'temperature_2m',
    'relative_humidity_2m',
    'wind_speed_10m',
    'precipitation',
    'weather_code',
]

# Descrições WMO weather code → emoji (pro WhatsApp)
WMO_EMOJI = {
    0: '☀️', 1: '🌤️', 2: '⛅', 3: '☁️',
    45: '🌫️', 48: '🌫️',
    51: '🌦️', 53: '🌦️', 55: '🌧️',
    61: '🌧️', 63: '🌧️', 65: '🌧️',
    71: '❄️', 73: '❄️', 75: '❄️',
    80: '🌧️', 81: '🌧️', 82: '⛈️',
    95: '⛈️', 96: '⛈️', 99: '⛈️',
}

WMO_DESC = {
    0: 'Céu limpo', 1: 'Poucas nuvens', 2: 'Parcialmente nublado', 3: 'Nublado',
    45: 'Névoa', 48: 'Geada',
    51: 'Garoa leve', 53: 'Garoa', 55: 'Garoa forte',
    61: 'Chuva leve', 63: 'Chuva moderada', 65: 'Chuva forte',
    71: 'Neve leve', 73: 'Neve', 75: 'Neve forte',
    80: 'Pancadas leves', 81: 'Pancadas', 82: 'Pancadas fortes',
    95: 'Tempestade', 96: 'Tempestade c/ granizo', 99: 'Tempestade forte c/ granizo',
}


def get_conn():
    return pymysql.connect(**DB, cursorclass=pymysql.cursors.DictCursor, connect_timeout=10, autocommit=False)


def buscar_municipios(conn, filtro_cidade=None):
    """Busca municípios do banco. Se filtro_cidade, filtra por nome_busca."""
    with conn.cursor() as cur:
        if filtro_cidade:
            cur.execute(
                'SELECT id, nome, uf, latitude, longitude FROM municipios WHERE nome_busca LIKE %s',
                (f'%{filtro_cidade.lower()}%',)
            )
        else:
            cur.execute('SELECT id, nome, uf, latitude, longitude FROM municipios ORDER BY id')
        return cur.fetchall()


def fetch_clima(lat, lon):
    """
    Chama Open-Meteo e retorna previsão 7 dias + clima atual.
    Gratuita, sem API key, limite ~10.000 req/dia.
    """
    params = {
        'latitude': float(lat),
        'longitude': float(lon),
        'daily': ','.join(DAILY_VARS),
        'current': ','.join(CURRENT_VARS),
        'timezone': 'America/Sao_Paulo',
        'forecast_days': 7,
    }

    try:
        r = SESSION.get(OPENMETEO_FORECAST, params=params, timeout=12)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f'  OpenMeteo erro: {e}')
        return None


def salvar_previsao(conn, municipio_id, dados):
    """Salva previsão 7 dias (upsert por municipio_id + data)."""
    daily = dados.get('daily', {})
    datas = daily.get('time', [])
    if not datas:
        return 0

    saved = 0
    with conn.cursor() as cur:
        for i, data_str in enumerate(datas):
            try:
                cur.execute(
                    """INSERT INTO clima_previsao
                       (municipio_id, data_prev, temp_max, temp_min, chuva_mm,
                        prob_chuva, umidade_media, vento_max_kmh, radiacao_mj,
                        et0_mm, codigo_clima)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE
                        temp_max=VALUES(temp_max), temp_min=VALUES(temp_min),
                        chuva_mm=VALUES(chuva_mm), prob_chuva=VALUES(prob_chuva),
                        umidade_media=VALUES(umidade_media), vento_max_kmh=VALUES(vento_max_kmh),
                        radiacao_mj=VALUES(radiacao_mj), et0_mm=VALUES(et0_mm),
                        codigo_clima=VALUES(codigo_clima), atualizado_em=NOW()""",
                    (
                        municipio_id,
                        data_str,
                        _safe(daily, 'temperature_2m_max', i),
                        _safe(daily, 'temperature_2m_min', i),
                        _safe(daily, 'precipitation_sum', i),
                        _safe(daily, 'precipitation_probability_max', i),
                        _safe(daily, 'relative_humidity_2m_mean', i),
                        _safe(daily, 'wind_speed_10m_max', i),
                        _safe(daily, 'shortwave_radiation_sum', i),
                        _safe(daily, 'et0_fao_evapotranspiration', i),
                        _safe(daily, 'weather_code', i),
                    )
                )
                saved += 1
            except Exception as e:
                log.warning(f'  Erro salvar previsão {data_str}: {e}')
    return saved


def salvar_atual(conn, municipio_id, dados):
    """Salva clima atual (upsert por municipio_id)."""
    current = dados.get('current', {})
    if not current:
        return 0

    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO clima_atual
                   (municipio_id, temperatura, umidade, vento_kmh, chuva_1h_mm, codigo_clima)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                    temperatura=VALUES(temperatura), umidade=VALUES(umidade),
                    vento_kmh=VALUES(vento_kmh), chuva_1h_mm=VALUES(chuva_1h_mm),
                    codigo_clima=VALUES(codigo_clima), atualizado_em=NOW()""",
                (
                    municipio_id,
                    current.get('temperature_2m'),
                    current.get('relative_humidity_2m'),
                    current.get('wind_speed_10m'),
                    current.get('precipitation'),
                    current.get('weather_code'),
                )
            )
        return 1
    except Exception as e:
        log.warning(f'  Erro salvar atual: {e}')
        return 0


def _safe(daily, key, idx):
    """Acesso seguro a arrays do Open-Meteo (podem ter None)."""
    arr = daily.get(key, [])
    if idx < len(arr):
        return arr[idx]
    return None


def salvar_log(conn, fonte, status, mensagem='', duracao_ms=0):
    """Mesmo padrão do scraper_cepea.py."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO scraper_log (fonte, status, mensagem, duracao_ms) VALUES (%s,%s,%s,%s)',
                (fonte, status, mensagem[:2000], duracao_ms)
            )
        conn.commit()
    except Exception:
        pass


def formatar_preview(municipio, dados):
    """Preview do clima pra modo --test (ou futuro WhatsApp)."""
    current = dados.get('current', {})
    daily = dados.get('daily', {})

    temp = current.get('temperature_2m', '?')
    umid = current.get('relative_humidity_2m', '?')
    code = current.get('weather_code', 0)
    emoji = WMO_EMOJI.get(code, '🌡️')
    desc = WMO_DESC.get(code, 'Indefinido')

    linhas = [
        f"  {emoji} {municipio['nome']}/{municipio['uf']} — {desc}",
        f"     Agora: {temp}°C | Umidade: {umid}%",
    ]

    datas = daily.get('time', [])
    for i in range(min(3, len(datas))):
        tmax = _safe(daily, 'temperature_2m_max', i) or '?'
        tmin = _safe(daily, 'temperature_2m_min', i) or '?'
        chuva = _safe(daily, 'precipitation_sum', i) or 0
        prob = _safe(daily, 'precipitation_probability_max', i) or 0
        et0 = _safe(daily, 'et0_fao_evapotranspiration', i) or 0
        d_code = _safe(daily, 'weather_code', i) or 0
        d_emoji = WMO_EMOJI.get(d_code, '🌡️')

        chuva_txt = f'💧 {chuva}mm ({prob}%)' if chuva > 0 else f'Sem chuva ({prob}%)'
        linhas.append(f"     {datas[i]}: {d_emoji} {tmin}°–{tmax}° | {chuva_txt} | ET₀ {et0}mm")

    return '\n'.join(linhas)


def run(test_mode=False, filtro_cidade=None):
    log.info('=' * 55)
    log.info('SCRAPER CLIMA AGRÍCOLA — iniciando')
    if test_mode:
        log.info('MODO TESTE — banco não será alterado')
    if filtro_cidade:
        log.info(f'Filtro: {filtro_cidade}')
    log.info('=' * 55)

    t0 = t.time()

    try:
        conn = get_conn()
        log.info('✓ Banco conectado')
    except Exception as e:
        log.error(f'✗ Conexão falhou: {e}')
        sys.exit(1)

    municipios = buscar_municipios(conn, filtro_cidade)
    if not municipios:
        log.warning('Nenhum município encontrado. Rode setup_clima.sql primeiro.')
        conn.close()
        return

    log.info(f'{len(municipios)} municípios para atualizar')
    total_prev = 0
    total_atual = 0
    erros = 0

    for mun in municipios:
        nome_display = f"{mun['nome']}/{mun['uf']}"
        log.info(f"\n── {nome_display} ({mun['latitude']}, {mun['longitude']})")

        dados = fetch_clima(mun['latitude'], mun['longitude'])
        if not dados:
            erros += 1
            continue

        if test_mode:
            print(formatar_preview(mun, dados))
        else:
            n_prev = salvar_previsao(conn, mun['id'], dados)
            n_atual = salvar_atual(conn, mun['id'], dados)
            conn.commit()
            total_prev += n_prev
            total_atual += n_atual
            log.info(f'  ✓ {n_prev} dias previsão + atual salvo')

        # Respeita rate limit Open-Meteo (gentil: 0.5s entre requests)
        t.sleep(0.5)

    duracao = int((t.time() - t0) * 1000)

    if not test_mode:
        salvar_log(conn, 'clima', 'ok', f'{total_prev} previsões, {total_atual} atuais, {erros} erros', duracao)

    conn.close()
    log.info(f'\n✓ Concluído em {duracao}ms — {total_prev} previsões + {total_atual} atuais | {erros} erros')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Scraper clima agrícola — Open-Meteo')
    ap.add_argument('--test', action='store_true', help='Testa sem salvar no banco')
    ap.add_argument('--cidade', type=str, default=None, help='Filtrar por nome da cidade')
    args = ap.parse_args()
    run(test_mode=args.test, filtro_cidade=args.cidade)
