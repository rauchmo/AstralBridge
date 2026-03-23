# AstralBridge

A two-part system that syncs **D&D Beyond** dice rolls into **FoundryVTT** as native rolls in real time.

---

## How it works

```
D&D Beyond (browser) ──WebSocket──▶ Python Bridge ──WebSocket──▶ FoundryVTT Module
```

1. **Python Bridge** (`bridge.py`, `dancing_lights.py`, `logger.py`) — connects to the D&D Beyond game log WebSocket, parses incoming rolls, and forwards them to all connected Foundry clients. Ships with a web dashboard at `http://host:8765`.
2. **Foundry Module** (`/modules/astral-bridge/`) — receives rolls from the bridge and creates native Foundry chat rolls with the exact dice results from DDB.

---

## Features

- Native Foundry rolls with exact DDB dice values (d20, damage dice, modifiers)
- **Attack rolls** — target picker popup with AC comparison → ✓ HIT / ✗ MISS; Force Hit button overrides the result
- **Damage rolls** — unified picker: pre-selects hit targets, lets you adjust, apply, or double (crit); auto-applies HP
- **Heal rolls** — target picker → automatically restores HP (capped at max)
- **Initiative rolls** — auto-sets initiative in the Foundry combat tracker
- **Floating numbers** — damage and heal amounts float over tokens via [Sequencer](https://github.com/fantasycalendar/FoundryVTT-Sequencer) (optional)
- **HP Sync** — compares Foundry max HP with D&D Beyond on first roll per session; prompts to update if different (optional, off by default)
- **Automated Animations** integration — triggers AA animations on damage
- **Dice So Nice** toggle — enable/disable 3D dice animations for DDB rolls
- Spell & weapon lookup via [D&D 5e API](https://www.dnd5eapi.co/) — shows spell school, damage type, weapon properties, and flavour text in chat
- Critical hit detection with gold ★ CRIT badge
- Multi-target support with pre-selection of manually targeted tokens
- **Web dashboard** — live log stream, roll statistics with charts, roll history with detail modal, config editor
- **Dancing Lights** — WLED LED strip integration; triggers ambient lighting effects for dice events and combat turns; includes a dashboard with Automatic/Manual mode toggle for direct LED control

---

## Requirements

### Python Bridge
- Python 3.10+ **or** Docker

### Foundry Module
- FoundryVTT v12 or v13
- D&D 5e system
- Optional: [Automated Animations](https://github.com/otigon/automated-jb2a-animations), [Dice So Nice](https://gitlab.com/riccisi/foundryvtt-dice-so-nice), [Sequencer](https://github.com/fantasycalendar/FoundryVTT-Sequencer)

---

## Setup

### 1. Configure credentials

Create a `.env` file (or use the web dashboard later):

```env
DDB_COBALT_TOKEN=eyJ...   # CobaltSession cookie from dndbeyond.com
DDB_GAME_ID=1234567       # Your campaign/game ID
DDB_USER_ID=123456789     # Your DDB user ID
```

To get your `CobaltSession` token: open D&D Beyond → DevTools → Application → Cookies → copy `CobaltSession`.

### 2. Run the bridge

**Option A — Docker (recommended):**

```bash
docker compose up -d
```

**Option B — Python directly:**

```bash
pip install fastapi uvicorn websocket-client requests python-dotenv pydantic
python3 bridge.py
```

Web dashboard: `http://localhost:8765`
Press `Q + Enter` to stop (Python mode).

### 3. Install the Foundry module

Copy the `astral-bridge` folder into your FoundryVTT `Data/modules/` directory and enable it in **Settings → Manage Modules**.

### 4. Configure the module

In FoundryVTT: **Settings → Module Settings → AstralBridge**

| Setting | Default | Description |
|---|---|---|
| Bridge WebSocket URL | `ws://localhost:8765/ws` | Address of the Python bridge |
| Roll Mode | Public Roll | How DDB rolls appear in chat |
| Auto-set Initiative | ✓ | Updates combat tracker on initiative rolls |
| Dice So Nice Animation | ✓ | Show 3D dice for DDB rolls |
| Automated Animations | ✓ | Trigger AA animations on damage |
| Damage Confirm Dialog | ✓ | Show target picker before applying damage |
| Floating Numbers | ✓ | Show floating damage/heal numbers via Sequencer |
| HP Sync | ✗ | Compare DDB max HP with Foundry on first roll per session |

---

## Web Dashboard

The bridge ships a built-in dashboard at `http://host:8765`:

- **Dashboard** — live log stream + recent rolls; click any roll for full detail (dice, raw JSON, resend)
- **Statistics** — Nat 20s, Nat 1s, average per character, roll distribution charts
- **Config** — update credentials and restart the DDB connection without touching the terminal

---

## Dancing Lights

Optional WLED LED strip integration for physical ambiance at the table. Configure under the **Dancing Lights** section of the web dashboard.

**Tabs:**

- **Dashboard** — Automatic/Manual mode toggle. In Automatic mode, dice events and combat turns drive the LEDs. In Manual mode, automatic signals are suspended and you control the strip directly via preset buttons or a custom color/effect/brightness/speed editor.
- **Events** — configure which roll events trigger animations (nat 20, nat 1, damage, heal, …) and set their color, effect, brightness, speed, and duration.
- **Ambient** — define named ambient lighting modes (e.g. Tavern, Ocean, Hell) and activate one as the background layer.
- **Config** — set the WLED device IP, total LED count, brightness, player segments, and corner preview positions.

**Layer model** (highest wins):

| Layer | Source |
|-------|--------|
| 2 — Roll | Triggered by dice events; auto-restores after duration |
| 1 — Player | Combat turn signal mapped by character name |
| 0 — Ambient | Persistent background mode |
| — | Neutral (dim blue-white) |

---

## Character Name Matching

The Foundry module matches the character name from DDB against actor names in Foundry. If **Bichael May** rolls in DDB, the Foundry actor must also be named **Bichael May** for the speaker portrait to appear. The roll still posts to chat if no match is found.

---

## File Structure

```
bridge.py                  # Python FastAPI bridge server + DDB WebSocket client
dancing_lights.py          # Dancing Lights logic, layer model, WLED API, routes
logger.py                  # Shared log buffer and persistence
Dockerfile                 # Docker image definition
docker-compose.yml         # Docker Compose config
templates/
  index.html               # Web dashboard UI
data/
  logs.jsonl               # Persistent log history (auto-created, gitignored)
  rolls.json               # Persistent roll history (auto-created, gitignored)
  dancing_lights.json      # Dancing Lights config (auto-created, gitignored)

modules/astral-bridge/
  module.json
  scripts/main.js          # Foundry module logic
  styles/astral-bridge.css
```

---

## Disclaimer

> **This project was built with the assistance of [Claude](https://claude.ai) (Anthropic), an AI coding assistant.**
>
> The majority of the code — including the Python bridge, FastAPI endpoints, FoundryVTT module logic, web dashboard UI, and all integrations — was written collaboratively with Claude Code (claude-sonnet-4-6). The project was directed, tested, and iterated on by a human, with AI generating and refining the implementation.
>
> This is not an official D&D Beyond or FoundryVTT product. It uses unofficial/internal DDB WebSocket APIs that may change without notice. Use at your own risk.

---

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE) for details.
