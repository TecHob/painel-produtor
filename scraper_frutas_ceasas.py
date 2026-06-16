#!/usr/bin/env python3
"""
scraper_frutas_ceasas.py — Cotações de frutas de 3 CEASAs (Campinas, BH, CEAGESP)
Fonte: noticiasagricolas.com.br/cotacoes/frutas/

Salva em cotacoes_atual com fonte indicando a CEASA.
Complementa o CEASA-MG (que só tem preço Grande BH).

Cron sugerido (junto com scraper_cepea.py):
30 */6 * * * cd /opt/painel-produtor && python3 scraper_frutas_ceasas.py >> /var/log/painel-produtor/frutas.log 2>&1
"""

import re
import logging
import time
from datetime import date

import requests
from bs4 import BeautifulSoup
import pymysql
import pymysql.cursors
import urllib3

urllib3.disable_warnings()

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger("frutas")

DB = {
    'host': '199.167.147.66', 'port': 3306,
    'user': 'techobco_agropecuaria', 'password': '@precisao2203',
    'db': 'techobco_agropecuaria', 'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor, 'connect_timeout': 10,
}

SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36',
    'Accept-Language': 'pt-BR,pt;q=0.9',
})

BASE = 'https://www.noticiasagricolas.com.br/cotacoes/frutas'

# Slug -> nome bonito do produto
FRUTAS = {
    'abacate-ceasas':          'abacate',
    'abacaxi-ceasas':          'abacaxi',
    'banana-nanicaprata-ceasas': 'banana',
    'limao-tahiti-ceasas':     'limao_tahiti',
    'mamao-ceasas':            'mamao',
    'maracuja-ceasas':         'maracuja_na',
    'maca-fuji-ceasas':        'maca_fuji',
    'maca-gala-ceasas':        'maca_gala',
    'melancia-ceasas':         'melancia_na',
    'pera-ceasas':             'pera_na',
    'tangerina-ceasas':        'tangerina_na',
    'uva-ceasas':              'uva_na',
}

# Mapeia header da CEASA -> sufixo
CEASA_MAP = {
    'ceasa campinas/sp': 'campinas',
    'ceasa belo horizonte/mg': 'bh',
    'ceagesp/sp': 'ceagesp',
}


def parse_price(text):
    """Extrai float de texto como '6,00' ou '1.234,56'."""
    if not text or 's/ cota' in text.lower() or text.strip() in ('-', '***', ''):
        return None
    text = text.replace('.', '').replace(',', '.')
    try:
        v = float(text)
        return v if v > 0 else None
    except ValueError:
        return None


def parse_var(text):
    """Extrai variação percentual."""
    if not text or text.strip() in ('-', '***', ''):
        return 0.0
    text = text.replace('+', '').replace(',', '.').replace('%', '')
    try:
        return float(text)
    except ValueError:
        return 0.0


def scrape_fruta(slug, nome):
    """Scrape uma fruta, retorna lista de dicts com preços."""
    url = f'{BASE}/{slug}'
    results = []

    try:
        r = SESSION.get(url, timeout=15, verify=False)
        if r.status_code != 200:
            log.warning(f'  {slug}: HTTP {r.status_code}')
            return []

        soup = BeautifulSoup(r.text, 'html.parser')
        tables = soup.find_all('table', class_='cot-fisicas')
        if not tables:
            tables = soup.find_all('table')

        if not tables:
            log.warning(f'  {slug}: nenhuma tabela encontrada')
            return []

        # Tabela 0 = cotação mais recente
        table = tables[0]
        rows = table.find_all('tr')

        current_ceasa = None
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all(['td', 'th'])]
            if not cells or len(cells) < 2:
                continue

            # Header row (Origem/Tipo, Preço, Variação)
            if cells[0] == 'Origem/Tipo':
                continue

            # CEASA header (marcado com ***)
            if len(cells) >= 2 and cells[1] == '***':
                ceasa_key = cells[0].lower().strip()
                current_ceasa = CEASA_MAP.get(ceasa_key)
                continue

            # Linha de preço
            if current_ceasa and len(cells) >= 2:
                tipo = cells[0].strip()
                preco = parse_price(cells[1])
                variacao = parse_var(cells[2]) if len(cells) > 2 else 0.0

                if preco:
                    # Produto: nome_ceasa (ex: abacate_ceagesp)
                    produto_key = f'{nome}_{current_ceasa}'
                    results.append({
                        'produto': produto_key,
                        'preco': preco,
                        'variacao_pct': variacao,
                        'unidade': 'R$/kg',
                        'fonte': f'CEASA-{current_ceasa.upper()}',
                        'tipo': tipo,
                        'categoria': 'hortifruti',
                    })

    except Exception as e:
        log.error(f'  {slug}: ERRO {e}')

    return results


def salvar(conn, resultados):
    """Salva no cotacoes_atual com UPSERT."""
    saved = 0
    with conn.cursor() as cur:
        for r in resultados:
            try:
                # Buscar preço anterior
                cur.execute('SELECT preco FROM cotacoes_atual WHERE produto = %s', (r['produto'],))
                row = cur.fetchone()
                preco_ant = float(row['preco']) if row else r['preco']
                variacao = r['preco'] - preco_ant
                var_pct = r['variacao_pct']

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
                    r['produto'], r['preco'], preco_ant, variacao, var_pct,
                    r['unidade'], r['fonte'], date.today(), r['categoria'],
                ))
                saved += 1
            except Exception as e:
                log.warning(f"  Erro ao salvar {r['produto']}: {e}")

    conn.commit()
    return saved


def main():
    log.info('=' * 55)
    log.info('SCRAPER FRUTAS CEASAs — Campinas + BH + CEAGESP')
    log.info('=' * 55)

    conn = pymysql.connect(**DB)
    log.info('Banco conectado')

    todos = []
    for slug, nome in FRUTAS.items():
        log.info(f'  {nome} ({slug})...')
        results = scrape_fruta(slug, nome)
        for r in results:
            log.info(f"    {r['fonte']}: {r['tipo']} R$ {r['preco']:.2f} ({r['variacao_pct']:+.1f}%)")
        todos.extend(results)
        time.sleep(2)  # Gentil com o servidor

    log.info(f'\nTotal: {len(todos)} preços coletados')

    saved = salvar(conn, todos)
    conn.close()

    log.info(f'Salvos: {saved} no banco')
    log.info('Concluído')


if __name__ == '__main__':
    main()
