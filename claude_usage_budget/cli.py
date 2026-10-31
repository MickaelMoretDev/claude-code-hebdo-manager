"""
claude-usage-budget
===================

Pace your Claude *weekly* usage limit with per-day caps.

Two entry points:

* ``claude-usage-budget statusline`` — reads the JSON Claude Code pipes to a
  statusline command on stdin, prints a one-line colored status, and fires a
  desktop notification (Windows toast / WSL / Linux notify-send / macOS) the
  first time a cap is crossed.
* ``claude-usage-budget check --used 42`` — same logic with a manual value,
  handy for testing or for cron jobs.

Zero dependencies, Python 3.8+.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import math
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__

# --------------------------------------------------------------------------- #
# Paths & defaults
# --------------------------------------------------------------------------- #

CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
CONFIG_PATH = Path(os.environ.get("CLAUDE_USAGE_BUDGET_CONFIG", CLAUDE_DIR / "usage-budget.json"))
STATE_PATH = Path(os.environ.get("CLAUDE_USAGE_BUDGET_STATE", CLAUDE_DIR / "usage-budget-state.json"))

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# --------------------------------------------------------------------------- #
# Localisation (en by default, "lang": "fr" in the config switches to French)
# --------------------------------------------------------------------------- #

STRINGS: Dict[str, Dict[str, str]] = {
    "en": {
        "label": "weekly",
        "cap": "cap",
        "margin": "margin",
        "reset": "reset",
        "now": "now",
        "day_prefix": "d",
        "notif_over_title": "Claude — daily cap exceeded",
        "notif_over_body": "{label} usage {used:.0f}% ≥ cap {cap:.0f}% ({day}).",
        "notif_warn_title": "Claude — close to today's cap",
        "notif_warn_body": "{label} usage {used:.0f}% — cap {cap:.0f}% ({day}).",
        "notif_global_title": "Claude — {thr}% of the {label} limit",
        "notif_global_body": "{label} usage at {used:.0f}%.",
        "notif_test": "Notifications are working ✔",
        "sim_header": "{d:>5} {p:>12} {c:>8} {m:>11} {e:>12}  status",
        "sim_day": "day", "sim_plan": "planned cum.", "sim_cap": "cap",
        "sim_margin": "day margin", "sim_end": "end of day",
        "sim_ok": "ok", "sim_warn": "⚠ close", "sim_over": "✖ exceeded",
        "cfg_exists": "Config already present: {path} (use --force to overwrite)",
        "cfg_written": "Config written: {path}",
        "add_to_settings": "\nAdd this to ~/.claude/settings.json:\n",
        "quick_test": "\nQuick test:  claude-usage-budget check --used 42 --reset-in-hours 60",
        "notif_test_cmd": "Notif test:  claude-usage-budget test-notify",
        "config": "Config: {path}",
        "no_editor": "No editor found. File: {path}",
        "ramp_count": "ramp expects 7 cumulative values (d1..d7), e.g.: set ramp 30 45 60 72 84 94 100",
        "ramp_increasing": "ramp must be non-decreasing (cumulative caps).",
        "unknown_key": "Unknown key: {k}. Valid keys: {keys}",
        "notif_sent": "[{env}] notification sent",
        "notif_failed": "[{env}] notification FAILED (no backend found)",
        "state_reset": "State reset: {path}",
        "no_state": "No state to reset.",
        "state": "State:  {path}",
    },
    "fr": {
        "label": "hebdo",
        "cap": "plafond",
        "margin": "marge",
        "reset": "reset",
        "now": "maintenant",
        "day_prefix": "j",
        "notif_over_title": "Claude — plafond du jour dépassé",
        "notif_over_body": "Usage {label} {used:.0f} % ≥ plafond {cap:.0f} % ({day}).",
        "notif_warn_title": "Claude — proche du plafond du jour",
        "notif_warn_body": "Usage {label} {used:.0f} % — plafond {cap:.0f} % ({day}).",
        "notif_global_title": "Claude — {thr} % de la limite {label}",
        "notif_global_body": "Usage {label} à {used:.0f} %.",
        "notif_test": "Les notifications fonctionnent ✔",
        "sim_header": "{d:>5} {p:>12} {c:>8} {m:>11} {e:>12}  statut",
        "sim_day": "jour", "sim_plan": "plan cumulé", "sim_cap": "plafond",
        "sim_margin": "marge jour", "sim_end": "fin de jour",
        "sim_ok": "ok", "sim_warn": "⚠ proche", "sim_over": "✖ dépassé",
        "cfg_exists": "Config déjà présente : {path} (utilise --force pour écraser)",
        "cfg_written": "Config écrite : {path}",
        "add_to_settings": "\nÀ ajouter dans ~/.claude/settings.json :\n",
        "quick_test": "\nTest rapide :  claude-usage-budget check --used 42 --reset-in-hours 60",
        "notif_test_cmd": "Test notif  :  claude-usage-budget test-notify",
        "config": "Config : {path}",
        "no_editor": "Aucun éditeur trouvé. Fichier : {path}",
        "ramp_count": "ramp attend 7 valeurs cumulées (j1..j7), ex. : set ramp 30 45 60 72 84 94 100",
        "ramp_increasing": "ramp doit être croissante (plafonds cumulés).",
        "unknown_key": "Clé inconnue : {k}. Clés valides : {keys}",
        "notif_sent": "[{env}] notification envoyée",
        "notif_failed": "[{env}] notification IMPOSSIBLE (aucun backend trouvé)",
        "state_reset": "État réinitialisé : {path}",
        "no_state": "Aucun état à réinitialiser.",
        "state": "État   : {path}",
    },
}


def tr(cfg: Dict[str, Any], key: str, **kw: Any) -> str:
    lang = str(cfg.get("lang", "en")).lower()[:2]
    table = STRINGS.get(lang, STRINGS["en"])
    return table.get(key, STRINGS["en"].get(key, key)).format(**kw)


def display_label(cfg: Dict[str, Any]) -> str:
    """Word shown before the percentage: config `label`, else per-language default."""
    return str(cfg.get("label") or tr(cfg, "label"))


DEFAULT_CONFIG: Dict[str, Any] = {
    # "reset"    -> caps are indexed by the number of days elapsed since the
    #               weekly window started (day 0 = first day after reset).
    #               Robust whatever weekday your week resets on.
    # "calendar" -> caps are keyed by weekday name (mon..sun, local time).
    "mode": "reset",
    # Cumulative caps (% of the weekly limit) for mode "reset": day 0..6.
    "ramp": [15, 30, 45, 60, 75, 90, 100],
    # Cumulative caps for mode "calendar".
    "calendar": {"mon": 15, "tue": 30, "wed": 45, "thu": 60, "fri": 75, "sat": 90, "sun": 100},
    # Weekday on which your weekly window resets (used by mode "calendar" to
    # order the days; mode "reset" reads it from Claude Code directly).
    "week_starts": "sat",
    # Adaptive caps: unused margin of past days is spread over the remaining
    # days of the window, proportionally to their planned share.
    "redistribute": True,
    # If False, overspending a day does NOT shrink the following days' caps
    # (only slack is redistributed, never debt).
    "carry_overspend": True,
    # Warn when usage reaches this fraction of today's cap (0.9 = 90 %).
    "warn_ratio": 0.9,
    # Extra one-shot alerts on the raw weekly percentage, whatever the day.
    "global_alerts": [50, 75, 90, 100],
    # Which rate limit bucket drives the budget. "seven_day" is the account-wide
    # weekly limit; model-specific buckets (e.g. "seven_day_fable") are shown
    # as secondary info when present.
    "primary_bucket": "seven_day",
    "notify": True,
    "show_model": True,
    "show_reset": True,
    "show_five_hour": True,
    # UI language for the statusline and notifications: "en" or "fr".
    "lang": "en",
    # Word shown before the percentage; empty -> language default.
    "label": "",
    "colors": True,
}


# --------------------------------------------------------------------------- #
# Config / state helpers
# --------------------------------------------------------------------------- #


def load_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save_json(path: Path, data: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        tmp.replace(path)
    except OSError:
        # Never break the statusline because of a disk hiccup.
        pass


def load_config() -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    user = load_json(CONFIG_PATH, {})
    if isinstance(user, dict):
        cfg.update(user)
    return cfg


# --------------------------------------------------------------------------- #
# Time helpers
# --------------------------------------------------------------------------- #


def parse_reset(value: Any) -> Optional[dt.datetime]:
    """Claude Code sends resets_at either as ISO-8601 or epoch seconds."""
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            # Heuristic: milliseconds if absurdly large.
            if value > 1e12:
                value = value / 1000.0
            return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc)
        if isinstance(value, str):
            s = value.strip()
            if s.isdigit():
                return parse_reset(int(s))
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            d = dt.datetime.fromisoformat(s)
            if d.tzinfo is None:
                d = d.replace(tzinfo=dt.timezone.utc)
            return d
    except (ValueError, OverflowError, OSError):
        return None
    return None


def humanize_delta(delta: dt.timedelta, cfg: Optional[Dict[str, Any]] = None) -> str:
    cfg = cfg or {}
    secs = int(delta.total_seconds())
    if secs <= 0:
        return tr(cfg, "now")
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}{tr(cfg, 'day_prefix')} {hours:02d}h"
    if hours:
        return f"{hours}h{minutes:02d}"
    return f"{minutes}min"


# --------------------------------------------------------------------------- #
# Budget logic
# --------------------------------------------------------------------------- #


def _cumulative_plan(cfg: Dict[str, Any], now: dt.datetime, resets_at: Optional[dt.datetime]):
    """
    Return (plan, idx, label):
      plan  -> list of 7 cumulative caps (%), day 0 = first day of the window
      idx   -> index of the current day in that list (0..6)
      label -> short label for display ("j2" or "tue")
    """
    mode = cfg.get("mode", "reset")
    if mode == "reset" and resets_at is not None:
        remaining = resets_at - now
        days_left = max(0.0, remaining.total_seconds() / 86400.0)
        idx = 7 - int(math.ceil(days_left))  # 0..6 (7 only at the exact reset second)
        idx = min(max(idx, 0), 6)
        ramp: List[float] = list(cfg.get("ramp") or DEFAULT_CONFIG["ramp"])
        if len(ramp) < 7:
            ramp += [100.0] * (7 - len(ramp))
        plan = [float(x) for x in ramp[:7]]
        return plan, idx, f"{tr(cfg, 'day_prefix')}{idx + 1}"

    # calendar mode (or no resets_at available): order weekdays from week_starts
    cal = cfg.get("calendar") or DEFAULT_CONFIG["calendar"]
    start = str(cfg.get("week_starts", "sat")).lower()[:3]
    start_i = WEEKDAYS.index(start) if start in WEEKDAYS else 5
    ordered = [WEEKDAYS[(start_i + i) % 7] for i in range(7)]
    plan = [float(cal.get(d, 100)) for d in ordered]
    today = WEEKDAYS[now.astimezone().weekday()]
    idx = ordered.index(today)
    return plan, idx, today


def _increments(plan: List[float]) -> List[float]:
    inc, prev = [], 0.0
    for c in plan:
        inc.append(max(0.0, c - prev))
        prev = max(prev, c)
    return inc


def day_cap(cfg: Dict[str, Any], now: dt.datetime, resets_at: Optional[dt.datetime],
            used: float, state: Dict[str, Any]) -> (float, str, float, float):
    """
    Return (cap_percent, label, planned_cap, allowance_delta).

    ``allowance_delta`` is today's adaptive allowance minus today's planned
    allowance (in points of weekly %): +2 means "you may spend 2 points more
    than planned today thanks to earlier savings".

    With ``redistribute`` on, the cap is adaptive: whatever was not consumed
    (or was over-consumed) on previous days is spread over the remaining days
    proportionally to their planned share. ``state`` is read/updated with the
    usage observed at the start of each day of the window.
    """
    plan, idx, label = _cumulative_plan(cfg, now, resets_at)
    planned = plan[idx]

    if not cfg.get("redistribute", True):
        return planned, label, planned, 0.0

    # Usage snapshot at the start of the current day (first observation wins).
    starts: Dict[str, float] = state.setdefault("day_start_used", {})
    key = str(idx)
    if key not in starts:
        # Earlier days never observed (tool installed mid-week): backfill with
        # the current value so they don't count as "unused margin".
        for i in range(idx + 1):
            starts.setdefault(str(i), used)
    used_at_start = float(starts[key])

    inc = _increments(plan)
    share_today = inc[idx]
    share_remaining = sum(inc[idx:]) or 1.0
    total = plan[-1] if plan else 100.0
    remaining_budget = max(0.0, total - used_at_start)
    adaptive = used_at_start + remaining_budget * (share_today / share_remaining)

    if not cfg.get("carry_overspend", True):
        adaptive = max(adaptive, planned)
    allowance_delta = (adaptive - used_at_start) - share_today
    return round(adaptive, 1), label, planned, round(allowance_delta, 1)


def evaluate(used: float, cap: float, warn_ratio: float) -> str:
    if used >= cap:
        return "over"
    if used >= cap * warn_ratio:
        return "warn"
    return "ok"


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #

TOAST_PS = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml(@"
<toast><visual><binding template="ToastGeneric"><text>__TITLE__</text><text>__BODY__</text></binding></visual></toast>
"@)
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
$appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
"""


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def is_wsl() -> bool:
    if sys.platform != "linux":
        return False
    try:
        with open("/proc/version", "r", encoding="utf-8") as fh:
            return "microsoft" in fh.read().lower()
    except OSError:
        return False


def _run_quiet(cmd: List[str]) -> bool:
    kwargs: Dict[str, Any] = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  stdin=subprocess.DEVNULL)
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(cmd, **kwargs)
        return True
    except (OSError, ValueError):
        return False


def notify(title: str, body: str) -> bool:
    """Best-effort desktop notification. Never raises."""
    title_x, body_x = _xml_escape(title), _xml_escape(body)

    # Windows native or WSL -> PowerShell toast
    if sys.platform == "win32" or is_wsl():
        ps = shutil.which("powershell.exe") or shutil.which("pwsh.exe") or shutil.which("powershell")
        if not ps and is_wsl():
            for cand in ("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",):
                if os.path.exists(cand):
                    ps = cand
                    break
        if ps:
            script = TOAST_PS.replace("__TITLE__", title_x).replace("__BODY__", body_x)
            encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
            return _run_quiet([ps, "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                               "-EncodedCommand", encoded])

    # macOS
    if sys.platform == "darwin":
        osa = shutil.which("osascript")
        if osa:
            safe_title = title.replace('"', '\\"')
            safe_body = body.replace('"', '\\"')
            return _run_quiet([osa, "-e", f'display notification "{safe_body}" with title "{safe_title}"'])

    # Linux desktop
    if sys.platform.startswith("linux"):
        ns = shutil.which("notify-send")
        if ns:
            return _run_quiet([ns, "-a", "Claude Usage Budget", "-u", "normal", title, body])

    return False


# --------------------------------------------------------------------------- #
# Alert state (one shot per threshold per weekly window)
# --------------------------------------------------------------------------- #


def load_state(cfg: Dict[str, Any], now: dt.datetime, resets_at: Optional[dt.datetime]) -> Dict[str, Any]:
    """Load the per-window state, starting a fresh one when the window changed."""
    state = load_json(STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    if resets_at is not None:
        window_key = resets_at.isoformat()
    else:
        # No reset info: derive the window from week_starts (calendar mode).
        start = str(cfg.get("week_starts", "sat")).lower()[:3]
        start_i = WEEKDAYS.index(start) if start in WEEKDAYS else 5
        local = now.astimezone()
        back = (local.weekday() - start_i) % 7
        window_key = (local - dt.timedelta(days=back)).strftime("week-%Y-%m-%d")
    if state.get("window") != window_key:
        state = {"window": window_key, "fired": [], "day_start_used": {}}
    state.setdefault("fired", [])
    state.setdefault("day_start_used", {})
    return state


def process_alerts(cfg: Dict[str, Any], state: Dict[str, Any], used: float, cap: float,
                   cap_label: str, status: str, dry_run: bool = False) -> List[str]:
    """Fire notifications for newly crossed thresholds. Returns the list fired."""
    fired: List[str] = list(state.get("fired", []))
    newly: List[str] = []

    def fire(key: str, title: str, body: str) -> None:
        if key in fired:
            return
        fired.append(key)
        newly.append(key)
        if cfg.get("notify", True) and not dry_run:
            notify(title, body)

    label = display_label(cfg)
    if status == "over":
        fire(f"day:{cap_label}:over",
             tr(cfg, "notif_over_title"),
             tr(cfg, "notif_over_body", label=label, used=used, cap=cap, day=cap_label))
    elif status == "warn":
        fire(f"day:{cap_label}:warn",
             tr(cfg, "notif_warn_title"),
             tr(cfg, "notif_warn_body", label=label, used=used, cap=cap, day=cap_label))

    for thr in cfg.get("global_alerts", []):
        try:
            t = float(thr)
        except (TypeError, ValueError):
            continue
        if used >= t:
            fire(f"global:{int(t)}",
                 tr(cfg, "notif_global_title", thr=int(t), label=label),
                 tr(cfg, "notif_global_body", label=label, used=used))

    state["fired"] = fired
    state["last_used"] = used
    state["last_seen"] = dt.datetime.now(dt.timezone.utc).isoformat()
    if not dry_run:
        save_json(STATE_PATH, state)
    return newly


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

ANSI = {
    "ok": "\033[32m",
    "warn": "\033[33m",
    "over": "\033[31m",
    "dim": "\033[2m",
    "reset": "\033[0m",
}


def paint(text: str, color: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{ANSI.get(color, '')}{text}{ANSI['reset']}"


def bar(pct: float, cap: float, width: int = 10) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = int(round(pct / 100.0 * width))
    cap_pos = int(round(max(0.0, min(100.0, cap)) / 100.0 * width))
    cells = []
    for i in range(width):
        if i < filled:
            cells.append("█")
        elif i == cap_pos:
            cells.append("┆")
        else:
            cells.append("░")
    return "".join(cells)


def extract_buckets(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rl = payload.get("rate_limits") or {}
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(rl, dict):
        for key, val in rl.items():
            if isinstance(val, dict):
                out[key] = val
    return out


def used_pct(bucket: Dict[str, Any]) -> Optional[float]:
    for k in ("used_percentage", "used_percent", "utilization", "used"):
        if k in bucket and bucket[k] is not None:
            try:
                v = float(bucket[k])
                return v * 100.0 if 0.0 < v <= 1.0 and k == "utilization" else v
            except (TypeError, ValueError):
                continue
    return None


def render(cfg: Dict[str, Any], payload: Dict[str, Any], now: Optional[dt.datetime] = None,
           dry_run: bool = False) -> str:
    now = now or dt.datetime.now(dt.timezone.utc)
    colors = bool(cfg.get("colors", True)) and os.environ.get("NO_COLOR") is None
    buckets = extract_buckets(payload)
    primary_key = cfg.get("primary_bucket", "seven_day")
    primary = buckets.get(primary_key)

    parts: List[str] = []

    if cfg.get("show_model", True):
        model = payload.get("model") or {}
        name = model.get("display_name") or model.get("id") if isinstance(model, dict) else None
        if name:
            parts.append(paint(str(name), "dim", colors))

    if primary is None or used_pct(primary) is None:
        parts.append(paint(f"{display_label(cfg)} n/a", "dim", colors))
        return " │ ".join(parts)

    used = used_pct(primary) or 0.0
    resets_at = parse_reset(primary.get("resets_at"))
    state = load_state(cfg, now, resets_at)
    cap, cap_label, planned, delta = day_cap(cfg, now, resets_at, used, state)
    status = evaluate(used, cap, float(cfg.get("warn_ratio", 0.9)))

    label = display_label(cfg)
    main = f"{label} {used:.0f}% {bar(used, cap)} {tr(cfg, 'cap')} {cap_label} {cap:.0f}%"
    if cfg.get("redistribute", True) and abs(delta) >= 0.5:
        sign = "+" if delta > 0 else "−"
        main += f" ({tr(cfg, 'margin')} {sign}{abs(delta):.0f})"
    if status == "over":
        main += " ✖"
    elif status == "warn":
        main += " ⚠"
    parts.append(paint(main, status, colors))

    # Secondary weekly buckets (per-model), if any.
    for key, b in sorted(buckets.items()):
        if key == primary_key or not key.startswith("seven_day"):
            continue
        u = used_pct(b)
        if u is not None:
            short = key.replace("seven_day_", "").replace("seven_day", "")
            parts.append(paint(f"{short} {u:.0f}%", "dim", colors))

    if cfg.get("show_five_hour", True):
        fh = buckets.get("five_hour")
        u = used_pct(fh) if fh else None
        if u is not None:
            parts.append(paint(f"5h {u:.0f}%", "dim", colors))

    if cfg.get("show_reset", True) and resets_at:
        parts.append(paint(f"{tr(cfg, 'reset')} {humanize_delta(resets_at - now, cfg)}", "dim", colors))

    process_alerts(cfg, state, used, cap, cap_label, status, dry_run=dry_run)
    return " │ ".join(parts)


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def cmd_statusline(args: argparse.Namespace) -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {}
    cfg = load_config()
    sys.stdout.write(render(cfg, payload))
    sys.stdout.flush()
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    cfg = load_config()
    resets_at = None
    if args.reset_in_hours is not None:
        resets_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=args.reset_in_hours)
    payload = {
        "model": {"display_name": args.model} if args.model else {},
        "rate_limits": {
            "seven_day": {
                "used_percentage": args.used,
                "resets_at": resets_at.isoformat() if resets_at else None,
            }
        },
    }
    print(render(cfg, payload, dry_run=args.dry_run))
    return 0


def cmd_simulate(args: argparse.Namespace) -> int:
    """Replay a week of usage values and print the adaptive caps day by day."""
    cfg = load_config()
    values = [float(v) for v in args.used]
    plan = list(cfg.get("ramp") or DEFAULT_CONFIG["ramp"])
    state: Dict[str, Any] = {"window": "sim", "fired": [], "day_start_used": {}}
    base = dt.datetime(2026, 1, 3, 10, 0, tzinfo=dt.timezone.utc)  # a Saturday
    resets_at = base + dt.timedelta(days=7)
    print(tr(cfg, "sim_header", d=tr(cfg, "sim_day"), p=tr(cfg, "sim_plan"), c=tr(cfg, "sim_cap"),
             m=tr(cfg, "sim_margin"), e=tr(cfg, "sim_end")))
    for i, end_of_day_used in enumerate(values[:7]):
        now = base + dt.timedelta(days=i, hours=1)
        # start of day: cap computed from yesterday's end value
        used_start = values[i - 1] if i else 0.0
        cap, label, planned, delta = day_cap(cfg, now, resets_at, used_start, state)
        status = evaluate(end_of_day_used, cap, float(cfg.get("warn_ratio", 0.9)))
        mark = tr(cfg, f"sim_{status}")
        margin = f"{delta:+.1f}" if abs(delta) >= 0.05 else "—"
        print(f"{label:>5} {planned:>11.0f}% {cap:>7.1f}% {margin:>11} {end_of_day_used:>11.0f}%  {mark}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    cfg = load_config()
    if CONFIG_PATH.exists() and not args.force:
        print(tr(cfg, "cfg_exists", path=CONFIG_PATH))
    else:
        if args.lang:
            cfg = dict(DEFAULT_CONFIG, lang=args.lang)
        else:
            cfg = dict(DEFAULT_CONFIG)
        save_json(CONFIG_PATH, cfg)
        print(tr(cfg, "cfg_written", path=CONFIG_PATH))
    exe = shutil.which("claude-usage-budget") or "claude-usage-budget"
    snippet = {
        "statusLine": {
            "type": "command",
            "command": f"{exe} statusline",
            "padding": 0,
        }
    }
    print(tr(cfg, "add_to_settings"))
    print(json.dumps(snippet, indent=2))
    print(tr(cfg, "quick_test"))
    print(tr(cfg, "notif_test_cmd"))
    return 0


def _ensure_config() -> None:
    if not CONFIG_PATH.exists():
        save_json(CONFIG_PATH, DEFAULT_CONFIG)


def cmd_edit(args: argparse.Namespace) -> int:
    """Open the config file in an editor (VS Code if available)."""
    _ensure_config()
    if args.path:
        print(CONFIG_PATH)
        return 0
    candidates: List[List[str]] = []
    for var in ("VISUAL", "EDITOR"):
        val = os.environ.get(var)
        if val:
            candidates.append(val.split())
    if shutil.which("code"):
        candidates.insert(0, ["code", "--wait"] if args.wait else ["code"])
    for name in ("nano", "vim", "vi", "notepad"):
        if shutil.which(name):
            candidates.append([name])
    for cmd in candidates:
        try:
            subprocess.run(cmd + [str(CONFIG_PATH)], check=False)
        except OSError:
            continue
        print(tr(load_config(), "config", path=CONFIG_PATH))
        return 0
    print(tr(load_config(), "no_editor", path=CONFIG_PATH))
    return 1


def _coerce(values: List[str]) -> Any:
    """Turn CLI strings into JSON-ish values: numbers, booleans, lists."""
    def one(v: str) -> Any:
        low = v.lower()
        if low in ("true", "on", "yes", "oui"):
            return True
        if low in ("false", "off", "no", "non"):
            return False
        try:
            return int(v)
        except ValueError:
            pass
        try:
            return float(v)
        except ValueError:
            pass
        try:
            return json.loads(v)
        except ValueError:
            return v
    out = [one(v) for v in values]
    return out[0] if len(out) == 1 else out


def cmd_set(args: argparse.Namespace) -> int:
    """Set one config key from the command line, e.g. `set ramp 30 45 60 72 84 94 100`."""
    _ensure_config()
    cfg = load_json(CONFIG_PATH, {}) or {}
    key = args.key
    value = _coerce(args.values)

    # Per-weekday shortcut: `set mon 30` -> calendar["mon"] = 30
    if key in WEEKDAYS:
        cal = dict(cfg.get("calendar") or DEFAULT_CONFIG["calendar"])
        cal[key] = value
        cfg["calendar"] = cal
    elif key == "ramp":
        if not isinstance(value, list):
            value = [value]
        if len(value) != 7:
            print(tr(cfg, "ramp_count"))
            return 2
        if any(b < a for a, b in zip(value, value[1:])):
            print(tr(cfg, "ramp_increasing"))
            return 2
        cfg["ramp"] = value
    elif key in DEFAULT_CONFIG:
        cfg[key] = value
    else:
        print(tr(cfg, "unknown_key", k=key, keys=", ".join(list(DEFAULT_CONFIG) + WEEKDAYS)))
        return 2

    save_json(CONFIG_PATH, cfg)
    print(f"{key} = {json.dumps(cfg.get(key, cfg.get('calendar')), ensure_ascii=False)}")
    print(f"→ {CONFIG_PATH}")
    return 0


def cmd_test_notify(args: argparse.Namespace) -> int:
    cfg = load_config()
    ok = notify("Claude Usage Budget", tr(cfg, "notif_test"))
    env = "WSL" if is_wsl() else platform.system()
    print(tr(cfg, "notif_sent" if ok else "notif_failed", env=env))
    return 0 if ok else 1


def cmd_reset_state(args: argparse.Namespace) -> int:
    try:
        STATE_PATH.unlink()
        print(tr(load_config(), "state_reset", path=STATE_PATH))
    except FileNotFoundError:
        print(tr(load_config(), "no_state"))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    cfg = load_config()
    print(tr(cfg, "config", path=CONFIG_PATH))
    print(json.dumps(cfg, indent=2, ensure_ascii=False))
    print()
    print(tr(cfg, "state", path=STATE_PATH))
    print(json.dumps(load_json(STATE_PATH, {}), indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="claude-usage-budget",
                                description="Daily caps and alerts for your Claude weekly usage limit.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("statusline", help="Claude Code statusline command (reads JSON on stdin)").set_defaults(fn=cmd_statusline)

    c = sub.add_parser("check", help="Evaluate a manual usage value")
    c.add_argument("--used", type=float, required=True, help="weekly usage in percent")
    c.add_argument("--reset-in-hours", type=float, default=None, help="hours until the weekly reset")
    c.add_argument("--model", default=None)
    c.add_argument("--dry-run", action="store_true", help="do not notify nor persist state")
    c.set_defaults(fn=cmd_check)

    i = sub.add_parser("init", help="Write default config and print the settings.json snippet")
    i.add_argument("--force", action="store_true")
    i.add_argument("--lang", choices=["en", "fr"], default=None, help="UI language written in the config")
    i.set_defaults(fn=cmd_init)

    s = sub.add_parser("simulate", help="Replay end-of-day usage values and show adaptive caps")
    s.add_argument("used", nargs="+", help="end-of-day weekly % for day 1, 2, ... (max 7)")
    s.set_defaults(fn=cmd_simulate)

    e = sub.add_parser("edit", help="Open the config file in your editor (VS Code if available)")
    e.add_argument("--path", action="store_true", help="only print the config path")
    e.add_argument("--wait", action="store_true", help="with VS Code, wait until the file is closed")
    e.set_defaults(fn=cmd_edit)

    st = sub.add_parser("set", help="Set a config key, e.g. `set ramp 30 45 60 72 84 94 100` or `set warn_ratio 0.8`")
    st.add_argument("key")
    st.add_argument("values", nargs="+")
    st.set_defaults(fn=cmd_set)

    sub.add_parser("test-notify", help="Send a test desktop notification").set_defaults(fn=cmd_test_notify)
    sub.add_parser("reset-state", help="Forget fired alerts for the current week").set_defaults(fn=cmd_reset_state)
    sub.add_parser("show", help="Print effective config and state").set_defaults(fn=cmd_show)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args))
    except BrokenPipeError:
        # stdout closed early (e.g. piped into `head`): exit quietly.
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
        return 0
    except Exception as exc:  # noqa: BLE001 — a statusline must never crash Claude Code
        if args.cmd == "statusline":
            sys.stdout.write(f"usage-budget error: {exc}")
            return 0
        raise


if __name__ == "__main__":
    sys.exit(main())
