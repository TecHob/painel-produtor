#!/usr/bin/env python3
"""
scraper_ceasa_curitiba.py — Cotações CEASA Curitiba (181 produtos)
Fonte: celepar7.pr.gov.br/ceasa/hoje_curitiba.asp

Inclui pitaya, caqui, kiwi, manga e outros que CEASA-MG não tem.
Converte preço de caixa/saco pra R$/kg automaticamente.

Cron sugerido:
0 8,14 * * * cd /opt/painel-produtor && python3 scraper_ceasa_curitiba.py >> /var/log/painel-produtor/ceasa_cwb.log 2>&1
"""

import re
import logging
from datetime import date

import requests
from bs4 import BeautifulSoup
import pymysql
import pymysql.cursors

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger("ceasa_cwb")

DB = {
    'host': '199.167.147.66', 'port': 3306,
    'user': 'techobco_agropecuaria', 'password': '@precisao2203',
    'db': 'techobco_agropecuaria', 'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor, 'connect_timeout': 10,
}

URL = 'https://celepar7.pr.gov.br/ceasa/hoje_curitiba.asp'

# Produtos que queremos coletar (nome parcial -> chave no banco)
# Peso da embalagem pra converter pra R$/kg
PRODUTOS = {
    'PITAIA':           {'key': 'pitaya_cwb',       'peso_kg': 4,    'cat': 'hortifruti'},
    'CAQUI FUYU':       {'key': 'caqui_cwb',        'peso_kg': 10,   'cat': 'hortifruti'},
    'KIWI NACIONAL':    {'key': 'kiwi_cwb',         'peso_kg': 8,    'cat': 'hortifruti'},
    'MANGA TOMMY':      {'key': 'manga_cwb',        'peso_kg': 10,   'cat': 'hortifruti'},
    'MORANGO':          {'key': 'morango_cwb',       'peso_kg': 1.2,  'cat': 'hortifruti'},
    'MARACUJA AZEDO':   {'key': 'maracuja_cwb',     'peso_kg': 12,   'cat': 'hortifruti'},
    'BANANA PRATA':     {'key': 'banana_prata_cwb',  'peso_kg': 13,  'cat': 'hortifruti'},
    'ABACATE FORTUNA':  {'key': 'abacate_cwb',      'peso_kg': 20,   'cat': 'hortifruti'},
    'LARANJA PERA':     {'key': 'laranja_cwb',      'peso_kg': 20,   'cat': 'hortifruti'},
    'LIMAO TAHITI':     {'key': 'limao_cwb',        'peso_kg': 23,   'cat': 'hortifruti'},
    'MAMAO PAPAYA':     {'key': 'mamao_cwb',        'peso_kg': 8,    'cat': 'hortifruti'},
    'MELANCIA':         {'key': 'melancia_cwb',     'peso_kg': 1,    'cat': 'hortifruti'},  # já em kg
    'TOMATE':           {'key': 'tomate_cwb',       'peso_kg': 20,   'cat': 'hortifruti'},
    'BATATA':           {'key': 'batata_cwb',       'peso_kg': 25,   'cat': 'hortifruti'},
    'CEBOLA PERA':      {'key': 'cebola_cwb',       'peso_kg': 20,   'cat': 'hortifruti'},
    'CENOURA':          {'key': 'cenoura_cwb',      'peso_kg': 20,   'cat': 'hortifruti'},
    'ALHO':             {'key': 'alho_cwb',         'peso_kg': 10,   'cat': 'hortifruti'},
    'UVA NIAGARA':      {'key': 'uva_niagara_cwb',  'peso_kg': 6,   'cat': 'hortifruti'},
    'UVA THOMPSON':     {'key': 'uva_thompson_cwb', 'peso_kg': 5,    'cat': 'hortifruti'},
    'GOIABA':           {'key': 'goiaba_cwb',       'peso_kg': 2,    'cat': 'hortifruti'},
    'TANGERINA PONKAN': {'key': 'tangerina_cwb',    'peso_kg': 20,   'cat': 'hortifruti'},
    'PERA NACIONAL':    {'key': 'pera_cwb',         'peso_kg': 20,   'cat': 'hortifruti'},
}


def extrair_peso(nome):
    """Tenta extrair peso da embalagem do nome (ex: 'cx 4 kg' -> 4)."""
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*kg', nome.lower())
    if m:
        return float(m.group(1).replace(',', '.'))
    return None


def scrape():
    log.info('Conectando CEASA Curitiba...')
    r = requests.get(URL, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
    if r.status_code != 200:
        log.error(f'HTTP {r.status_code}')
        return []

    soup = BeautifulSoup(r.text, 'html.parser')
    rows = soup.find_all('tr')
    results = []

    for row in rows:
        cells = [td.get_text(strip=True) for td in row.find_all('td')]
        if len(cells) != 2:
            continue

        nome_raw = cells[0]
        preco_raw = cells[1]

        # Parsear preço
        try:
            preco_cx = float(preco_raw.replace('.', '').replace(',', '.'))
        except ValueError:
            continue

        if preco_cx <= 0:
            continue

        # Verificar se é um produto que queremos
        nome_upper = nome_raw.upper().strip()
        for match_key, config in PRODUTOS.items():
            if match_key in nome_upper:
                # Extrair peso real do nome ou usar o default
                peso = extrair_peso(nome_raw) or config['peso_kg']

                # Se já em kg (ex: MELANCIA kg), não divide
                # Mas se tem 'cx','sc','bj','un' no nome, é preço por embalagem
                eh_embalagem = any(x in nome_raw.lower() for x in ['cx ', 'sc ', 'bj ', ' un ', 'c/'])
                if not eh_embalagem and ('kg' == nome_raw.strip().split()[-1].lower() or peso == 1):
                    preco_kg = preco_cx
                else:
                    preco_kg = round(preco_cx / peso, 2)

                results.append({
                    'produto': config['key'],
                    'preco': preco_kg,
                    'preco_cx': preco_cx,
                    'unidade': 'R$/kg',
                    'fonte': 'CEASA-Curitiba',
                    'categoria': config['cat'],
                    'nome_original': nome_raw.strip(),
                })
                log.info(f"  {config['key']:25} R$ {preco_kg:8.2f}/kg (cx R${preco_cx:.2f} / {peso}kg) <- {nome_raw.strip()}")
                break  # Pega só o primeiro match por produto-chave

    return results


def salvar(results):
    if not results:
        return 0

    conn = pymysql.connect(**DB)
    saved = 0
    with conn.cursor() as cur:
        for r in results:
            try:
                cur.execute('SELECT preco FROM cotacoes_atual WHERE produto = %s', (r['produto'],))
                row = cur.fetchone()
                preco_ant = float(row['preco']) if row else r['preco']
                variacao = r['preco'] - preco_ant
                var_pct = (variacao / preco_ant * 100) if preco_ant else 0

                cur.execute('''
                    INSERT INTO cotacoes_atual (produto, preco, preco_ant, variacao, variacao_pct, unidade, fonte, data_ref, categoria)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        preco_ant = preco,
                        preco = VALUES(preco),
                        variacao = VALUES(variacao),
                        variacao_pct = VALUES(variacao_pct),
                        fonte = VALUES(fonte),
                        data_ref = VALUES(data_ref),
                        categoria = VALUES(categoria)
                ''', (
                    r['produto'], r['preco'], preco_ant, variacao, round(var_pct, 2),
                    r['unidade'], r['fonte'], date.today(), r['categoria'],
                ))
                saved += 1
            except Exception as e:
                log.warning(f"  Erro {r['produto']}: {e}")

    conn.commit()
    conn.close()
    return saved


def main():
    log.info('=' * 55)
    log.info('SCRAPER CEASA CURITIBA — incluindo pitaya')
    log.info('=' * 55)

    results = scrape()
    log.info(f'\n{len(results)} produtos coletados')

    saved = salvar(results)
    log.info(f'{saved} salvos no banco')
    log.info('Concluído')


if __name__ == '__main__':
    main()
