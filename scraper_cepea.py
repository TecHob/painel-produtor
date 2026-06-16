#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, time, logging, argparse
from datetime import date
from decimal import Decimal, InvalidOperation
import requests
from bs4 import BeautifulSoup
import pymysql, pymysql.cursors

DB = {
    'host': '199.167.147.66',
    'port': 3306,
    'user': 'techobco_agropecuaria',
    'password': '@precisao2203',
    'database': 'techobco_agropecuaria',
    'charset': 'utf8mb4',
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('scraper')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Referer': 'https://www.google.com.br/',
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

def parse_price(text):
    if not text: return None
    t = text.strip()
    for ch in ['R$','US$','$',' ','\xa0','\t','\n']: t = t.replace(ch,'')
    if ',' in t and '.' in t: t = t.replace('.','').replace(',','.')
    elif ',' in t: t = t.replace(',','.')
    try:
        v = Decimal(t)
        return v if v > 0 else None
    except: return None

def get_page(url):
    try:
        r = SESSION.get(url, timeout=15)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or 'utf-8'
        return BeautifulSoup(r.text, 'html.parser')
    except Exception as e:
        log.warning(f'GET {url} -> {e}')
        return None

def primeira_tabela_preco(soup, col=1):
    """Pega o preco da primeira linha de dados da primeira tabela valida."""
    for table in soup.find_all('table'):
        rows = table.find_all('tr')
        for row in rows[1:2]:
            cells = [td.get_text(strip=True) for td in row.find_all('td')]
            if len(cells) > col:
                p = parse_price(cells[col])
                if p: return p
    return None

def scrape_noticiasagricolas():
    """
    Mapeamento final confirmado:
    cafe       -> tabela 0 col1 = Arabica, tabela 1 col1 = Conillon
    milho      -> tabela 0 col1
    soja       -> tabela 0 col1
    boi        -> tabela 0 col1
    sucroener  -> tabela 0 col1 = Acucar sc50kg, tabela 2 col1 = Etanol R$/L
    frango     -> tabela 0 col1
    leite      -> tabela 0 col1
    suinos     -> tabela 1 col1 = preco SP (referencia CEPEA)
    algodao    -> tabela 0 col1
    trigo      -> tabela 3 col1 = sc60kg CEPEA
    """
    results = []
    hoje = date.today()

    URLS = {
        'cafe':         'https://www.noticiasagricolas.com.br/cotacoes/cafe',
        'milho':        'https://www.noticiasagricolas.com.br/cotacoes/milho',
        'soja':         'https://www.noticiasagricolas.com.br/cotacoes/soja',
        'boi':          'https://www.noticiasagricolas.com.br/cotacoes/boi-gordo',
        'sucro':        'https://www.noticiasagricolas.com.br/cotacoes/sucroenergetico',
        'frango':       'https://www.noticiasagricolas.com.br/cotacoes/frango',
        'leite':        'https://www.noticiasagricolas.com.br/cotacoes/leite',
        'suinos':       'https://www.noticiasagricolas.com.br/cotacoes/suinos',
        'algodao':      'https://www.noticiasagricolas.com.br/cotacoes/algodao',
        'trigo':        'https://www.noticiasagricolas.com.br/cotacoes/trigo',
    }

    def tabela_n_col(soup, n, col=1):
        tabelas = soup.find_all('table')
        if len(tabelas) <= n: return None
        rows = tabelas[n].find_all('tr')
        for row in rows[1:2]:
            cells = [td.get_text(strip=True) for td in row.find_all('td')]
            if len(cells) > col:
                return parse_price(cells[col])
        return None

    log.info('-> Noticias Agricolas: iniciando...')

    # CAFE
    soup = get_page(URLS['cafe'])
    if soup:
        p = tabela_n_col(soup, 0, 1)  # Arabica
        if p:
            results.append({'produto':'cafe_arabica','preco':p,'unidade':'R$/sc 60kg','fonte':'NoticiasAgricolas'})
            log.info(f'  OK cafe_arabica: R$ {p}')
        p2 = tabela_n_col(soup, 1, 1)  # Conillon
        if p2:
            results.append({'produto':'cafe_conillon','preco':p2,'unidade':'R$/sc 60kg','fonte':'NoticiasAgricolas'})
            log.info(f'  OK cafe_conillon: R$ {p2}')
    time.sleep(1)

    # MILHO
    soup = get_page(URLS['milho'])
    if soup:
        p = tabela_n_col(soup, 0, 1)
        if p:
            results.append({'produto':'milho','preco':p,'unidade':'R$/sc 60kg','fonte':'NoticiasAgricolas'})
            log.info(f'  OK milho: R$ {p}')
    time.sleep(1)

    # SOJA
    soup = get_page(URLS['soja'])
    if soup:
        p = tabela_n_col(soup, 0, 1)
        if p:
            results.append({'produto':'soja','preco':p,'unidade':'R$/sc 60kg','fonte':'NoticiasAgricolas'})
            log.info(f'  OK soja: R$ {p}')
    time.sleep(1)

    # BOI GORDO
    soup = get_page(URLS['boi'])
    if soup:
        p = tabela_n_col(soup, 0, 1)
        if p:
            results.append({'produto':'boi_gordo','preco':p,'unidade':'R$/@','fonte':'NoticiasAgricolas'})
            log.info(f'  OK boi_gordo: R$ {p}')
    time.sleep(1)

    # SUCROENERGETICO: acucar (tabela 0) e etanol (tabela 2)
    soup = get_page(URLS['sucro'])
    if soup:
        p = tabela_n_col(soup, 0, 1)  # Acucar R$/sc 50kg
        if p:
            results.append({'produto':'acucar_vhp','preco':p,'unidade':'R$/sc 50kg','fonte':'NoticiasAgricolas'})
            log.info(f'  OK acucar_vhp: R$ {p}')
        p2 = tabela_n_col(soup, 2, 1)  # Etanol R$/L
        if p2:
            results.append({'produto':'etanol','preco':p2,'unidade':'R$/L','fonte':'NoticiasAgricolas'})
            log.info(f'  OK etanol: R$ {p2}')
    time.sleep(1)

    # FRANGO
    soup = get_page(URLS['frango'])
    if soup:
        p = tabela_n_col(soup, 0, 1)
        if p:
            results.append({'produto':'frango_vivo','preco':p,'unidade':'R$/kg','fonte':'NoticiasAgricolas'})
            log.info(f'  OK frango_vivo: R$ {p}')
    time.sleep(1)

    # LEITE
    soup = get_page(URLS['leite'])
    if soup:
        p = tabela_n_col(soup, 0, 1)
        if p:
            results.append({'produto':'leite','preco':p,'unidade':'R$/L','fonte':'NoticiasAgricolas'})
            log.info(f'  OK leite: R$ {p}')
    time.sleep(1)

    # SUINOS (tabela 1 = referencia SP)
    soup = get_page(URLS['suinos'])
    if soup:
        p = tabela_n_col(soup, 1, 1)
        if p:
            results.append({'produto':'suino_vivo','preco':p,'unidade':'R$/kg','fonte':'NoticiasAgricolas'})
            log.info(f'  OK suino_vivo: R$ {p}')
    time.sleep(1)

    # ALGODAO
    soup = get_page(URLS['algodao'])
    if soup:
        p = tabela_n_col(soup, 0, 1)
        if p:
            results.append({'produto':'algodao','preco':p,'unidade':'R$/@','fonte':'NoticiasAgricolas'})
            log.info(f'  OK algodao: R$ {p}')
    time.sleep(1)

    # TRIGO (tabela 3 = CEPEA sc60kg)
    soup = get_page(URLS['trigo'])
    if soup:
        p = tabela_n_col(soup, 3, 1)
        if p:
            results.append({'produto':'trigo','preco':p,'unidade':'R$/sc 60kg','fonte':'NoticiasAgricolas'})
            log.info(f'  OK trigo: R$ {p}')

    # Adiciona data_ref em todos
    for r in results:
        r['data_ref'] = hoje
        r['referencia'] = 'noticiasagricolas.com.br'

    return results

def scrape_cambio():
    log.info('-> Cambio: AwesomeAPI...')
    try:
        r = SESSION.get('https://economia.awesomeapi.com.br/json/last/USD-BRL,EUR-BRL,GBP-BRL', timeout=10)
        data = r.json()
    except Exception as e:
        log.warning(f'Cambio erro: {e}')
        return []
    results = []
    for key, par in [('USDBRL','USDBRL'),('EURBRL','EURBRL'),('GBPBRL','GBPBRL')]:
        if key not in data: continue
        d = data[key]
        try:
            results.append({'par':par,'compra':Decimal(str(d.get('bid',0))),'venda':Decimal(str(d.get('ask',0))),'variacao_pct':Decimal(str(d.get('pctChange',0))),'fonte':'AwesomeAPI'})
            log.info(f'  OK {par}: R$ {d.get("bid")}')
        except Exception as e:
            log.warning(f'  {par}: {e}')
    return results

def get_conn():
    return pymysql.connect(**DB, cursorclass=pymysql.cursors.DictCursor, connect_timeout=10, autocommit=False)

def salvar_cotacoes(conn, cotacoes):
    if not cotacoes: return 0
    saved = 0
    with conn.cursor() as cur:
        for c in cotacoes:
            produto = c['produto']
            preco = float(c['preco'])
            cur.execute('SELECT preco FROM cotacoes_atual WHERE produto = %s', (produto,))
            row = cur.fetchone()
            preco_ant = float(row['preco']) if row else None
            variacao = round(preco - preco_ant, 4) if preco_ant else None
            var_pct = round((preco - preco_ant) / preco_ant * 100, 4) if preco_ant and preco_ant != 0 else None
            cur.execute('INSERT INTO cotacoes (produto,preco,preco_ant,variacao,variacao_pct,unidade,fonte,referencia,data_ref) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (produto,preco,preco_ant,variacao,var_pct,c.get('unidade'),c.get('fonte'),c.get('referencia'),c.get('data_ref',date.today())))
            cur.execute('''INSERT INTO cotacoes_atual (produto,preco,preco_ant,variacao,variacao_pct,unidade,fonte,data_ref)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE preco_ant=VALUES(preco_ant),preco=VALUES(preco),variacao=VALUES(variacao),variacao_pct=VALUES(variacao_pct),unidade=VALUES(unidade),fonte=VALUES(fonte),data_ref=VALUES(data_ref),atualizado_em=NOW()''',
                (produto,preco,preco_ant,variacao,var_pct,c.get('unidade'),c.get('fonte'),c.get('data_ref',date.today())))
            saved += 1
    conn.commit()
    return saved

def salvar_cambio(conn, cambio):
    if not cambio: return 0
    saved = 0
    with conn.cursor() as cur:
        for c in cambio:
            cur.execute('INSERT INTO cambio (par,compra,venda,variacao_pct,fonte) VALUES (%s,%s,%s,%s,%s)',
                (c['par'],float(c['compra']),float(c['venda']),float(c.get('variacao_pct',0) or 0),c.get('fonte')))
            cur.execute('''INSERT INTO cambio_atual (par,compra,venda,variacao_pct,fonte)
                VALUES (%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE compra=VALUES(compra),venda=VALUES(venda),variacao_pct=VALUES(variacao_pct),fonte=VALUES(fonte),atualizado_em=NOW()''',
                (c['par'],float(c['compra']),float(c['venda']),float(c.get('variacao_pct',0) or 0),c.get('fonte')))
            saved += 1
    conn.commit()
    return saved

def salvar_log(conn, fonte, status, mensagem='', duracao_ms=0):
    with conn.cursor() as cur:
        cur.execute('INSERT INTO scraper_log (fonte,status,mensagem,duracao_ms) VALUES (%s,%s,%s,%s)',
            (fonte,status,mensagem[:2000],duracao_ms))
    conn.commit()

def run_once():
    log.info('='*50)
    log.info('SCRAPER INICIANDO')
    log.info('='*50)
    import time as t
    t0 = t.time()
    try:
        conn = get_conn()
        log.info('Banco conectado')
    except Exception as e:
        log.error(f'Erro MySQL: {e}'); return

    # Cambio
    try:
        cambio = scrape_cambio()
        n = salvar_cambio(conn, cambio)
        salvar_log(conn, 'cambio', 'ok', f'{n} pares', int((t.time()-t0)*1000))
        log.info(f'Cambio: {n} pares salvos')
    except Exception as e:
        log.error(f'Cambio: {e}')
        try: salvar_log(conn, 'cambio', 'erro', str(e))
        except: pass

    # Cotacoes
    t1 = t.time()
    try:
        cotacoes = scrape_noticiasagricolas()
        n = salvar_cotacoes(conn, cotacoes)
        salvar_log(conn, 'cepea', 'ok', f'{n} produtos via NoticiasAgricolas', int((t.time()-t1)*1000))
        log.info(f'Cotacoes: {n} produtos salvos')
    except Exception as e:
        log.error(f'Cotacoes: {e}')
        try: salvar_log(conn, 'cepea', 'erro', str(e))
        except: pass

    # CEASA-MG hortifruti
    t2 = t.time()
    try:
        cotacoes_ceasa = scrape_ceasa_mg()
        n2 = salvar_cotacoes(conn, cotacoes_ceasa)
        salvar_log(conn, 'ceasa_mg', 'ok', f'{n2} produtos CEASA-MG', int((t.time()-t2)*1000))
        log.info(f'CEASA-MG: {n2} produtos salvos')
    except Exception as e:
        log.error(f'CEASA-MG: {e}')
        try: salvar_log(conn, 'ceasa_mg', 'erro', str(e))
        except: pass
    log.info(f'CONCLUIDO em {int((t.time()-t0)*1000)}ms')
    conn.close()


# ═══════════════════════════════════════════════════════════
# CEASA-MG
# ═══════════════════════════════════════════════════════════
CEASA_MG_PRODUTOS = {
    # === Já existiam (18) ===
    'MORANGO':         ('morango_ceasa',  'R$/kg',  'hortifruti'),
    'PIMENTAO':        ('pimentao',       'R$/kg',  'hortifruti'),
    'ALHO BRASILEIRO': ('alho',           'R$/kg',  'hortifruti'),
    'BATATA':          ('batata_ceasa',   'R$/kg',  'hortifruti'),
    'CEBOLA':          ('cebola_ceasa',   'R$/kg',  'hortifruti'),
    'TOMATE':          ('tomate_ceasa',   'R$/kg',  'hortifruti'),
    'ALFACE':          ('alface',         'R$/dz',  'hortifruti'),
    'BROCOLO':         ('brocolo',        'R$/dz',  'hortifruti'),
    'COUVE':           ('couve',          'R$/dz',  'hortifruti'),
    'REPOLHO':         ('repolho',        'R$/kg',  'hortifruti'),
    'CENOURA':         ('cenoura',        'R$/kg',  'hortifruti'),
    'PEPINO':          ('pepino',         'R$/kg',  'hortifruti'),
    'CHUCHU':          ('chuchu',         'R$/kg',  'hortifruti'),
    'BERINJELA':       ('berinjela',      'R$/kg',  'hortifruti'),
    'VAGEM':           ('vagem',          'R$/kg',  'hortifruti'),
    'MARACUJA':        ('maracuja',       'R$/kg',  'hortifruti'),
    'BANANA-NANICA':   ('banana_nanica',  'R$/kg',  'hortifruti'),
    'BANANA-PRATA':    ('banana_prata',   'R$/kg',  'hortifruti'),
    # === Novos (30) ===
    'ABACATE':         ('abacate',        'R$/kg',  'hortifruti'),
    'ABACAXI':         ('abacaxi',        'R$/dz',  'hortifruti'),
    'ABO. ITALIANA':   ('abobrinha',      'R$/kg',  'hortifruti'),
    'ABO. MENINA':     ('abobora_menina', 'R$/kg',  'hortifruti'),
    'ABO. MOGANGA':    ('abobora_moganga','R$/kg',  'hortifruti'),
    'BATATA-DOCE':     ('batata_doce',    'R$/kg',  'hortifruti'),
    'BETERRABA':       ('beterraba',      'R$/kg',  'hortifruti'),
    'COCO VERDE':      ('coco_verde',     'R$/un',  'hortifruti'),
    'COUVE-FLOR':      ('couve_flor',     'R$/un',  'hortifruti'),
    'ESPINAFRE':       ('espinafre',      'R$/dz',  'hortifruti'),
    'GOIABA':          ('goiaba',         'R$/kg',  'hortifruti'),
    'INHAME':          ('inhame',         'R$/kg',  'hortifruti'),
    'JILO':            ('jilo',           'R$/kg',  'hortifruti'),
    'LARANJA':         ('laranja',        'R$/kg',  'hortifruti'),
    'LIMAO':           ('limao',          'R$/kg',  'hortifruti'),
    'MACA':            ('maca',           'R$/kg',  'hortifruti'),
    'MAMAO-FORMOSA':   ('mamao_formosa',  'R$/kg',  'hortifruti'),
    'MAMAO-HAVAI':     ('mamao_havai',    'R$/kg',  'hortifruti'),
    'MANDIOCA':        ('mandioca',       'R$/kg',  'hortifruti'),
    'MANDIOQUINHA':    ('mandioquinha',   'R$/kg',  'hortifruti'),
    'MANGA':           ('manga',          'R$/kg',  'hortifruti'),
    'MELANCIA':        ('melancia',       'R$/kg',  'hortifruti'),
    'MELAO':           ('melao',          'R$/kg',  'hortifruti'),
    'MILHO-VERDE':     ('milho_verde',    'R$/kg',  'hortifruti'),
    'MORANGA':         ('moranga',        'R$/kg',  'hortifruti'),
    'OVOS':            ('ovos',           'R$/30dz','hortifruti'),
    'PERA':            ('pera',           'R$/kg',  'hortifruti'),
    'QUIABO':          ('quiabo',         'R$/kg',  'hortifruti'),
    'TANGERINA':       ('tangerina',      'R$/kg',  'hortifruti'),
    'UVA':             ('uva',            'R$/kg',  'hortifruti'),
}

def scrape_ceasa_mg():
    log.info('-> CEASA-MG: iniciando...')
    url = 'https://minas1.ceasa.mg.gov.br/ceasainternet/cst_precosmaiscomumMG/cst_precosmaiscomumMG.php'
    results = []
    try:
        r = SESSION.get(url, timeout=15, verify=False)
        soup = BeautifulSoup(r.text, 'html.parser')
        cells = [td.get_text(strip=True) for td in soup.find_all('td')]
        i = 0
        while i < len(cells):
            nome = cells[i].upper().strip()
            if nome in CEASA_MG_PRODUTOS and i+2 < len(cells):
                preco_bh = cells[i+2]
                if preco_bh and preco_bh != '------':
                    p = parse_price(preco_bh)
                    if p and p > 0:
                        produto_key, unidade, _ = CEASA_MG_PRODUTOS[nome]
                        # Batata cotada em SC 50kg em BH -> converte para R$/kg
                        unidade_real = cells[i+1] if i+1 < len(cells) else ''
                        if unidade_real == 'SC' and p > 10:
                            p = round(p / 50, 2)
                            unidade = 'R$/kg'
                        results.append({
                            'produto': produto_key,
                            'preco': p,
                            'unidade': unidade,
                            'fonte': 'CEASA-MG',
                            'referencia': url,
                            'data_ref': date.today(),
                        })
                        log.info(f'  OK {produto_key}: R$ {p} (Grande BH)')
            i += 1
    except Exception as e:
        log.error(f'CEASA-MG erro: {e}')
    return results

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--test-db', action='store_true')
    args = parser.parse_args()
    if args.test_db:
        try:
            conn = get_conn()
            with conn.cursor() as cur:
                cur.execute('SELECT produto, preco, atualizado_em FROM cotacoes_atual ORDER BY produto')
                for r in cur.fetchall():
                    print(f'  {r["produto"]:20} R$ {r["preco"]:10} | {r["atualizado_em"]}')
            conn.close()
        except Exception as e:
            print(f'ERRO: {e}'); sys.exit(1)
    else:
        run_once()
