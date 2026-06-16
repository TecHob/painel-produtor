#!/usr/bin/env python3
"""
Fix: Adiciona endpoints admin + auto-save de LIDs pendentes ao api_agro.py
Rodar: python3 /tmp/fix_admin.py
"""

with open('/opt/painel-produtor/api_agro.py', 'r') as f:
    code = f.read()

# 1. SUBSTITUIR o bloco de auto-registro por auto-save de LID pendente
old_auto = '''            # Auto-registro: tentar achar o número via Evolution API
            log.info(f'  📱 Auto-registro: tentando resolver LID {numero_log}')
            try:
                # Buscar número via onWhatsApp da Evolution API
                push_name = data.get('pushName', 'Usuário')
                # Tentar enviar direto pelo LID (Evolution v1.8.2 pode não suportar)
                # Alternativa: buscar na API de contatos
                evo_r = requests.post(
                    f"{EVOLUTION_URL}/chat/whatsappNumbers/{EVOLUTION_INST}",
                    headers={'apikey': EVOLUTION_KEY, 'Content-Type': 'application/json'},
                    json={"numbers": [remote_jid]},
                    timeout=5
                )
                if evo_r.status_code == 200:
                    evo_data = evo_r.json()
                    log.info(f'  📱 Evolution response: {str(evo_data)[:200]}')
                    # Tentar extrair o número real
                    if isinstance(evo_data, list) and len(evo_data) > 0:
                        found = evo_data[0]
                        jid_found = found.get('jid', '')
                        if '@s.whatsapp.net' in jid_found:
                            num_found = jid_found.replace('@s.whatsapp.net', '')
                            # Registrar automaticamente
                            conn_wp2 = get_conn()
                            with conn_wp2.cursor() as cur2:
                                cur2.execute(
                                    'INSERT INTO whatsapp_contatos (lid, numero, nome) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE numero=VALUES(numero), nome=VALUES(nome)',
                                    (lid_key, num_found, push_name)
                                )
                            conn_wp2.commit()
                            conn_wp2.close()
                            log.info(f'  ✅ Auto-registrado: {lid_key} -> {num_found} ({push_name})')
                            numero = num_found
                            # Não retorna — continua pra processar a mensagem normalmente
                        else:
                            log.info(f'  ❌ Não conseguiu resolver LID')
                            return {'status': 'needs_registration'}
                    else:
                        log.info(f'  ❌ Evolution retornou vazio')
                        return {'status': 'needs_registration'}
                else:
                    log.info(f'  ❌ Evolution status {evo_r.status_code}: {evo_r.text[:100]}')
                    return {'status': 'needs_registration'}
            except Exception as e:
                log.warning(f'  ❌ Erro auto-registro: {e}')
                return {'status': 'needs_registration'}'''

new_auto = '''            # Auto-save: salvar LID como pendente pra aprovar no painel
            push_name = data.get('pushName', 'Desconhecido')
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
            return {'status': 'pending_approval'}'''

code = code.replace(old_auto, new_auto)

# 2. Também tratar contatos bloqueados
old_found = '''                    numero = row['numero']
                    log.info(f'  🔗 LID {lid_key} -> {numero}')'''

new_found = '''                    if row.get('status') == 'bloqueado':
                        log.info(f'  🚫 LID {lid_key} BLOQUEADO')
                        return {'status': 'blocked'}
                    if row.get('status') == 'pendente' or not row.get('numero'):
                        log.info(f'  ⏳ LID {lid_key} ainda PENDENTE')
                        return {'status': 'pending'}
                    numero = row['numero']
                    log.info(f'  🔗 LID {lid_key} -> {numero}')'''

code = code.replace(old_found, new_found)

# 3. ADICIONAR endpoints admin ANTES do main
old_main = '''# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════'''

new_main = '''# ═══════════════════════════════════════════════════════════════
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
            for r in rows:
                for k, v in r.items():
                    if hasattr(v, 'isoformat'): r[k] = v.isoformat()
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
        # Enviar boas-vindas
        try:
            enviar_whatsapp(numero, f'🌾 Olá {nome}! Você foi aprovado no Painel do Produtor.\\n\\nDigite ! seguido da sua pergunta:\\n\\n! Preço da soja?\\n! Vai chover em Pitangui?\\n! Últimas notícias do agro')
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
                    <button class="btn btn-block" onclick="bloquear('${c.lid}')">Bloquear</button>
                ` : ''}
                ${c.status === 'bloqueado' ? `
                    <span style="color:#ef4444">✗ Bloqueado</span>
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

function toast(msg, color) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.style.background = color || '#4ade80';
    t.style.color = color === '#ef4444' ? '#fff' : '#000';
    t.style.display = 'block';
    setTimeout(() => t.style.display = 'none', 3000);
}

load();
setInterval(load, 15000); // Atualiza a cada 15s
</script>
</body>
</html>"""

from fastapi.responses import HTMLResponse

@app.get('/admin', response_class=HTMLResponse)
def admin_page():
    return ADMIN_HTML


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════'''

code = code.replace(old_main, new_main)

# 4. Adicionar import HTMLResponse no topo se não existir
if 'HTMLResponse' not in code:
    code = code.replace(
        'from fastapi.middleware.cors import CORSMiddleware',
        'from fastapi.middleware.cors import CORSMiddleware\nfrom fastapi.responses import HTMLResponse'
    )

with open('/opt/painel-produtor/api_agro.py', 'w') as f:
    f.write(code)
print("OK - Admin panel + auto-save pendentes aplicado")
