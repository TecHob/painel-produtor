# 🌾 Painel do Produtor — AI-Powered Agricultural Assistant

> WhatsApp chatbot that provides real-time agricultural market data to Brazilian farmers using Claude AI (tool-use), 8 automated scrapers, and 140+ price quotes from 4 wholesale markets.

![Python](https://img.shields.io/badge/Python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green)
![Claude AI](https://img.shields.io/badge/Claude_AI-Sonnet_4.6-purple)
![License](https://img.shields.io/badge/License-MIT-yellow)

## 🎯 What It Does

A Brazilian farmer sends a WhatsApp message like `! soybean price` and gets an instant response with real-time data from official sources — no app download, no login, just WhatsApp.

### Key Features

- **140+ commodity & produce prices** from 4 Brazilian wholesale markets (CEASA-MG, CEASA Curitiba, CEAGESP/SP, CEASA Campinas/SP)
- **10 AI tools** powered by Claude (Anthropic) with tool-use for natural language queries
- **7-day weather forecasts** for 34 agricultural municipalities
- **Crop estimates** from CONAB (Brazilian National Supply Company)
- **Historical price trends** with CEPEA daily series
- **Export data** from ComexStat (Brazilian foreign trade)
- **Production data** from IBGE (Brazilian Institute of Geography and Statistics)
- **Proactive alerts** — push notifications for price spikes (>2%) and extreme weather (frost, heavy rain)
- **Admin panel** — web-based contact management with per-user alert toggles
- **Smart media handling** — silently ignores audio/images, shows interactive menu on `!`

## 📊 Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│  WhatsApp    │────▶│  Evolution API    │────▶│  FastAPI     │
│  (farmer)    │◀────│  (v1.8.2 Docker)  │◀────│  (port 5056) │
└─────────────┘     └──────────────────┘     └──────┬──────┘
                                                     │
                              ┌───────────────────────┤
                              │                       │
                        ┌─────▼──────┐         ┌─────▼──────┐
                        │ Claude AI  │         │   MySQL    │
                        │ (10 tools) │         │ (14 tables)│
                        └────────────┘         └─────▲──────┘
                                                     │
                    ┌────────────────────────────────┤
                    │           8 Scrapers            │
                    ├────────────────────────────────┤
                    │ CEPEA (commodities)             │
                    │ CEASA-MG (48 produce items)     │
                    │ CEASA Curitiba (39 items)       │
                    │ 3-CEASA fruits (41 items)       │
                    │ agrobr (CONAB+IBGE+exports)     │
                    │ OpenMeteo (34 municipalities)   │
                    │ Canal Rural RSS (news)          │
                    │ Proactive alerts (price+weather)│
                    └────────────────────────────────┘
```

## 💬 Example Interactions

| Farmer asks | Bot responds |
|---|---|
| `! soybean price` | 🌾 Soja: R$ 129.85/sc 60kg (stable) — CEPEA |
| `! pitaya price` | 🌵 Pitaya: R$ 18.75/kg — CEASA Curitiba |
| `! weather in Pitangui` | 🌧️ 7-day forecast with rain probability, temp, wind |
| `! soybean harvest` | 📊 CONAB 9th survey: 140M tons, top 5 states by production |
| `! coffee trend` | 📈 15-day CEPEA series: +0.3% trend, R$1,416/bag |
| `! avocado in SP and BH` | 🥑 CEAGESP R$5.87, Campinas R$6.00, BH R$1.66 |
| `! dollar today` | 💵 Buy R$5.077 / Sell R$5.080 (+0.32%) |
| `!` (empty) | 🌾 Interactive menu with all available commands |
| (sends audio) | Silently ignored (zero API cost) |

## 🛠️ Tech Stack

- **Backend**: Python 3.12, FastAPI, uvicorn
- **AI**: Claude Sonnet 4.6 (Anthropic) with tool-use (10 tools)
- **Database**: MySQL (remote, 14 tables, 140+ price records)
- **WhatsApp**: Evolution API v1.8.2 (Docker, Baileys)
- **Data Sources**: CEPEA, CEASA-MG, CEASA Curitiba, CEAGESP, Notícias Agrícolas, CONAB, IBGE, ComexStat, OpenMeteo, Canal Rural RSS
- **Automation**: 8 cron jobs (scrapers + alerts)
- **Admin**: Web panel with contact management and alert toggles

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- MySQL database
- Docker (for Evolution API)
- Anthropic API key

### Setup

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/painel-produtor.git
cd painel-produtor

# Configure
cp config.env.example config.env
# Edit config.env with your credentials

# Install dependencies
pip install fastapi uvicorn pymysql anthropic requests beautifulsoup4

# Start Evolution API (WhatsApp)
docker run -d --name evolution-api \
  -p 8080:8080 \
  -e AUTHENTICATION_API_KEY=your-key \
  atendai/evolution-api:v1.8.2

# Run the API
python3 api_agro.py

# Run scrapers (populate database first)
python3 scraper_clima.py
python3 scraper_agrobr.py
python3 scraper_frutas_ceasas.py
python3 scraper_ceasa_curitiba.py
```

### Cron Schedule
```
*/2 * * * *   Watchdog (ensures API is running)
0 */3 * * *   Weather data (34 municipalities)
0 6,18 * * *  agrobr data (CONAB + IBGE + exports)
0 */2 * * *   News RSS
30 */6 * * *  Fruit prices (3 CEASAs)
0 8,14 * * *  CEASA Curitiba (pitaya + 39 items)
30 7,19 * * * Proactive alerts (price + weather)
```

## 📱 Admin Panel

Web-based dashboard for managing WhatsApp contacts:

- Approve/block/unblock contacts
- Toggle push alerts per contact (🔔/🔕)
- Real-time stats (pending, approved, blocked, alert-enabled)

## 📈 Data Coverage

| Source | Products | Update Frequency |
|---|---|---|
| CEPEA (commodities) | 12 | Every 6h |
| CEASA-MG (produce) | 48 | Every 6h |
| CEASA Curitiba (exotic+general) | 39 | 8am + 2pm |
| 3-CEASA fruits (Campinas+BH+CEAGESP) | 41 | Every 6h |
| Weather (OpenMeteo) | 34 municipalities | Every 3h |
| CONAB crop estimates | 4 crops × 27 states | 2x/day |
| IBGE production | 9 crops × 5 years | 2x/day |
| ComexStat exports | 7 products | 2x/day |

## 🔒 Security

- API keys stored in `config.env` (chmod 600, not in code)
- WhatsApp contacts require approval before bot responds
- Bot ignores all messages without `!` prefix (zero unwanted API calls)
- Media (audio/images) silently ignored
- Admin messages (fromMe) blocked except `!add`

## 🌍 Context

Built for **Inova Precisão Agrotecnologia**, a Brazilian agtech startup focused on small and medium-sized farmers. In Brazil, 85% of farmers use WhatsApp daily but lack access to real-time market data. This bot bridges that gap — no app needed, just send a message.

## 📄 License

MIT

---

*Built with ❤️ in Pitangui, Minas Gerais, Brazil*
