#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper de Notícias Agropecuárias — Painel do Produtor
Precisão Inova / André CTO

Fontes RSS:
  - Notícias Agrícolas  (noticiasagricolas.com.br)
  - AgroLink            (agrolink.com.br)
  - Canal Rural         (canalrural.com.br)

Salva em: agro_noticias (techobco_agropecuaria)

Cron (a cada 2h):
  0 */2 * * * /opt/painel-produtor/venv/bin/python3 /opt/painel-produtor/scraper_noticias.py >> /var/log/painel-produtor/noticias.log 2>&1

Uso:
  python3 scraper_noticias.py          # roda uma vez
  python3 scraper_noticias.py --test   # testa sem salvar no banco
"""

import re
import sys
import hashlib
import logging
import argparse
import urllib3
from datetime import datetime
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

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

# ── Banco (mesmo padrão do scraper_cepea.py) ──────────────────
DB_CFG = {
    'host':        '199.167.147.66',
    'port':        3306,
    'user':        'techobco_agropecuaria',
    'password':    '@precisao2203',
    'db':          'techobco_agropecuaria',
    'charset':     'utf8mb4',
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
    'Accept': 'application/rss+xml, application/xml, text/xml, */*',
})

MAX_POR_FONTE  = 8   # itens por fonte por execução
MAX_NO_BANCO   = 60  # total de notícias RSS mantidas (limpa antigas)

# ── Fontes RSS ────────────────────────────────────────────────
FONTES = [
    {'nome': 'Notícias Agrícolas', 'url': 'https://www.noticiasagricolas.com.br/rss/noticias.xml'},
    {'nome': 'AgroLink',           'url': 'https://www.agrolink.com.br/rss/noticias.xml'},
    {'nome': 'Embrapa',            'url': 'https://www.embrapa.br/rss/ultimas-noticias.xml'},
    {'nome': 'MAPA Gov',           'url': 'https://www.gov.br/agricultura/pt-br/assuntos/noticias/RSS'},
    {'nome': 'Canal Rural',        'url': 'https://www.canalrural.com.br/feed/'},
]

# ── Categoria + emoji por palavras-chave ──────────────────────
REGRAS_CAT = [
    (['drone','satélite','iot','sensor','ia ','inteligência artificial',
      'tecnologia','precisão','inovação','robô','startup','agtech','digital'],
     'tecnologia', '🤖'),
    (['clima','chuva','seca','geada','temperatura','previsão',
      'el niño','la niña','umidade','irrigação','estiagem'],
     'clima', '🌧️'),
    (['orgânico','regenerativo','sustentável','carbono','biológico',
      'agroecologia','certificação','ambiental','sequestro'],
     'sustentabilidade', '🌱'),
    (['pesquisa','embrapa','epamig','universidade','estudo',
      'descoberta','genética','variedade','cultivar'],
     'inovacao', '🔬'),
    (['preço','cotação','mercado','bolsa','exportação','importação',
      'dólar','câmbio','safra','produção','tonelada','saca','arroba',
      'crédito','financiamento','custo','receita'],
     'mercado', '📈'),
]

EMOJI_PRODUTO = {
    'café': '☕', 'milho': '🌽', 'soja': '🫘', 'boi': '🐂',
    'frango': '🐔', 'suíno': '🐷', 'trigo': '🌾', 'algodão': '🪡',
    'açúcar': '🍬', 'laranja': '🍊', 'eucalipto': '🌲', 'arroz': '🍚',
}


def detectar_categoria(titulo: str, descricao: str) -> tuple:
    texto = (titulo + ' ' + descricao).lower()

    emoji = '🌾'
    for prod, em in EMOJI_PRODUTO.items():
        if prod in texto:
            emoji = em
            break

    for keywords, cat, em_cat in REGRAS_CAT:
        if any(k in texto for k in keywords):
            return cat, (emoji if emoji != '🌾' else em_cat)

    return 'mercado', emoji


def slugify(text: str) -> str:
    text = text.lower()
    for a, b in [('á','a'),('à','a'),('ã','a'),('â','a'),('é','e'),('ê','e'),
                 ('í','i'),('ó','o'),('õ','o'),('ô','o'),('ú','u'),('ç','c')]:
        text = text.replace(a, b)
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'\s+', '-', text.strip())
    return text[:80]


def limpar_html(text: str) -> str:
    if not text:
        return ''
    text = re.sub(r'<[^>]+>', '', text)
    for ent, ch in [('&amp;','&'),('&lt;','<'),('&gt;','>'),
                    ('&quot;','"'),('&#39;',"'"),('&nbsp;',' ')]:
        text = text.replace(ent, ch)
    return ' '.join(text.split())


def fetch_rss(url: str) -> list:
    try:
        r = SESSION.get(url, timeout=12, verify=False)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        log.warning(f'  RSS error {url}: {e}')
        return []

    items = root.findall('.//item')
    out = []
    for item in items[:MAX_POR_FONTE]:
        titulo    = limpar_html(item.findtext('title') or '')
        descricao = limpar_html(item.findtext('description') or '')
        pub_date  = item.findtext('pubDate') or ''

        if not titulo or len(titulo) < 10:
            continue

        # Parse data de publicação
        criado_em = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if pub_date:
            try:
                criado_em = parsedate_to_datetime(pub_date).strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                pass

        resumo = descricao[:250] + ('...' if len(descricao) > 250 else '')

        # Slug com hash curto para evitar duplicatas
        h = hashlib.md5(titulo.encode('utf-8')).hexdigest()[:6]
        slug = f"{slugify(titulo)}-{h}"

        cat, emoji = detectar_categoria(titulo, descricao)

        out.append({
            'titulo':    titulo[:255],
            'slug':      slug,
            'resumo':    resumo,
            'conteudo':  descricao or resumo,
            'emoji':     emoji,
            'categoria': cat,
            'criado_em': criado_em,
        })
    return out


def salvar_noticias(conn, noticias: list) -> int:
    if not noticias:
        return 0

    saved = 0
    with conn.cursor() as cur:
        for n in noticias:
            try:
                cur.execute(
                    """INSERT IGNORE INTO agro_noticias
                       (titulo, slug, resumo, conteudo, emoji, categoria, publicado, criado_em)
                       VALUES (%s, %s, %s, %s, %s, %s, 1, %s)""",
                    (n['titulo'], n['slug'], n['resumo'], n['conteudo'],
                     n['emoji'], n['categoria'], n['criado_em'])
                )
                if cur.rowcount > 0:
                    saved += 1
                    log.info(f"  + [{n['categoria']}] {n['emoji']}  {n['titulo'][:65]}")
            except Exception as e:
                log.warning(f"  Erro ao salvar: {e}")

        # Mantém só as MAX_NO_BANCO mais recentes de RSS (autor_id IS NULL)
        cur.execute(f"""
            DELETE FROM agro_noticias
            WHERE autor_id IS NULL
              AND id NOT IN (
                SELECT id FROM (
                    SELECT id FROM agro_noticias
                    WHERE autor_id IS NULL
                    ORDER BY criado_em DESC
                    LIMIT {MAX_NO_BANCO}
                ) AS t
              )
        """)
        if cur.rowcount:
            log.info(f"  Limpeza: {cur.rowcount} antigas removidas")

    conn.commit()
    return saved


def run(test_mode: bool = False):
    log.info('=' * 55)
    log.info('SCRAPER NOTÍCIAS AGRO — iniciando')
    if test_mode:
        log.info('MODO TESTE — banco não será alterado')
    log.info('=' * 55)

    conn = None
    if not test_mode:
        try:
            conn = pymysql.connect(**DB_CFG)
            log.info('✓ Banco conectado')
        except Exception as e:
            log.error(f'✗ Conexão falhou: {e}')
            sys.exit(1)

    total = 0
    for fonte in FONTES:
        log.info(f"\n── {fonte['nome']}")
        noticias = fetch_rss(fonte['url'])
        log.info(f"  {len(noticias)} itens no RSS")

        if test_mode:
            for n in noticias[:3]:
                log.info(f"  [{n['categoria']}] {n['emoji']}  {n['titulo'][:70]}")
        else:
            n = salvar_noticias(conn, noticias)
            total += n

    if conn:
        conn.close()

    log.info(f'\n✓ Concluído — {total} novas notícias salvas')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Scraper notícias agro')
    ap.add_argument('--test', action='store_true', help='Testa sem salvar no banco')
    args = ap.parse_args()
    run(test_mode=args.test)
