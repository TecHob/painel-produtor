#!/usr/bin/env python3
"""
alertas_agro.py — Alertas proativos via WhatsApp
Detecta variações de preço e condições climáticas extremas.
Envia pra todos os contatos aprovados.

Cron sugerido (2x/dia, após scrapers):
30 7,19 * * * cd /opt/painel-produtor && python3 alertas_agro.py >> /var/log/painel-produtor/alertas.log 2>&1

Criado: 15/06/2026
"""

import logging
import json
from datetime import datetime, date, timedelta

import pymysql
import pymysql.cursors
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger("alertas")

# ── Config ──
DB = {
    'host': '199.167.147.66',
    'port': 3306,
    'user': 'techobco_agropecuaria',
    'password': '@precisao2203',
    'database': 'techobco_agropecuaria',
    'charset': 'utf8mb4',
}

EVOLUTION_URL = 'http://localhost:8080'
EVOLUTION_KEY = 'inova-secret-key'
EVOLUTION_INST = 'agro-bot'

# Thresholds
PRECO_VARIACAO_MIN = 2.0        # % minima pra alertar variação de preço
CHUVA_FORTE_MM = 40.0           # mm/dia pra alertar chuva forte
GEADA_TEMP_C = 3.0              # °C minima pra alertar geada
VENTO_FORTE_KMH = 60.0          # km/h pra alertar vento
SECA_DIAS = 5                   # dias sem chuva pra alertar seca

# Produtos prioritários pro alerta de preço
PRODUTOS_ALERTA = ['soja', 'milho', 'cafe_arabica', 'cafe_conillon', 'boi_gordo', 'trigo', 'algodao']

# Emojis por tipo
EMOJI = {
    'alta': '📈', 'queda': '📉', 'geada': '🥶', 'chuva': '🌧️',
    'vento': '💨', 'seca': '☀️', 'geral': '🌾',
}


def get_conn():
    return pymysql.connect(**DB, cursorclass=pymysql.cursors.DictCursor, connect_timeout=10)


def enviar_whatsapp(numero, texto):
    """Envia mensagem via Evolution API."""
    url = f"{EVOLUTION_URL}/message/sendText/{EVOLUTION_INST}"
    try:
        r = requests.post(
            url,
            json={'number': numero, 'textMessage': {'text': texto}},
            headers={'apikey': EVOLUTION_KEY},
            timeout=10,
        )
        if r.status_code == 201:
            log.info(f"  Enviado para {numero[:8]}...")
        else:
            log.warning(f"  Falha envio {numero[:8]}: {r.status_code}")
    except Exception as e:
        log.error(f"  Erro envio {numero[:8]}: {e}")


def get_contatos_aprovados(conn):
    """Retorna lista de números aprovados."""
    with conn.cursor() as cur:
        cur.execute("SELECT numero FROM whatsapp_contatos WHERE status = 'aprovado' AND numero != '' AND recebe_alertas = 1")
        return [r['numero'] for r in cur.fetchall()]


# ═══════════════════════════════════════════════════════════════
# ALERTAS DE PREÇO
# ═══════════════════════════════════════════════════════════════

def detectar_variacoes_preco(conn):
    """Detecta variações significativas nos preços (cotacoes_atual)."""
    alertas = []
    with conn.cursor() as cur:
        cur.execute("SELECT produto, preco, preco_ant, variacao_pct, unidade FROM cotacoes_atual WHERE produto IN (%s)" % ','.join(['%s'] * len(PRODUTOS_ALERTA)), PRODUTOS_ALERTA)
        rows = cur.fetchall()

        for r in rows:
            var = float(r.get('variacao_pct') or 0)
            if abs(var) >= PRECO_VARIACAO_MIN:
                preco = float(r.get('preco') or 0)
                produto = r['produto'].replace('_', ' ').title()
                unidade = r.get('unidade') or ''
                direcao = 'alta' if var > 0 else 'queda'
                emoji = EMOJI[direcao]
                alertas.append({
                    'tipo': 'preco',
                    'msg': f"{emoji} {produto}: R$ {preco:,.2f}/{unidade} ({'+' if var > 0 else ''}{var:.1f}%)"
                })

    # Também verificar histórico (agrobr) pra tendência de 5 dias
    with conn.cursor() as cur:
        for produto in ['soja', 'milho', 'cafe', 'boi', 'trigo', 'algodao']:
            cur.execute("""
                SELECT valor FROM preco_historico
                WHERE produto = %s
                ORDER BY data_ref DESC LIMIT 2
            """, (produto,))
            rows = cur.fetchall()
            if len(rows) == 2:
                atual = float(rows[0]['valor'])
                anterior = float(rows[1]['valor'])
                if anterior > 0:
                    var = ((atual - anterior) / anterior) * 100
                    if abs(var) >= PRECO_VARIACAO_MIN and not any(produto.replace('_', ' ') in a['msg'].lower() for a in alertas):
                        direcao = 'alta' if var > 0 else 'queda'
                        emoji = EMOJI[direcao]
                        alertas.append({
                            'tipo': 'preco',
                            'msg': f"{emoji} {produto.title()}: R$ {atual:,.2f} ({'+' if var > 0 else ''}{var:.1f}% vs dia anterior)"
                        })

    return alertas


# ═══════════════════════════════════════════════════════════════
# ALERTAS DE CLIMA
# ═══════════════════════════════════════════════════════════════

def detectar_alertas_clima(conn):
    """Detecta condições climáticas extremas nos próximos 3 dias."""
    alertas = []
    with conn.cursor() as cur:
        # Previsão dos próximos 3 dias pra todos os municípios
        cur.execute("""
            SELECT m.nome, m.uf, p.data_prev, p.temp_min, p.temp_max,
                   p.chuva_mm, p.vento_max_kmh, p.prob_chuva
            FROM clima_previsao p
            JOIN municipios m ON m.id = p.municipio_id
            WHERE p.data_prev BETWEEN CURDATE() AND CURDATE() + INTERVAL 3 DAY
            ORDER BY p.data_prev
        """)
        rows = cur.fetchall()

        geada_cidades = []
        chuva_cidades = []
        vento_cidades = []

        for r in rows:
            cidade = f"{r['nome']}/{r['uf']}"
            data = r['data_prev'].strftime('%d/%m') if hasattr(r['data_prev'], 'strftime') else str(r['data_prev'])
            temp_min = float(r.get('temp_min') or 99)
            chuva = float(r.get('chuva_mm') or 0)
            vento = float(r.get('vento_max_kmh') or 0)

            if temp_min <= GEADA_TEMP_C:
                geada_cidades.append(f"{cidade} ({data}: {temp_min:.0f}°C)")

            if chuva >= CHUVA_FORTE_MM:
                chuva_cidades.append(f"{cidade} ({data}: {chuva:.0f}mm)")

            if vento >= VENTO_FORTE_KMH:
                vento_cidades.append(f"{cidade} ({data}: {vento:.0f}km/h)")

        # Agrupa por tipo (máximo 5 cidades por alerta)
        if geada_cidades:
            cidades_str = ', '.join(geada_cidades[:5])
            if len(geada_cidades) > 5:
                cidades_str += f" +{len(geada_cidades) - 5}"
            alertas.append({
                'tipo': 'geada',
                'msg': f"{EMOJI['geada']} GEADA: Temp abaixo de {GEADA_TEMP_C}°C prevista em {cidades_str}"
            })

        if chuva_cidades:
            cidades_str = ', '.join(chuva_cidades[:5])
            if len(chuva_cidades) > 5:
                cidades_str += f" +{len(chuva_cidades) - 5}"
            alertas.append({
                'tipo': 'chuva',
                'msg': f"{EMOJI['chuva']} CHUVA FORTE: Acima de {CHUVA_FORTE_MM:.0f}mm prevista em {cidades_str}"
            })

        if vento_cidades:
            cidades_str = ', '.join(vento_cidades[:5])
            if len(vento_cidades) > 5:
                cidades_str += f" +{len(vento_cidades) - 5}"
            alertas.append({
                'tipo': 'vento',
                'msg': f"{EMOJI['vento']} VENTO FORTE: Acima de {VENTO_FORTE_KMH:.0f}km/h previsto em {cidades_str}"
            })

        # Detectar seca (sem chuva significativa nos próximos dias)
        cur.execute("""
            SELECT m.nome, m.uf, SUM(p.chuva_mm) as total_chuva
            FROM clima_previsao p
            JOIN municipios m ON m.id = p.municipio_id
            WHERE p.data_prev BETWEEN CURDATE() AND CURDATE() + INTERVAL %s DAY
            GROUP BY m.id, m.nome, m.uf
            HAVING total_chuva < 2
        """, (SECA_DIAS,))
        seca_rows = cur.fetchall()
        if len(seca_rows) >= 10:  # Se muitos municípios sem chuva
            alertas.append({
                'tipo': 'seca',
                'msg': f"{EMOJI['seca']} SECA: {len(seca_rows)} municípios sem chuva significativa nos próximos {SECA_DIAS} dias"
            })

    return alertas


# ═══════════════════════════════════════════════════════════════
# CONTROLE DE DUPLICATAS (não mandar o mesmo alerta 2x no dia)
# ═══════════════════════════════════════════════════════════════

def criar_tabela_alertas(conn):
    """Cria tabela de controle se não existir."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS alertas_enviados (
                id INT AUTO_INCREMENT PRIMARY KEY,
                data_ref DATE NOT NULL,
                hash_alerta VARCHAR(64) NOT NULL,
                tipo VARCHAR(20),
                mensagem TEXT,
                contatos_enviados INT DEFAULT 0,
                criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uk_alerta_dia (data_ref, hash_alerta)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
    conn.commit()


def alerta_ja_enviado(conn, hash_alerta):
    """Verifica se um alerta já foi enviado hoje."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM alertas_enviados WHERE data_ref = CURDATE() AND hash_alerta = %s",
            (hash_alerta,)
        )
        return cur.fetchone() is not None


def registrar_alerta(conn, hash_alerta, tipo, mensagem, contatos):
    """Registra alerta como enviado."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT IGNORE INTO alertas_enviados (data_ref, hash_alerta, tipo, mensagem, contatos_enviados) VALUES (CURDATE(), %s, %s, %s, %s)",
            (hash_alerta, tipo, mensagem[:500], contatos)
        )
    conn.commit()


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    import hashlib

    log.info("=" * 50)
    log.info("ALERTAS AGRO — Verificando condições")
    log.info("=" * 50)

    conn = get_conn()
    criar_tabela_alertas(conn)

    # Coletar alertas
    alertas = []

    log.info("Verificando preços...")
    alertas += detectar_variacoes_preco(conn)

    log.info("Verificando clima...")
    alertas += detectar_alertas_clima(conn)

    if not alertas:
        log.info("Nenhum alerta para hoje. Tudo tranquilo.")
        conn.close()
        return

    log.info(f"{len(alertas)} alerta(s) detectado(s)")

    # Filtrar alertas já enviados hoje
    alertas_novos = []
    for a in alertas:
        h = hashlib.md5(a['msg'].encode()).hexdigest()[:16]
        if not alerta_ja_enviado(conn, h):
            a['hash'] = h
            alertas_novos.append(a)
        else:
            log.info(f"  (já enviado) {a['msg'][:60]}")

    if not alertas_novos:
        log.info("Todos os alertas já foram enviados hoje.")
        conn.close()
        return

    log.info(f"{len(alertas_novos)} alerta(s) novo(s) para enviar")

    # Montar mensagem única com todos os alertas
    hora = datetime.now().strftime('%H:%M')
    linhas = [f"🌾 Alertas Agro ({hora}):", ""]
    for a in alertas_novos:
        linhas.append(a['msg'])
    linhas.append("")
    linhas.append("Pergunte mais: ! preço da soja, ! clima Pitangui")

    mensagem = '\n'.join(linhas)
    log.info(f"Mensagem ({len(mensagem)} chars):\n{mensagem}")

    # Buscar contatos
    contatos = get_contatos_aprovados(conn)
    if not contatos:
        log.warning("Nenhum contato aprovado para enviar alertas")
        conn.close()
        return

    log.info(f"Enviando para {len(contatos)} contato(s)...")

    # Enviar
    enviados = 0
    for numero in contatos:
        enviar_whatsapp(numero, mensagem)
        enviados += 1

    # Registrar como enviados
    for a in alertas_novos:
        registrar_alerta(conn, a['hash'], a['tipo'], a['msg'], enviados)

    conn.close()
    log.info(f"Concluído: {len(alertas_novos)} alertas enviados para {enviados} contatos")


if __name__ == '__main__':
    main()
