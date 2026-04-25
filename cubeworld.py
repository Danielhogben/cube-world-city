#!/usr/bin/env python3
"""
🎮 Cube World City — Living Simulation
Stick people walk around a city, make friends, become rivals,
get hungry, sleep, work, and help you with tasks.

Usage:
    python3 cubeworld.py              # Auto-detect AI
    python3 cubeworld.py --local      # Ollama
    python3 cubeworld.py --cloud      # Cloud APIs
"""

import argparse
import atexit
import json
import os
import random
import select
import shutil
import sys
import termios
import threading
import time
import tty
import urllib.request
from typing import Optional, List, Dict, Any, Tuple, Set
from concurrent.futures import ThreadPoolExecutor, as_completed

# ═══════════════════════════════════════════════════════════════════════════════
#  🎨 Palette
# ═══════════════════════════════════════════════════════════════════════════════
COLORS = {
    "red": "\033[38;5;196m", "blue": "\033[38;5;27m", "green": "\033[38;5;46m",
    "yellow": "\033[38;5;226m", "orange": "\033[38;5;208m", "pink": "\033[38;5;205m",
    "cyan": "\033[38;5;51m", "white": "\033[38;5;255m", "black": "\033[38;5;232m",
    "grey": "\033[38;5;245m", "darkgrey": "\033[38;5;240m", "brown": "\033[38;5;130m",
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
}
BG = {
    "grass": "\033[48;5;28m", "water": "\033[48;5;24m", "road": "\033[48;5;240m",
    "sand": "\033[48;5;180m", "reset": "\033[0m",
}


def c(name: str, text: str) -> str:
    return f"{COLORS.get(name, '')}{text}{COLORS['reset']}"


def bg(name: str, text: str) -> str:
    return f"{BG.get(name, '')}{text}{BG['reset']}"


# ═══════════════════════════════════════════════════════════════════════════════
#  🤖 AI Backend
# ═══════════════════════════════════════════════════════════════════════════════

class AIBackend:
    def __init__(self, mode: str = "auto"):
        self.backend = self._detect(mode)

    def _detect(self, mode: str) -> str:
        if mode == "local":
            return "ollama"
        if mode == "cloud":
            return self._first_cloud() or "openrouter"
        if self._ollama_available():
            return "ollama"
        return self._first_cloud() or "ollama"

    def _first_cloud(self) -> Optional[str]:
        for p in ["openrouter", "groq", "cohere"]:
            val = os.getenv(f"{p.upper()}_API_KEY", "").strip().lower()
            if val and val not in ("", "dummy", "none", "null", "your_api_key"):
                return p
        return None

    def _ollama_available(self) -> bool:
        try:
            with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET"), timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def _post(self, url: str, data: Dict, headers: Optional[Dict] = None) -> Dict:
        req = urllib.request.Request(url, data=json.dumps(data).encode(), method="POST", headers={"Content-Type": "application/json", **(headers or {})})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode())

    def chat(self, messages: List[Dict], max_tokens: int = 400) -> str:
        try:
            if self.backend == "ollama":
                return self._post("http://127.0.0.1:11434/api/chat", {"model": os.getenv("CUBEWORLD_MODEL", "llama3.2:1b"), "messages": messages, "stream": False, "options": {"temperature": 0.8, "num_predict": max_tokens}}).get("message", {}).get("content", "...")
            elif self.backend == "openrouter":
                return self._post("https://openrouter.ai/api/v1/chat/completions", {"model": os.getenv("CUBEWORLD_CLOUD_MODEL", "deepseek/deepseek-chat"), "messages": messages, "temperature": 0.8, "max_tokens": max_tokens}, {"Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY', '')}", "HTTP-Referer": "https://localhost", "X-Title": "CubeWorldCLI"})["choices"][0]["message"]["content"]
            elif self.backend == "groq":
                return self._post("https://api.groq.com/openai/v1/chat/completions", {"model": os.getenv("CUBEWORLD_CLOUD_MODEL", "llama-3.1-8b-instant"), "messages": messages, "temperature": 0.8, "max_tokens": max_tokens}, {"Authorization": f"Bearer {os.getenv('GROQ_API_KEY', '')}"})["choices"][0]["message"]["content"]
            elif self.backend == "cohere":
                return self._post("https://api.cohere.ai/compatibility/v1/chat/completions", {"model": os.getenv("CUBEWORLD_CLOUD_MODEL", "command-r"), "messages": messages, "temperature": 0.8, "max_tokens": max_tokens}, {"Authorization": f"Bearer {os.getenv('COHERE_API_KEY', '')}"})["choices"][0]["message"]["content"]
        except Exception as e:
            return f"*beep* {str(e)[:60]}"
        return "*beep* No AI connected"


# ═══════════════════════════════════════════════════════════════════════════════
#  🗺️ City & Location System
# ═══════════════════════════════════════════════════════════════════════════════

class Location:
    def __init__(self, id: str, name: str, x: int, y: int, w: int, h: int, color: str, icon: str, desc: str):
        self.id = id
        self.name = name
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.color = color
        self.icon = icon
        self.desc = desc
        self.occupants: Set[str] = set()

    def contains(self, gx: int, gy: int) -> bool:
        return self.x <= gx < self.x + self.w and self.y <= gy < self.y + self.h

    def center(self) -> Tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2


class RoadNetwork:
    def __init__(self):
        self.paths: Dict[Tuple[str, str], List[Tuple[int, int]]] = {}

    def add_path(self, a: str, b: str, waypoints: List[Tuple[int, int]]):
        self.paths[(a, b)] = waypoints
        self.paths[(b, a)] = list(reversed(waypoints))

    def get_path(self, a: str, b: str) -> List[Tuple[int, int]]:
        return self.paths.get((a, b), [])


class City:
    def __init__(self):
        self.locations: Dict[str, Location] = {}
        self.roads = RoadNetwork()
        self.time = 0.0  # simulated time in hours
        self.day = 1
        self._build_city()

    def _build_city(self):
        # Locations: (id, name, x, y, w, h, color, icon, desc)
        locs = [
            ("dodger_house", "Dodger's House", 2, 2, 10, 6, "red", "🏠", "A sporty red cube house"),
            ("scoop_house", "Scoop's House", 28, 2, 10, 6, "blue", "🏠", "A cozy blue cube house with a dog bed"),
            ("slim_house", "Slim's House", 54, 2, 10, 6, "green", "🏠", "A minimal green cube house"),
            ("whip_house", "Whip's House", 40, 14, 10, 6, "yellow", "🏠", "A flexible yellow cube house"),
            ("park", "Cube Park", 16, 8, 12, 8, "green", "🌳", "Trees and grass for fun"),
            ("shop", "Item Shop", 2, 12, 10, 6, "orange", "🛒", "Buy food and items"),
            ("cafe", "Pixel Cafe", 54, 12, 10, 6, "pink", "☕", "Coffee and snacks"),
            ("office", "Task Tower", 30, 14, 10, 6, "grey", "🏢", "Where work gets done"),
        ]
        for lid, name, x, y, w, h, col, icon, desc in locs:
            self.locations[lid] = Location(lid, name, x, y, w, h, col, icon, desc)

        # Road paths (waypoints between locations)
        self.roads.add_path("dodger_house", "park", [(12, 4), (14, 4), (16, 8)])
        self.roads.add_path("scoop_house", "park", [(28, 8), (24, 8), (22, 8), (20, 8), (18, 8), (16, 8)])
        self.roads.add_path("slim_house", "cafe", [(54, 8), (56, 8), (58, 12)])
        self.roads.add_path("whip_house", "office", [(40, 14), (38, 14), (36, 14), (34, 14), (32, 14), (30, 14)])
        self.roads.add_path("park", "shop", [(16, 16), (14, 16), (12, 14), (10, 14), (8, 14), (6, 14), (4, 14), (2, 12)])
        self.roads.add_path("park", "office", [(22, 16), (24, 16), (26, 16), (28, 16), (30, 14)])
        self.roads.add_path("cafe", "office", [(54, 14), (52, 14), (50, 14), (48, 14), (46, 14), (44, 14), (42, 14), (40, 14)])
        self.roads.add_path("shop", "dodger_house", [(6, 12), (6, 10), (6, 8), (6, 6), (6, 4), (4, 4), (2, 2)])
        self.roads.add_path("scoop_house", "slim_house", [(38, 4), (42, 4), (46, 4), (50, 4), (54, 2)])

    def tick(self, dt: float):
        self.time += dt
        if self.time >= 24:
            self.time -= 24
            self.day += 1

    def time_str(self) -> str:
        h = int(self.time)
        m = int((self.time - h) * 60)
        period = "AM" if h < 12 else "PM"
        h12 = h if h <= 12 else h - 12
        if h12 == 0:
            h12 = 12
        return f"Day {self.day} — {h12}:{m:02d} {period}"


# ═══════════════════════════════════════════════════════════════════════════════
#  🧍 Stick Person with Needs & Relationships
# ═══════════════════════════════════════════════════════════════════════════════

CHARACTER_DATA = {
    "dodger": {"color": "red", "item": "⚽", "prompt": "You are Dodger, a competitive stick person who lives in a red cube. You love sports and execute tasks FAST. Speak with energy. Keep responses concise."},
    "scoop": {"color": "blue", "item": "🐕", "prompt": "You are Scoop, a friendly stick person with a dog. You FETCH information and love meeting friends. Keep responses concise."},
    "slim": {"color": "green", "item": "🦯", "prompt": "You are Slim, a minimal stick person. You write clean, efficient code and hate bloat. Keep responses very concise."},
    "whip": {"color": "yellow", "item": "➰", "prompt": "You are Whip, a flexible stick person. You connect ideas creatively and adapt to any situation. Keep responses concise."},
}

NEEDS = ["energy", "hunger", "social", "fun"]


class StickPerson:
    def __init__(self, char_id: str, backend: AIBackend):
        self.char_id = char_id
        data = CHARACTER_DATA[char_id]
        self.name = char_id.capitalize()
        self.color = data["color"]
        self.item = data["item"]
        self.prompt = data["prompt"]
        self.backend = backend
        self.history = [{"role": "system", "content": self.prompt}]

        # World state
        self.gx = 0.0  # City grid x
        self.gy = 0.0  # City grid y
        self.location = ""
        self.dest_location = ""
        self.path: List[Tuple[int, int]] = []
        self.path_index = 0
        self.state = "idle"
        self.frame = 0
        self.facing_right = True
        self.state_timer = 0.0
        self.anim_timer = 0.0

        # Needs (0-100)
        self.needs = {n: random.randint(60, 100) for n in NEEDS}
        self.need_decay = {"energy": 2.0, "hunger": 3.0, "social": 2.5, "fun": 2.0}

        # Relationships (-100 to +100)
        self.relations: Dict[str, int] = {}

        # Stats
        self.level = 1
        self.xp = 0
        self.tasks_completed = 0
        self.money = 10
        self.inventory: List[str] = []

    def relation_to(self, other_id: str) -> int:
        return self.relations.get(other_id, 0)

    def set_relation(self, other_id: str, delta: int):
        self.relations[other_id] = max(-100, min(100, self.relations.get(other_id, 0) + delta))

    def relation_label(self, other_id: str) -> str:
        score = self.relation_to(other_id)
        if score >= 60:
            return c("pink", "BFF")
        elif score >= 30:
            return c("green", "Friend")
        elif score >= 10:
            return c("cyan", "Buddy")
        elif score <= -60:
            return c("red", "Enemy")
        elif score <= -30:
            return c("orange", "Rival")
        elif score <= -10:
            return c("yellow", "Annoyed")
        return c("grey", "Neutral")

    def lowest_need(self) -> str:
        return min(self.needs, key=self.needs.get)

    def need_action(self) -> Tuple[str, str]:
        """Returns (action, target_location) based on lowest need."""
        need = self.lowest_need()
        if need == "energy":
            return "sleep", f"{self.char_id}_house"
        elif need == "hunger":
            return "eat", random.choice(["shop", "cafe"])
        elif need == "social":
            return "socialize", random.choice(["park", "cafe"])
        elif need == "fun":
            return "play", random.choice(["park", "office"])
        return "idle", self.location

    def think(self, city: "City") -> str:
        """AI decides what to do next. Returns a thought string."""
        need = self.lowest_need()
        action, target = self.need_action()

        if self.location != target and not self.dest_location:
            self.dest_location = target
            self.path = city.roads.get_path(self.location, target)
            self.path_index = 0
            if self.path:
                self.state = "walk"
                return f"{self.name} wants to {action}, heading to {city.locations[target].name}"
            else:
                # No direct path, teleport (shouldn't happen with our layout)
                loc = city.locations[target]
                self.gx, self.gy = loc.center()
                self.location = target
                loc.occupants.add(self.char_id)
                return f"{self.name} arrived at {loc.name}"

        # If at destination, fulfill need
        if self.location == target and action != "idle":
            if action == "sleep":
                self.needs["energy"] = min(100, self.needs["energy"] + 30)
                self.state = "idle"
                return f"{self.name} took a nap"
            elif action == "eat":
                self.needs["hunger"] = min(100, self.needs["hunger"] + 40)
                self.state = "idle"
                return f"{self.name} grabbed a bite"
            elif action == "socialize":
                self.needs["social"] = min(100, self.needs["social"] + 25)
                self.state = "idle"
                return f"{self.name} hung out with someone"
            elif action == "play":
                self.needs["fun"] = min(100, self.needs["fun"] + 30)
                self.state = "idle"
                return f"{self.name} had some fun"

        return ""

    def update(self, dt: float, city: "City"):
        self.anim_timer += dt
        self.state_timer += dt

        # Animation frame
        if self.anim_timer > 0.25:
            self.anim_timer = 0
            self.frame = (self.frame + 1) % 4

        # Decay needs
        for n in NEEDS:
            self.needs[n] = max(0, self.needs[n] - self.need_decay[n] * dt)

        # Travel
        if self.dest_location and self.path and self.path_index < len(self.path):
            self.state = "walk"
            tx, ty = self.path[self.path_index]
            dx = tx - self.gx
            dy = ty - self.gy
            dist = (dx * dx + dy * dy) ** 0.5
            speed = 8.0 * dt
            if dist < speed:
                self.gx, self.gy = tx, ty
                self.path_index += 1
                if self.path_index >= len(self.path):
                    # Arrived
                    old_loc = city.locations.get(self.location)
                    if old_loc:
                        old_loc.occupants.discard(self.char_id)
                    self.location = self.dest_location
                    new_loc = city.locations.get(self.location)
                    if new_loc:
                        new_loc.occupants.add(self.char_id)
                        # Snap to inside location
                        cx, cy = new_loc.center()
                        self.gx, self.gy = cx, cy + 1
                    self.dest_location = ""
                    self.path = []
                    self.path_index = 0
                    self.state = "idle"
            else:
                self.gx += (dx / dist) * speed
                self.gy += (dy / dist) * speed
                self.facing_right = dx > 0
        else:
            # Wander slightly inside location
            loc = city.locations.get(self.location)
            if loc and self.state == "idle":
                cx, cy = loc.center()
                target_x = cx + random.uniform(-2, 2)
                target_y = cy + 1 + random.uniform(-1, 1)
                self.gx += (target_x - self.gx) * 2.0 * dt
                self.gy += (target_y - self.gy) * 2.0 * dt

    def chat(self, message: str, task_mode: bool = False) -> str:
        self.history.append({"role": "user", "content": message})
        max_tokens = 600 if task_mode else 300
        try:
            reply = self.backend.chat(self.history, max_tokens)
        except Exception as e:
            reply = f"*static* {str(e)[:80]}"
        self.history.append({"role": "assistant", "content": reply})
        self.xp += 10 if task_mode else 5
        if self.xp >= self.level * 25:
            self.level += 1
            self.xp = 0
        return reply

    def reset_chat(self):
        self.history = [{"role": "system", "content": self.prompt}]

    def status_line(self) -> str:
        need = self.lowest_need()
        need_val = self.needs[need]
        need_color = "green" if need_val > 50 else ("yellow" if need_val > 25 else "red")
        loc_name = self.location.replace("_", " ").title() if self.location else "Unknown"
        return (
            f"{c(self.color, self.name)} {self.item} "
            f"{c('dim', f'Lv.{self.level}')} "
            f"📍{c('cyan', loc_name[:10])} "
            f"{c(need_color, f'{need}:{int(need_val)}')} "
            f"💰{self.money}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  🌍 World Simulation
# ═══════════════════════════════════════════════════════════════════════════════

class Simulation:
    def __init__(self, backend: AIBackend):
        self.backend = backend
        self.city = City()
        self.sticks: Dict[str, StickPerson] = {}
        self.active = "dodger"
        self.tasks: List[Dict] = []
        self.events: List[str] = []
        self.think_interval = 5.0
        self.think_timer = 0.0
        self._spawn()

    def _spawn(self):
        home_map = {"dodger": "dodger_house", "scoop": "scoop_house", "slim": "slim_house", "whip": "whip_house"}
        for cid in CHARACTER_DATA:
            sp = StickPerson(cid, self.backend)
            home = home_map[cid]
            loc = self.city.locations[home]
            sp.location = home
            sp.gx, sp.gy = loc.center()
            sp.gy += 1
            loc.occupants.add(cid)
            self.sticks[cid] = sp

        # Initialize neutral relations
        for a in self.sticks:
            for b in self.sticks:
                if a != b:
                    self.sticks[a].relations[b] = random.randint(-10, 10)

    def get(self, cid: Optional[str] = None) -> StickPerson:
        return self.sticks.get(cid or self.active, self.sticks["dodger"])

    def switch(self, cid: str) -> bool:
        cid = cid.lower()
        if cid in self.sticks:
            self.active = cid
            return True
        return False

    def assign_task(self, cid: str, desc: str) -> Dict:
        stick = self.sticks.get(cid)
        if not stick:
            return {"error": f"No stick person named '{cid}'"}
        tid = f"tsk_{int(time.time() * 1000)}"
        task = {"id": tid, "cid": cid, "desc": desc, "status": "running", "result": None}
        self.tasks.append(task)

        def run():
            stick.state = "work"
            result = stick.chat(f"TASK: {desc}\n\nComplete this task. Be concise and actionable.", True)
            task["result"] = result
            task["status"] = "done"
            stick.tasks_completed += 1
            stick.state = "idle"
            self.events.append(f"{stick.name} finished a task!")

        threading.Thread(target=run, daemon=True).start()
        return task

    def collab_task(self, desc: str) -> Dict:
        tid = f"clb_{int(time.time() * 1000)}"
        task = {"id": tid, "cid": "party", "desc": desc, "status": "running", "result": None, "votes": {}}
        self.tasks.append(task)
        ids = list(self.sticks.keys())

        def run():
            for s in self.sticks.values():
                s.state = "work"
            with ThreadPoolExecutor(max_workers=len(ids)) as pool:
                futures = {
                    pool.submit(self.sticks[sid].chat, f"BRAINSTORM: {desc}\nYour angle? (2 sentences)", True): sid
                    for sid in ids
                }
                for future in as_completed(futures):
                    sid = futures[future]
                    try:
                        task["votes"][sid] = future.result()
                    except Exception as e:
                        task["votes"][sid] = f"*zap* {e}"
            synth = "slim" if "slim" in ids else ids[0]
            prompt = f"SYNTHESIZE:\n\nTASK: {desc}\n\n" + "\n\n".join(f"[{n.upper()}]: {t}" for n, t in task["votes"].items()) + "\n\nFinal answer:"
            final = self.sticks[synth].chat(prompt, True)
            task["result"] = final
            task["status"] = "done"
            for s in self.sticks.values():
                s.tasks_completed += 1
                s.state = "idle"
            self.events.append("Party collaboration complete!")

        threading.Thread(target=run, daemon=True).start()
        return task

    def interact(self, a_id: str, b_id: str):
        """Two stick people interact. Update relations."""
        a = self.sticks[a_id]
        b = self.sticks[b_id]
        score_a = a.relation_to(b_id)
        score_b = b.relation_to(a_id)

        if score_a > 30 and score_b > 30:
            # Friends!
            a.needs["social"] = min(100, a.needs["social"] + 15)
            b.needs["social"] = min(100, b.needs["social"] + 15)
            a.needs["fun"] = min(100, a.needs["fun"] + 10)
            b.needs["fun"] = min(100, b.needs["fun"] + 10)
            a.set_relation(b_id, 2)
            b.set_relation(a_id, 2)
            self.events.append(f"{a.name} and {b.name} hung out as friends!")
        elif score_a < -20 or score_b < -20:
            # Enemies!
            a.set_relation(b_id, -5)
            b.set_relation(a_id, -5)
            a.needs["social"] = max(0, a.needs["social"] - 10)
            b.needs["social"] = max(0, b.needs["social"] - 10)
            self.events.append(f"{a.name} and {b.name} had a conflict!")
        else:
            # Neutral
            a.set_relation(b_id, random.choice([-2, 2]))
            b.set_relation(a_id, random.choice([-2, 2]))
            a.needs["social"] = min(100, a.needs["social"] + 5)
            b.needs["social"] = min(100, b.needs["social"] + 5)

    def tick(self, dt: float):
        self.city.tick(dt)
        self.think_timer += dt

        for sp in self.sticks.values():
            sp.update(dt, self.city)

        # Periodic AI thinking
        if self.think_timer >= self.think_interval:
            self.think_timer = 0
            for sp in self.sticks.values():
                thought = sp.think(self.city)
                if thought:
                    self.events.append(thought)

        # Co-location interactions
        for loc in self.city.locations.values():
            occupants = list(loc.occupants)
            if len(occupants) >= 2:
                for i in range(len(occupants)):
                    for j in range(i + 1, len(occupants)):
                        if random.random() < 0.1:  # 10% chance per interval
                            self.interact(occupants[i], occupants[j])

        # Trim events
        while len(self.events) > 20:
            self.events.pop(0)

    def pending_tasks(self) -> List[Dict]:
        return [t for t in self.tasks if t["status"] == "running"]

    def completed_tasks(self) -> List[Dict]:
        return [t for t in self.tasks if t["status"] == "done"]


# ═══════════════════════════════════════════════════════════════════════════════
#  🖼️ Terminal Renderer
# ═══════════════════════════════════════════════════════════════════════════════

class Cell:
    __slots__ = ("char", "color")
    def __init__(self, char: str = " ", color: str = ""):
        self.char = char
        self.color = color


class TerminalEngine:
    def __init__(self):
        self.w, self.h = shutil.get_terminal_size()
        self.buf: List[List[Cell]] = [[Cell() for _ in range(self.w)] for _ in range(self.h)]
        self._hide_cursor()
        atexit.register(self._show_cursor)

    def _hide_cursor(self):
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()

    def _show_cursor(self):
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()

    def clear(self):
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
        self.w, self.h = shutil.get_terminal_size()
        self.buf = [[Cell() for _ in range(self.w)] for _ in range(self.h)]

    def set_cell(self, x: int, y: int, char: str, color: str = ""):
        if 0 <= x < self.w and 0 <= y < self.h and len(char) == 1:
            self.buf[y][x] = Cell(char, color)

    def draw_text(self, x: int, y: int, text: str, color: str = ""):
        for i, ch in enumerate(text):
            self.set_cell(x + i, y, ch, color)

    def draw_box(self, x: int, y: int, w: int, h: int, color: str = ""):
        for dx in range(w):
            self.set_cell(x + dx, y, "─", color)
            self.set_cell(x + dx, y + h - 1, "─", color)
        for dy in range(h):
            self.set_cell(x, y + dy, "│", color)
            self.set_cell(x + w - 1, y + dy, "│", color)
        self.set_cell(x, y, "┌", color)
        self.set_cell(x + w - 1, y, "┐", color)
        self.set_cell(x, y + h - 1, "└", color)
        self.set_cell(x + w - 1, y + h - 1, "┘", color)

    def fill_rect(self, x: int, y: int, w: int, h: int, char: str, color: str = ""):
        for dy in range(h):
            for dx in range(w):
                self.set_cell(x + dx, y + dy, char, color)

    def draw_sprite(self, x: int, y: int, sprite_lines: List[str], color: str = ""):
        for dy, line in enumerate(sprite_lines):
            for dx, ch in enumerate(line):
                if ch != " " and 0 <= x + dx < self.w and 0 <= y + dy < self.h:
                    self.set_cell(x + dx, y + dy, ch, color)

    def render(self):
        lines = []
        for y, row in enumerate(self.buf):
            line_chars = []
            current_color = ""
            for cell in row:
                cell_color_code = COLORS.get(cell.color, cell.color) if cell.color else ""
                if cell_color_code != current_color:
                    if current_color:
                        line_chars.append(COLORS["reset"])
                    if cell_color_code:
                        line_chars.append(cell_color_code)
                    current_color = cell_color_code
                line_chars.append(cell.char if cell.char else " ")
            if current_color:
                line_chars.append(COLORS["reset"])
            lines.append("".join(line_chars))
        sys.stdout.write("\033[H" + "\n".join(lines))
        sys.stdout.flush()


# ═══════════════════════════════════════════════════════════════════════════════
#  🏙️ City Renderer
# ═══════════════════════════════════════════════════════════════════════════════

class CityRenderer:
    ROAD_CHARS = {"h": "═", "v": "║", "corner": "+"}
    GROUND = {
        "park": ("░", "green"),
        "road": ("·", "darkgrey"),
        "house": ("▒", "brown"),
        "default": (" ", ""),
    }

    def __init__(self, engine: TerminalEngine):
        self.engine = engine

    def render_city(self, sim: Simulation, view_w: int, view_h: int, offset_x: int = 0, offset_y: int = 0):
        """Render the city map into the engine buffer."""
        city = sim.city

        # Ground/roads
        for y in range(view_h):
            for x in range(view_w):
                gx, gy = x + offset_x, y + offset_y
                char, color = self.GROUND["default"]
                # Check if on a road path
                for path in city.roads.paths.values():
                    for px, py in path:
                        if px == gx and py == gy:
                            char, color = self.GROUND["road"]
                            break
                self.engine.set_cell(x, y, char, color)

        # Locations
        for loc in city.locations.values():
            lx = loc.x - offset_x
            ly = loc.y - offset_y
            if lx + loc.w < 0 or ly + loc.h < 0 or lx >= view_w or ly >= view_h:
                continue

            # Location border
            for dy in range(loc.h):
                for dx in range(loc.w):
                    sx, sy = lx + dx, ly + dy
                    if 0 <= sx < view_w and 0 <= sy < view_h:
                        if dy == 0 or dy == loc.h - 1 or dx == 0 or dx == loc.w - 1:
                            self.engine.set_cell(sx, sy, "▓", loc.color)
                        else:
                            self.engine.set_cell(sx, sy, " ", "")

            # Location name
            name_x = max(0, min(view_w - len(loc.name), lx + 1))
            name_y = max(0, min(view_h - 1, ly))
            self.engine.draw_text(name_x, name_y, loc.name[:loc.w - 2], c("bold", ""))

            # Icon inside
            icon_x = lx + loc.w // 2
            icon_y = ly + loc.h // 2
            if 0 <= icon_x < view_w and 0 <= icon_y < view_h:
                self.engine.draw_text(icon_x, icon_y, loc.icon)

        # Stick people
        for cid, stick in sim.sticks.items():
            sx = int(stick.gx) - offset_x
            sy = int(stick.gy) - offset_y
            if 0 <= sx < view_w and 0 <= sy < view_h:
                # Head
                self.engine.set_cell(sx, sy, "◯", stick.color)
                # Body
                if sy + 1 < view_h:
                    self.engine.set_cell(sx, sy + 1, "│", stick.color)
                # Legs (animate)
                if sy + 2 < view_h:
                    if stick.state == "walk":
                        leg = "/" if stick.frame % 2 == 0 else "\\"
                        self.engine.set_cell(sx - 1 if stick.facing_right else sx + 1, sy + 2, leg, stick.color)
                    else:
                        self.engine.set_cell(sx - 1, sy + 2, "/", stick.color)
                        self.engine.set_cell(sx + 1, sy + 2, "\\", stick.color)
                # Item above head
                if sy - 1 >= 0:
                    self.engine.set_cell(sx, sy - 1, stick.item[0] if stick.item else " ", stick.color)
                # Status bubble
                if stick.state == "work":
                    if sx + 2 < view_w:
                        self.engine.set_cell(sx + 2, sy, "⚡", "yellow")
                elif stick.state == "idle" and random.random() < 0.3:
                    if sx - 2 >= 0:
                        self.engine.set_cell(sx - 2, sy - 1, "💭", "grey")

    def render_ui(self, sim: Simulation, view_h: int):
        """Render status panel below the city view."""
        engine = self.engine
        w = engine.w
        y = view_h + 1

        # Divider
        for x in range(w):
            engine.set_cell(x, y - 1, "─", "darkgrey")

        # Time
        engine.draw_text(2, y, sim.city.time_str(), "white")

        # Active stick status
        active = sim.get()
        engine.draw_text(2, y + 1, active.status_line())

        # Relations
        rel_y = y + 2
        rel_parts = []
        for other_id, other in sim.sticks.items():
            if other_id != active.char_id:
                rel_parts.append(f"{other.name}:{active.relation_label(other_id)}")
        engine.draw_text(2, rel_y, "Relations: " + "  ".join(rel_parts))

        # Events
        event_y = y + 4
        engine.draw_text(2, event_y, "📰 Events:", "bold")
        for i, evt in enumerate(sim.events[-5:]):
            engine.draw_text(4, event_y + 1 + i, evt[:w - 6], "dim")

        # Tasks
        task_y = event_y + 7
        engine.draw_text(2, task_y, "📋 Tasks:", "bold")
        row = 1
        for t in sim.pending_tasks():
            engine.draw_text(4, task_y + row, f"◐ [{t['cid']}] {t['desc'][:30]}", "orange")
            row += 1
        for t in sim.completed_tasks()[-3:]:
            preview = t.get("result", "")[:35].replace("\n", " ")
            engine.draw_text(4, task_y + row, f"◉ [{t['cid']}] {preview}...", "green")
            row += 1

        # Input
        input_y = engine.h - 2
        engine.draw_text(2, input_y, "> " + getattr(sim, '_input_buffer', ''), "cyan")
        hint_y = engine.h - 1
        engine.draw_text(2, hint_y, "/task /collab /switch /goto /interact /relations /new /help /quit", "dim")


# ═══════════════════════════════════════════════════════════════════════════════
#  🎮 Main Game Loop
# ═══════════════════════════════════════════════════════════════════════════════

class CubeWorldCLI:
    FPS = 8

    def __init__(self, mode: str = "auto"):
        self.backend = AIBackend(mode=mode)
        self.sim = Simulation(self.backend)
        self.engine = TerminalEngine()
        self.city_renderer = CityRenderer(self.engine)
        self.running = True
        self.messages: List[str] = []
        self._input_buffer = ""
        self._setup_terminal()

    def _setup_terminal(self):
        self._tty_ok = False
        try:
            self._old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
            self._tty_ok = True
            atexit.register(self._restore_terminal)
        except Exception:
            pass

    def _restore_terminal(self):
        if getattr(self, '_tty_ok', False):
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old_settings)
            except Exception:
                pass
        self.engine._show_cursor()

    def _read_input(self) -> Optional[str]:
        if not getattr(self, '_tty_ok', False):
            return None
        if select.select([sys.stdin], [], [], 0)[0]:
            ch = sys.stdin.read(1)
            if ch in ("\n", "\r"):
                line = self._input_buffer
                self._input_buffer = ""
                return line
            elif ch == "\x7f":
                self._input_buffer = self._input_buffer[:-1]
            elif ch == "\x03":
                self.running = False
                return None
            elif ch.isprintable():
                self._input_buffer += ch
        return None

    def draw_scene(self):
        self.engine.clear()
        w, h = self.engine.w, self.engine.h
        view_h = max(10, h - 14)

        # Render city
        self.city_renderer.render_city(self.sim, w, view_h)
        self.city_renderer.render_ui(self.sim, view_h)

        # Message overlay
        if self.messages:
            last = self.messages[-1]
            msg_y = view_h - 3
            self.engine.draw_text(2, msg_y, "╭" + "─" * (w - 6) + "╮", "white")
            lines = self._wrap_text(last, w - 8)
            for i, line in enumerate(lines[:2]):
                self.engine.draw_text(2, msg_y + 1 + i, "│ " + line.ljust(w - 6) + "│", "white")
            self.engine.draw_text(2, msg_y + 1 + min(len(lines), 2), "╰" + "─" * (w - 6) + "╯", "white")

        self.engine.render()

    def _wrap_text(self, text: str, width: int) -> List[str]:
        words = text.split()
        lines = []
        current = ""
        for word in words:
            if len(current) + len(word) + 1 <= width:
                current += (" " if current else "") + word
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines if lines else ["..."]

    def _process_command(self, cmd_line: str):
        if not cmd_line.startswith("/"):
            stick = self.sim.get()
            self.messages.append(f"You → {stick.name}: {cmd_line}")
            stick.state = "work"
            def respond():
                reply = stick.chat(cmd_line)
                self.messages.append(f"{stick.name}: {reply}")
                stick.state = "idle"
            threading.Thread(target=respond, daemon=True).start()
            return

        parts = cmd_line[1:].split(None, 1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd in ("quit", "q"):
            self.messages.append("Shutting down Cube World City...")
            self.running = False
        elif cmd == "switch":
            if self.sim.switch(args.strip().lower()):
                s = self.sim.get()
                self.messages.append(f"Now following {s.name}!")
            else:
                self.messages.append("Names: dodger, scoop, slim, whip")
        elif cmd == "goto":
            target = args.strip().lower().replace(" ", "_")
            if target in self.sim.city.locations:
                stick = self.sim.get()
                stick.dest_location = target
                stick.path = self.sim.city.roads.get_path(stick.location, target)
                stick.path_index = 0
                if stick.path:
                    stick.state = "walk"
                    self.messages.append(f"{stick.name} is walking to {self.sim.city.locations[target].name}!")
                else:
                    loc = self.sim.city.locations[target]
                    stick.gx, stick.gy = loc.center()
                    stick.gy += 1
                    stick.location = target
                    loc.occupants.add(stick.char_id)
                    self.messages.append(f"{stick.name} teleported to {loc.name}")
            else:
                locs = ", ".join(l.name for l in self.sim.city.locations.values())
                self.messages.append(f"Locations: {locs}")
        elif cmd == "interact":
            stick = self.sim.get()
            loc = self.sim.city.locations.get(stick.location)
            if loc:
                others = [o for o in loc.occupants if o != stick.char_id]
                if others:
                    target = random.choice(others)
                    self.sim.interact(stick.char_id, target)
                    self.messages.append(f"{stick.name} interacted with {self.sim.sticks[target].name}!")
                else:
                    self.messages.append("No one else is here!")
            else:
                self.messages.append("Not in a valid location")
        elif cmd == "relations":
            stick = self.sim.get()
            lines = [f"{self.sim.sticks[oid].name}: {stick.relation_label(oid)} ({stick.relation_to(oid)})" for oid in self.sim.sticks if oid != stick.char_id]
            self.messages.append("  ".join(lines))
        elif cmd == "task":
            sub = args.split(None, 1)
            if len(sub) < 2:
                self.messages.append("Usage: /task <name> <description>")
            else:
                cid, desc = sub[0].lower(), sub[1]
                task = self.sim.assign_task(cid, desc)
                self.messages.append(task.get("error") or f"Task assigned to {cid}!")
        elif cmd == "collab":
            if not args.strip():
                self.messages.append("Usage: /collab <description>")
            else:
                self.sim.collab_task(args.strip())
                self.messages.append("Party collaboration started!")
        elif cmd == "check":
            pending = self.sim.pending_tasks()
            done = self.sim.completed_tasks()
            self.messages.append(f"Running: {len(pending)} | Done: {len(done)}")
        elif cmd == "new":
            for s in self.sim.sticks.values():
                s.reset_chat()
            self.messages.append("All memories reset!")
        elif cmd in ("help", "h"):
            self.messages.append(
                "/switch <name>  /goto <location>  /interact  /relations  "
                "/task <n> <desc>  /collab <desc>  /check  /new  /quit"
            )
        else:
            self.messages.append(f"Unknown /{cmd}. Try /help")

    def run(self):
        self.messages.append("Welcome to Cube World City! Watch your stick people live their lives.")
        last_time = time.time()

        while self.running:
            now = time.time()
            dt = min(now - last_time, 0.2)
            last_time = now

            self.sim.tick(dt)
            self.sim._input_buffer = self._input_buffer
            self.draw_scene()

            line = self._read_input()
            if line is not None:
                self._process_command(line)

            sleep_time = max(0, (1.0 / self.FPS) - (time.time() - now))
            time.sleep(sleep_time)

        self.engine.clear()
        print(c("bold", "Cube World City closed. See you!"))


def main():
    parser = argparse.ArgumentParser(description="Cube World City — Living Simulation")
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--cloud", action="store_true")
    args = parser.parse_args()
    mode = "local" if args.local else ("cloud" if args.cloud else "auto")
    CubeWorldCLI(mode=mode).run()


if __name__ == "__main__":
    main()
