"""
NOVAS TOOLS AGROBR — Integrar no api_agro.py
=============================================

3 blocos pra copiar:
  1. TOOL DEFINITIONS — adicionar na lista `tools` do messages API call
  2. HANDLER FUNCTIONS — adicionar antes do handler principal
  3. TOOL DISPATCH — adicionar no if/elif do tool_name

Depois de integrar, o agente responde perguntas como:
  "como tá a safra da soja?"
  "produção de milho em MG?"
  "tendência do café último mês?"
  "exportações de soja 2025?"
  "crédito rural pra milho?"
"""

# ============================================================
# BLOCO 1: TOOL DEFINITIONS
# Adicionar estes dicts na lista `tools` existente
# ============================================================

TOOLS_AGROBR = [
    {
        "name": "consultar_safra",
        "description": (
            "Consulta a estimativa de safra CONAB para um produto agrícola. "
            "Retorna dados por UF: área plantada (mil ha), área colhida (mil ha), "
            "produtividade (kg/ha) e produção (mil ton). "
            "Disponível para: soja, milho, arroz, feijão, trigo, algodão, sorgo, amendoim."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "produto": {
                    "type": "string",
                    "description": "Nome do produto (ex: soja, milho, trigo)"
                },
                "uf": {
                    "type": "string",
                    "description": "Sigla do estado (ex: MG, MT, PR). Opcional, sem filtro retorna todas UFs."
                },
            },
            "required": ["produto"],
        },
    },
    {
        "name": "consultar_producao",
        "description": (
            "Consulta a produção anual de um produto agrícola (IBGE/PAM). "
            "Retorna dados históricos por UF: área colhida, quantidade produzida, "
            "rendimento e valor da produção. "
            "Disponível para: soja, milho, café, arroz, feijão, trigo, algodão, cana-de-açúcar, laranja."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "produto": {
                    "type": "string",
                    "description": "Nome do produto (ex: soja, milho, café)"
                },
                "uf": {
                    "type": "string",
                    "description": "Sigla do estado (ex: MG, GO). Opcional."
                },
                "ano": {
                    "type": "integer",
                    "description": "Ano específico. Opcional, sem filtro retorna últimos 5 anos."
                },
            },
            "required": ["produto"],
        },
    },
    {
        "name": "consultar_historico_preco",
        "description": (
            "Consulta o histórico de preços diários de um produto (CEPEA). "
            "Retorna série temporal com data, valor, praça e variação. "
            "Útil para tendências e comparação de preços ao longo do tempo. "
            "Disponível para: soja, milho, café, boi, trigo, arroz, algodão, açúcar, etanol, frango, suíno, leite."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "produto": {
                    "type": "string",
                    "description": "Nome do produto (ex: soja, café, boi)"
                },
                "dias": {
                    "type": "integer",
                    "description": "Quantos dias pra trás consultar. Padrão: 15. Max: 90."
                },
            },
            "required": ["produto"],
        },
    },
    {
        "name": "consultar_exportacao",
        "description": (
            "Consulta dados de exportação brasileira de produtos agrícolas (ComexStat). "
            "Retorna volume (kg) e valor (USD) por ano/mês. "
            "Disponível para: soja, milho, café, algodão, açúcar, carne bovina, carne de frango."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "produto": {
                    "type": "string",
                    "description": "Nome do produto (ex: soja, café)"
                },
                "ano": {
                    "type": "integer",
                    "description": "Ano específico. Opcional, sem filtro retorna últimos 3 anos."
                },
            },
            "required": ["produto"],
        },
    },
    {
        "name": "consultar_credito_rural",
        "description": (
            "Consulta dados de crédito rural do Banco Central (SICOR). "
            "Retorna valor total e quantidade de contratos por UF e ano. "
            "Disponível para: soja, milho, café, arroz, feijão, trigo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "produto": {
                    "type": "string",
                    "description": "Nome do produto (ex: soja, milho)"
                },
                "uf": {
                    "type": "string",
                    "description": "Sigla do estado. Opcional."
                },
            },
            "required": ["produto"],
        },
    },
]


# ============================================================
# BLOCO 2: HANDLER FUNCTIONS
# Adicionar estas funções no api_agro.py (antes do handler principal)
# ============================================================

def tool_consultar_safra(produto: str, uf: str = None) -> str:
    """Consulta safra CONAB no MySQL."""
    import mysql.connector
    conn = mysql.connector.connect(
        host="199.167.147.66",
        user="techobco_agropecuaria",
        password="@precisao2203",
        database="techobco_agropecuaria",
    )
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT produto, safra, uf, area_plantada, area_colhida,
               produtividade, producao, levantamento, fonte, atualizado_em
        FROM safra_conab
        WHERE produto LIKE %s
    """
    params = [f"%{produto}%"]

    if uf:
        query += " AND uf = %s"
        params.append(uf.upper())

    query += " ORDER BY safra DESC, producao DESC LIMIT 30"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if not rows:
        return f"Sem dados de safra para '{produto}'" + (f" em {uf}" if uf else "") + ". Tente: soja, milho, arroz, feijão, trigo, algodão."

    # Formata resultado
    safra = rows[0]["safra"]
    levantamento = rows[0].get("levantamento", "")
    atualizado = rows[0]["atualizado_em"].strftime("%d/%m/%Y") if rows[0].get("atualizado_em") else ""

    linhas = [f"SAFRA {safra} — {produto.upper()} (CONAB, {levantamento})"]
    linhas.append(f"Atualizado: {atualizado}")
    linhas.append("")

    total_prod = 0
    total_area = 0
    for r in rows:
        uf_row = r.get("uf") or "BR"
        prod = r.get("producao") or 0
        area = r.get("area_plantada") or 0
        produtiv = r.get("produtividade") or 0
        total_prod += float(prod)
        total_area += float(area)
        linhas.append(f"{uf_row}: {float(prod):,.1f} mil ton | {float(area):,.1f} mil ha | {float(produtiv):,.0f} kg/ha")

    if len(rows) > 1:
        linhas.append(f"\nTOTAL: {total_prod:,.1f} mil ton em {total_area:,.1f} mil ha")

    return "\n".join(linhas)


def tool_consultar_producao(produto: str, uf: str = None, ano: int = None) -> str:
    """Consulta produção IBGE no MySQL."""
    import mysql.connector
    conn = mysql.connector.connect(
        host="199.167.147.66",
        user="techobco_agropecuaria",
        password="@precisao2203",
        database="techobco_agropecuaria",
    )
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT produto, ano, uf, area_colhida, quantidade,
               rendimento, valor_producao, fonte, atualizado_em
        FROM producao_ibge
        WHERE produto LIKE %s
    """
    params = [f"%{produto}%"]

    if uf:
        query += " AND uf = %s"
        params.append(uf.upper())

    if ano:
        query += " AND ano = %s"
        params.append(ano)
    else:
        query += " AND ano >= YEAR(CURDATE()) - 5"

    query += " ORDER BY ano DESC, quantidade DESC LIMIT 30"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if not rows:
        return f"Sem dados de produção para '{produto}'" + (f" em {uf}" if uf else "") + ". Tente: soja, milho, café, arroz, trigo."

    linhas = [f"PRODUCAO {produto.upper()} (IBGE/PAM)"]
    linhas.append("")

    ano_atual = None
    for r in rows:
        if r["ano"] != ano_atual:
            ano_atual = r["ano"]
            linhas.append(f"--- {ano_atual} ---")
        uf_row = r.get("uf") or "BR"
        qtd = r.get("quantidade") or 0
        area = r.get("area_colhida") or 0
        valor = r.get("valor_producao") or 0
        linhas.append(f"{uf_row}: {float(qtd):,.0f} ton | {float(area):,.0f} ha | R$ {float(valor):,.0f}")

    return "\n".join(linhas)


def tool_consultar_historico_preco(produto: str, dias: int = 15) -> str:
    """Consulta histórico de preços CEPEA no MySQL."""
    import mysql.connector
    conn = mysql.connector.connect(
        host="199.167.147.66",
        user="techobco_agropecuaria",
        password="@precisao2203",
        database="techobco_agropecuaria",
    )
    cursor = conn.cursor(dictionary=True)

    dias = min(max(dias, 5), 90)

    cursor.execute(
        """SELECT produto, praca, data_ref, valor, unidade, fonte
           FROM preco_historico
           WHERE produto LIKE %s
             AND data_ref >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
           ORDER BY data_ref DESC
           LIMIT 60""",
        (f"%{produto}%", dias),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if not rows:
        return f"Sem histórico de preço para '{produto}' nos últimos {dias} dias. Tente: soja, milho, café, boi."

    # Calcula variação
    primeiro = float(rows[-1]["valor"])
    ultimo = float(rows[0]["valor"])
    variacao = ((ultimo - primeiro) / primeiro) * 100 if primeiro else 0
    seta = "alta" if variacao > 0 else ("queda" if variacao < 0 else "estável")
    unidade = rows[0].get("unidade") or ""
    praca = rows[0].get("praca") or ""

    linhas = [f"HISTORICO {produto.upper()} — últimos {dias} dias ({praca})"]
    linhas.append(f"Tendência: {seta} de {abs(variacao):.1f}%")
    linhas.append(f"Atual: R$ {ultimo:,.2f}/{unidade} | Início período: R$ {primeiro:,.2f}/{unidade}")
    linhas.append("")

    for r in rows[:15]:  # Mostra até 15 pontos
        data = r["data_ref"].strftime("%d/%m") if hasattr(r["data_ref"], "strftime") else str(r["data_ref"])
        linhas.append(f"{data}: R$ {float(r['valor']):,.2f}")

    if len(rows) > 15:
        linhas.append(f"... +{len(rows) - 15} registros anteriores")

    return "\n".join(linhas)


def tool_consultar_exportacao(produto: str, ano: int = None) -> str:
    """Consulta exportações ComexStat no MySQL."""
    import mysql.connector
    conn = mysql.connector.connect(
        host="199.167.147.66",
        user="techobco_agropecuaria",
        password="@precisao2203",
        database="techobco_agropecuaria",
    )
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT produto, ano, mes, peso_kg, valor_usd, pais_destino, fonte
        FROM exportacao
        WHERE produto LIKE %s
    """
    params = [f"%{produto}%"]

    if ano:
        query += " AND ano = %s"
        params.append(ano)
    else:
        query += " AND ano >= YEAR(CURDATE()) - 3"

    query += " ORDER BY ano DESC, mes DESC LIMIT 50"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if not rows:
        return f"Sem dados de exportação para '{produto}'. Tente: soja, milho, café, açúcar, carne bovina."

    linhas = [f"EXPORTACOES {produto.upper()} (ComexStat)"]
    linhas.append("")

    # Agrupa por ano
    por_ano = {}
    for r in rows:
        a = r["ano"]
        if a not in por_ano:
            por_ano[a] = {"peso": 0, "valor": 0, "meses": 0}
        por_ano[a]["peso"] += float(r.get("peso_kg") or 0)
        por_ano[a]["valor"] += float(r.get("valor_usd") or 0)
        por_ano[a]["meses"] += 1

    for a in sorted(por_ano.keys(), reverse=True):
        d = por_ano[a]
        peso_mt = d["peso"] / 1_000_000  # kg para mil ton
        valor_mi = d["valor"] / 1_000_000  # USD para milhões
        linhas.append(f"{a}: {peso_mt:,.1f} mil ton | US$ {valor_mi:,.1f} milhões ({d['meses']} meses)")

    return "\n".join(linhas)


def tool_consultar_credito_rural(produto: str, uf: str = None) -> str:
    """Consulta crédito rural BCB/SICOR no MySQL."""
    import mysql.connector
    conn = mysql.connector.connect(
        host="199.167.147.66",
        user="techobco_agropecuaria",
        password="@precisao2203",
        database="techobco_agropecuaria",
    )
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT produto, ano, uf, valor, qtd_contratos, fonte
        FROM credito_rural
        WHERE produto LIKE %s
    """
    params = [f"%{produto}%"]

    if uf:
        query += " AND uf = %s"
        params.append(uf.upper())

    query += " ORDER BY ano DESC, valor DESC LIMIT 30"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if not rows:
        return f"Sem dados de crédito rural para '{produto}'" + (f" em {uf}" if uf else "") + ". Tente: soja, milho, café."

    linhas = [f"CREDITO RURAL {produto.upper()} (BCB/SICOR)"]
    linhas.append("")

    ano_atual = None
    for r in rows:
        if r["ano"] != ano_atual:
            ano_atual = r["ano"]
            linhas.append(f"--- {ano_atual} ---")
        uf_row = r.get("uf") or "BR"
        valor = float(r.get("valor") or 0)
        contratos = r.get("qtd_contratos") or 0
        if valor >= 1_000_000:
            valor_fmt = f"R$ {valor / 1_000_000:,.1f} mi"
        elif valor >= 1_000:
            valor_fmt = f"R$ {valor / 1_000:,.1f} mil"
        else:
            valor_fmt = f"R$ {valor:,.2f}"
        linhas.append(f"{uf_row}: {valor_fmt} | {contratos:,} contratos")

    return "\n".join(linhas)


# ============================================================
# BLOCO 3: TOOL DISPATCH
# Adicionar estes elif no handler de tools do api_agro.py
# ============================================================

"""
# No trecho onde você faz o dispatch das tools, adicionar:

elif tool_name == "consultar_safra":
    produto = tool_input.get("produto", "")
    uf = tool_input.get("uf")
    result = tool_consultar_safra(produto, uf)

elif tool_name == "consultar_producao":
    produto = tool_input.get("produto", "")
    uf = tool_input.get("uf")
    ano = tool_input.get("ano")
    result = tool_consultar_producao(produto, uf, ano)

elif tool_name == "consultar_historico_preco":
    produto = tool_input.get("produto", "")
    dias = tool_input.get("dias", 15)
    result = tool_consultar_historico_preco(produto, dias)

elif tool_name == "consultar_exportacao":
    produto = tool_input.get("produto", "")
    ano = tool_input.get("ano")
    result = tool_consultar_exportacao(produto, ano)

elif tool_name == "consultar_credito_rural":
    produto = tool_input.get("produto", "")
    uf = tool_input.get("uf")
    result = tool_consultar_credito_rural(produto, uf)
"""
