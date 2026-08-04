#!/usr/bin/env python3
"""Windows 11 Fluent Design GUI for Zeaz AI Command Center.

A native-feeling desktop client using tkinter with WinUI 3 / Fluent Design
styling — Mica-like backgrounds, rounded corners, Segoe UI, and accent colors.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any
import urllib.request
import urllib.error
import urllib.parse

# ---------------------------------------------------------------------------
# Win11 Fluent Design constants
# ---------------------------------------------------------------------------

FONT_FAMILY = "Segoe UI Variable"
FONT_FAMILY_MONO = "Cascadia Code"
ACCENT = "#0078D4"
ACCENT_HOVER = "#106EBE"
ACCENT_LIGHT = "#DEECF9"
BG_MICA = "#F3F3F3"
BG_CARD = "#FFFFFF"
BG_NAV = "#F9F9F9"
BG_INPUT = "#FFFFFF"
FG_PRIMARY = "#1A1A1A"
FG_SECONDARY = "#616161"
FG_DISABLED = "#A0A0A0"
BORDER = "#E0E0E0"
BORDER_FOCUS = ACCENT
SUCCESS = "#107C10"
WARNING = "#FF8C00"
ERROR = "#D13438"
INFO = "#0078D4"
RADIUS = 6

NAV_ITEMS = [
    ("Dashboard", "📊"),
    ("Jobs", "⚡"),
    ("Workflows", "🔄"),
    ("Templates", "📋"),
    ("Presets", "⭐"),
    ("Analytics", "📈"),
    ("Providers", "🔧"),
    ("Users", "👥"),
    ("API Keys", "🔑"),
    ("Webhooks", "📡"),
    ("Notifications", "🔔"),
    ("MCP Servers", "🔌"),
    ("Audit Log", "📜"),
    ("Scheduler", "📅"),
    ("Settings", "⚙️"),
]


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

class APIClient:
    """Lightweight REST client for the Command Center API."""

    def __init__(self, base_url: str = "http://127.0.0.1:8765", token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.api_version = "v1"

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        h["X-API-Version"] = self.api_version
        return h

    def _url(self, path: str) -> str:
        if path.startswith("/api/"):
            return f"{self.base_url}{path}"
        return f"{self.base_url}/api/{self.api_version}{path}"

    def request(self, method: str, path: str, body: dict | None = None, params: dict | None = None) -> dict[str, Any]:
        url = self._url(path)
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 204:
                    return {"ok": True}
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode())
            except Exception:
                err_body = {"error": e.reason}
            return {"error": err_body.get("error", str(e)), "status": e.code}
        except urllib.error.URLError as e:
            return {"error": f"Connection failed: {e.reason}"}
        except Exception as e:
            return {"error": str(e)}

    def get(self, path: str, **params: Any) -> dict:
        return self.request("GET", path, params=params if params else None)

    def post(self, path: str, body: dict | None = None) -> dict:
        return self.request("POST", path, body)

    def put(self, path: str, body: dict | None = None) -> dict:
        return self.request("PUT", path, body)

    def delete(self, path: str) -> dict:
        return self.request("DELETE", path)


class SSEClient:
    """Minimal SSE client that reads /api/events in a background thread."""

    def __init__(self, base_url: str, token: str = "", on_event=None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.on_event = on_event
        self._running = False
        self._thread: threading.Thread | None = None
        self._event_type: str | None = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _listen(self):
        url = f"{self.base_url}/api/events"
        headers = {"Accept": "text/event-stream", "Cache-Control": "no-cache"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, headers=headers, method="GET")
        while self._running:
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    buf = ""
                    for raw_line in resp:
                        if not self._running:
                            break
                        line = raw_line.decode("utf-8", errors="replace").rstrip("\n\r")
                        if line.startswith("data:"):
                            payload = line[5:].strip()
                            if payload:
                                try:
                                    event = json.loads(payload)
                                except json.JSONDecodeError:
                                    event = {"raw": payload}
                                if self._event_type is not None:
                                    event["sse_type"] = self._event_type
                                    self._event_type = None
                                if self.on_event:
                                    self.on_event(event)
                        elif line == "":
                            buf = ""
                            self._event_type = None
                        elif line.startswith("event:"):
                            self._event_type = line[6:].strip()
            except Exception:
                if not self._running:
                    break
                time.sleep(3)


# ---------------------------------------------------------------------------
# Fluent-styled widgets
# ---------------------------------------------------------------------------

class FluentButton(tk.Canvas):
    """Rounded Win11-style button."""

    def __init__(self, parent, text="", command=None, accent=False, width=120, height=32, **kw):
        bg = ACCENT if accent else BG_CARD
        fg = "#FFFFFF" if accent else FG_PRIMARY
        self._hover_bg = ACCENT_HOVER if accent else "#E8E8E8"
        self._normal_bg = bg
        self._fg = fg
        self._command = command
        self._text = text
        self._width = width
        self._height = height
        super().__init__(parent, width=width, height=height, bg=parent.cget("bg"),
                         highlightthickness=0, cursor="hand2", **kw)
        self._draw(bg)
        self.bind("<Enter>", lambda e: self._draw(self._hover_bg))
        self.bind("<Leave>", lambda e: self._draw(self._normal_bg))
        self.bind("<Button-1>", lambda e: self._command() if self._command else None)

    def _draw(self, bg):
        self.delete("all")
        self.create_rounded_rect(1, 1, self._width - 1, self._height - 1, RADIUS, fill=bg, outline=BORDER if bg == self._normal_bg else "")
        self.create_text(self._width // 2, self._height // 2, text=self._text,
                         font=(FONT_FAMILY, 10), fill=self._fg)

    def create_rounded_rect(self, x1, y1, x2, y2, r, **kw):
        points = [
            x1 + r, y1, x2 - r, y1,
            x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r,
            x1, y1 + r, x1, y1,
        ]
        return self.create_polygon(points, smooth=True, **kw)


class FluentEntry(tk.Frame):
    """Win11-style text input with label and rounded border."""

    def __init__(self, parent, label="", placeholder="", width=30, show=None, **kw):
        super().__init__(parent, bg=parent.cget("bg"), **kw)
        self._var = tk.StringVar()
        if label:
            tk.Label(self, text=label, font=(FONT_FAMILY, 10), bg=self.cget("bg"),
                     fg=FG_SECONDARY, anchor="w").pack(fill="x", pady=(0, 3))
        self._entry = tk.Entry(self, textvariable=self._var, font=(FONT_FAMILY, 10),
                               bg=BG_INPUT, fg=FG_PRIMARY, insertbackground=ACCENT,
                               relief="flat", highlightthickness=1,
                               highlightcolor=BORDER_FOCUS, highlightbackground=BORDER,
                               width=width, show=show)
        self._entry.pack(fill="x", ipady=4)
        if placeholder:
            self._entry.insert(0, placeholder)
            self._entry.bind("<FocusIn>", self._clear_placeholder)
            self._placeholder = placeholder
        else:
            self._placeholder = ""

    def _clear_placeholder(self, e=None):
        if self._var.get() == self._placeholder:
            self._entry.delete(0, "end")

    def get(self):
        return self._var.get()

    def set(self, value):
        self._var.set(value)


class FluentCombo(tk.Frame):
    """Win11-style combobox with label."""

    def __init__(self, parent, label="", values=None, width=28, **kw):
        super().__init__(parent, bg=parent.cget("bg"), **kw)
        self._var = tk.StringVar()
        if label:
            tk.Label(self, text=label, font=(FONT_FAMILY, 10), bg=self.cget("bg"),
                     fg=FG_SECONDARY, anchor="w").pack(fill="x", pady=(0, 3))
        self._combo = ttk.Combobox(self, textvariable=self._var, values=values or [],
                                   font=(FONT_FAMILY, 10), state="readonly", width=width)
        self._combo.pack(fill="x", ipady=2)
        if values:
            self._combo.current(0)

    def get(self):
        return self._var.get()

    def set(self, value):
        self._var.set(value)

    def configure(self, **kw):
        self._combo.configure(**kw)


class FluentText(tk.Frame):
    """Win11-style multi-line text area."""

    def __init__(self, parent, label="", height=8, width=60, **kw):
        super().__init__(parent, bg=parent.cget("bg"), **kw)
        if label:
            tk.Label(self, text=label, font=(FONT_FAMILY, 10), bg=self.cget("bg"),
                     fg=FG_SECONDARY, anchor="w").pack(fill="x", pady=(0, 3))
        self._text = tk.Text(self, font=(FONT_FAMILY_MONO, 10), bg=BG_INPUT, fg=FG_PRIMARY,
                             insertbackground=ACCENT, relief="flat", highlightthickness=1,
                             highlightcolor=BORDER_FOCUS, highlightbackground=BORDER,
                             height=height, width=width, wrap="word", padx=8, pady=6)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._text.yview)
        self._text.configure(yscrollcommand=scrollbar.set)
        self._text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def get(self):
        return self._text.get("1.0", "end-1c")

    def set(self, value):
        self._text.delete("1.0", "end")
        self._text.insert("1.0", value)

    def clear(self):
        self._text.delete("1.0", "end")


class Card(tk.Frame):
    """Win11-style card with rounded shadow."""

    def __init__(self, parent, title="", **kw):
        super().__init__(parent, bg=BG_CARD, highlightbackground=BORDER,
                         highlightthickness=1, padx=16, pady=12, **kw)
        if title:
            tk.Label(self, text=title, font=(FONT_FAMILY, 13, "bold"), bg=BG_CARD,
                     fg=FG_PRIMARY, anchor="w").pack(fill="x", pady=(0, 8))


class StatusBadge(tk.Label):
    """Colored status indicator."""

    COLORS = {
        "succeeded": SUCCESS, "failed": ERROR, "running": INFO,
        "queued": WARNING, "stopped": FG_SECONDARY, "timed_out": ERROR,
        "orphaned": FG_DISABLED, "active": SUCCESS, "draft": FG_SECONDARY,
        "stopping": WARNING, "open": ERROR, "closed": SUCCESS, "half_open": WARNING,
    }

    def __init__(self, parent, status="", **kw):
        color = self.COLORS.get(status, FG_SECONDARY)
        super().__init__(parent, text=f"● {status}", font=(FONT_FAMILY, 10),
                         bg=parent.cget("bg"), fg=color, anchor="w", **kw)


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class ZeazGUI(tk.Tk):
    """Windows 11 Fluent Design GUI for Zeaz AI Command Center."""

    def __init__(self):
        super().__init__()
        self.title("Zeaz AI Command Center")
        self.geometry("1280x800")
        self.minsize(1024, 640)
        self.configure(bg=BG_MICA)

        self.api = APIClient()
        self._sse: SSEClient | None = None
        self._current_page = "Dashboard"
        self._refresh_after_id = None
        self._event_log: list[dict] = []

        self._build_nav()
        self._build_content_area()
        self._build_event_feed()
        self._show_page("Dashboard")
        self._start_auto_refresh()
        self._start_sse()

        try:
            self.iconbitmap("static/favicon.ico")
        except Exception:
            pass

    # ---- Navigation sidebar ----

    def _build_nav(self):
        self._nav = tk.Frame(self, bg=BG_NAV, width=220)
        self._nav.pack(side="left", fill="y")
        self._nav.pack_propagate(False)

        tk.Label(self._nav, text="Zeaz AI", font=(FONT_FAMILY, 18, "bold"),
                 bg=BG_NAV, fg=ACCENT).pack(pady=(20, 4), padx=16, anchor="w")
        tk.Label(self._nav, text="Command Center", font=(FONT_FAMILY, 11),
                 bg=BG_NAV, fg=FG_SECONDARY).pack(pady=(0, 16), padx=16, anchor="w")

        sep = tk.Frame(self._nav, bg=BORDER, height=1)
        sep.pack(fill="x", padx=12, pady=(0, 8))

        self._nav_buttons: dict[str, tk.Frame] = {}
        for name, icon in NAV_ITEMS:
            btn_frame = tk.Frame(self._nav, bg=BG_NAV, cursor="hand2")
            btn_frame.pack(fill="x", padx=4, pady=1)
            lbl = tk.Label(btn_frame, text=f"  {icon}  {name}", font=(FONT_FAMILY, 10),
                           bg=BG_NAV, fg=FG_PRIMARY, anchor="w", padx=8, pady=6)
            lbl.pack(fill="x")
            for widget in (btn_frame, lbl):
                widget.bind("<Button-1>", lambda e, n=name: self._show_page(n))
                widget.bind("<Enter>", lambda e, bf=btn_frame, l=lbl: (bf.configure(bg=ACCENT_LIGHT), l.configure(bg=ACCENT_LIGHT)))
                widget.bind("<Leave>", lambda e, bf=btn_frame, l=lbl, n=name: (
                    bf.configure(bg=ACCENT if n == self._current_page else BG_NAV),
                    l.configure(bg=ACCENT if n == self._current_page else BG_NAV),
                    l.configure(fg="#FFFFFF" if n == self._current_page else FG_PRIMARY)))
            self._nav_buttons[name] = btn_frame

        # Connection status at bottom
        self._conn_status = tk.Label(self._nav, text="● Disconnected", font=(FONT_FAMILY, 9),
                                     bg=BG_NAV, fg=ERROR, anchor="w")
        self._conn_status.pack(side="bottom", fill="x", padx=16, pady=12)

    def _highlight_nav(self, name: str):
        self._current_page = name
        for n, btn_frame in self._nav_buttons.items():
            lbl = btn_frame.winfo_children()[0]
            if n == name:
                btn_frame.configure(bg=ACCENT)
                lbl.configure(bg=ACCENT, fg="#FFFFFF")
            else:
                btn_frame.configure(bg=BG_NAV)
                lbl.configure(bg=BG_NAV, fg=FG_PRIMARY)

    # ---- Content area ----

    def _build_content_area(self):
        self._content = tk.Frame(self, bg=BG_MICA)
        self._content.pack(side="right", fill="both", expand=True)

        # Header bar
        self._header = tk.Frame(self._content, bg=BG_MICA, height=48)
        self._header.pack(fill="x", padx=24, pady=(16, 0))
        self._header.pack_propagate(False)
        self._header_title = tk.Label(self._header, text="Dashboard", font=(FONT_FAMILY, 20, "bold"),
                                      bg=BG_MICA, fg=FG_PRIMARY)
        self._header_title.pack(side="left")
        self._header_actions = tk.Frame(self._header, bg=BG_MICA)
        self._header_actions.pack(side="right")

        # Scrollable page container
        self._page_container = tk.Frame(self._content, bg=BG_MICA)
        self._page_container.pack(fill="both", expand=True, padx=24, pady=(8, 16))

        self._page_frame: tk.Frame | None = None

    def _show_page(self, name: str):
        self._highlight_nav(name)
        self._header_title.configure(text=name)
        if self._page_frame:
            self._page_frame.destroy()
        self._page_frame = tk.Frame(self._page_container, bg=BG_MICA)
        self._page_frame.pack(fill="both", expand=True)

        # Clear header actions
        for w in self._header_actions.winfo_children():
            w.destroy()

        builder = {
            "Dashboard": self._page_dashboard,
            "Jobs": self._page_jobs,
            "Workflows": self._page_workflows,
            "Templates": self._page_templates,
            "Presets": self._page_presets,
            "Analytics": self._page_analytics,
            "Providers": self._page_providers,
            "Users": self._page_users,
            "API Keys": self._page_api_keys,
            "Webhooks": self._page_webhooks,
            "Notifications": self._page_notifications,
            "MCP Servers": self._page_mcp_servers,
            "Audit Log": self._page_audit_log,
            "Scheduler": self._page_scheduler,
            "Settings": self._page_settings,
        }.get(name)
        if builder:
            builder()

    # ---- Auto-refresh ----

    def _start_auto_refresh(self):
        self._refresh_connection_status()

    def _refresh_connection_status(self):
        def check():
            result = self.api.get("/health")
            connected = "ok" in result and result.get("ok") is True
            self.after(0, lambda: self._conn_status.configure(
                text=f"● Connected ({result.get('engine', 'sqlite3')})" if connected else "● Disconnected",
                fg=SUCCESS if connected else ERROR))
        threading.Thread(target=check, daemon=True).start()
        self._refresh_after_id = self.after(15000, self._refresh_connection_status)

    # ---- Live event feed (bottom panel) ----

    def _build_event_feed(self):
        self._feed_frame = tk.Frame(self, bg=BG_CARD, height=120)
        self._feed_frame.pack(side="bottom", fill="x", before=self._content)
        self._feed_frame.pack_propagate(False)

        hdr = tk.Frame(self._feed_frame, bg=BG_CARD)
        hdr.pack(fill="x", padx=8, pady=(4, 0))
        tk.Label(hdr, text="📡 Live Events", font=(FONT_FAMILY, 10, "bold"),
                 bg=BG_CARD, fg=FG_PRIMARY).pack(side="left")
        self._feed_count = tk.Label(hdr, text="0 events", font=(FONT_FAMILY, 9),
                                    bg=BG_CARD, fg=FG_SECONDARY)
        self._feed_count.pack(side="left", padx=8)

        self._feed_toggle = FluentButton(hdr, "▼", command=self._toggle_event_feed, width=24, height=20)
        self._feed_toggle.pack(side="right")
        FluentButton(hdr, "Clear", command=self._clear_event_feed, width=50, height=20).pack(side="right", padx=4)

        self._feed_text = tk.Text(self._feed_frame, font=(FONT_FAMILY_MONO, 9), bg=BG_CARD,
                                  fg=FG_PRIMARY, relief="flat", height=5, wrap="word",
                                  state="disabled", padx=8, pady=4)
        self._feed_text.pack(fill="both", expand=True, padx=8, pady=(2, 4))

        # Tag colours for event types
        self._feed_text.tag_configure("job", foreground=INFO)
        self._feed_text.tag_configure("workflow", foreground=SUCCESS)
        self._feed_text.tag_configure("error", foreground=ERROR)
        self._feed_text.tag_configure("default", foreground=FG_SECONDARY)

        self._feed_expanded = True

    def _toggle_event_feed(self):
        self._feed_expanded = not self._feed_expanded
        if self._feed_expanded:
            self._feed_text.pack(fill="both", expand=True, padx=8, pady=(2, 4))
            self._feed_frame.configure(height=120)
            self._feed_toggle._text = "▼"
        else:
            self._feed_text.pack_forget()
            self._feed_frame.configure(height=32)
            self._feed_toggle._text = "▲"
        self._feed_toggle._draw(self._feed_toggle._normal_bg)

    def _clear_event_feed(self):
        self._event_log.clear()
        self._feed_text.configure(state="normal")
        self._feed_text.delete("1.0", "end")
        self._feed_text.configure(state="disabled")
        self._feed_count.configure(text="0 events")

    def _on_sse_event(self, event: dict):
        self._event_log.append(event)
        tag = "default"
        event_type = event.get("type", event.get("event", ""))
        if "job" in event_type:
            tag = "job"
        elif "workflow" in event_type:
            tag = "workflow"
        elif "error" in event_type or "fail" in event_type:
            tag = "error"

        ts = time.strftime("%H:%M:%S")
        job_id = event.get("job_id", event.get("id", ""))
        status = event.get("status", event.get("state", ""))
        line = f"[{ts}] {event_type}"
        if job_id:
            line += f"  id={job_id[:8]}"
        if status:
            line += f"  status={status}"
        if event.get("provider_id"):
            line += f"  provider={event['provider_id']}"
        line += "\n"

        def update():
            self._feed_text.configure(state="normal")
            self._feed_text.insert("end", line, tag)
            self._feed_text.see("end")
            self._feed_text.configure(state="disabled")
            self._feed_count.configure(text=f"{len(self._event_log)} events")

            # Auto-refresh current page on relevant events
            if "job" in event_type and self._current_page == "Jobs":
                self._load_jobs()
            elif "workflow" in event_type and self._current_page == "Workflows":
                self._load_workflows()
            elif self._current_page == "Dashboard":
                self._load_dashboard()

        self.after(0, update)

    # ---- SSE connection ----

    def _start_sse(self):
        if self._sse:
            self._sse.stop()
        self._sse = SSEClient(self.api.base_url, self.api.token, on_event=self._on_sse_event)
        self._sse.start()

    def _restart_sse(self):
        self._start_sse()

    # ===================================================================
    # PAGE: Dashboard
    # ===================================================================

    def _page_dashboard(self):
        f = self._page_frame

        # Stats row
        stats_frame = tk.Frame(f, bg=BG_MICA)
        stats_frame.pack(fill="x", pady=(0, 12))

        self._dash_cards: dict[str, Card] = {}
        for label in ["Total Jobs", "Running", "Succeeded", "Failed"]:
            card = Card(stats_frame, title=label)
            card.pack(side="left", fill="both", expand=True, padx=(0, 8))
            card._value = tk.Label(card, text="—", font=(FONT_FAMILY, 24, "bold"),
                                   bg=BG_CARD, fg=ACCENT)
            card._value.pack(anchor="w")
            self._dash_cards[label] = card

        # Health & load row
        row2 = tk.Frame(f, bg=BG_MICA)
        row2.pack(fill="x", pady=(0, 12))

        health_card = Card(row2, title="System Health")
        health_card.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self._health_text = tk.Label(health_card, text="Loading…", font=(FONT_FAMILY_MONO, 10),
                                     bg=BG_CARD, fg=FG_PRIMARY, justify="left", anchor="nw")
        self._health_text.pack(fill="x")

        load_card = Card(row2, title="Load & Shedding")
        load_card.pack(side="left", fill="both", expand=True)
        self._load_text = tk.Label(load_card, text="Loading…", font=(FONT_FAMILY_MONO, 10),
                                   bg=BG_CARD, fg=FG_PRIMARY, justify="left", anchor="nw")
        self._load_text.pack(fill="x")

        # Recent jobs
        recent_card = Card(f, title="Recent Jobs")
        recent_card.pack(fill="both", expand=True)
        self._recent_tree = self._create_tree(recent_card, ["ID", "Provider", "Status", "Priority", "Created"],
                                              heights={"ID": 80, "Provider": 100, "Status": 100, "Priority": 80, "Created": 140})

        self._load_dashboard()

    def _load_dashboard(self):
        def load():
            jobs = self.api.get("/jobs", limit="10")
            health = self.api.get("/health")
            load_data = self.api.get("/load")
            version = self.api.get("/version")

            self.after(0, lambda: self._update_dashboard(jobs, health, load_data, version))
        threading.Thread(target=load, daemon=True).start()

    def _update_dashboard(self, jobs, health, load_data, version):
        if not isinstance(jobs, list):
            jobs = []
        total = len(jobs)
        running = sum(1 for j in jobs if j.get("status") == "running")
        succeeded = sum(1 for j in jobs if j.get("status") == "succeeded")
        failed = sum(1 for j in jobs if j.get("status") == "failed")

        self._dash_cards["Total Jobs"]._value.configure(text=str(total))
        self._dash_cards["Running"]._value.configure(text=str(running), fg=INFO)
        self._dash_cards["Succeeded"]._value.configure(text=str(succeeded), fg=SUCCESS)
        self._dash_cards["Failed"]._value.configure(text=str(failed), fg=ERROR)

        self._health_text.configure(text=(
            f"Status:  {'OK' if health.get('ok') else 'ERROR'}\n"
            f"Engine:  {health.get('engine', '—')}\n"
            f"Jobs:    {health.get('jobs', '—')}\n"
            f"Latency: {health.get('latency_ms', '—')} ms\n"
            f"Version: {version.get('version', '—')}"
        ))
        self._load_text.configure(text=(
            f"Active:    {load_data.get('active_jobs', '—')}\n"
            f"Queued:    {load_data.get('queued_jobs', '—')}\n"
            f"Shedding:  {load_data.get('load_shedding_active', False)}\n"
            f"Circuits:  {load_data.get('open_circuits', '—')} open"
        ))

        for item in self._recent_tree.get_children():
            self._recent_tree.delete(item)
        for j in jobs[:10]:
            self._recent_tree.insert("", "end", values=(
                j.get("id", "")[:8],
                j.get("provider_id", ""),
                j.get("status", ""),
                j.get("priority", ""),
                time.strftime("%H:%M:%S", time.localtime(j.get("created_at", 0))) if j.get("created_at") else "—",
            ))

    # ===================================================================
    # PAGE: Jobs
    # ===================================================================

    def _page_jobs(self):
        f = self._page_frame

        # Toolbar
        toolbar = tk.Frame(f, bg=BG_MICA)
        toolbar.pack(fill="x", pady=(0, 8))

        FluentButton(toolbar, "＋ New Job", command=self._job_create_dialog, accent=True, width=100, height=30).pack(side="left", padx=(0, 4))
        FluentButton(toolbar, "▶ Retry", command=self._job_retry, width=80, height=30).pack(side="left", padx=(0, 4))
        FluentButton(toolbar, "⏹ Stop", command=self._job_stop, width=80, height=30).pack(side="left", padx=(0, 4))
        FluentButton(toolbar, "🗑 Delete", command=self._job_delete, width=80, height=30).pack(side="left", padx=(0, 4))
        FluentButton(toolbar, "Bulk Stop", command=self._job_bulk_stop, width=80, height=30).pack(side="left", padx=(0, 4))
        FluentButton(toolbar, "Bulk Delete", command=self._job_bulk_delete, width=90, height=30).pack(side="left", padx=(0, 4))
        FluentButton(toolbar, "↻ Refresh", command=self._load_jobs, width=80, height=30).pack(side="right")

        # Filter
        filter_frame = tk.Frame(f, bg=BG_MICA)
        filter_frame.pack(fill="x", pady=(0, 8))
        tk.Label(filter_frame, text="Status:", font=(FONT_FAMILY, 10), bg=BG_MICA, fg=FG_SECONDARY).pack(side="left", padx=(0, 4))
        self._job_filter = FluentCombo(filter_frame, values=["all", "running", "queued", "succeeded", "failed", "stopped", "timed_out", "orphaned"], width=15)
        self._job_filter.pack(side="left", padx=(0, 12))
        self._job_filter.set("all")
        FluentButton(filter_frame, "Filter", command=self._load_jobs, width=60, height=28).pack(side="left")

        # Tree
        tree_frame = tk.Frame(f, bg=BG_MICA)
        tree_frame.pack(fill="both", expand=True)
        self._job_tree = self._create_tree(tree_frame, ["ID", "Provider", "Status", "Priority", "Risk", "Retries", "Created", "Finished"],
                                            heights={"ID": 80, "Provider": 100, "Status": 100, "Priority": 80, "Risk": 70, "Retries": 60, "Created": 130, "Finished": 130})
        self._job_tree.bind("<Double-1>", lambda e: self._job_output_dialog())

        self._load_jobs()

    def _load_jobs(self):
        def load():
            status = self._job_filter.get() if hasattr(self, "_job_filter") else "all"
            params = {"limit": "200"}
            if status != "all":
                params["status"] = status
            result = self.api.get("/jobs", **params)
            self.after(0, lambda: self._update_jobs(result))
        threading.Thread(target=load, daemon=True).start()

    def _update_jobs(self, jobs):
        if not isinstance(jobs, list):
            jobs = []
        for item in self._job_tree.get_children():
            self._job_tree.delete(item)
        for j in jobs:
            self._job_tree.insert("", "end", iid=j.get("id", ""), values=(
                j.get("id", "")[:8],
                j.get("provider_id", ""),
                j.get("status", ""),
                j.get("priority", ""),
                j.get("risk", ""),
                f"{j.get('retry_count', 0)}/{j.get('max_retries', 0)}",
                time.strftime("%m/%d %H:%M", time.localtime(j["created_at"])) if j.get("created_at") else "—",
                time.strftime("%m/%d %H:%M", time.localtime(j["finished_at"])) if j.get("finished_at") else "—",
            ))

    def _selected_job_id(self) -> str | None:
        sel = self._job_tree.selection()
        return sel[0] if sel else None

    def _job_create_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Create Job")
        dlg.geometry("480x420")
        dlg.configure(bg=BG_MICA)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="Create New Job", font=(FONT_FAMILY, 16, "bold"),
                 bg=BG_MICA, fg=FG_PRIMARY).pack(pady=(16, 12))

        form = tk.Frame(dlg, bg=BG_MICA)
        form.pack(fill="both", expand=True, padx=24)

        provider = FluentEntry(form, label="Provider ID", placeholder="e.g. openai")
        provider.pack(fill="x", pady=4)
        args = FluentEntry(form, label="Arguments (JSON array)", placeholder='["--model", "gpt-4"]')
        args.pack(fill="x", pady=4)
        cwd = FluentEntry(form, label="Working Directory", placeholder="/workspace")
        cwd.pack(fill="x", pady=4)
        priority = FluentCombo(form, label="Priority", values=["urgent", "normal", "background"])
        priority.pack(fill="x", pady=4)
        risk = FluentCombo(form, label="Risk Level", values=["normal", "elevated", "high"])
        risk.pack(fill="x", pady=4)
        timeout = FluentEntry(form, label="Timeout (seconds)", placeholder="3600")
        timeout.pack(fill="x", pady=4)

        def submit():
            try:
                argv = json.loads(args.get())
            except json.JSONDecodeError:
                argv = args.get().split()
            body = {
                "provider_id": provider.get(),
                "argv": argv,
                "cwd": cwd.get() or "/workspace",
                "priority": priority.get(),
                "risk": risk.get(),
                "timeout_seconds": int(timeout.get() or 3600),
            }
            result = self.api.post("/jobs", body)
            if "error" in result:
                messagebox.showerror("Error", result["error"], parent=dlg)
            else:
                dlg.destroy()
                self._load_jobs()

        btn_frame = tk.Frame(dlg, bg=BG_MICA)
        btn_frame.pack(pady=16)
        FluentButton(btn_frame, "Create", command=submit, accent=True, width=100, height=32).pack(side="left", padx=4)
        FluentButton(btn_frame, "Cancel", command=dlg.destroy, width=100, height=32).pack(side="left", padx=4)

    def _job_stop(self):
        job_id = self._selected_job_id()
        if not job_id:
            return messagebox.showinfo("Info", "Select a job first")
        result = self.api.post(f"/jobs/{job_id}/stop")
        if "error" in result:
            messagebox.showerror("Error", result["error"])
        else:
            self._load_jobs()

    def _job_delete(self):
        job_id = self._selected_job_id()
        if not job_id:
            return messagebox.showinfo("Info", "Select a job first")
        if messagebox.askyesno("Confirm", f"Delete job {job_id[:8]}…?"):
            result = self.api.delete(f"/jobs/{job_id}")
            if "error" in result:
                messagebox.showerror("Error", result["error"])
            else:
                self._load_jobs()

    def _job_retry(self):
        job_id = self._selected_job_id()
        if not job_id:
            return messagebox.showinfo("Info", "Select a job first")
        result = self.api.post(f"/jobs/{job_id}/retry")
        if "error" in result:
            messagebox.showerror("Error", result["error"])
        else:
            self._load_jobs()

    def _job_bulk_stop(self):
        sel = self._job_tree.selection()
        if not sel:
            return messagebox.showinfo("Info", "Select jobs first")
        result = self.api.post("/jobs/bulk/stop", {"ids": list(sel)})
        if "error" in result:
            messagebox.showerror("Error", result["error"])
        else:
            self._load_jobs()

    def _job_bulk_delete(self):
        sel = self._job_tree.selection()
        if not sel:
            return messagebox.showinfo("Info", "Select jobs first")
        if messagebox.askyesno("Confirm", f"Delete {len(sel)} jobs?"):
            result = self.api.post("/jobs/bulk/delete", {"ids": list(sel)})
            if "error" in result:
                messagebox.showerror("Error", result["error"])
            else:
                self._load_jobs()

    def _job_output_dialog(self):
        job_id = self._selected_job_id()
        if not job_id:
            return
        result = self.api.get(f"/jobs/{job_id}")
        if "error" in result:
            return messagebox.showerror("Error", result["error"])

        dlg = tk.Toplevel(self)
        dlg.title(f"Job {job_id[:8]}… — Output")
        dlg.geometry("720x520")
        dlg.configure(bg=BG_MICA)
        dlg.transient(self)

        # Header
        hdr = tk.Frame(dlg, bg=BG_MICA)
        hdr.pack(fill="x", padx=16, pady=(12, 0))
        tk.Label(hdr, text=f"Job {job_id[:8]}", font=(FONT_FAMILY, 14, "bold"),
                 bg=BG_MICA, fg=FG_PRIMARY).pack(side="left")
        StatusBadge(hdr, result.get("status", "")).pack(side="left", padx=12)

        # Details
        details = tk.Frame(dlg, bg=BG_MICA)
        details.pack(fill="x", padx=16, pady=8)
        for k, v in [("Provider", result.get("provider_id")), ("Priority", result.get("priority")),
                      ("Risk", result.get("risk")), ("Retries", f"{result.get('retry_count', 0)}/{result.get('max_retries', 0)}"),
                      ("Return Code", result.get("return_code", "—"))]:
            tk.Label(details, text=f"{k}:", font=(FONT_FAMILY, 10, "bold"), bg=BG_MICA, fg=FG_SECONDARY).pack(side="left", padx=(0, 2))
            tk.Label(details, text=str(v or "—"), font=(FONT_FAMILY, 10), bg=BG_MICA, fg=FG_PRIMARY).pack(side="left", padx=(0, 12))

        # Output
        output_text = FluentText(dlg, height=20)
        output_text.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        output = result.get("output", "")
        if isinstance(output, bytes):
            try:
                output = output.decode("utf-8", errors="replace")
            except Exception:
                output = repr(output)
        output_text.set(output or "(no output)")

    # ===================================================================
    # PAGE: Workflows
    # ===================================================================

    def _page_workflows(self):
        f = self._page_frame
        toolbar = tk.Frame(f, bg=BG_MICA)
        toolbar.pack(fill="x", pady=(0, 8))
        FluentButton(toolbar, "＋ New Workflow", command=self._workflow_create_dialog, accent=True, width=120, height=30).pack(side="left", padx=(0, 4))
        FluentButton(toolbar, "🗑 Delete", command=self._workflow_delete, width=80, height=30).pack(side="left")
        FluentButton(toolbar, "↻ Refresh", command=self._load_workflows, width=80, height=30).pack(side="right")

        self._wf_tree = self._create_tree(f, ["ID", "Name", "Status", "Steps"])
        self._load_workflows()

    def _load_workflows(self):
        def load():
            result = self.api.get("/workflows")
            self.after(0, lambda: self._update_list(self._wf_tree, result, ["id", "name", "status", "steps"],
                                                     lambda v: str(len(v)) if isinstance(v, list) else str(v)))
        threading.Thread(target=load, daemon=True).start()

    def _workflow_create_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Create Workflow")
        dlg.geometry("520x400")
        dlg.configure(bg=BG_MICA)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="Create Workflow", font=(FONT_FAMILY, 16, "bold"),
                 bg=BG_MICA, fg=FG_PRIMARY).pack(pady=(16, 12))

        form = tk.Frame(dlg, bg=BG_MICA)
        form.pack(fill="both", expand=True, padx=24)
        name = FluentEntry(form, label="Name")
        name.pack(fill="x", pady=4)
        steps = FluentText(form, label="Steps (JSON array)", height=10)
        steps.set('[\n  {"provider_id": "shell", "argv": ["echo", "hello"]}\n]')
        steps.pack(fill="both", expand=True, pady=4)

        def submit():
            try:
                steps_data = json.loads(steps.get())
            except json.JSONDecodeError:
                return messagebox.showerror("Error", "Invalid JSON", parent=dlg)
            result = self.api.post("/workflows", {"name": name.get(), "steps": steps_data})
            if "error" in result:
                messagebox.showerror("Error", result["error"], parent=dlg)
            else:
                dlg.destroy()
                self._load_workflows()

        btn_frame = tk.Frame(dlg, bg=BG_MICA)
        btn_frame.pack(pady=12)
        FluentButton(btn_frame, "Create", command=submit, accent=True, width=100, height=32).pack(side="left", padx=4)
        FluentButton(btn_frame, "Cancel", command=dlg.destroy, width=100, height=32).pack(side="left", padx=4)

    def _workflow_delete(self):
        sel = self._wf_tree.selection()
        if not sel:
            return messagebox.showinfo("Info", "Select a workflow first")
        if messagebox.askyesno("Confirm", f"Delete {len(sel)} workflow(s)?"):
            for wf_id in sel:
                self.api.delete(f"/workflows/{wf_id}")
            self._load_workflows()

    # ===================================================================
    # PAGE: Templates
    # ===================================================================

    def _page_templates(self):
        f = self._page_frame
        toolbar = tk.Frame(f, bg=BG_MICA)
        toolbar.pack(fill="x", pady=(0, 8))
        FluentButton(toolbar, "＋ New Template", command=self._template_create_dialog, accent=True, width=120, height=30).pack(side="left", padx=(0, 4))
        FluentButton(toolbar, "🗑 Delete", command=self._template_delete, width=80, height=30).pack(side="left")
        FluentButton(toolbar, "↻ Refresh", command=self._load_templates, width=80, height=30).pack(side="right")

        self._tpl_tree = self._create_tree(f, ["ID", "Name", "Description"])
        self._load_templates()

    def _load_templates(self):
        def load():
            result = self.api.get("/templates")
            self.after(0, lambda: self._update_list(self._tpl_tree, result, ["id", "name", "description"]))
        threading.Thread(target=load, daemon=True).start()

    def _template_create_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Create Template")
        dlg.geometry("520x440")
        dlg.configure(bg=BG_MICA)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="Create Job Template", font=(FONT_FAMILY, 16, "bold"),
                 bg=BG_MICA, fg=FG_PRIMARY).pack(pady=(16, 12))

        form = tk.Frame(dlg, bg=BG_MICA)
        form.pack(fill="both", expand=True, padx=24)
        name = FluentEntry(form, label="Name")
        name.pack(fill="x", pady=4)
        desc = FluentEntry(form, label="Description")
        desc.pack(fill="x", pady=4)
        template = FluentText(form, label="Template JSON", height=10)
        template.set('{\n  "provider_id": "shell",\n  "argv": ["echo", "hello"],\n  "priority": "normal"\n}')
        template.pack(fill="both", expand=True, pady=4)

        def submit():
            try:
                tpl_data = json.loads(template.get())
            except json.JSONDecodeError:
                return messagebox.showerror("Error", "Invalid JSON", parent=dlg)
            result = self.api.post("/templates", {"name": name.get(), "description": desc.get(), "template": tpl_data})
            if "error" in result:
                messagebox.showerror("Error", result["error"], parent=dlg)
            else:
                dlg.destroy()
                self._load_templates()

        btn_frame = tk.Frame(dlg, bg=BG_MICA)
        btn_frame.pack(pady=12)
        FluentButton(btn_frame, "Create", command=submit, accent=True, width=100, height=32).pack(side="left", padx=4)
        FluentButton(btn_frame, "Cancel", command=dlg.destroy, width=100, height=32).pack(side="left", padx=4)

    def _template_delete(self):
        sel = self._tpl_tree.selection()
        if not sel:
            return messagebox.showinfo("Info", "Select a template first")
        if messagebox.askyesno("Confirm", f"Delete {len(sel)} template(s)?"):
            for tid in sel:
                self.api.delete(f"/templates/{tid}")
            self._load_templates()

    # ===================================================================
    # PAGE: Presets
    # ===================================================================

    def _page_presets(self):
        f = self._page_frame
        toolbar = tk.Frame(f, bg=BG_MICA)
        toolbar.pack(fill="x", pady=(0, 8))
        FluentButton(toolbar, "＋ New Preset", command=self._preset_create_dialog, accent=True, width=110, height=30).pack(side="left", padx=(0, 4))
        FluentButton(toolbar, "🗑 Delete", command=self._preset_delete, width=80, height=30).pack(side="left")
        FluentButton(toolbar, "↻ Refresh", command=self._load_presets, width=80, height=30).pack(side="right")

        self._preset_tree = self._create_tree(f, ["ID", "Name", "Provider", "Prompt"])
        self._load_presets()

    def _load_presets(self):
        def load():
            result = self.api.get("/presets")
            self.after(0, lambda: self._update_list(self._preset_tree, result, ["id", "name", "provider_id", "prompt"],
                                                     lambda v: str(v)[:50] if v else ""))
        threading.Thread(target=load, daemon=True).start()

    def _preset_create_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Create Preset")
        dlg.geometry("520x400")
        dlg.configure(bg=BG_MICA)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="Create Preset", font=(FONT_FAMILY, 16, "bold"),
                 bg=BG_MICA, fg=FG_PRIMARY).pack(pady=(16, 12))

        form = tk.Frame(dlg, bg=BG_MICA)
        form.pack(fill="both", expand=True, padx=24)
        name = FluentEntry(form, label="Name")
        name.pack(fill="x", pady=4)
        provider = FluentEntry(form, label="Provider ID")
        provider.pack(fill="x", pady=4)
        prompt = FluentEntry(form, label="Prompt")
        prompt.pack(fill="x", pady=4)
        args = FluentText(form, label="Raw Args (JSON array)", height=6)
        args.set('["--help"]')
        args.pack(fill="both", expand=True, pady=4)

        def submit():
            try:
                raw_args = json.loads(args.get())
            except json.JSONDecodeError:
                raw_args = args.get().split()
            result = self.api.post("/presets", {"name": name.get(), "provider_id": provider.get(),
                                                "prompt": prompt.get(), "raw_args": raw_args})
            if "error" in result:
                messagebox.showerror("Error", result["error"], parent=dlg)
            else:
                dlg.destroy()
                self._load_presets()

        btn_frame = tk.Frame(dlg, bg=BG_MICA)
        btn_frame.pack(pady=12)
        FluentButton(btn_frame, "Create", command=submit, accent=True, width=100, height=32).pack(side="left", padx=4)
        FluentButton(btn_frame, "Cancel", command=dlg.destroy, width=100, height=32).pack(side="left", padx=4)

    def _preset_delete(self):
        sel = self._preset_tree.selection()
        if not sel:
            return messagebox.showinfo("Info", "Select a preset first")
        if messagebox.askyesno("Confirm", f"Delete {len(sel)} preset(s)?"):
            for pid in sel:
                self.api.delete(f"/presets/{pid}")
            self._load_presets()

    # ===================================================================
    # PAGE: Analytics
    # ===================================================================

    def _page_analytics(self):
        f = self._page_frame

        stats_frame = tk.Frame(f, bg=BG_MICA)
        stats_frame.pack(fill="x", pady=(0, 12))

        self._analytics_cards: dict[str, Card] = {}
        for label in ["Total Jobs", "Success Rate", "Avg Duration", "Active Providers"]:
            card = Card(stats_frame, title=label)
            card.pack(side="left", fill="both", expand=True, padx=(0, 8))
            card._value = tk.Label(card, text="—", font=(FONT_FAMILY, 20, "bold"),
                                   bg=BG_CARD, fg=ACCENT)
            card._value.pack(anchor="w")
            self._analytics_cards[label] = card

        # Provider breakdown
        provider_card = Card(f, title="Provider Usage")
        provider_card.pack(fill="both", expand=True)
        self._provider_tree = self._create_tree(provider_card, ["Provider", "Total", "Succeeded", "Failed", "Avg Duration"])

        # Retry stats
        retry_card = Card(f, title="Retry Statistics")
        retry_card.pack(fill="both", expand=True, pady=(8, 0))
        self._retry_tree = self._create_tree(retry_card, ["Provider", "Retry Count", "Max Retries", "Policy"])

        self._load_analytics()

    def _load_analytics(self):
        def load():
            analytics = self.api.get("/analytics")
            jobs = self.api.get("/jobs", limit="500")
            self.after(0, lambda: self._update_analytics(analytics, jobs))
        threading.Thread(target=load, daemon=True).start()

    def _update_analytics(self, analytics, jobs):
        if not isinstance(jobs, list):
            jobs = []
        total = len(jobs)
        succeeded = sum(1 for j in jobs if j.get("status") == "succeeded")
        failed = sum(1 for j in jobs if j.get("status") == "failed")
        rate = f"{succeeded / total * 100:.1f}%" if total else "—"

        durations = []
        for j in jobs:
            if j.get("started_at") and j.get("finished_at"):
                durations.append(j["finished_at"] - j["started_at"])
        avg_dur = f"{sum(durations) / len(durations):.1f}s" if durations else "—"

        providers = set(j.get("provider_id", "") for j in jobs if j.get("provider_id"))

        self._analytics_cards["Total Jobs"]._value.configure(text=str(total))
        self._analytics_cards["Success Rate"]._value.configure(text=rate, fg=SUCCESS if succeeded > failed else ERROR)
        self._analytics_cards["Avg Duration"]._value.configure(text=avg_dur)
        self._analytics_cards["Active Providers"]._value.configure(text=str(len(providers)))

        # Provider breakdown
        for item in self._provider_tree.get_children():
            self._provider_tree.delete(item)
        prov_stats: dict[str, dict] = {}
        for j in jobs:
            pid = j.get("provider_id", "unknown")
            if pid not in prov_stats:
                prov_stats[pid] = {"total": 0, "succeeded": 0, "failed": 0, "durations": []}
            prov_stats[pid]["total"] += 1
            if j.get("status") == "succeeded":
                prov_stats[pid]["succeeded"] += 1
            if j.get("status") == "failed":
                prov_stats[pid]["failed"] += 1
            if j.get("started_at") and j.get("finished_at"):
                prov_stats[pid]["durations"].append(j["finished_at"] - j["started_at"])
        for pid, s in prov_stats.items():
            avg = f"{sum(s['durations']) / len(s['durations']):.1f}s" if s["durations"] else "—"
            self._provider_tree.insert("", "end", values=(pid, s["total"], s["succeeded"], s["failed"], avg))

        # Retry stats
        for item in self._retry_tree.get_children():
            self._retry_tree.delete(item)
        for j in jobs:
            if j.get("retry_count", 0) > 0:
                self._retry_tree.insert("", "end", values=(
                    j.get("provider_id", ""),
                    j.get("retry_count", 0),
                    j.get("max_retries", 0),
                    j.get("retry_policy", "—"),
                ))

    # ===================================================================
    # PAGE: Providers
    # ===================================================================

    def _page_providers(self):
        f = self._page_frame

        # Provider health / circuit breaker / rate limits
        row = tk.Frame(f, bg=BG_MICA)
        row.pack(fill="both", expand=True)

        # Circuit breaker
        cb_card = Card(row, title="Circuit Breakers")
        cb_card.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self._cb_tree = self._create_tree(cb_card, ["Provider", "State", "Failures", "Last Failure"])

        # Rate limits
        rl_card = Card(row, title="Rate Limits")
        rl_card.pack(side="left", fill="both", expand=True)
        self._rl_tree = self._create_tree(rl_card, ["Provider", "Concurrent", "RPM", "Active"])

        # Health probes
        hp_card = Card(f, title="Health Probes")
        hp_card.pack(fill="both", expand=True, pady=(8, 0))
        self._hp_tree = self._create_tree(hp_card, ["Provider", "Status", "Last Check", "Failures"])

        self._load_providers()

    def _load_providers(self):
        def load():
            cb = self.api.get("/circuit-breaker")
            rl = self.api.get("/provider-limits")
            hp = self.api.get("/health-probes")
            self.after(0, lambda: self._update_providers(cb, rl, hp))
        threading.Thread(target=load, daemon=True).start()

    def _update_providers(self, cb, rl, hp):
        for tree, data, cols in [
            (self._cb_tree, cb, ["provider_id", "state", "failure_count", "last_failure_time"]),
            (self._rl_tree, rl, ["provider_id", "max_concurrent", "max_rpm", "active_jobs"]),
            (self._hp_tree, hp, ["provider_id", "status", "last_check", "consecutive_failures"]),
        ]:
            for item in tree.get_children():
                tree.delete(item)
            items = data if isinstance(data, list) else data.get("breakers", data.get("limits", data.get("probes", [])))
            if isinstance(items, list):
                for entry in items:
                    vals = []
                    for c in cols:
                        v = entry.get(c, "—")
                        if isinstance(v, float) and c.endswith("_time"):
                            v = time.strftime("%H:%M:%S", time.localtime(v)) if v else "—"
                        vals.append(str(v))
                    tree.insert("", "end", values=vals)

    # ===================================================================
    # PAGE: Users
    # ===================================================================

    def _page_users(self):
        f = self._page_frame
        toolbar = tk.Frame(f, bg=BG_MICA)
        toolbar.pack(fill="x", pady=(0, 8))
        FluentButton(toolbar, "＋ New User", command=self._user_create_dialog, accent=True, width=100, height=30).pack(side="left", padx=(0, 4))
        FluentButton(toolbar, "🗑 Delete", command=self._user_delete, width=80, height=30).pack(side="left")
        FluentButton(toolbar, "↻ Refresh", command=self._load_users, width=80, height=30).pack(side="right")

        self._user_tree = self._create_tree(f, ["Username", "Role", "Created"])
        self._load_users()

    def _load_users(self):
        def load():
            result = self.api.get("/users")
            self.after(0, lambda: self._update_list(self._user_tree, result, ["username", "role"],
                                                     formatters={"created_at": lambda v: time.strftime("%Y-%m-%d", time.localtime(v)) if v else "—"}))
        threading.Thread(target=load, daemon=True).start()

    def _user_create_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Create User")
        dlg.geometry("420x320")
        dlg.configure(bg=BG_MICA)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="Create User", font=(FONT_FAMILY, 16, "bold"),
                 bg=BG_MICA, fg=FG_PRIMARY).pack(pady=(16, 12))

        form = tk.Frame(dlg, bg=BG_MICA)
        form.pack(fill="both", expand=True, padx=24)
        username = FluentEntry(form, label="Username")
        username.pack(fill="x", pady=4)
        password = FluentEntry(form, label="Password", show="•")
        password.pack(fill="x", pady=4)
        role = FluentCombo(form, label="Role", values=["admin", "operator", "viewer"])
        role.pack(fill="x", pady=4)

        def submit():
            result = self.api.post("/users", {"username": username.get(), "password": password.get(), "role": role.get()})
            if "error" in result:
                messagebox.showerror("Error", result["error"], parent=dlg)
            else:
                dlg.destroy()
                self._load_users()

        btn_frame = tk.Frame(dlg, bg=BG_MICA)
        btn_frame.pack(pady=12)
        FluentButton(btn_frame, "Create", command=submit, accent=True, width=100, height=32).pack(side="left", padx=4)
        FluentButton(btn_frame, "Cancel", command=dlg.destroy, width=100, height=32).pack(side="left", padx=4)

    def _user_delete(self):
        sel = self._user_tree.selection()
        if not sel:
            return messagebox.showinfo("Info", "Select a user first")
        if messagebox.askyesno("Confirm", f"Delete user {sel[0]}?"):
            self.api.delete(f"/users/{sel[0]}")
            self._load_users()

    # ===================================================================
    # PAGE: API Keys
    # ===================================================================

    def _page_api_keys(self):
        f = self._page_frame
        toolbar = tk.Frame(f, bg=BG_MICA)
        toolbar.pack(fill="x", pady=(0, 8))
        FluentButton(toolbar, "＋ New Key", command=self._apikey_create_dialog, accent=True, width=100, height=30).pack(side="left", padx=(0, 4))
        FluentButton(toolbar, "🗑 Revoke", command=self._apikey_revoke, width=80, height=30).pack(side="left")
        FluentButton(toolbar, "↻ Refresh", command=self._load_api_keys, width=80, height=30).pack(side="right")

        self._apikey_tree = self._create_tree(f, ["ID", "Name", "Role", "Created", "Expires"])
        self._load_api_keys()

    def _load_api_keys(self):
        def load():
            result = self.api.get("/api-keys")
            self.after(0, lambda: self._update_list(self._apikey_tree, result, ["id", "name", "role"],
                                                     formatters={"created_at": lambda v: time.strftime("%Y-%m-%d", time.localtime(v)) if v else "—",
                                                                 "expires_at": lambda v: time.strftime("%Y-%m-%d", time.localtime(v)) if v else "Never"}))
        threading.Thread(target=load, daemon=True).start()

    def _apikey_create_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Create API Key")
        dlg.geometry("420x300")
        dlg.configure(bg=BG_MICA)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="Create API Key", font=(FONT_FAMILY, 16, "bold"),
                 bg=BG_MICA, fg=FG_PRIMARY).pack(pady=(16, 12))

        form = tk.Frame(dlg, bg=BG_MICA)
        form.pack(fill="both", expand=True, padx=24)
        name = FluentEntry(form, label="Name")
        name.pack(fill="x", pady=4)
        role = FluentCombo(form, label="Role", values=["admin", "operator", "viewer"])
        role.pack(fill="x", pady=4)

        self._generated_key_label = None

        def submit():
            result = self.api.post("/api-keys", {"name": name.get(), "role": role.get()})
            if "error" in result:
                messagebox.showerror("Error", result["error"], parent=dlg)
            else:
                key_val = result.get("key", result.get("id", ""))
                if self._generated_key_label:
                    self._generated_key_label.configure(text=f"Key: {key_val}", fg=SUCCESS)
                else:
                    self._generated_key_label = tk.Label(form, text=f"Key: {key_val}", font=(FONT_FAMILY_MONO, 10),
                                                         bg=BG_MICA, fg=SUCCESS, wraplength=350)
                    self._generated_key_label.pack(fill="x", pady=8)
                messagebox.showinfo("API Key Created", f"Copy your key now — it won't be shown again:\n\n{key_val}", parent=dlg)
                dlg.destroy()
                self._load_api_keys()

        btn_frame = tk.Frame(dlg, bg=BG_MICA)
        btn_frame.pack(pady=12)
        FluentButton(btn_frame, "Create", command=submit, accent=True, width=100, height=32).pack(side="left", padx=4)
        FluentButton(btn_frame, "Cancel", command=dlg.destroy, width=100, height=32).pack(side="left", padx=4)

    def _apikey_revoke(self):
        sel = self._apikey_tree.selection()
        if not sel:
            return messagebox.showinfo("Info", "Select an API key first")
        if messagebox.askyesno("Confirm", f"Revoke {len(sel)} key(s)?"):
            for kid in sel:
                self.api.delete(f"/api-keys/{kid}")
            self._load_api_keys()

    # ===================================================================
    # PAGE: Webhooks
    # ===================================================================

    def _page_webhooks(self):
        f = self._page_frame
        toolbar = tk.Frame(f, bg=BG_MICA)
        toolbar.pack(fill="x", pady=(0, 8))
        FluentButton(toolbar, "＋ New Webhook", command=self._webhook_create_dialog, accent=True, width=120, height=30).pack(side="left", padx=(0, 4))
        FluentButton(toolbar, "🗑 Delete", command=self._webhook_delete, width=80, height=30).pack(side="left")
        FluentButton(toolbar, "↻ Refresh", command=self._load_webhooks, width=80, height=30).pack(side="right")

        self._webhook_tree = self._create_tree(f, ["ID", "URL", "Events", "Enabled"])
        self._load_webhooks()

    def _load_webhooks(self):
        def load():
            result = self.api.get("/webhooks")
            self.after(0, lambda: self._update_list(self._webhook_tree, result, ["id", "url", "events", "enabled"],
                                                     formatters={"events": lambda v: ", ".join(v) if isinstance(v, list) else str(v),
                                                                 "enabled": lambda v: "✓" if v else "✗"}))
        threading.Thread(target=load, daemon=True).start()

    def _webhook_create_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Create Webhook")
        dlg.geometry("480x360")
        dlg.configure(bg=BG_MICA)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="Create Webhook", font=(FONT_FAMILY, 16, "bold"),
                 bg=BG_MICA, fg=FG_PRIMARY).pack(pady=(16, 12))

        form = tk.Frame(dlg, bg=BG_MICA)
        form.pack(fill="both", expand=True, padx=24)
        url = FluentEntry(form, label="URL", placeholder="https://hooks.example.com/...")
        url.pack(fill="x", pady=4)
        secret = FluentEntry(form, label="HMAC Secret", show="•")
        secret.pack(fill="x", pady=4)
        events = FluentEntry(form, label="Events (comma-separated)", placeholder="job.completed,job.failed")
        events.pack(fill="x", pady=4)

        def submit():
            result = self.api.post("/webhooks", {
                "url": url.get(),
                "secret": secret.get(),
                "events": [e.strip() for e in events.get().split(",") if e.strip()],
            })
            if "error" in result:
                messagebox.showerror("Error", result["error"], parent=dlg)
            else:
                dlg.destroy()
                self._load_webhooks()

        btn_frame = tk.Frame(dlg, bg=BG_MICA)
        btn_frame.pack(pady=12)
        FluentButton(btn_frame, "Create", command=submit, accent=True, width=100, height=32).pack(side="left", padx=4)
        FluentButton(btn_frame, "Cancel", command=dlg.destroy, width=100, height=32).pack(side="left", padx=4)

    def _webhook_delete(self):
        sel = self._webhook_tree.selection()
        if not sel:
            return messagebox.showinfo("Info", "Select a webhook first")
        if messagebox.askyesno("Confirm", f"Delete {len(sel)} webhook(s)?"):
            for wid in sel:
                self.api.delete(f"/webhooks/{wid}")
            self._load_webhooks()

    # ===================================================================
    # PAGE: Notifications
    # ===================================================================

    def _page_notifications(self):
        f = self._page_frame
        toolbar = tk.Frame(f, bg=BG_MICA)
        toolbar.pack(fill="x", pady=(0, 8))
        FluentButton(toolbar, "＋ New Channel", command=self._notif_create_dialog, accent=True, width=120, height=30).pack(side="left", padx=(0, 4))
        FluentButton(toolbar, "🗑 Delete", command=self._notif_delete, width=80, height=30).pack(side="left")
        FluentButton(toolbar, "↻ Refresh", command=self._load_notifications, width=80, height=30).pack(side="right")

        self._notif_tree = self._create_tree(f, ["ID", "Type", "Name", "URL", "Events"])
        self._load_notifications()

    def _load_notifications(self):
        def load():
            result = self.api.get("/notifications")
            self.after(0, lambda: self._update_list(self._notif_tree, result, ["id", "type", "name", "url", "events"],
                                                     formatters={"events": lambda v: ", ".join(v) if isinstance(v, list) else str(v)}))
        threading.Thread(target=load, daemon=True).start()

    def _notif_create_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Create Notification Channel")
        dlg.geometry("480x380")
        dlg.configure(bg=BG_MICA)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="Create Notification Channel", font=(FONT_FAMILY, 16, "bold"),
                 bg=BG_MICA, fg=FG_PRIMARY).pack(pady=(16, 12))

        form = tk.Frame(dlg, bg=BG_MICA)
        form.pack(fill="both", expand=True, padx=24)
        ctype = FluentCombo(form, label="Type", values=["slack", "discord", "email"])
        ctype.pack(fill="x", pady=4)
        name = FluentEntry(form, label="Name")
        name.pack(fill="x", pady=4)
        url = FluentEntry(form, label="Webhook URL / Email Recipients")
        url.pack(fill="x", pady=4)
        events = FluentEntry(form, label="Events (comma-separated)", placeholder="job.completed,job.failed")
        events.pack(fill="x", pady=4)

        def submit():
            result = self.api.post("/notifications", {
                "type": ctype.get(),
                "name": name.get(),
                "url": url.get(),
                "events": [e.strip() for e in events.get().split(",") if e.strip()],
            })
            if "error" in result:
                messagebox.showerror("Error", result["error"], parent=dlg)
            else:
                dlg.destroy()
                self._load_notifications()

        btn_frame = tk.Frame(dlg, bg=BG_MICA)
        btn_frame.pack(pady=12)
        FluentButton(btn_frame, "Create", command=submit, accent=True, width=100, height=32).pack(side="left", padx=4)
        FluentButton(btn_frame, "Cancel", command=dlg.destroy, width=100, height=32).pack(side="left", padx=4)

    def _notif_delete(self):
        sel = self._notif_tree.selection()
        if not sel:
            return messagebox.showinfo("Info", "Select a channel first")
        if messagebox.askyesno("Confirm", f"Delete {len(sel)} channel(s)?"):
            for nid in sel:
                self.api.delete(f"/notifications/{nid}")
            self._load_notifications()

    # ===================================================================
    # PAGE: MCP Servers
    # ===================================================================

    def _page_mcp_servers(self):
        f = self._page_frame
        toolbar = tk.Frame(f, bg=BG_MICA)
        toolbar.pack(fill="x", pady=(0, 8))
        FluentButton(toolbar, "＋ New Server", command=self._mcp_create_dialog, accent=True, width=110, height=30).pack(side="left", padx=(0, 4))
        FluentButton(toolbar, "🗑 Delete", command=self._mcp_delete, width=80, height=30).pack(side="left")
        FluentButton(toolbar, "↻ Refresh", command=self._load_mcp_servers, width=80, height=30).pack(side="right")

        self._mcp_tree = self._create_tree(f, ["ID", "Name", "Command", "Args", "Status"])
        self._load_mcp_servers()

    def _load_mcp_servers(self):
        def load():
            result = self.api.get("/mcp-servers")
            self.after(0, lambda: self._update_list(self._mcp_tree, result, ["id", "name", "command", "args", "status"],
                                                     formatters={"args": lambda v: " ".join(v) if isinstance(v, list) else str(v)}))
        threading.Thread(target=load, daemon=True).start()

    def _mcp_create_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Create MCP Server")
        dlg.geometry("480x320")
        dlg.configure(bg=BG_MICA)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="Create MCP Server", font=(FONT_FAMILY, 16, "bold"),
                 bg=BG_MICA, fg=FG_PRIMARY).pack(pady=(16, 12))

        form = tk.Frame(dlg, bg=BG_MICA)
        form.pack(fill="both", expand=True, padx=24)
        name = FluentEntry(form, label="Name")
        name.pack(fill="x", pady=4)
        command = FluentEntry(form, label="Command", placeholder="npx")
        command.pack(fill="x", pady=4)
        args = FluentEntry(form, label="Arguments (comma-separated)")
        args.pack(fill="x", pady=4)

        def submit():
            result = self.api.post("/mcp-servers", {
                "name": name.get(),
                "command": command.get(),
                "args": [a.strip() for a in args.get().split(",") if a.strip()],
            })
            if "error" in result:
                messagebox.showerror("Error", result["error"], parent=dlg)
            else:
                dlg.destroy()
                self._load_mcp_servers()

        btn_frame = tk.Frame(dlg, bg=BG_MICA)
        btn_frame.pack(pady=12)
        FluentButton(btn_frame, "Create", command=submit, accent=True, width=100, height=32).pack(side="left", padx=4)
        FluentButton(btn_frame, "Cancel", command=dlg.destroy, width=100, height=32).pack(side="left", padx=4)

    def _mcp_delete(self):
        sel = self._mcp_tree.selection()
        if not sel:
            return messagebox.showinfo("Info", "Select an MCP server first")
        if messagebox.askyesno("Confirm", f"Delete {len(sel)} server(s)?"):
            for sid in sel:
                self.api.delete(f"/mcp-servers/{sid}")
            self._load_mcp_servers()

    # ===================================================================
    # PAGE: Audit Log
    # ===================================================================

    def _page_audit_log(self):
        f = self._page_frame
        toolbar = tk.Frame(f, bg=BG_MICA)
        toolbar.pack(fill="x", pady=(0, 8))
        FluentButton(toolbar, "↻ Refresh", command=self._load_audit, width=80, height=30).pack(side="left")
        FluentButton(toolbar, "Verify Chain", command=self._verify_audit, width=100, height=30).pack(side="left", padx=(8, 0))
        FluentButton(toolbar, "Export", command=self._export_audit, width=80, height=30).pack(side="right")

        self._audit_tree = self._create_tree(f, ["ID", "Time", "Action", "Actor", "Target", "Details"])
        self._load_audit()

    def _load_audit(self):
        def load():
            result = self.api.get("/audit")
            self.after(0, lambda: self._update_audit(result))
        threading.Thread(target=load, daemon=True).start()

    def _update_audit(self, entries):
        if not isinstance(entries, list):
            entries = []
        for item in self._audit_tree.get_children():
            self._audit_tree.delete(item)
        for e in entries[-200:]:
            self._audit_tree.insert("", "end", values=(
                e.get("id", ""),
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.get("timestamp", 0))) if e.get("timestamp") else "—",
                e.get("action", ""),
                e.get("actor", ""),
                f"{e.get('target_type', '')}/{e.get('target_id', '')}",
                str(e.get("details", ""))[:80],
            ))

    def _verify_audit(self):
        result = self.api.get("/audit/verify")
        if result.get("intact"):
            messagebox.showinfo("Audit Chain", f"✓ Chain intact — {result.get('valid', 0)} entries verified")
        else:
            messagebox.showwarning("Audit Chain", f"✗ Chain broken at entry {result.get('broken_at')}")

    def _export_audit(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if path:
            result = self.api.get("/audit")
            with open(path, "w") as fp:
                json.dump(result, fp, indent=2, default=str)
            messagebox.showinfo("Exported", f"Audit log saved to {path}")

    # ===================================================================
    # PAGE: Scheduler
    # ===================================================================

    def _page_scheduler(self):
        f = self._page_frame
        toolbar = tk.Frame(f, bg=BG_MICA)
        toolbar.pack(fill="x", pady=(0, 8))
        FluentButton(toolbar, "＋ New Schedule", command=self._schedule_create_dialog, accent=True, width=120, height=30).pack(side="left", padx=(0, 4))
        FluentButton(toolbar, "🗑 Delete", command=self._schedule_delete, width=80, height=30).pack(side="left")
        FluentButton(toolbar, "↻ Refresh", command=self._load_schedules, width=80, height=30).pack(side="right")

        self._sched_tree = self._create_tree(f, ["ID", "Name", "Provider", "Interval", "Enabled", "Next Run"])
        self._load_schedules()

    def _load_schedules(self):
        def load():
            result = self.api.get("/schedules")
            self.after(0, lambda: self._update_list(self._sched_tree, result, ["id", "name", "provider_id", "interval_seconds", "enabled", "next_run_at"],
                                                     formatters={"interval_seconds": lambda v: f"{v}s" if v else "—",
                                                                 "enabled": lambda v: "✓" if v else "✗",
                                                                 "next_run_at": lambda v: time.strftime("%Y-%m-%d %H:%M", time.localtime(v)) if v else "—"}))
        threading.Thread(target=load, daemon=True).start()

    def _schedule_create_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Create Schedule")
        dlg.geometry("480x380")
        dlg.configure(bg=BG_MICA)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="Create Scheduled Workflow", font=(FONT_FAMILY, 16, "bold"),
                 bg=BG_MICA, fg=FG_PRIMARY).pack(pady=(16, 12))

        form = tk.Frame(dlg, bg=BG_MICA)
        form.pack(fill="both", expand=True, padx=24)
        name = FluentEntry(form, label="Name")
        name.pack(fill="x", pady=4)
        provider = FluentEntry(form, label="Provider ID", placeholder="shell")
        provider.pack(fill="x", pady=4)
        command = FluentEntry(form, label="Command (JSON array)", placeholder='["echo", "hello"]')
        command.pack(fill="x", pady=4)
        interval = FluentEntry(form, label="Interval (seconds)", placeholder="3600")
        interval.pack(fill="x", pady=4)

        def submit():
            try:
                cmd = json.loads(command.get())
            except json.JSONDecodeError:
                cmd = command.get().split()
            result = self.api.post("/schedules", {
                "name": name.get(),
                "provider_id": provider.get(),
                "command": cmd,
                "interval_seconds": int(interval.get() or 3600),
            })
            if "error" in result:
                messagebox.showerror("Error", result["error"], parent=dlg)
            else:
                dlg.destroy()
                self._load_schedules()

        btn_frame = tk.Frame(dlg, bg=BG_MICA)
        btn_frame.pack(pady=12)
        FluentButton(btn_frame, "Create", command=submit, accent=True, width=100, height=32).pack(side="left", padx=4)
        FluentButton(btn_frame, "Cancel", command=dlg.destroy, width=100, height=32).pack(side="left", padx=4)

    def _schedule_delete(self):
        sel = self._sched_tree.selection()
        if not sel:
            return messagebox.showinfo("Info", "Select a schedule first")
        if messagebox.askyesno("Confirm", f"Delete {len(sel)} schedule(s)?"):
            for sid in sel:
                self.api.delete(f"/schedules/{sid}")
            self._load_schedules()

    # ===================================================================
    # PAGE: Settings
    # ===================================================================

    def _page_settings(self):
        f = self._page_frame

        # Connection settings
        conn_card = Card(f, title="Connection")
        conn_card.pack(fill="x", pady=(0, 12))

        form = tk.Frame(conn_card, bg=BG_CARD)
        form.pack(fill="x")
        self._settings_url = FluentEntry(form, label="Server URL", placeholder="http://127.0.0.1:8765")
        self._settings_url.set(self.api.base_url)
        self._settings_url.pack(fill="x", pady=4)
        self._settings_token = FluentEntry(form, label="Bearer Token", show="•")
        self._settings_token.set(self.api.token)
        self._settings_token.pack(fill="x", pady=4)

        FluentButton(form, "Save & Connect", command=self._settings_connect, accent=True, width=140, height=32).pack(pady=8)

        # Backup / Restore
        backup_card = Card(f, title="Database Backup & Restore")
        backup_card.pack(fill="x", pady=(0, 12))

        btn_row = tk.Frame(backup_card, bg=BG_CARD)
        btn_row.pack(fill="x")
        FluentButton(btn_row, "📥 Export Backup", command=self._backup_export, width=140, height=32).pack(side="left", padx=(0, 8))
        FluentButton(btn_row, "📤 Import Backup", command=self._backup_import, width=140, height=32).pack(side="left")

        # Version info
        version_card = Card(f, title="About")
        version_card.pack(fill="x")
        self._version_label = tk.Label(version_card, text="Version: —", font=(FONT_FAMILY, 10),
                                       bg=BG_CARD, fg=FG_PRIMARY)
        self._version_label.pack(anchor="w")
        self._load_version()

    def _settings_connect(self):
        self.api.base_url = self._settings_url.get().rstrip("/")
        self.api.token = self._settings_token.get()
        self._load_version()
        self._refresh_connection_status()
        self._restart_sse()

    def _load_version(self):
        def load():
            result = self.api.get("/version")
            self.after(0, lambda: self._version_label.configure(
                text=f"Version: {result.get('version', '—')}  |  API: {result.get('api_version', '—')}  |  Engine: {result.get('engine', '—')}"))
        threading.Thread(target=load, daemon=True).start()

    def _backup_export(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if path:
            result = self.api.get("/backup")
            with open(path, "w") as fp:
                json.dump(result, fp, indent=2, default=str)
            messagebox.showinfo("Backup", f"Backup saved to {path}")

    def _backup_import(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if path:
            with open(path) as fp:
                data = json.load(fp)
            result = self.api.post("/backup/restore", data)
            if result.get("ok"):
                messagebox.showinfo("Restore", f"Imported: {result.get('imported', {})}")
            else:
                messagebox.showerror("Error", result.get("error", "Unknown error"))

    # ===================================================================
    # Shared helpers
    # ===================================================================

    def _create_tree(self, parent, columns: list[str], heights: dict | None = None) -> ttk.Treeview:
        frame = tk.Frame(parent, bg=parent.cget("bg"))
        frame.pack(fill="both", expand=True)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", font=(FONT_FAMILY, 10), rowheight=28, background=BG_CARD,
                         fieldbackground=BG_CARD, foreground=FG_PRIMARY)
        style.configure("Treeview.Heading", font=(FONT_FAMILY, 10, "bold"), background=BG_NAV,
                         foreground=FG_PRIMARY, relief="flat")
        style.map("Treeview", background=[("selected", ACCENT_LIGHT)], foreground=[("selected", ACCENT)])

        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="extended",
                             style="Treeview")
        for col in columns:
            w = (heights or {}).get(col, 120)
            tree.heading(col, text=col.title())
            tree.column(col, width=w, minwidth=40)

        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        return tree

    def _update_list(self, tree: ttk.Treeview, data: Any, fields: list[str],
                     formatters: dict | None = None, truncate: int = 0):
        """Generic tree updater from API list response."""
        for item in tree.get_children():
            tree.delete(item)
        if not isinstance(data, list):
            return
        for entry in data:
            vals = []
            for f in fields:
                v = entry.get(f, "")
                if formatters and f in formatters:
                    v = formatters[f](v)
                elif truncate and isinstance(v, str) and len(v) > truncate:
                    v = v[:truncate] + "…"
                else:
                    v = str(v) if v is not None else ""
                vals.append(v)
            iid = entry.get("id", entry.get("username", ""))
            try:
                tree.insert("", "end", iid=iid, values=vals)
            except tk.TclError:
                tree.insert("", "end", values=vals)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = ZeazGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
