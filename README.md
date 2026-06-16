# 🌾 Painel do Produtor — AI-Powered Agricultural Assistant

> WhatsApp chatbot that provides real-time agricultural market data to Brazilian farmers using Claude AI (tool-use), 8 automated scrapers, and 140+ price quotes from 4 wholesale markets.

## What It Does

A farmer sends a WhatsApp message like `! soybean price` and gets instant data from official sources.

### Features

- **140+ prices** from 4 Brazilian wholesale markets (CEASA-MG, Curitiba, CEAGESP, Campinas)
- **10 AI tools** powered by Claude with tool-use for natural language queries
- **7-day weather** for 34 agricultural municipalities
- **Crop estimates** from CONAB (national supply company)
- **Price trends** with 15-day CEPEA series
- **Export data** from ComexStat
- **Production data** from IBGE
- **Proactive alerts** for price spikes (>2%) and extreme weather
- **Admin panel** with contact management and alert toggles

## Tech Stack

- Python 3.12, FastAPI, Claude Sonnet 4.6 (Anthropic tool-use)
- MySQL, Evolution API v1.8.2 (Docker/WhatsApp)
- 8 cron jobs (CEPEA, CEASA-MG, CEASA Curitiba, CEAGESP, CONAB, IBGE, OpenMeteo, Canal Rural)

## Example Interactions

| Farmer asks | Bot responds |
|---|---|
| `! soybean price` | Soja: R$ 129.85/sc 60kg — CEPEA |
| `! pitaya price` | Pitaya: R$ 18.75/kg — CEASA Curitiba |
| `! weather Pitangui` | 7-day forecast with rain, temp, wind |
| `! soy harvest` | CONAB: 140M tons, top 5 states |
| `! avocado SP vs BH` | CEAGESP R\.87, Campinas R\.00, BH R\.66 |
| `! dollar today` | Buy R\.077 / Sell R\.080 (+0.32%) |

## Quick Start

1. Clone and configure:
```bash
git clone https://github.com/TecHob/painel-produtor.git
cp config.env.example config.env
# Edit config.env with your credentials
```

2. Install and run:
```bash
pip install fastapi uvicorn pymysql anthropic requests beautifulsoup4
python3 api_agro.py
```

## Context

Built by **Inova Precisao Agrotecnologia** for small/medium Brazilian farmers. 85% of Brazilian farmers use WhatsApp daily — this bot brings real-time market data to their pocket.

## License

MIT

---
*Built in Pitangui, Minas Gerais, Brazil*
