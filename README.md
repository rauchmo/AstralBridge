# AstralBridge

A two-part system that syncs **D&D Beyond** dice rolls into **FoundryVTT** as native rolls in real time.

---

## How it works

```
D&D Beyond (browser) ──WebSocket──▶ Python Bridge ──WebSocket──▶ FoundryVTT Module
```

1. **Python Bridge** (`bridge.py`) — connects to the D&D Beyond game log WebSocket, parses incoming rolls, and forwards them to all connected Foundry clients. Ships with a web dashboard at `http://host:8765`.
2. **Foundry Module** (`/modules/astral-bridge/`) — receives rolls from the bridge and creates native Foundry chat rolls with the exact dice results from DDB.

---

## Features

- Native Foundry rolls with exact DDB dice values (d20, damage dice, modifiers)
- **Attack rolls** — target picker popup with AC comparison → ✓ HIT / ✗ MISS
- **Damage rolls** — auto-applies HP to hit targets; spell damage shows a target picker
- **Heal rolls** — target picker → automatically restores HP (capped at max)
- **Initiative rolls** — auto-sets initiative in the Foundry combat tracker
- **Automated Animations** integration — triggers AA animations on attacks, spells, and heals
- **Dice So Nice** toggle — enable/disable 3D dice animations for DDB rolls
- Spell & weapon lookup via [D&D 5e API](https://www.dnd5eapi.co/) — shows spell school, damage type, weapon properties, and flavour text in chat
- Critical hit detection with gold ✦ badge
- Multi-target support with pre-selection of manually targeted tokens
- **Web dashboard** — live log stream, roll history with detail modal, config editor, campaign switcher

---

## Requirements

### Python Bridge
- Python 3.10+
- `fastapi`, `uvicorn`, `websocket-client`, `requests`, `python-dotenv`

```bash
pip install fastapi uvicorn websocket-client requests python-dotenv
```

### Foundry Module
- FoundryVTT v12 or v13
- D&D 5e system
- Optional: [Automated Animations](https://github.com/otigon/automated-jb2a-animations), [Dice So Nice](https://gitlab.com/riccisi/foundryvtt-dice-so-nice)

---

## Setup

### 1. Configure credentials

Create a `.env` file next to `bridge.py` (or use the web dashboard):

```env
DDB_COBALT_TOKEN=eyJ...   # CobaltSession cookie from dndbeyond.com
DDB_GAME_ID=1234567       # Your campaign/game ID
DDB_USER_ID=123456789     # Your DDB user ID
```

To get your `CobaltSession` token: open D&D Beyond in your browser → DevTools → Application → Cookies → copy the value of `CobaltSession`.

### 2. Run the bridge

```bash
python bridge.py
```

Web dashboard: `http://localhost:8765`
Press `Q + Enter` to stop.

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
| Automated Animations | ✓ | Trigger AA on attacks/spells/heals |

---

## Web Dashboard

The bridge ships a built-in dashboard at `http://host:8765`:

- **Live Log** — real-time log stream with persist across restarts
- **Recent Rolls** — click any roll for full detail (dice, character info, raw JSON, resend button)
- **Campaign Switcher** — load your DDB campaigns and switch with one click
- **Config** — update credentials and restart the DDB connection without touching the terminal

---

## Character Name Matching

The Foundry module matches the character name from DDB against actor names in Foundry. If **Bichael May** rolls in DDB, the Foundry actor must also be named **Bichael May** for the speaker portrait to appear. The roll still posts to chat if no match is found.

---

## File Structure

```
bridge.py                  # Python FastAPI bridge server
templates/
  index.html               # Web dashboard UI
data/
  logs.jsonl               # Persistent log history (auto-created)
  rolls.json               # Persistent roll history (auto-created)

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
