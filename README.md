# 🏙️ Cube World City — Living Simulation

A real-time terminal life simulation inspired by the **Mattel Cube World** toy. Four stick people live in a city, walk around, make friends, become rivals, get hungry, sleep, and help you with tasks.

![city](https://img.shields.io/badge/city-8_locations-brightgreen)
![agents](https://img.shields.io/badge/agents-4_autonomous-blue)
![ram](https://img.shields.io/badge/RAM-%3C20MB-orange)

## ✨ Features

### 🗺️ Living City
- **8 locations**: 4 houses, Park, Shop, Cafe, Office
- **Road network** connecting everything
- **Day/night cycle** with time progression
- Stick people **walk between locations** in real-time

### 🧍 Autonomous Stick People
Each character has independent AI that decides:
- Where to go based on **needs** (energy, hunger, social, fun)
- Who to interact with
- When to sleep, eat, socialize, or play

| Name | Home | Personality |
|------|------|-------------|
| **Dodger** | 🔴 Red House | Fast, sporty, competitive |
| **Scoop** | 🔵 Blue House | Friendly, loyal, loves dogs |
| **Slim** | 🟢 Green House | Minimal, precise, efficient |
| **Whip** | 🟡 Yellow House | Flexible, creative, connector |

### 💕 Friends & Enemies
- **Relationship system** (-100 to +100) between every pair
- Co-located stick people **interact automatically**
- Friends help each other, enemies cause conflicts
- Relationship labels: BFF, Friend, Rival, Enemy, Neutral

### 📋 Task System
- Assign tasks to individual stick people
- `/collab` for party-wide collaboration
- Task results saved in event log

## 🚀 Quick Start

```bash
cd ~/Desktop/cubeworld-cli
python3 cubeworld.py
```

### Force cloud APIs
```bash
python3 cubeworld.py --cloud
```

### Force local Ollama
```bash
python3 cubeworld.py --local
```

## 🎮 Commands

| Command | Action |
|---------|--------|
| *(type)* | Chat with the active stick person |
| `/switch <name>` | Follow a different character |
| `/goto <location>` | Tell active character to walk somewhere |
| `/interact` | Force interaction with someone nearby |
| `/relations` | View all relationship scores |
| `/task <name> <desc>` | Assign a task |
| `/collab <desc>` | All 4 collaborate on a task |
| `/check` | View task status |
| `/new` | Reset all memories |
| `/quit` | Exit |

### Locations you can `/goto`
- `dodger_house`, `scoop_house`, `slim_house`, `whip_house`
- `park`, `shop`, `cafe`, `office`

## 🎨 What You'll See

```
  ▓Dodger's▓                ▓Scoop's ▓                ▓Slim's H▓
  ▓        ▓                ▓        ▓                ▓        ▓
  ▓   ⚽   ▓                ▓   🐕   ▓                ▓   🦯   ▓
  ▓   ◯    ▓                ▓   ◯    ▓                ▓   ◯    ▓
  ▓▓▓▓│▓▓▓▓▓                ▓▓▓▓▓│▓▓▓▓                ▓▓▓▓│▓▓▓▓▓
     /·\        ▓Cube Park▓▓·   / \                   · ·/\
                ▓          ▓
                ▓     🌳   ▓
  ▓Item Sho▓    ▓          ▓                          ▓Pixel Ca▓
  ▓        ▓                                          ▓        ▓
────────────────────────────────────────────────────────────────
  Day 1 — 3:00 AM
  Dodger ⚽ Lv.1 📍Dodger House social:45 💰10
  Relations: Scoop:Neutral  Slim:Neutral  Whip:Neutral

  📰 Events:
  Dodger wants to eat, heading to Cafe
  Scoop and Slim hung out as friends!

  📋 Tasks:
  ◐ [dodger] Write a Python script...
  ◉ [party] Plan the weekend → Go hiking...

  > _
  /task /collab /switch /goto /interact /relations /new /help /quit
```

**Animations** (8 FPS):
- Characters walk along roads between locations
- Idle wobbling and thinking bubbles
- Working lightning bolts ⚡
- Automatic interactions when co-located

## 🔧 Setup

### Cloud Mode (~20MB RAM)
```bash
export OPENROUTER_API_KEY=sk-or-...
# or GROQ_API_KEY, COHERE_API_KEY
python3 cubeworld.py --cloud
```

### Local Ollama (~1.5GB RAM)
```bash
ollama pull llama3.2:1b
python3 cubeworld.py --local
```

## ⚙️ Environment Variables

| Variable | Description |
|----------|-------------|
| `CUBEWORLD_MODEL` | Ollama model (default: `llama3.2:1b`) |
| `CUBEWORLD_CLOUD_MODEL` | Cloud model override |
| `OPENROUTER_API_KEY` | OpenRouter key |
| `GROQ_API_KEY` | Groq key |
| `COHERE_API_KEY` | Cohere key |

## 📁 Files

```
cubeworld-cli/
├── cubeworld.py   # ~1000 lines, 43KB, pure stdlib
└── README.md
```

Zero dependencies!

## 📝 License

MIT — Build your own cube city!
