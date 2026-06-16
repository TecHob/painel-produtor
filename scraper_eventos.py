#!/usr/bin/env python3
"""
Scraper de Eventos Agro — Painel do Produtor
Precisão Inova / André CTO
"""

import re
import time
import logging
import hashlib
import argparse
import urllib3
from datetime import date, datetime, timedelta
from bs4 import BeautifulSoup
import requests
import pymysql
import pymysql.cursors

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)

DB_CFG = {
    'host':     '199.167.147.66',
    'port':     3306,
    'user':     'techobco_agropecuaria',
    'password': '@precisao2203',
    'db':       'techobco_agropecuaria',
    'charset':  'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
    'connect_timeout': 10,
}

SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': (
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'pt-BR,pt;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
})

MESES_BR = {
    'janeiro': 1,  'fevereiro': 2,  'marco': 3,    'março': 3,
    'abril': 4,    'maio': 5,       'junho': 6,
    'julho': 7,    'agosto': 8,     'setembro': 9,
    'outubro': 10, 'novembro': 11,  'dezembro': 12,
    'jan': 1, 'fev': 2, 'mar': 3, 'abr': 4, 'mai': 5, 'jun': 6,
    'jul': 7, 'ago': 8, 'set': 9, 'out': 10, 'nov': 11, 'dez': 12,
}

ESTADOS_BR = {
    'São Paulo': 'SP', 'Sao Paulo': 'SP', 'SP': 'SP',
    'Minas Gerais': 'MG', 'MG': 'MG', 'Minas': 'MG',
    'Paraná': 'PR', 'Parana': 'PR', 'PR': 'PR',
    'Rio Grande do Sul': 'RS', 'RS': 'RS',
    'Goiás': 'GO', 'Goias': 'GO', 'GO': 'GO',
    'Mato Grosso': 'MT', 'MT': 'MT',
    'Mato Grosso do Sul': 'MS', 'MS': 'MS',
    'Bahia': 'BA', 'BA': 'BA',
    'Brasília': 'DF', 'Brasilia': 'DF', 'DF': 'DF',
    'Distrito Federal': 'DF',
    'Maranhão': 'MA', 'Maranhao': 'MA', 'MA': 'MA',
    'Rio de Janeiro': 'RJ', 'RJ': 'RJ',
    'Santa Catarina': 'SC', 'SC': 'SC',
    'Espírito Santo': 'ES', 'ES': 'ES',
    'Pernambuco': 'PE', 'PE': 'PE',
    'Ceará': 'CE', 'Ceara': 'CE', 'CE': 'CE',
    'Pará': 'PA', 'Para': 'PA', 'PA': 'PA',
    'Tocantins': 'TO', 'TO': 'TO',
    'Rondônia': 'RO', 'Rondonia': 'RO', 'RO': 'RO',
}

CATEGORIAS_KEYWORDS = {
    'feira':        ['feira', 'show rural', 'expodireto', 'agrishow', 'expointer',
                     'expo ', 'agrofair', 'tecnoshow', 'femec', 'agrobrasília',
                     'agrobrasilia', 'farm show', 'bahia farm', 'farmshow'],
    'congresso':    ['congresso', 'conferência', 'conferencia', 'conference', 'summit'],
    'curso':        ['curso', 'treinamento', 'capacitação', 'capacitacao', 'masterclass'],
    'dia_de_campo': ['dia de campo', 'field day'],
    'webinar':      ['webinar', 'live', 'online', 'virtual', 'zoom'],
    'workshop':     ['workshop', 'oficina'],
    'seminar':      ['seminário', 'seminario', 'simpósio', 'simposio', 'fórum', 'forum'],
    'exposicao':    ['exposição', 'exposicao', 'mostra'],
}


def parse_data_br(texto: str) -> tuple:
    if not texto:
        return (None, None)
    texto = texto.strip().lower()

    # DD/MM/YYYY
    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', texto)
    if m:
        d, mo, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a < 100:
            a += 2000
        try:
            return (date(a, mo, d), None)
        except ValueError:
            pass

    # "DD, DD e DD de MES de YYYY"
    m = re.search(r'(\d{1,2})(?:,\s*\d{1,2})*\s+e\s+(\d{1,2})\s+de\s+(\w+)\s+(?:de\s+)?(\d{4})', texto)
    if m:
        d1, d2 = int(m.group(1)), int(m.group(2))
        mes = MESES_BR.get(m.group(3).lower())
        ano = int(m.group(4))
        if mes:
            try:
                return (date(ano, mes, d1), date(ano, mes, d2))
            except ValueError:
                pass

    # "DD a DD de MES de YYYY"
    m = re.search(r'(\d{1,2})\s+(?:a|e|até|ate)\s+(\d{1,2})\s+de\s+(\w+)\s+(?:de\s+)?(\d{4})', texto)
    if m:
        d1, d2 = int(m.group(1)), int(m.group(2))
        mes = MESES_BR.get(m.group(3).lower())
        ano = int(m.group(4))
        if mes:
            try:
                return (date(ano, mes, d1), date(ano, mes, d2))
            except ValueError:
                pass

    # "DD de MES a DD de MES de YYYY"
    m = re.search(r'(\d{1,2})\s+de\s+(\w+)\s+(?:a|até|ate)\s+(\d{1,2})\s+de\s+(\w+)\s+(?:de\s+)?(\d{4})', texto)
    if m:
        d1, mes1 = int(m.group(1)), MESES_BR.get(m.group(2).lower())
        d2, mes2 = int(m.group(3)), MESES_BR.get(m.group(4).lower())
        ano = int(m.group(5))
        if mes1 and mes2:
            try:
                return (date(ano, mes1, d1), date(ano, mes2, d2))
            except ValueError:
                pass

    # "DD de MES de YYYY"
    m = re.search(r'(\d{1,2})\s+de\s+(\w+)\s+(?:de\s+)?(\d{4})', texto)
    if m:
        mes = MESES_BR.get(m.group(2).lower())
        ano = int(m.group(3))
        if mes:
            try:
                return (date(ano, mes, int(m.group(1))), None)
            except ValueError:
                pass

    # "MES de YYYY"
    m = re.search(r'\b(\w+)\s+(?:de\s+)?(\d{4})\b', texto)
    if m:
        mes = MESES_BR.get(m.group(1).lower())
        if mes:
            return (date(int(m.group(2)), mes, 1), None)

    # Só ano
    m = re.search(r'\b(202[5-9])\b', texto)
    if m:
        return (date(int(m.group(1)), 1, 1), None)

    return (None, None)


def detectar_estado(texto: str) -> tuple:
    if not texto:
        return (None, None)
    m = re.search(r'([A-Za-zÀ-ÿ\s]+)[/\-,]\s*([A-Z]{2})\b', texto)
    if m:
        uf = m.group(2).upper()
        if uf in ESTADOS_BR.values():
            return (m.group(1).strip().title(), uf)
    texto_norm = texto.lower()
    for nome, uf in ESTADOS_BR.items():
        if nome.lower() in texto_norm:
            idx = texto_norm.find(nome.lower())
            cidade = texto[:idx].strip().strip(',').strip('-').strip().title() or None
            return (cidade, uf)
    return (None, None)


def detectar_categoria(titulo: str, descricao: str = '') -> str:
    texto = (titulo + ' ' + (descricao or '')).lower()
    for cat, keywords in CATEGORIAS_KEYWORDS.items():
        if any(kw in texto for kw in keywords):
            return cat
    return 'outro'


def gerar_slug(titulo: str, data_inicio) -> str:
    base = f"{titulo}-{data_inicio}"
    return hashlib.md5(base.lower().encode('utf-8')).hexdigest()[:12]


def normalizar(texto: str) -> str:
    return re.sub(r'\s+', ' ', texto.strip().upper())


def conectar_db():
    return pymysql.connect(**DB_CFG)


def salvar_evento(conn, ev: dict) -> bool:
    slug = ev.get('slug') or gerar_slug(ev.get('titulo', ''), ev.get('data_inicio'))
    sql = """
        INSERT INTO eventos_agro
            (titulo, slug, descricao, categoria, data_inicio, data_fim,
             local_cidade, local_estado, local_endereco, online,
             url_evento, url_imagem, organizador, publico_est,
             entrada, fonte, status)
        VALUES
            (%(titulo)s, %(slug)s, %(descricao)s, %(categoria)s,
             %(data_inicio)s, %(data_fim)s,
             %(local_cidade)s, %(local_estado)s, %(local_endereco)s, %(online)s,
             %(url_evento)s, %(url_imagem)s, %(organizador)s, %(publico_est)s,
             %(entrada)s, %(fonte)s, %(status)s)
        ON DUPLICATE KEY UPDATE
            titulo        = VALUES(titulo),
            descricao     = VALUES(descricao),
            data_inicio   = VALUES(data_inicio),
            data_fim      = VALUES(data_fim),
            local_cidade  = VALUES(local_cidade),
            local_estado  = VALUES(local_estado),
            organizador   = VALUES(organizador),
            publico_est   = VALUES(publico_est),
            atualizado_em = CURRENT_TIMESTAMP
    """
    defaults = {
        'titulo': '', 'slug': slug, 'descricao': None,
        'categoria': 'outro', 'data_inicio': None, 'data_fim': None,
        'local_cidade': None, 'local_estado': None, 'local_endereco': None,
        'online': 0, 'url_evento': None, 'url_imagem': None,
        'organizador': None, 'publico_est': None,
        'entrada': 'paga', 'fonte': None, 'status': 'ativo',
    }
    dados = {**defaults, **ev, 'slug': slug}
    with conn.cursor() as cur:
        cur.execute(sql, dados)
        novo = cur.lastrowid != 0 and cur.rowcount == 1
    conn.commit()
    return novo


def registrar_log(conn, fonte, status, novos, atualizados, erros, mensagem, duracao_ms):
    sql = """
        INSERT INTO eventos_log (fonte, status, novos, atualizados, erros, mensagem, duracao_ms)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    with conn.cursor() as cur:
        cur.execute(sql, (fonte, status, novos, atualizados, erros, mensagem, duracao_ms))
    conn.commit()


def get_html(url: str, verify_ssl: bool = True, encoding: str = None):
    try:
        r = SESSION.get(url, timeout=15, verify=verify_ssl)
        r.raise_for_status()
        if encoding:
            r.encoding = encoding
        return BeautifulSoup(r.text, 'html.parser')
    except Exception as e:
        log.warning(f"Erro ao buscar {url}: {e}")
        return None


def scrape_agroagenda() -> list:
    eventos = []
    base_url = 'https://agroagenda.agr.br/lista-de-eventos/'
    page = 1
    max_pages = 20
    log.info("AgroAgenda: iniciando scraping...")
    while page <= max_pages:
        url = base_url if page == 1 else f"{base_url}page/{page}/"
        soup = get_html(url)
        if not soup:
            break
        items = soup.select('article.type-tribe_events, .tribe-events-loop .tribe-event-featured-image')
        if not items:
            items = soup.select('article, .event-item')
        if not items:
            break
        novos_nessa_pagina = 0
        for item in items:
            titulo_el = item.select_one('h2 a, h3 a, .tribe-events-list-event__title a')
            if not titulo_el:
                continue
            titulo = titulo_el.get_text(strip=True)
            url_ev = titulo_el.get('href', '')
            data_el = item.select_one('.tribe-events-start-datetime, time')
            data_txt = data_el.get_text(strip=True) if data_el else ''
            dt_ini, dt_fim = parse_data_br(data_txt)
            local_el = item.select_one('.tribe-venue, .tribe-events-address')
            local_txt = local_el.get_text(strip=True) if local_el else ''
            cidade, estado = detectar_estado(local_txt)
            if not titulo or len(titulo) < 4:
                continue
            eventos.append({
                'titulo': titulo[:255], 'categoria': detectar_categoria(titulo),
                'data_inicio': dt_ini, 'data_fim': dt_fim,
                'local_cidade': cidade, 'local_estado': estado,
                'url_evento': url_ev[:500] if url_ev else None, 'fonte': 'agroagenda',
            })
            novos_nessa_pagina += 1
        log.info(f"AgroAgenda: página {page} → {novos_nessa_pagina} eventos")
        prox = soup.select_one('a.tribe-events-nav-next, .next.page-numbers')
        if not prox:
            break
        page += 1
        time.sleep(2)
    log.info(f"AgroAgenda: total coletado = {len(eventos)}")
    return eventos


def scrape_irancho() -> list:
    url = ('https://www.irancho.com.br/eventos-do-agro-confira-as-principais'
           '-feiras-e-eventos-em-2026/')
    soup = None
    try:
        r = SESSION.get(url, timeout=30)
        r.encoding = 'utf-8'
        soup = BeautifulSoup(r.text, 'html.parser')
        with open('/tmp/irancho_cache.html', 'w', encoding='utf-8') as f:
            f.write(r.text)
    except Exception as e:
        log.warning(f"iRancho: timeout ({e}), tentando cache...")
        try:
            with open('/tmp/irancho_cache.html', 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f.read(), 'html.parser')
            log.info("iRancho: usando cache local")
        except FileNotFoundError:
            log.warning("iRancho: sem cache, pulando")
            return []

    eventos = []
    log.info("iRancho: parsing estruturado...")
    ano = 2026
    mes_atual = 1
    evento_atual = None

    for tag in soup.find_all(['h2', 'h5', 'p']):
        texto = tag.get_text(strip=True)
        if not texto:
            continue

        if tag.name == 'h2':
            mes_lower = texto.lower().strip()
            if mes_lower in MESES_BR:
                mes_atual = MESES_BR[mes_lower]
            continue

        if tag.name == 'h5':
            if evento_atual and evento_atual.get('titulo'):
                eventos.append(evento_atual)
            evento_atual = {
                'titulo': texto[:255],
                'categoria': detectar_categoria(texto),
                'fonte': 'irancho',
            }
            continue

        if tag.name == 'p' and evento_atual:
            if '📅' in texto:
                data_txt = texto.replace('📅', '').strip()
                if str(ano) not in data_txt:
                    tem_mes = any(m in data_txt.lower() for m in MESES_BR)
                    if not tem_mes:
                        nome_mes = next(
                            (k for k, v in MESES_BR.items() if v == mes_atual and len(k) > 3), ''
                        )
                        data_txt = f"{data_txt} de {nome_mes} de {ano}"
                    else:
                        data_txt = f"{data_txt} de {ano}"
                dt_ini, dt_fim = parse_data_br(data_txt)
                evento_atual['data_inicio'] = dt_ini
                evento_atual['data_fim'] = dt_fim
            elif '📍' in texto:
                local_txt = texto.replace('📍', '').strip()
                cidade, estado = detectar_estado(local_txt)
                evento_atual['local_cidade'] = cidade
                evento_atual['local_estado'] = estado
            elif (not evento_atual.get('descricao') and len(texto) > 20
                  and 'saiba mais' not in texto.lower()
                  and not texto.startswith('http')):
                evento_atual['descricao'] = texto[:500]

    if evento_atual and evento_atual.get('titulo'):
        eventos.append(evento_atual)

    eventos = [e for e in eventos if len(e.get('titulo', '')) > 4]
    log.info(f"iRancho: {len(eventos)} eventos encontrados")
    return eventos


def scrape_caep() -> list:
    url = ('https://www.caep.com.br/2026/02/02/feiras-do-agro-2026-no-brasil'
           '-calendario-completo-dos-principais-eventos-do-agronegocio/')
    soup = get_html(url)
    eventos = []
    if not soup:
        return eventos
    log.info("CAEP: parsing...")
    conteudo = soup.select_one('.entry-content, .post-content, article, main') or soup
    texto_completo = conteudo.get_text(separator='\n', strip=True)
    linhas = texto_completo.split('\n')
    evento_atual = {}
    for linha in linhas:
        linha = linha.strip()
        if not linha:
            continue
        if any(kw in linha.lower() for kw in ['feira', 'expo', 'show', 'congresso', 'tecnoshow']):
            if evento_atual.get('titulo'):
                eventos.append(evento_atual)
            evento_atual = {'titulo': linha[:255], 'categoria': detectar_categoria(linha), 'fonte': 'caep'}
        if '📅' in linha or re.search(r'\d{1,2}\s+(?:a|e)\s+\d{1,2}\s+de\s+\w+', linha):
            dt_ini, dt_fim = parse_data_br(re.sub(r'📅', '', linha))
            if dt_ini:
                evento_atual['data_inicio'] = dt_ini
                evento_atual['data_fim'] = dt_fim
        if '📍' in linha:
            cidade, estado = detectar_estado(re.sub(r'📍', '', linha).strip())
            evento_atual['local_cidade'] = cidade
            evento_atual['local_estado'] = estado
    if evento_atual.get('titulo'):
        eventos.append(evento_atual)
    log.info(f"CAEP: {len(eventos)} eventos encontrados")
    return eventos


def parse_embrapa_data(txt: str) -> tuple:
    """Parseia formato EMBRAPA: '10 MARa14 MAR2026' ou '01 JANa01 DEZ2026'"""
    import re as _re
    meses = {
        'jan':1,'fev':2,'mar':3,'abr':4,'mai':5,'jun':6,
        'jul':7,'ago':8,'set':9,'out':10,'nov':11,'dez':12
    }
    txt = txt.lower().strip()
    m = _re.search(r'(\d{1,2})\s*(\w{3})\s*a\s*(\d{1,2})\s*(\w{3})\s*(\d{4})', txt)
    if m:
        d1, m1 = int(m.group(1)), m.group(2)
        d2, m2 = int(m.group(3)), m.group(4)
        ano = int(m.group(5))
        mes1, mes2 = meses.get(m1), meses.get(m2)
        if mes1 and mes2:
            try:
                return date(ano, mes1, d1), date(ano, mes2, d2)
            except ValueError:
                pass
    return None, None


def scrape_embrapa() -> list:
    base_url = 'https://www.embrapa.br/busca-de-eventos/-/evento/'
    eventos = []
    log.info("EMBRAPA: iniciando scraping...")
    vistos = set()

    for pag in range(0, 5):
        url = base_url if pag == 0 else f"{base_url}?p_p_id=br_com_sistemafaemg_listagemEventos_web_portlet_ListagemEventosPortlet_INSTANCE_S1La8zlDbSUH&p_p_lifecycle=0&_br_com_sistemafaemg_listagemEventos_web_portlet_ListagemEventosPortlet_INSTANCE_S1La8zlDbSUH_cur={pag}"
        soup = get_html(url)
        if not soup:
            break

        links = soup.select('a[href*="/busca-de-eventos/-/evento/"]')
        encontrados = 0

        # Agrupa pares: (link_data, link_titulo) com mesmo href
        hrefs_vistos_pagina = {}
        for a in links:
            href = a.get('href', '')
            txt = a.get_text(strip=True)
            if not href or not txt:
                continue
            if href not in hrefs_vistos_pagina:
                hrefs_vistos_pagina[href] = {'data_txt': None, 'titulo': None}
            # Link de data tem padrão "DDMESaDD MES YYYY"
            if re.search(r'\d{1,2}\s*[A-Za-z]{3}a', txt):
                hrefs_vistos_pagina[href]['data_txt'] = txt
            elif len(txt) > 5:
                hrefs_vistos_pagina[href]['titulo'] = txt

        for href, info in hrefs_vistos_pagina.items():
            titulo = info['titulo']
            if not titulo or titulo in vistos or len(titulo) < 5:
                continue
            vistos.add(titulo)

            dt_ini, dt_fim = parse_embrapa_data(info['data_txt'] or '')
            cat = detectar_categoria(titulo)
            if cat == 'outro':
                cat = 'curso'

            eventos.append({
                'titulo':      titulo[:255],
                'categoria':   cat,
                'data_inicio': dt_ini,
                'data_fim':    dt_fim,
                'url_evento':  href[:500],
                'organizador': 'EMBRAPA',
                'entrada':     'gratuita',
                'fonte':       'embrapa',
            })
            encontrados += 1

        log.info(f"EMBRAPA: página {pag} → {encontrados} eventos")
        if encontrados == 0:
            break
        time.sleep(2)

    log.info(f"EMBRAPA: total = {len(eventos)}")
    return eventos


def scrape_nfeiras() -> list:
    url = 'https://www.nfeiras.com/agricola/brasil/'
    soup = get_html(url, verify_ssl=False)
    eventos = []
    if not soup:
        return eventos
    log.info("NFeiras: parsing...")
    for item in soup.select('table tr'):
        colunas = item.select('td')
        if len(colunas) < 2:
            continue
        titulo = colunas[0].get_text(strip=True)
        if not titulo or len(titulo) < 4:
            continue
        data_txt = colunas[1].get_text(strip=True) if len(colunas) > 1 else ''
        local_txt = colunas[2].get_text(strip=True) if len(colunas) > 2 else ''
        dt_ini, dt_fim = parse_data_br(data_txt)
        cidade, estado = detectar_estado(local_txt)
        link_el = colunas[0].select_one('a')
        url_ev = link_el.get('href', '') if link_el else ''
        eventos.append({
            'titulo': titulo[:255], 'categoria': 'feira',
            'data_inicio': dt_ini, 'data_fim': dt_fim,
            'local_cidade': cidade, 'local_estado': estado,
            'url_evento': url_ev[:500] if url_ev else None, 'fonte': 'nfeiras',
        })
    log.info(f"NFeiras: {len(eventos)} eventos encontrados")
    return eventos


def scrape_falker() -> list:
    url = 'https://www.falker.com.br/br/blog-feiras-agricolas-calendario-para-2026'
    soup = get_html(url)
    eventos = []
    if not soup:
        return eventos
    log.info("Falker: parsing...")
    conteudo = soup.select_one('.blog-content, .entry-content, article, main') or soup
    for item in conteudo.select('li, tr, p'):
        texto = item.get_text(separator=' ', strip=True)
        if len(texto) < 10:
            continue
        if not any(w in texto.lower() for w in ['feira', 'expo', 'show', 'congresso', 'agro']):
            continue
        dt_ini, dt_fim = parse_data_br(texto)
        cidade, estado = detectar_estado(texto)
        nome = re.split(r'[:\-–|]|\d{1,2}/\d{2}', texto)[0].strip()
        if len(nome) < 4:
            nome = texto[:120]
        eventos.append({
            'titulo': nome[:255], 'categoria': detectar_categoria(texto),
            'data_inicio': dt_ini, 'data_fim': dt_fim,
            'local_cidade': cidade, 'local_estado': estado, 'fonte': 'falker',
        })
    log.info(f"Falker: {len(eventos)} eventos encontrados")
    return eventos


FEIRAS_FIXAS_2026 = [
    {'titulo': 'Tecnoshow Comigo 2026', 'categoria': 'feira',
     'data_inicio': date(2026,4,6), 'data_fim': date(2026,4,10),
     'local_cidade': 'Rio Verde', 'local_estado': 'GO',
     'url_evento': 'https://www.tecnoshow.com.br/',
     'publico_est': '140.000 visitantes', 'entrada': 'gratuita',
     'organizador': 'Comigo', 'fonte': 'seed_data'},
    {'titulo': 'Expodireto Cotrijal 2026', 'categoria': 'feira',
     'data_inicio': date(2026,3,2), 'data_fim': date(2026,3,6),
     'local_cidade': 'Não-Me-Toque', 'local_estado': 'RS',
     'url_evento': 'https://www.expodireto.com.br/',
     'publico_est': '200.000 visitantes', 'entrada': 'gratuita',
     'organizador': 'Cotrijal', 'fonte': 'seed_data'},
    {'titulo': 'Agrishow 2026', 'categoria': 'feira',
     'data_inicio': date(2026,4,27), 'data_fim': date(2026,5,1),
     'local_cidade': 'Ribeirão Preto', 'local_estado': 'SP',
     'url_evento': 'https://www.agrishow.com.br/',
     'publico_est': '180.000 visitantes', 'entrada': 'paga',
     'organizador': 'Informa Markets', 'fonte': 'seed_data'},
    {'titulo': 'Expointer 2026', 'categoria': 'feira',
     'data_inicio': date(2026,8,29), 'data_fim': date(2026,9,6),
     'local_cidade': 'Esteio', 'local_estado': 'RS',
     'url_evento': 'https://www.expointer.rs.gov.br/',
     'publico_est': '1.200.000 visitantes', 'entrada': 'paga',
     'organizador': 'Governo do RS', 'fonte': 'seed_data'},
    {'titulo': 'AgroBrasília 2026', 'categoria': 'feira',
     'data_inicio': date(2026,5,5), 'data_fim': date(2026,5,9),
     'local_cidade': 'Brasília', 'local_estado': 'DF',
     'url_evento': 'https://agrobrasilia.coop.br/',
     'entrada': 'gratuita', 'organizador': 'OCB/DF', 'fonte': 'seed_data'},
    {'titulo': 'Bahia Farm Show 2026', 'categoria': 'feira',
     'data_inicio': date(2026,6,2), 'data_fim': date(2026,6,6),
     'local_cidade': 'Luís Eduardo Magalhães', 'local_estado': 'BA',
     'url_evento': 'https://www.bahiafarmshow.com.br/',
     'publico_est': '100.000 visitantes', 'entrada': 'gratuita', 'fonte': 'seed_data'},
    {'titulo': 'FEMEC 2026', 'categoria': 'feira',
     'data_inicio': date(2026,5,13), 'data_fim': date(2026,5,17),
     'local_cidade': 'Uberaba', 'local_estado': 'MG',
     'url_evento': 'https://femec.agr.br/',
     'entrada': 'gratuita', 'organizador': 'ABCZ', 'fonte': 'seed_data'},
    {'titulo': 'Show Rural Coopavel 2026', 'categoria': 'feira',
     'data_inicio': date(2026,2,2), 'data_fim': date(2026,2,6),
     'local_cidade': 'Cascavel', 'local_estado': 'PR',
     'url_evento': 'https://www.showrural.com.br/',
     'publico_est': '270.000 visitantes', 'entrada': 'gratuita',
     'organizador': 'Coopavel', 'fonte': 'seed_data'},
    {'titulo': 'ExpoZebu 2026', 'categoria': 'exposicao',
     'data_inicio': date(2026,4,24), 'data_fim': date(2026,5,3),
     'local_cidade': 'Uberaba', 'local_estado': 'MG',
     'url_evento': 'https://expozebufeirase.com.br/',
     'publico_est': '600.000 visitantes', 'entrada': 'paga',
     'organizador': 'ABCZ', 'fonte': 'seed_data'},
    {'titulo': 'Agro Centro-Oeste 2026', 'categoria': 'feira',
     'data_inicio': date(2026,6,9), 'data_fim': date(2026,6,13),
     'local_cidade': 'Campo Grande', 'local_estado': 'MS',
     'entrada': 'gratuita', 'fonte': 'seed_data'},
]


def scrape_feiras_fixas() -> list:
    log.info(f"Seed data: {len(FEIRAS_FIXAS_2026)} feiras principais carregadas")
    return FEIRAS_FIXAS_2026


FONTES = {
    'seed':       scrape_feiras_fixas,
    'agroagenda': scrape_agroagenda,
    'irancho':    scrape_irancho,
    'caep':       scrape_caep,
    'embrapa':    scrape_embrapa,
    'nfeiras':    scrape_nfeiras,
    'falker':     scrape_falker,
}


def run_once(fontes_selecionadas: list = None):
    t_inicio = time.time()
    conn = conectar_db()
    fontes_ativas = fontes_selecionadas or list(FONTES.keys())
    total_novos = total_atualizados = total_erros = 0

    for nome_fonte in fontes_ativas:
        if nome_fonte not in FONTES:
            log.warning(f"Fonte desconhecida: {nome_fonte}")
            continue
        log.info(f"══ Iniciando fonte: {nome_fonte.upper()} ══")
        t0 = time.time()
        novos = atualizados = erros = 0
        try:
            eventos = FONTES[nome_fonte]()
            for ev in eventos:
                try:
                    if salvar_evento(conn, ev):
                        novos += 1
                    else:
                        atualizados += 1
                except Exception as e:
                    erros += 1
                    log.error(f"Erro ao salvar '{ev.get('titulo', '?')}': {e}")
            duracao = int((time.time() - t0) * 1000)
            registrar_log(conn, nome_fonte, 'ok', novos, atualizados, erros,
                          f"Coletados: {len(eventos)}", duracao)
            log.info(f"[{nome_fonte}] novos={novos} atualizados={atualizados} erros={erros}")
        except Exception as e:
            duracao = int((time.time() - t0) * 1000)
            registrar_log(conn, nome_fonte, 'erro', 0, 0, 1, str(e), duracao)
            log.error(f"Fonte {nome_fonte} falhou: {e}")
        total_novos += novos
        total_atualizados += atualizados
        total_erros += erros

    conn.close()
    duracao_total = int((time.time() - t_inicio) * 1000)
    log.info(f"══ CONCLUÍDO ══ novos={total_novos} atualizados={total_atualizados} "
             f"erros={total_erros} tempo={duracao_total}ms")


def cmd_listar(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT titulo, categoria, data_inicio, local_cidade, local_estado, fonte
            FROM eventos_agro WHERE status = 'ativo'
            ORDER BY data_inicio ASC LIMIT 50
        """)
        rows = cur.fetchall()
    print(f"\n{'TÍTULO':<50} {'CAT':<15} {'DATA':<12} {'LOCAL':<25} {'FONTE'}")
    print('-' * 120)
    for r in rows:
        local = f"{r.get('local_cidade','?')}/{r.get('local_estado','?')}"
        print(f"{str(r['titulo']):<50} {str(r.get('categoria','')):<15} "
              f"{str(r.get('data_inicio','')):<12} {local:<25} {r.get('fonte','')}")
    print(f"\nTotal: {len(rows)} eventos\n")


def cmd_proximos(conn, dias: int):
    hoje = date.today()
    ate = hoje + timedelta(days=dias)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT titulo, categoria, data_inicio, data_fim,
                   local_cidade, local_estado,
                   DATEDIFF(data_inicio, CURDATE()) AS dias_para_evento
            FROM eventos_agro
            WHERE status = 'ativo' AND data_inicio BETWEEN %s AND %s
            ORDER BY data_inicio ASC
        """, (hoje, ate))
        rows = cur.fetchall()
    print(f"\nEventos nos próximos {dias} dias ({hoje} → {ate}):\n")
    for r in rows:
        d = r.get('dias_para_evento', '?')
        badge = 'HOJE' if d == 0 else f'em {d}d'
        print(f"  [{badge:>8}] {r['titulo'][:50]:<50} {r.get('data_inicio','')} "
              f"{r.get('local_cidade','')}/{r.get('local_estado','')}")
    print(f"\nTotal: {len(rows)} eventos\n")


def cmd_test_db():
    try:
        conn = conectar_db()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM eventos_agro")
            r = cur.fetchone()
        print(f"✅ Conexão OK — {r['total']} eventos no banco")
        conn.close()
    except Exception as e:
        print(f"❌ Erro: {e}")


def main():
    parser = argparse.ArgumentParser(description='Scraper de Eventos Agro')
    parser.add_argument('--fonte', help='Fonte específica')
    parser.add_argument('--listar', action='store_true')
    parser.add_argument('--proximos', type=int, metavar='DIAS')
    parser.add_argument('--test-db', action='store_true')
    args = parser.parse_args()

    if args.test_db:
        cmd_test_db()
        return
    if args.listar:
        conn = conectar_db()
        cmd_listar(conn)
        conn.close()
        return
    if args.proximos:
        conn = conectar_db()
        cmd_proximos(conn, args.proximos)
        conn.close()
        return
    fontes = [args.fonte] if args.fonte else None
    run_once(fontes)


if __name__ == '__main__':
    main()
