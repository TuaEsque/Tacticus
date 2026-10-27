"""
Always-on-top guild raid overlay for Tacticus.

Shows the advisor's next moves in a small, semi-transparent window that sits
over the game. It only reads the official API and draws its own window: it
does not touch the game process or automate any input.
"""
from __future__ import annotations

import argparse
import queue
import threading
import time
import tkinter as tk
import traceback
from datetime import datetime, timezone

from tacticus_raid_advisor import (
    add_common_arguments,
    build_advice,
    describe_team,
    describe_token_pool,
    format_duration,
    format_number,
    make_payload_source,
    player_token_pools,
)

MIN_REFRESH_SECONDS = 30
TICK_MS = 500
TEXT_WIDTH = 400
HP_BAR_WIDTH = 90
FONT_FAMILY = "Helvetica"

COLORS = {
    "bg": "#15171c",
    "header": "#22252d",
    "text": "#e8e8e8",
    "muted": "#9aa0a6",
    "bomb": "#ff9f43",
    "battle": "#4fc3f7",
    "wait": "#b0bec5",
    "warning": "#ffd54f",
    "error": "#ef5350",
    "hp": "#e53935",
    "hp_empty": "#3a3d45",
}


def configure_window(root: tk.Tk, opacity: float, framed: bool) -> None:
    root.title("Tacticus Raid Advisor")
    root.configure(bg=COLORS["bg"])
    root.geometry("+40+40")
    root.attributes("-topmost", True)
    try:
        root.attributes("-alpha", opacity)
    except tk.TclError:
        print("Window transparency is not supported here; continuing fully opaque.")
    if not framed:
        root.overrideredirect(True)


class RaidOverlay:
    """
    Owns the widgets and the refresh cycle.

    API calls run on a worker thread and hand results back through a queue,
    because Tk widgets may only be touched from the main thread. A periodic
    tick drains that queue, starts refreshes and updates the live countdowns.
    """

    def __init__(self, root: tk.Tk, fetch_payloads, user_id, refresh_seconds: int):
        self.root = root
        self.fetch_payloads = fetch_payloads
        self.user_id = user_id
        self.refresh_seconds = refresh_seconds

        self.results = queue.Queue()
        self.fetching = False
        self.next_refresh = 0.0
        self.payloads = None
        self.last_success = None
        self.last_error = None
        # Token counts the body was last rendered for; None forces a re-render.
        self.rendered_counts = None
        self.drag_offset = (0, 0)

        self.title_var = tk.StringVar(value="Guild Raid")
        self.tokens_var = tk.StringVar(value="Loading…")
        self.footer_var = tk.StringVar()
        self._build_chrome()
        self.root.after(0, self._tick)

    # ── Widgets ────────────────────────────────────────────────────────────

    def _label(self, parent, text="", color="text", size=10, bold=False, **kwargs):
        font = (FONT_FAMILY, size, "bold") if bold else (FONT_FAMILY, size)
        return tk.Label(
            parent, text=text, fg=COLORS[color], bg=parent["bg"], font=font,
            justify="left", anchor="w", **kwargs,
        )

    def _build_chrome(self):
        header = tk.Frame(self.root, bg=COLORS["header"], padx=8, pady=4)
        header.pack(fill="x")
        title = self._label(header, textvariable=self.title_var, size=11, bold=True)
        title.pack(side="left")
        for symbol, command in (("✕", self.root.destroy), ("⟳", self.refresh_now)):
            tk.Button(
                header, text=symbol, command=command, fg=COLORS["text"], bg=COLORS["header"],
                activebackground=COLORS["bg"], activeforeground=COLORS["text"],
                relief="flat", bd=0, highlightthickness=0, padx=6, cursor="hand2",
            ).pack(side="right")
        for widget in (header, title):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag)

        self._label(self.root, textvariable=self.tokens_var, bold=True, padx=10, pady=4).pack(fill="x")
        self.body = tk.Frame(self.root, bg=COLORS["bg"], padx=10)
        self.body.pack(fill="both", expand=True)
        self._label(self.body, "Fetching guild raid data…", color="muted").pack(anchor="w")
        self.footer = self._label(self.root, textvariable=self.footer_var, color="muted", size=8, padx=10, pady=4)
        self.footer.pack(fill="x")

        self.root.bind("<Escape>", lambda _event: self.root.destroy())
        self.root.bind("<F5>", lambda _event: self.refresh_now())

    def _start_drag(self, event):
        self.drag_offset = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag(self, event):
        dx, dy = self.drag_offset
        self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def _section(self, title):
        self._label(self.body, title, color="muted", size=8, bold=True, pady=2).pack(anchor="w", pady=(8, 0))

    def _hp_bar(self, parent, encounter):
        bar = tk.Canvas(parent, width=HP_BAR_WIDTH, height=8, bg=COLORS["hp_empty"], highlightthickness=0)
        if encounter.remaining_hp is not None and encounter.max_hp:
            share = max(0.0, min(1.0, encounter.remaining_hp / encounter.max_hp))
            bar.create_rectangle(0, 0, int(HP_BAR_WIDTH * share), 8, fill=COLORS["hp"], width=0)
        return bar

    def _encounter_row(self, table, row, encounter):
        name_color = "muted" if encounter.is_defeated else "text"
        self._label(table, encounter.name, color=name_color, size=9).grid(row=row, column=0, sticky="w")
        self._hp_bar(table, encounter).grid(row=row, column=1, padx=6)
        if encounter.is_defeated:
            status = "defeated"
        else:
            status = f"{format_number(encounter.remaining_hp)} / {format_number(encounter.max_hp)}"
        if encounter.battles_in_progress:
            status += f"  ⚔{encounter.battles_in_progress} in progress"
        self._label(table, status, color="muted", size=9).grid(row=row, column=2, sticky="w")

    # ── Rendering ──────────────────────────────────────────────────────────

    def _render(self):
        raid_payload, player_payload = self.payloads
        advice = build_advice(raid_payload, player_payload, self.user_id)

        for child in self.body.winfo_children():
            child.destroy()
        season = f" · Season {advice.season}" if advice.season is not None else ""
        self.title_var.set(f"Guild Raid{season}")

        self._section("NEXT MOVES")
        for number, action in enumerate(advice.actions, 1):
            self._label(self.body, f"{number}. {action.headline}", color=action.kind, bold=True).pack(anchor="w")
            self._label(self.body, action.reason, color="muted", size=9, wraplength=TEXT_WIDTH).pack(
                anchor="w", padx=(14, 0)
            )

        if advice.encounters:
            first = advice.encounters[0]
            self._section(f"ENCOUNTERS · tier {first.tier}, set {first.set_index}")
            # One grid for all rows keeps the HP bars aligned.
            table = tk.Frame(self.body, bg=COLORS["bg"])
            table.pack(fill="x")
            for row, encounter in enumerate(advice.encounters):
                self._encounter_row(table, row, encounter)

        target = advice.battle_target
        if target is not None and advice.teams.get(target.key):
            self._section(f"BEST TEAMS vs {target.boss_type}")
            for stats in advice.teams[target.key]:
                source = "you" if stats.yours else "guild"
                text = (
                    f"{format_number(stats.mean_damage)} avg ×{stats.battles} [{source}]  "
                    f"{describe_team(stats.team, advice.unit_names)}"
                )
                self._label(self.body, text, size=9, wraplength=TEXT_WIDTH).pack(anchor="w")

        for warning in advice.warnings:
            self._label(self.body, f"! {warning}", color="warning", size=9, wraplength=TEXT_WIDTH).pack(
                anchor="w", pady=(4, 0)
            )

    def _render_safely(self):
        try:
            self._render()
        except Exception as exc:  # UI boundary: an unexpected payload must not kill the overlay.
            traceback.print_exc()
            self.last_error = f"could not analyse data: {exc}"

    def _update_live(self):
        if self.payloads is not None:
            raid_tokens, bomb_tokens = player_token_pools(self.payloads[1], datetime.now(timezone.utc))
            self.tokens_var.set(
                f"{describe_token_pool('Raid tokens', raid_tokens)}    {describe_token_pool('Bombs', bomb_tokens)}"
            )
            # Re-render when new data arrives or a token regenerates, since the advice depends on both.
            counts = (
                raid_tokens.current if raid_tokens else None,
                bomb_tokens.current if bomb_tokens else None,
            )
            if counts != self.rendered_counts:
                self.rendered_counts = counts
                self._render_safely()

        if self.last_error is not None:
            stale = f" · showing data from {self.last_success:%H:%M}" if self.last_success else ""
            self.footer.configure(fg=COLORS["error"])
            self.footer_var.set(f"Refresh failed: {self.last_error}{stale}")
            return

        self.footer.configure(fg=COLORS["muted"])
        if self.fetching:
            self.footer_var.set("Refreshing…")
        else:
            wait = format_duration(self.next_refresh - time.monotonic())
            updated = f"Updated {self.last_success:%H:%M:%S} · " if self.last_success else ""
            self.footer_var.set(f"{updated}next refresh in {wait} · F5 refresh · Esc close")

    # ── Refresh cycle ──────────────────────────────────────────────────────

    def refresh_now(self):
        self.next_refresh = 0.0

    def _tick(self):
        # Schedule first so an unexpected error below can't stop the loop.
        self.root.after(TICK_MS, self._tick)
        self._collect_result()
        if not self.fetching and time.monotonic() >= self.next_refresh:
            self.fetching = True
            threading.Thread(target=self._fetch_worker, daemon=True).start()
        self._update_live()

    def _fetch_worker(self):
        try:
            payloads = self.fetch_payloads()
        except Exception as exc:  # Thread boundary: report every failure in the UI.
            self.results.put(("error", exc))
        else:
            self.results.put(("ok", payloads))

    def _collect_result(self):
        try:
            status, value = self.results.get_nowait()
        except queue.Empty:
            return

        self.fetching = False
        self.next_refresh = time.monotonic() + self.refresh_seconds
        if status == "ok":
            self.payloads = value
            self.last_success = datetime.now()
            self.last_error = None
            self.rendered_counts = None
        else:
            self.last_error = value


def parse_args():
    parser = argparse.ArgumentParser(description="Always-on-top guild raid advisor overlay for Tacticus.")
    add_common_arguments(parser)
    parser.add_argument(
        "--refresh", type=int, default=120,
        help=f"Seconds between API refreshes (default 120, minimum {MIN_REFRESH_SECONDS}).",
    )
    parser.add_argument("--opacity", type=float, default=0.9, help="Window opacity from 0.3 to 1.0 (default 0.9).")
    parser.add_argument(
        "--framed", action="store_true",
        help="Keep the normal window frame (use this if the borderless window misbehaves).",
    )
    args = parser.parse_args()

    if args.refresh < MIN_REFRESH_SECONDS:
        parser.error(f"--refresh must be at least {MIN_REFRESH_SECONDS} seconds")
    if not 0.3 <= args.opacity <= 1.0:
        parser.error("--opacity must be between 0.3 and 1.0")
    return args


def main():
    args = parse_args()
    # Prompts for any missing API keys in the terminal before the window opens.
    fetch_payloads = make_payload_source(args.raid_file, args.player_file)

    root = tk.Tk()
    configure_window(root, args.opacity, args.framed)
    RaidOverlay(root, fetch_payloads, args.user_id, args.refresh)
    root.mainloop()


if __name__ == "__main__":
    main()
