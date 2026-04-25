#!/usr/bin/env python3
"""
🎮 Cube World City — Multi-Style Edition
A living terminal simulation with pluggable visual themes:
  toy        — Mattel Cube World colorful cubes
  roguelike  — Classic ASCII dungeon crawler
  isometric  — Fake-3D isometric projection
  emoji      — Modern emoji tileset
  retro      — Green CRT phosphor monochrome
  minimal    — Clean geometric abstraction

Usage:
    python3 cubeworld.py --style toy
    python3 cubeworld.py --style retro --local
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
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, Tuple, Set
from concurrent.futures import ThreadPoolExecutor, as_completed

# ═══════════════════════════════════════════════════════════════════════════════
#  🎨 Master Palette (all styles draw from this)
# ═══════════════════════════════════════════════════════════════════════════════
COLORS = {
    "red": "\033[38;5;196m", "blue": "\033[38;5;27m", "green": "\033[38;5;46m",
    "yellow": "\033[38;5;226m", "orange": "\033[38;5;208m", "pink": "\033[38;5;205m",
    "cyan": "\033[38;5;51m", "white": "\033[38;5;255m", "black": "\033[38;5;232m",
    "grey": "\033[38;5;245m", "darkgrey": "\033[38;5;240m", "brown": "\033[38;5;130m",
    "magenta": "\033[38;5;201m", "teal": "\033[38;5;37m", "lime": "\033[38;5;118m",
    "crimson": "\033[38;5;161m", "gold": "\033[38;5;220m",
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
    "bg_black": "\033[40m", "bg_green": "\033[42m", "bg_white": "\033[47m",
}


def c(name: str, text: str = "") -> str:
    return f"{COLORS.get(name, '')}{text}{COLORS['reset']}"


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
#  🗺️ City & Simulation
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
        self.time = 8.0
        self.day = 1
        self._build()

    def _build(self):
        locs = [
            ("dodger_house", "Dodger's House", 2, 2, 10, 6, "red", "🏠", "Sporty red cube"),
            ("scoop_house", "Scoop's House", 28, 2, 10, 6, "blue", "🏠", "Cozy blue cube"),
            ("slim_house", "Slim's House", 54, 2, 10, 6, "green", "🏠", "Minimal green cube"),
            ("whip_house", "Whip's House", 40, 14, 10, 6, "yellow", "🏠", "Flexible yellow cube"),
            ("park", "Cube Park", 16, 8, 12, 8, "green", "🌳", "Trees and grass"),
            ("shop", "Item Shop", 2, 12, 10, 6, "orange", "🛒", "Buy food and items"),
            ("cafe", "Pixel Cafe", 54, 12, 10, 6, "pink", "☕", "Coffee and snacks"),
            ("office", "Task Tower", 30, 14, 10, 6, "grey", "🏢", "Where work happens"),
        ]
        for lid, name, x, y, w, h, col, icon, desc in locs:
            self.locations[lid] = Location(lid, name, x, y, w, h, col, icon, desc)

        paths = [
            ("dodger_house", "park", [(12, 4), (14, 4), (16, 8)]),
            ("scoop_house", "park", [(28, 8), (24, 8), (20, 8), (18, 8), (16, 8)]),
            ("slim_house", "cafe", [(54, 8), (56, 8), (58, 12)]),
            ("whip_house", "office", [(40, 14), (36, 14), (32, 14), (30, 14)]),
            ("park", "shop", [(16, 16), (12, 14), (8, 14), (4, 14), (2, 12)]),
            ("park", "office", [(22, 16), (26, 16), (30, 14)]),
            ("cafe", "office", [(54, 14), (50, 14), (46, 14), (42, 14), (40, 14)]),
            ("shop", "dodger_house", [(6, 12), (6, 8), (6, 4), (2, 2)]),
            ("scoop_house", "slim_house", [(38, 4), (46, 4), (54, 2)]),
        ]
        for a, b, pts in paths:
            self.roads.add_path(a, b, pts)

    def tick(self, dt: float):
        self.time += dt
        if self.time >= 24:
            self.time -= 24
            self.day += 1

    def time_str(self) -> str:
        h = int(self.time)
        m = int((self.time - h) * 60)
        period = "AM" if h < 12 else "PM"
        h12 = h if 1 <= h <= 12 else (12 if h == 0 else h - 12)
        return f"Day {self.day} — {h12}:{m:02d} {period}"


CHARACTER_DATA = {
    "dodger": {"color": "red", "item": "⚽", "prompt": "You are Dodger, a competitive stick person in a red cube. Execute tasks FAST. Speak with sporty energy. Keep responses concise."},
    "scoop": {"color": "blue", "item": "🐕", "prompt": "You are Scoop, a friendly stick person with a dog. You FETCH information. Keep responses concise."},
    "slim": {"color": "green", "item": "🦯", "prompt": "You are Slim, a minimal stick person. You write clean, efficient code. Hate bloat. Keep responses very concise."},
    "whip": {"color": "yellow", "item": "➰", "prompt": "You are Whip, a flexible stick person. You connect ideas creatively. Keep responses concise."},
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
        self.gx = 0.0
        self.gy = 0.0
        self.location = ""
        self.dest_location = ""
        self.path: List[Tuple[int, int]] = []
        self.path_index = 0
        self.state = "idle"
        self.frame = 0
        self.facing_right = True
        self.state_timer = 0.0
        self.anim_timer = 0.0
        self.needs = {n: random.randint(60, 100) for n in NEEDS}
        self.need_decay = {"energy": 2.0, "hunger": 3.0, "social": 2.5, "fun": 2.0}
        self.relations: Dict[str, int] = {}
        self.level = 1
        self.xp = 0
        self.tasks_completed = 0
        self.money = 10

    def relation_to(self, other_id: str) -> int:
        return self.relations.get(other_id, 0)

    def set_relation(self, other_id: str, delta: int):
        self.relations[other_id] = max(-100, min(100, self.relations.get(other_id, 0) + delta))

    def relation_label(self, other_id: str) -> str:
        score = self.relation_to(other_id)
        if score >= 60: return c("pink", "BFF")
        elif score >= 30: return c("lime", "Friend")
        elif score >= 10: return c("cyan", "Buddy")
        elif score <= -60: return c("crimson", "Enemy")
        elif score <= -30: return c("orange", "Rival")
        elif score <= -10: return c("yellow", "Annoyed")
        return c("grey", "Neutral")

    def lowest_need(self) -> str:
        return min(self.needs, key=self.needs.get)

    def need_action(self) -> Tuple[str, str]:
        need = self.lowest_need()
        if need == "energy": return "sleep", f"{self.char_id}_house"
        elif need == "hunger": return "eat", random.choice(["shop", "cafe"])
        elif need == "social": return "socialize", random.choice(["park", "cafe"])
        elif need == "fun": return "play", random.choice(["park", "office"])
        return "idle", self.location

    def think(self, city: City) -> str:
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
                loc = city.locations[target]
                self.gx, self.gy = loc.center()
                self.location = target
                loc.occupants.add(self.char_id)
                return f"{self.name} arrived at {loc.name}"
        if self.location == target and action != "idle":
            if action == "sleep": self.needs["energy"] = min(100, self.needs["energy"] + 30)
            elif action == "eat": self.needs["hunger"] = min(100, self.needs["hunger"] + 40)
            elif action == "socialize": self.needs["social"] = min(100, self.needs["social"] + 25)
            elif action == "play": self.needs["fun"] = min(100, self.needs["fun"] + 30)
            self.state = "idle"
            return f"{self.name} {action}ed"
        return ""

    def update(self, dt: float, city: City):
        self.anim_timer += dt
        self.state_timer += dt
        if self.anim_timer > 0.25:
            self.anim_timer = 0
            self.frame = (self.frame + 1) % 4
        for n in NEEDS:
            self.needs[n] = max(0, self.needs[n] - self.need_decay[n] * dt)

        if self.dest_location and self.path and self.path_index < len(self.path):
            self.state = "walk"
            tx, ty = self.path[self.path_index]
            dx, dy = tx - self.gx, ty - self.gy
            dist = (dx * dx + dy * dy) ** 0.5
            speed = 8.0 * dt
            if dist < speed:
                self.gx, self.gy = tx, ty
                self.path_index += 1
                if self.path_index >= len(self.path):
                    old = city.locations.get(self.location)
                    if old: old.occupants.discard(self.char_id)
                    self.location = self.dest_location
                    new = city.locations.get(self.location)
                    if new:
                        new.occupants.add(self.char_id)
                        self.gx, self.gy = new.center()
                        self.gy += 1
                    self.dest_location = ""
                    self.path = []
                    self.path_index = 0
                    self.state = "idle"
            else:
                self.gx += (dx / dist) * speed
                self.gy += (dy / dist) * speed
                self.facing_right = dx > 0
        else:
            loc = city.locations.get(self.location)
            if loc and self.state == "idle":
                cx, cy = loc.center()
                self.gx += (cx + random.uniform(-2, 2) - self.gx) * 2.0 * dt
                self.gy += (cy + 1 + random.uniform(-1, 1) - self.gy) * 2.0 * dt

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
        nv = self.needs[need]
        nc = "green" if nv > 50 else ("yellow" if nv > 25 else "red")
        loc = self.location.replace("_", " ").title() if self.location else "Nowhere"
        return f"{c(self.color, self.name)} {self.item} {c('dim', f'Lv.{self.level}')} 📍{c('cyan', loc[:10])} {c(nc, f'{need}:{int(nv)}')} 💰{self.money}"


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
        homes = {"dodger": "dodger_house", "scoop": "scoop_house", "slim": "slim_house", "whip": "whip_house"}
        for cid in CHARACTER_DATA:
            sp = StickPerson(cid, self.backend)
            home = homes[cid]
            loc = self.city.locations[home]
            sp.location = home
            sp.gx, sp.gy = loc.center()
            sp.gy += 1
            loc.occupants.add(cid)
            self.sticks[cid] = sp
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
                futures = {pool.submit(self.sticks[sid].chat, f"BRAINSTORM: {desc}\nYour angle? (2 sentences)", True): sid for sid in ids}
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
        a = self.sticks[a_id]
        b = self.sticks[b_id]
        sa, sb = a.relation_to(b_id), b.relation_to(a_id)
        if sa > 30 and sb > 30:
            a.needs["social"] = min(100, a.needs["social"] + 15)
            b.needs["social"] = min(100, b.needs["social"] + 15)
            a.set_relation(b_id, 2)
            b.set_relation(a_id, 2)
            self.events.append(f"{a.name} and {b.name} hung out as friends!")
        elif sa < -20 or sb < -20:
            a.set_relation(b_id, -5)
            b.set_relation(a_id, -5)
            a.needs["social"] = max(0, a.needs["social"] - 10)
            b.needs["social"] = max(0, b.needs["social"] - 10)
            self.events.append(f"{a.name} and {b.name} had a conflict!")
        else:
            a.set_relation(b_id, random.choice([-2, 2]))
            b.set_relation(a_id, random.choice([-2, 2]))
            a.needs["social"] = min(100, a.needs["social"] + 5)
            b.needs["social"] = min(100, b.needs["social"] + 5)

    def tick(self, dt: float):
        self.city.tick(dt)
        self.think_timer += dt
        for sp in self.sticks.values():
            sp.update(dt, self.city)
        if self.think_timer >= self.think_interval:
            self.think_timer = 0
            for sp in self.sticks.values():
                thought = sp.think(self.city)
                if thought:
                    self.events.append(thought)
        for loc in self.city.locations.values():
            occs = list(loc.occupants)
            for i in range(len(occs)):
                for j in range(i + 1, len(occs)):
                    if random.random() < 0.1:
                        self.interact(occs[i], occs[j])
        while len(self.events) > 20:
            self.events.pop(0)

    def pending_tasks(self) -> List[Dict]:
        return [t for t in self.tasks if t["status"] == "running"]

    def completed_tasks(self) -> List[Dict]:
        return [t for t in self.tasks if t["status"] == "done"]


# ═══════════════════════════════════════════════════════════════════════════════
#  🖼️ Terminal Engine
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

    def set(self, x: int, y: int, char: str, color: str = ""):
        if 0 <= x < self.w and 0 <= y < self.h and len(char) == 1:
            self.buf[y][x] = Cell(char, color)

    def text(self, x: int, y: int, text: str, color: str = ""):
        for i, ch in enumerate(text):
            self.set(x + i, y, ch, color)

    def box(self, x: int, y: int, w: int, h: int, color: str = ""):
        for dx in range(w):
            self.set(x + dx, y, "─", color)
            self.set(x + dx, y + h - 1, "─", color)
        for dy in range(h):
            self.set(x, y + dy, "│", color)
            self.set(x + w - 1, y + dy, "│", color)
        self.set(x, y, "┌", color)
        self.set(x + w - 1, y, "┐", color)
        self.set(x, y + h - 1, "└", color)
        self.set(x + w - 1, y + h - 1, "┘", color)

    def fill(self, x: int, y: int, w: int, h: int, char: str, color: str = ""):
        for dy in range(h):
            for dx in range(w):
                self.set(x + dx, y + dy, char, color)

    def sprite(self, x: int, y: int, lines: List[str], color: str = ""):
        for dy, line in enumerate(lines):
            for dx, ch in enumerate(line):
                if ch != " " and 0 <= x + dx < self.w and 0 <= y + dy < self.h:
                    self.set(x + dx, y + dy, ch, color)

    def render(self):
        lines = []
        for y, row in enumerate(self.buf):
            parts = []
            cur = ""
            for cell in row:
                code = COLORS.get(cell.color, cell.color) if cell.color else ""
                if code != cur:
                    if cur: parts.append(COLORS["reset"])
                    if code: parts.append(code)
                    cur = code
                parts.append(cell.char if cell.char else " ")
            if cur: parts.append(COLORS["reset"])
            lines.append("".join(parts))
        sys.stdout.write("\033[H" + "\n".join(lines))
        sys.stdout.flush()


# ═══════════════════════════════════════════════════════════════════════════════
#  🎨 Render Styles
# ═══════════════════════════════════════════════════════════════════════════════

class RenderStyle(ABC):
    name = "abstract"

    @abstractmethod
    def render_city(self, sim: Simulation, engine: TerminalEngine, view_w: int, view_h: int, off_x: int = 0, off_y: int = 0): ...

    @abstractmethod
    def render_ui(self, sim: Simulation, engine: TerminalEngine, view_h: int): ...

    @abstractmethod
    def style_cmd_hint(self) -> str: ...


class ToyStyle(RenderStyle):
    name = "toy"

    def render_city(self, sim, engine, view_w, view_h, off_x=0, off_y=0):
        city = sim.city
        for y in range(view_h):
            for x in range(view_w):
                gx, gy = x + off_x, y + off_y
                ch, col = " ", ""
                for path in city.roads.paths.values():
                    for px, py in path:
                        if px == gx and py == gy:
                            ch, col = "·", "darkgrey"
                            break
                engine.set(x, y, ch, col)

        for loc in city.locations.values():
            lx, ly = loc.x - off_x, loc.y - off_y
            if lx + loc.w < 0 or ly + loc.h < 0 or lx >= view_w or ly >= view_h:
                continue
            for dy in range(loc.h):
                for dx in range(loc.w):
                    sx, sy = lx + dx, ly + dy
                    if 0 <= sx < view_w and 0 <= sy < view_h:
                        if dy == 0 or dy == loc.h - 1 or dx == 0 or dx == loc.w - 1:
                            engine.set(sx, sy, "▓", loc.color)
                        else:
                            engine.set(sx, sy, " ", "")
            name_x = max(0, min(view_w - len(loc.name), lx + 1))
            name_y = max(0, min(view_h - 1, ly))
            engine.text(name_x, name_y, loc.name[:loc.w - 2], "bold")
            icon_x = lx + loc.w // 2
            icon_y = ly + loc.h // 2
            if 0 <= icon_x < view_w and 0 <= icon_y < view_h:
                engine.text(icon_x, icon_y, loc.icon)

        for cid, stick in sim.sticks.items():
            sx = int(stick.gx) - off_x
            sy = int(stick.gy) - off_y
            if 0 <= sx < view_w and 0 <= sy < view_h:
                engine.set(sx, sy, "◯", stick.color)
                if sy + 1 < view_h:
                    engine.set(sx, sy + 1, "│", stick.color)
                if sy + 2 < view_h:
                    if stick.state == "walk":
                        leg = "/" if stick.frame % 2 == 0 else "\\"
                        engine.set(sx - 1 if stick.facing_right else sx + 1, sy + 2, leg, stick.color)
                    else:
                        engine.set(sx - 1, sy + 2, "/", stick.color)
                        engine.set(sx + 1, sy + 2, "\\", stick.color)
                if sy - 1 >= 0:
                    engine.set(sx, sy - 1, stick.item[0] if stick.item else " ", stick.color)
                if stick.state == "work" and sx + 2 < view_w:
                    engine.set(sx + 2, sy, "⚡", "yellow")

    def render_ui(self, sim, engine, view_h):
        w = engine.w
        y = view_h + 1
        for x in range(w):
            engine.set(x, y - 1, "─", "darkgrey")
        engine.text(2, y, sim.city.time_str(), "white")
        active = sim.get()
        engine.text(2, y + 1, active.status_line())
        rel_parts = []
        for oid, other in sim.sticks.items():
            if oid != active.char_id:
                rel_parts.append(f"{other.name}:{active.relation_label(oid)}")
        engine.text(2, y + 2, "Relations: " + "  ".join(rel_parts))
        engine.text(2, y + 4, "📰 Events:", "bold")
        for i, evt in enumerate(sim.events[-5:]):
            engine.text(4, y + 5 + i, evt[:w - 6], "dim")
        task_y = y + 11
        engine.text(2, task_y, "📋 Tasks:", "bold")
        row = 1
        for t in sim.pending_tasks():
            engine.text(4, task_y + row, f"◐ [{t['cid']}] {t['desc'][:30]}", "orange")
            row += 1
        for t in sim.completed_tasks()[-3:]:
            preview = t.get("result", "")[:35].replace("\n", " ")
            engine.text(4, task_y + row, f"◉ [{t['cid']}] {preview}...", "green")
            row += 1
        input_y = engine.h - 2
        engine.text(2, input_y, "> " + getattr(sim, '_input_buffer', ''), "cyan")
        engine.text(2, engine.h - 1, self.style_cmd_hint(), "dim")

    def style_cmd_hint(self) -> str:
        return "/task /collab /switch /goto /interact /relations /style /new /help /quit"


class RoguelikeStyle(RenderStyle):
    name = "roguelike"
    TERRAIN = {"road": (".", "darkgrey"), "grass": ("\"", "green"), "water": ("~", "blue"), "floor": ("·", "grey")}
    WALL_CHAR = "#"

    def render_city(self, sim, engine, view_w, view_h, off_x=0, off_y=0):
        city = sim.city
        # Background terrain
        for y in range(view_h):
            for x in range(view_w):
                gx, gy = x + off_x, y + off_y
                ch, col = self.TERRAIN["grass"]
                # Roads
                for path in city.roads.paths.values():
                    for px, py in path:
                        if px == gx and py == gy:
                            ch, col = self.TERRAIN["road"]
                            break
                engine.set(x, y, ch, col)

        # Locations as rooms with walls
        for loc in city.locations.values():
            lx, ly = loc.x - off_x, loc.y - off_y
            if lx + loc.w < 0 or ly + loc.h < 0 or lx >= view_w or ly >= view_h:
                continue
            wall_col = loc.color
            for dy in range(loc.h):
                for dx in range(loc.w):
                    sx, sy = lx + dx, ly + dy
                    if 0 <= sx < view_w and 0 <= sy < view_h:
                        if dy == 0 or dy == loc.h - 1 or dx == 0 or dx == loc.w - 1:
                            engine.set(sx, sy, self.WALL_CHAR, wall_col)
                        else:
                            engine.set(sx, sy, ".", "")
            # Door
            door_x = lx + loc.w // 2
            door_y = ly + loc.h - 1
            if 0 <= door_x < view_w and 0 <= door_y < view_h:
                engine.set(door_x, door_y, "+", "white")
            # Name as sign
            name_x = max(0, min(view_w - len(loc.name), lx + 1))
            name_y = max(0, min(view_h - 2, ly + 1))
            engine.text(name_x, name_y, loc.name[:loc.w - 2], "bold")
            # Icon inside
            icon_x = lx + loc.w // 2
            icon_y = ly + loc.h // 2
            if 0 <= icon_x < view_w and 0 <= icon_y < view_h:
                engine.text(icon_x, icon_y, loc.icon)

        # Characters as @ with items
        for cid, stick in sim.sticks.items():
            sx = int(stick.gx) - off_x
            sy = int(stick.gy) - off_y
            if 0 <= sx < view_w and 0 <= sy < view_h:
                engine.set(sx, sy, "@", stick.color)
                if sy - 1 >= 0:
                    engine.set(sx, sy - 1, stick.item[0] if stick.item else " ", stick.color)
                if stick.state == "work" and sx + 2 < view_w:
                    engine.set(sx + 1, sy, "!", "yellow")

    def render_ui(self, sim, engine, view_h):
        w = engine.w
        y = view_h + 1
        for x in range(w):
            engine.set(x, y - 1, "-", "darkgrey")
        engine.text(2, y, f"[{sim.city.time_str()}]", "white")
        active = sim.get()
        engine.text(2, y + 1, active.status_line())
        engine.text(2, y + 2, "HP:100/100 MP:50/50" + " " * 10 + f"Need:{active.lowest_need()}", "dim")
        engine.text(2, y + 4, "Events:", "bold")
        for i, evt in enumerate(sim.events[-4:]):
            engine.text(4, y + 5 + i, "> " + evt[:w - 8], "dim")
        task_y = y + 10
        engine.text(2, task_y, "Quests:", "bold")
        row = 1
        for t in sim.pending_tasks():
            engine.text(4, task_y + row, f"[!] {t['desc'][:35]}", "orange")
            row += 1
        for t in sim.completed_tasks()[-2:]:
            engine.text(4, task_y + row, f"[✓] Done", "green")
            row += 1
        input_y = engine.h - 2
        engine.text(2, input_y, "> " + getattr(sim, '_input_buffer', ''), "cyan")
        engine.text(2, engine.h - 1, self.style_cmd_hint(), "dim")

    def style_cmd_hint(self) -> str:
        return "/task /collab /switch /goto /interact /relations /style /new /help /quit"


class EmojiStyle(RenderStyle):
    name = "emoji"

    TILES = {
        "dodger_house": ("🏠", "red"), "scoop_house": ("🏠", "blue"),
        "slim_house": ("🏠", "green"), "whip_house": ("🏠", "yellow"),
        "park": ("🌳", "green"), "shop": ("🏪", "orange"),
        "cafe": ("☕", "pink"), "office": ("🏢", "grey"),
        "road": ("🛣️", "darkgrey"), "grass": ("🌿", "green"),
    }

    def render_city(self, sim, engine, view_w, view_h, off_x=0, off_y=0):
        city = sim.city
        # Background
        for y in range(view_h):
            for x in range(view_w):
                gx, gy = x + off_x, y + off_y
                ch, col = " ", ""
                for path in city.roads.paths.values():
                    for px, py in path:
                        if px == gx and py == gy:
                            ch, col = self.TILES["road"]
                            break
                if not ch.strip():
                    ch, col = self.TILES["grass"]
                engine.set(x, y, ch, col)

        # Locations (every tile in location gets the icon)
        for loc in city.locations.values():
            tile, col = self.TILES.get(loc.id, ("◻", "white"))
            lx, ly = loc.x - off_x, loc.y - off_y
            if lx + loc.w < 0 or ly + loc.h < 0 or lx >= view_w or ly >= view_h:
                continue
            for dy in range(loc.h):
                for dx in range(loc.w):
                    sx, sy = lx + dx, ly + dy
                    if 0 <= sx < view_w and 0 <= sy < view_h:
                        if dy == 0 or dy == loc.h - 1 or dx == 0 or dx == loc.w - 1:
                            engine.set(sx, sy, "▪", loc.color)
                        else:
                            engine.set(sx, sy, tile, col)
            name_x = max(0, min(view_w - len(loc.name), lx + 1))
            name_y = max(0, min(view_h - 1, ly))
            engine.text(name_x, name_y, loc.name[:loc.w - 2], "bold")

        # Characters as emoji people
        emojis = {"dodger": "🤾", "scoop": "🙋", "slim": "🧍", "whip": "🤸"}
        for cid, stick in sim.sticks.items():
            sx = int(stick.gx) - off_x
            sy = int(stick.gy) - off_y
            if 0 <= sx < view_w and 0 <= sy < view_h:
                engine.set(sx, sy, emojis.get(cid, "🧍"), stick.color)
                if stick.state == "work" and sx + 2 < view_w:
                    engine.set(sx + 2, sy, "💼", "yellow")

    def render_ui(self, sim, engine, view_h):
        w = engine.w
        y = view_h + 1
        for x in range(w):
            engine.set(x, y - 1, "─", "darkgrey")
        engine.text(2, y, f"📅 {sim.city.time_str()}", "white")
        active = sim.get()
        engine.text(2, y + 1, active.status_line())
        rel_parts = []
        for oid, other in sim.sticks.items():
            if oid != active.char_id:
                rel_parts.append(f"{other.name}:{active.relation_label(oid)}")
        engine.text(2, y + 2, "❤️ " + "  ".join(rel_parts))
        engine.text(2, y + 4, "📰 Events:", "bold")
        for i, evt in enumerate(sim.events[-5:]):
            engine.text(4, y + 5 + i, evt[:w - 6], "dim")
        task_y = y + 11
        engine.text(2, task_y, "📋 Tasks:", "bold")
        row = 1
        for t in sim.pending_tasks():
            engine.text(4, task_y + row, f"⏳ {t['desc'][:30]}", "orange")
            row += 1
        for t in sim.completed_tasks()[-3:]:
            preview = t.get("result", "")[:35].replace("\n", " ")
            engine.text(4, task_y + row, f"✅ {preview}...", "green")
            row += 1
        input_y = engine.h - 2
        engine.text(2, input_y, "> " + getattr(sim, '_input_buffer', ''), "cyan")
        engine.text(2, engine.h - 1, self.style_cmd_hint(), "dim")

    def style_cmd_hint(self) -> str:
        return "/task /collab /switch /goto /interact /relations /style /new /help /quit"


class RetroStyle(RenderStyle):
    name = "retro"
    PALETTE = {"bg": "bg_black", "fg": "green", "dim": "dim", "bright": "bold"}

    def render_city(self, sim, engine, view_w, view_h, off_x=0, off_y=0):
        city = sim.city
        for y in range(view_h):
            row_dim = "dim" if y % 2 == 0 else "green"
            for x in range(view_w):
                gx, gy = x + off_x, y + off_y
                ch, col = "·", row_dim
                for path in city.roads.paths.values():
                    for px, py in path:
                        if px == gx and py == gy:
                            ch, col = "=", "green"
                            break
                engine.set(x, y, ch, col)

        for loc in city.locations.values():
            lx, ly = loc.x - off_x, loc.y - off_y
            if lx + loc.w < 0 or ly + loc.h < 0 or lx >= view_w or ly >= view_h:
                continue
            for dy in range(loc.h):
                for dx in range(loc.w):
                    sx, sy = lx + dx, ly + dy
                    if 0 <= sx < view_w and 0 <= sy < view_h:
                        if dy == 0 or dy == loc.h - 1 or dx == 0 or dx == loc.w - 1:
                            engine.set(sx, sy, "▓", "green")
                        else:
                            engine.set(sx, sy, " ", "")
            name_x = max(0, min(view_w - len(loc.name), lx + 1))
            name_y = max(0, min(view_h - 1, ly))
            engine.text(name_x, name_y, loc.name[:loc.w - 2], "bold")
            icon_x = lx + loc.w // 2
            icon_y = ly + loc.h // 2
            if 0 <= icon_x < view_w and 0 <= icon_y < view_h:
                engine.set(icon_x, icon_y, "+", "bold")

        for cid, stick in sim.sticks.items():
            sx = int(stick.gx) - off_x
            sy = int(stick.gy) - off_y
            if 0 <= sx < view_w and 0 <= sy < view_h:
                engine.set(sx, sy, "@", "bold")
                if sy + 1 < view_h:
                    engine.set(sx, sy + 1, "│", "green")
                if sy + 2 < view_h:
                    engine.set(sx - 1, sy + 2, "/", "green")
                    engine.set(sx + 1, sy + 2, "\\", "green")
                if sy - 1 >= 0:
                    engine.set(sx, sy - 1, "*", "green")

    def render_ui(self, sim, engine, view_h):
        w = engine.w
        y = view_h + 1
        for x in range(w):
            engine.set(x, y - 1, "-", "green")
        engine.text(2, y, f"> {sim.city.time_str()}", "bold")
        active = sim.get()
        engine.text(2, y + 1, active.status_line())
        engine.text(2, y + 2, "Relations: " + " ".join(f"{sim.sticks[oid].name}:{active.relation_to(oid)}" for oid in sim.sticks if oid != active.char_id))
        engine.text(2, y + 4, "> EVENTS:", "bold")
        for i, evt in enumerate(sim.events[-5:]):
            engine.text(4, y + 5 + i, "> " + evt[:w - 8], "dim")
        task_y = y + 11
        engine.text(2, task_y, "> TASKS:", "bold")
        row = 1
        for t in sim.pending_tasks():
            engine.text(4, task_y + row, f"> [RUNNING] {t['desc'][:30]}", "dim")
            row += 1
        for t in sim.completed_tasks()[-3:]:
            engine.text(4, task_y + row, f"> [DONE] {t['cid']}", "green")
            row += 1
        input_y = engine.h - 2
        engine.text(2, input_y, "> " + getattr(sim, '_input_buffer', ''), "green")
        engine.text(2, engine.h - 1, self.style_cmd_hint(), "dim")

    def style_cmd_hint(self) -> str:
        return "/task /collab /switch /goto /interact /relations /style /new /help /quit"


class MinimalStyle(RenderStyle):
    name = "minimal"

    def render_city(self, sim, engine, view_w, view_h, off_x=0, off_y=0):
        city = sim.city
        for y in range(view_h):
            for x in range(view_w):
                gx, gy = x + off_x, y + off_y
                ch, col = " ", ""
                for path in city.roads.paths.values():
                    for px, py in path:
                        if px == gx and py == gy:
                            ch, col = "─", "grey"
                            break
                engine.set(x, y, ch, col)

        for loc in city.locations.values():
            lx, ly = loc.x - off_x, loc.y - off_y
            if lx + loc.w < 0 or ly + loc.h < 0 or lx >= view_w or ly >= view_h:
                continue
            for dy in range(loc.h):
                for dx in range(loc.w):
                    sx, sy = lx + dx, ly + dy
                    if 0 <= sx < view_w and 0 <= sy < view_h:
                        if dy == 0 or dy == loc.h - 1:
                            engine.set(sx, sy, "─", loc.color)
                        elif dx == 0 or dx == loc.w - 1:
                            engine.set(sx, sy, "│", loc.color)
                        else:
                            engine.set(sx, sy, "·", "")
            engine.set(lx, ly, "┌", loc.color)
            engine.set(lx + loc.w - 1, ly, "┐", loc.color)
            engine.set(lx, ly + loc.h - 1, "└", loc.color)
            engine.set(lx + loc.w - 1, ly + loc.h - 1, "┘", loc.color)
            name_x = max(0, min(view_w - len(loc.name), lx + 2))
            name_y = max(0, min(view_h - 1, ly))
            engine.text(name_x, name_y, loc.name[:loc.w - 4], "bold")

        for cid, stick in sim.sticks.items():
            sx = int(stick.gx) - off_x
            sy = int(stick.gy) - off_y
            if 0 <= sx < view_w and 0 <= sy < view_h:
                engine.set(sx, sy, "●", stick.color)
                if stick.state == "walk":
                    dx = 1 if stick.facing_right else -1
                    if 0 <= sx + dx < view_w:
                        engine.set(sx + dx, sy, "·", stick.color)

    def render_ui(self, sim, engine, view_h):
        w = engine.w
        y = view_h + 1
        for x in range(w):
            engine.set(x, y - 1, "─", "grey")
        engine.text(2, y, sim.city.time_str(), "black")
        active = sim.get()
        engine.text(2, y + 1, active.status_line())
        engine.text(2, y + 3, "events", "bold")
        for i, evt in enumerate(sim.events[-4:]):
            engine.text(4, y + 4 + i, evt[:w - 8], "dim")
        task_y = y + 9
        engine.text(2, task_y, "tasks", "bold")
        row = 1
        for t in sim.pending_tasks():
            engine.text(4, task_y + row, f"○ {t['desc'][:35]}", "orange")
            row += 1
        for t in sim.completed_tasks()[-2:]:
            engine.text(4, task_y + row, f"● done", "green")
            row += 1
        input_y = engine.h - 2
        engine.text(2, input_y, "> " + getattr(sim, '_input_buffer', ''), "black")
        engine.text(2, engine.h - 1, self.style_cmd_hint(), "dim")

    def style_cmd_hint(self) -> str:
        return "/task /collab /switch /goto /interact /relations /style /new /help /quit"


class IsometricStyle(RenderStyle):
    name = "isometric"

    def _iso(self, gx: int, gy: int) -> Tuple[int, int]:
        """Convert grid to pseudo-isometric screen coords."""
        sx = (gx - gy) + 40
        sy = (gx + gy) // 2
        return sx, sy

    def render_city(self, sim, engine, view_w, view_h, off_x=0, off_y=0):
        city = sim.city
        # Draw roads first
        for path in city.roads.paths.values():
            for i in range(len(path) - 1):
                x1, y1 = self._iso(path[i][0], path[i][1])
                x2, y2 = self._iso(path[i + 1][0], path[i + 1][1])
                x1 -= off_x
                y1 -= off_y
                x2 -= off_x
                y2 -= off_y
                if 0 <= x1 < view_w and 0 <= y1 < view_h:
                    engine.set(x1, y1, "·", "darkgrey")

        # Draw locations as isometric blocks
        for loc in city.locations.values():
            cx, cy = self._iso(loc.x + loc.w // 2, loc.y + loc.h // 2)
            cx -= off_x
            cy -= off_y
            if not (0 <= cx < view_w and 0 <= cy < view_h):
                continue
            # Top face
            for dx in range(-3, 4):
                engine.set(cx + dx, cy - 2, "─", loc.color)
            engine.set(cx - 3, cy - 2, "╱", loc.color)
            engine.set(cx + 3, cy - 2, "╲", loc.color)
            # Front face
            for dy in range(-1, 3):
                engine.set(cx - 3, cy + dy, "│", loc.color)
                engine.set(cx + 3, cy + dy, "│", loc.color)
            for dx in range(-3, 4):
                engine.set(cx + dx, cy + 3, "─", loc.color)
            engine.text(cx - 2, cy, loc.icon, loc.color)
            engine.text(cx - 3, cy + 4, loc.name[:8], "bold")

        # Characters
        for cid, stick in sim.sticks.items():
            sx, sy = self._iso(int(stick.gx), int(stick.gy))
            sx -= off_x
            sy -= off_y
            if 0 <= sx < view_w and 0 <= sy < view_h:
                engine.set(sx, sy, "○", stick.color)
                if sy + 1 < view_h:
                    engine.set(sx, sy + 1, "│", stick.color)

    def render_ui(self, sim, engine, view_h):
        w = engine.w
        y = view_h + 1
        for x in range(w):
            engine.set(x, y - 1, "─", "darkgrey")
        engine.text(2, y, sim.city.time_str(), "white")
        active = sim.get()
        engine.text(2, y + 1, active.status_line())
        rel_parts = []
        for oid, other in sim.sticks.items():
            if oid != active.char_id:
                rel_parts.append(f"{other.name}:{active.relation_label(oid)}")
        engine.text(2, y + 2, "Relations: " + "  ".join(rel_parts))
        engine.text(2, y + 4, "Events:", "bold")
        for i, evt in enumerate(sim.events[-5:]):
            engine.text(4, y + 5 + i, evt[:w - 6], "dim")
        task_y = y + 11
        engine.text(2, task_y, "Tasks:", "bold")
        row = 1
        for t in sim.pending_tasks():
            engine.text(4, task_y + row, f"◐ {t['desc'][:30]}", "orange")
            row += 1
        for t in sim.completed_tasks()[-3:]:
            preview = t.get("result", "")[:35].replace("\n", " ")
            engine.text(4, task_y + row, f"◉ {preview}...", "green")
            row += 1
        input_y = engine.h - 2
        engine.text(2, input_y, "> " + getattr(sim, '_input_buffer', ''), "cyan")
        engine.text(2, engine.h - 1, self.style_cmd_hint(), "dim")

    def style_cmd_hint(self) -> str:
        return "/task /collab /switch /goto /interact /relations /style /new /help /quit"


STYLES: Dict[str, RenderStyle] = {
    "toy": ToyStyle(),
    "roguelike": RoguelikeStyle(),
    "emoji": EmojiStyle(),
    "retro": RetroStyle(),
    "minimal": MinimalStyle(),
    "isometric": IsometricStyle(),
}


# ═══════════════════════════════════════════════════════════════════════════════
#  🎮 Main Game Loop
# ═══════════════════════════════════════════════════════════════════════════════

class CubeWorldCLI:
    FPS = 8

    def __init__(self, mode: str = "auto", style_name: str = "toy"):
        self.backend = AIBackend(mode=mode)
        self.sim = Simulation(self.backend)
        self.engine = TerminalEngine()
        self.style = STYLES.get(style_name, ToyStyle())
        self.style_name = style_name
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
        self.sim._input_buffer = self._input_buffer
        self.style.render_city(self.sim, self.engine, w, view_h)
        self.style.render_ui(self.sim, self.engine, view_h)
        if self.messages:
            last = self.messages[-1]
            msg_y = view_h - 3
            self.engine.text(2, msg_y, "╭" + "─" * (w - 6) + "╮", "white")
            lines = self._wrap(last, w - 8)
            for i, line in enumerate(lines[:2]):
                self.engine.text(2, msg_y + 1 + i, "│ " + line.ljust(w - 6) + "│", "white")
            self.engine.text(2, msg_y + 1 + min(len(lines), 2), "╰" + "─" * (w - 6) + "╯", "white")
        self.engine.render()

    def _wrap(self, text: str, width: int) -> List[str]:
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
            self.messages.append("Shutting down...")
            self.running = False
        elif cmd == "switch":
            if self.sim.switch(args.strip().lower()):
                self.messages.append(f"Now following {self.sim.get().name}!")
            else:
                self.messages.append("Names: dodger, scoop, slim, whip")
        elif cmd == "style":
            sname = args.strip().lower()
            if sname in STYLES:
                self.style = STYLES[sname]
                self.style_name = sname
                self.messages.append(f"Style switched to {sname}!")
            else:
                self.messages.append(f"Styles: {', '.join(STYLES.keys())}")
        elif cmd == "goto":
            target = args.strip().lower().replace(" ", "_")
            if target in self.sim.city.locations:
                stick = self.sim.get()
                stick.dest_location = target
                stick.path = self.sim.city.roads.get_path(stick.location, target)
                stick.path_index = 0
                if stick.path:
                    stick.state = "walk"
                    self.messages.append(f"{stick.name} walking to {self.sim.city.locations[target].name}!")
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
            p = self.sim.pending_tasks()
            d = self.sim.completed_tasks()
            self.messages.append(f"Running: {len(p)} | Done: {len(d)}")
        elif cmd == "new":
            for s in self.sim.sticks.values():
                s.reset_chat()
            self.messages.append("All memories reset!")
        elif cmd in ("help", "h"):
            self.messages.append(
                "/switch <name>  /goto <loc>  /interact  /relations  "
                "/task <n> <desc>  /collab <desc>  /style <name>  /check  /new  /quit"
            )
        else:
            self.messages.append(f"Unknown /{cmd}. Try /help")

    def run(self):
        self.messages.append(f"Welcome to Cube World City! Style: {self.style_name}")
        last_time = time.time()
        while self.running:
            now = time.time()
            dt = min(now - last_time, 0.2)
            last_time = now
            self.sim.tick(dt)
            self.draw_scene()
            line = self._read_input()
            if line is not None:
                self._process_command(line)
            sleep_time = max(0, (1.0 / self.FPS) - (time.time() - now))
            time.sleep(sleep_time)
        self.engine.clear()
        print(c("bold", "Cube World City closed. See you!"))


def main():
    parser = argparse.ArgumentParser(description="Cube World City — Multi-Style Edition")
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--cloud", action="store_true")
    parser.add_argument("--style", default="toy", choices=list(STYLES.keys()), help="Visual style")
    args = parser.parse_args()
    mode = "local" if args.local else ("cloud" if args.cloud else "auto")
    CubeWorldCLI(mode=mode, style_name=args.style).run()


if __name__ == "__main__":
    main()
