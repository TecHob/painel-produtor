# Patch para scraper_noticias.py - novas URLs RSS
# BC deve rodar: python3 fix_noticias.py no servidor

with open('/opt/painel-produtor/scraper_noticias.py', 'r') as f:
    code = f.read()

old = """FONTES = [
    {'nome': 'Notícias Agrícolas', 'url': 'https://www.noticiasagricolas.com.br/rss.xml'},
    {'nome': 'AgroLink',           'url': 'https://www.agrolink.com.br/noticias/rss/'},
    {'nome': 'Canal Rural',        'url': 'https://www.canalrural.com.br/rss/'},
]"""

new = """FONTES = [
    {'nome': 'Notícias Agrícolas', 'url': 'https://www.noticiasagricolas.com.br/rss/noticias.xml'},
    {'nome': 'AgroLink',           'url': 'https://www.agrolink.com.br/rss/noticias.xml'},
    {'nome': 'Embrapa',            'url': 'https://www.embrapa.br/rss/ultimas-noticias.xml'},
    {'nome': 'MAPA Gov',           'url': 'https://www.gov.br/agricultura/pt-br/assuntos/noticias/RSS'},
    {'nome': 'Canal Rural',        'url': 'https://www.canalrural.com.br/feed/'},
]"""

if old in code:
    code = code.replace(old, new)
    with open('/opt/painel-produtor/scraper_noticias.py', 'w') as f:
        f.write(code)
    print('OK - 5 fontes RSS atualizadas')
else:
    print('ERRO - texto original nao encontrado')
