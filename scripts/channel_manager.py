#!/usr/bin/env python3

import contextlib
import json
import os
import re
import select
import shutil
import sys
import tempfile
import termios
import time
import tty
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "channels.json"

PRESETS = {
    "xkiro": {
        "base_url": "https://api.xkiro.com",
        "api_key_env": "XKIRO_API_KEY",
        "type": "openai",
    },
    "unorouter": {
        "base_url": "https://api.unorouter.com",
        "api_key_env": "UNROUTER_API_KEY",
        "type": "openai",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api",
        "api_key_env": "OPENROUTER_API_KEY",
        "type": "openai",
    },
}

PROVIDER_LIST = [
    ("1", "Xkiro", "xkiro"),
    ("2", "UnoRouter", "unorouter"),
    ("3", "OpenRouter", "openrouter"),
    ("4", "Custom", None),
]

USE_COLORS = sys.stdout.isatty()


def _c(msg, code):
    if USE_COLORS:
        return f"\033[{code}m{msg}\033[0m"
    return msg


def print_header(title):
    if is_interactive():
        return
    print()
    print(_c(title, "1"))
    print("=" * 60)


# -----------------------------------------------------------
# Terminal lifecycle (interactive TTY only, stdlib only).
#
# All alternate-screen / cursor / raw-mode handling is centralized
# here so business logic never emits raw ANSI sequences directly.
# -----------------------------------------------------------

ALT_ENTER = "\033[?1049h"
ALT_LEAVE = "\033[?1049l"
CURSOR_HIDE = "\033[?25l"
CURSOR_SHOW = "\033[?25h"


def is_interactive():
    return sys.stdin.isatty() and sys.stdout.isatty()


def _write_seq(seq):
    try:
        sys.stdout.write(seq)
        sys.stdout.flush()
    except Exception:
        pass


def enter_alt_screen():
    _write_seq(ALT_ENTER)


def leave_alt_screen():
    _write_seq(ALT_LEAVE)


def hide_cursor():
    _write_seq(CURSOR_HIDE)


def show_cursor():
    _write_seq(CURSOR_SHOW)


MIN_COLS = 60
MIN_ROWS = 20


def term_size():
    try:
        size = shutil.get_terminal_size()
        return max(1, size.columns), max(1, size.lines)
    except Exception:
        return 80, 24


def viewport_too_small():
    cols, rows = term_size()
    return cols < MIN_COLS or rows < MIN_ROWS


def content_height():
    _, rows = term_size()
    return max(1, rows - 6)


ANSI_SGR_RE = re.compile(r"\033\[[0-9;]*m")
ANSI_RESET = "\033[0m"


def visible_len(text):
    return len(ANSI_SGR_RE.sub("", str(text)))


def _truncate(text, width):
    text = str(text)
    if width <= 0:
        return ""
    if visible_len(text) <= width:
        return text
    out = []
    vis = 0
    i = 0
    limit = max(0, width - 1)
    style_open = False
    while i < len(text) and vis < limit:
        if text[i] == "\x1b":
            match = ANSI_SGR_RE.match(text, i)
            if not match:
                break
            seq = match.group(0)
            out.append(seq)
            style_open = seq not in ("\033[0m", "\033[m")
            i = match.end()
            continue
        out.append(text[i])
        vis += 1
        i += 1
    if style_open:
        out.append(ANSI_RESET)
    out.append("…")
    return "".join(out)


def ansi_ljust(text, width):
    text = str(text)
    return text + " " * max(0, width - visible_len(text))


def _fit(text, width):
    return ansi_ljust(_truncate(text, width), max(0, width))


def frame_lines(header_title, header_right, content_rows, footer_left,
                footer_right=""):
    cols, rows = term_size()
    if cols < MIN_COLS or rows < MIN_ROWS:
        return [
            "",
            "  Terminal too small",
            "  Resize to at least 60x20",
            f"  Current: {cols}x{rows}",
            "",
        ]
    inner = cols - 2
    right = str(header_right or "")
    left = _truncate(" " + str(header_title or ""),
                     max(0, inner - visible_len(right) - 1))
    header_row = ("│" + ansi_ljust(left, max(0, inner - visible_len(right)))
                  + right + "│")
    foot_left = str(footer_left or "")
    foot_right = str(footer_right or "")
    foot_left = _truncate(foot_left,
                          max(0, inner - visible_len(foot_right) - 1))
    footer_row = ("│" + ansi_ljust(foot_left,
                                   max(0, inner - visible_len(foot_right)))
                  + foot_right + "│")
    wanted = max(1, rows - 6)
    body = [_truncate(line, inner) for line in list(content_rows)[:wanted]]
    while len(body) < wanted:
        body.append("")
    body = ["│" + ansi_ljust(line, inner) + "│" for line in body]
    return [
        "┌" + "─" * inner + "┐",
        header_row,
        "├" + "─" * inner + "┤",
    ] + body + [
        "├" + "─" * inner + "┤",
        footer_row,
        "└" + "─" * inner + "┘",
    ]


def render_frame(header_title, header_right, content_rows, footer_left,
                 footer_right=""):
    render_screen(frame_lines(header_title, header_right, content_rows,
                              footer_left, footer_right))


def render_screen(lines):
    sys.stdout.write(ANSI_RESET + "\033[H\033[2J"
                     + "\r\n".join(str(line) for line in lines))
    sys.stdout.flush()


def clamp_offset(selected, offset, visible, total):
    if total <= visible:
        return 0
    offset = max(0, min(offset, total - visible))
    if selected < offset:
        return selected
    if selected >= offset + visible:
        return selected - visible + 1
    return offset


def scrollbar_column(offset, visible, total):
    if total <= visible:
        return [" "] * visible
    size = max(1, (visible * visible + total - 1) // total)
    size = min(size, visible)
    denom = max(1, total - visible)
    start = min(visible - size, (offset * (visible - size)) // denom)
    return ["█" if start <= k < start + size else "│"
            for k in range(visible)]


def render_form(title, header_right, label_lines, footer, input_prefix="> "):
    cols, rows = term_size()
    if cols < MIN_COLS or rows < MIN_ROWS:
        render_screen(["", "  Terminal too small",
                       "  Resize to at least 60x20", ""])
        return (5, 4)
    inner = cols - 2
    width = min(58, inner - 4)
    labels = [_truncate(line, width) for line in label_lines]
    panel_inner = labels + [_truncate(input_prefix, width)]
    panel_width = width + 2
    panel = ["╭" + "─" * width + "╮"]
    for line in panel_inner:
        panel.append("│" + line.ljust(width) + "│")
    panel.append("╰" + "─" * width + "╯")
    wanted = max(1, rows - 6)
    top_pad = max(0, (wanted - len(panel)) // 2)
    left_pad = max(0, (inner - panel_width) // 2)
    content = [""] * top_pad
    for prow in panel:
        content.append(" " * left_pad + prow)
    while len(content) < wanted:
        content.append("")
    render_frame(title, header_right, content[:wanted], footer)
    cursor_row = 3 + top_pad + 1 + (len(panel_inner) - 1) + 1
    cursor_col = 1 + left_pad + 1 + len(_truncate(input_prefix, width)) + 1
    return (cursor_row, cursor_col)


def _kv_lines(pairs):
    pairs = [(str(k), str(v)) for k, v in pairs]
    width = max([len(k) for k, _ in pairs] or [0])
    return [k.ljust(width) + "  " + v for k, v in pairs]


@contextlib.contextmanager
def terminal_session():
    if not is_interactive():
        yield False
        return
    fd = sys.stdin.fileno()
    try:
        old_settings = termios.tcgetattr(fd)
    except Exception:
        yield False
        return
    entered = False
    try:
        sys.stdout.write(ALT_ENTER)
        sys.stdout.flush()
        entered = True
        sys.stdout.write(CURSOR_HIDE)
        sys.stdout.flush()
        yield True
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except Exception:
            pass
        try:
            sys.stdout.write(CURSOR_SHOW)
            sys.stdout.flush()
        except Exception:
            pass
        if entered:
            try:
                sys.stdout.write(ALT_LEAVE)
                sys.stdout.flush()
            except Exception:
                pass


def show_info(title, lines, pause=True, footer=None):
    if not is_interactive():
        print_header(title)
        for line in lines:
            print(line)
        return
    body = [str(line) for line in lines] if lines else ["(empty)"]
    if not pause:
        render_frame(title, "", body, footer or "")
        return
    offset = 0
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        hide_cursor()
        while True:
            visible = content_height()
            offset = max(0, min(offset, max(0, len(body) - visible)))
            window = body[offset:offset + visible]
            while len(window) < visible:
                window.append("")
            if len(body) > visible:
                pos = (f"{offset + 1}-{min(offset + visible, len(body))} "
                       f"of {len(body)}")
                hints = "↑↓ PgUp PgDn scroll   any key back"
            else:
                pos = ""
                hints = footer or "Press any key to continue"
            render_frame(title, pos, window, hints)
            key = _read_key()
            if key is None:
                raise EOFError
            if key == "ctrl-c":
                raise KeyboardInterrupt
            if len(body) <= visible:
                return
            if key == "up":
                offset = max(0, offset - 1)
            elif key == "down":
                offset = min(max(0, len(body) - visible), offset + 1)
            elif key == "pageup":
                offset = max(0, offset - visible)
            elif key == "pagedown":
                offset = min(max(0, len(body) - visible), offset + visible)
            elif key == "home":
                offset = 0
            elif key == "end":
                offset = max(0, len(body) - visible)
            else:
                return
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except Exception:
            pass
        show_cursor()


def ask_text(title, prompt, default="", subtitle=None,
             footer="Enter Continue"):
    if not is_interactive():
        value = input(prompt)
        value = value.strip()
        return value if value else default
    labels = []
    if subtitle:
        labels.extend(str(line) for line in subtitle)
        labels.append("")
    labels.extend(str(prompt).split("\n"))
    cursor_row, cursor_col = render_form(title, "", labels, footer)
    sys.stdout.write(f"\033[{cursor_row};{cursor_col}H")
    sys.stdout.flush()
    show_cursor()
    try:
        value = input()
    finally:
        hide_cursor()
    value = value.strip()
    return value if value else default


def confirm_screen(title, lines):
    if not is_interactive():
        for line in lines:
            print(line)
        confirm = input("\nSave? [y/N] ").strip().lower()
        return confirm == "y"
    labels = [str(line) for line in lines]
    labels.append("")
    labels.append("Save this change?")
    cursor_row, cursor_col = render_form(title, "", labels, "y Save   n Cancel")
    sys.stdout.write(f"\033[{cursor_row};{cursor_col}H")
    sys.stdout.flush()
    show_cursor()
    try:
        answer = input()
    finally:
        hide_cursor()
    return answer.strip().lower() in ("y", "yes")


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_config(data):
    errors = validate_config_data(data)
    if errors:
        print(_c("Cannot save: validation errors found.", "31"))
        for e in errors:
            print(_c(f"  {e}", "31"))
        return False

    backup_path = CONFIG_PATH.with_suffix(".json.bak")
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            backup_path.write_text(f.read(), encoding="utf-8")
    except Exception:
        pass

    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(CONFIG_PATH.parent), suffix=".json"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, CONFIG_PATH)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return True


def validate_config_data(data):
    errors = []

    if not isinstance(data, dict):
        errors.append("Root must be an object")
        return errors

    if "version" not in data:
        errors.append("version is missing")

    if not isinstance(data.get("channels"), list):
        errors.append("channels must be an array")
        return errors

    channels = data["channels"]
    names = []

    for i, ch in enumerate(channels):
        name = ch.get("name")
        if not name or not isinstance(name, str) or not name.strip():
            errors.append(f"Channel at index {i} has empty or missing name")
        elif name in names:
            errors.append(f"Duplicate channel name: {name}")
        else:
            names.append(name)

        provider = ch.get("provider")
        if not provider or not isinstance(provider, str):
            errors.append(f"Channel '{name}': provider missing or invalid")

        if not ch.get("type"):
            errors.append(f"Channel '{name}': type missing")

        if not ch.get("base_url"):
            errors.append(f"Channel '{name}': base_url missing")

        if not ch.get("api_key_env"):
            errors.append(f"Channel '{name}': api_key_env missing")

        models = ch.get("models")
        if not isinstance(models, list) or len(models) == 0:
            errors.append(f"Channel '{name}': models must be a non-empty array")
        else:
            seen = set()
            for m in models:
                if not isinstance(m, str) or not m.strip():
                    errors.append(f"Channel '{name}': empty model ID found")
                elif m in seen:
                    errors.append(f"Channel '{name}': duplicate model '{m}'")
                else:
                    seen.add(m)

        if not ch.get("group") or not isinstance(ch.get("group"), str):
            errors.append(f"Channel '{name}': group must be a non-empty string")

        if not isinstance(ch.get("priority"), int):
            errors.append(f"Channel '{name}': priority must be an integer")

        if not isinstance(ch.get("weight"), (int, float)):
            errors.append(f"Channel '{name}': weight must be numeric")

        if not isinstance(ch.get("auto_ban"), bool):
            errors.append(f"Channel '{name}': auto_ban must be boolean")

        mm = ch.get("model_mapping")
        if mm is not None:
            if not isinstance(mm, dict):
                errors.append(f"Channel '{name}': model_mapping must be an object")
            else:
                for alias, target in mm.items():
                    if not alias or not isinstance(alias, str):
                        errors.append(f"Channel '{name}': mapping alias must be a non-empty string")
                    if not target or not isinstance(target, str):
                        errors.append(f"Channel '{name}': mapping target must be a non-empty string")

        tm = ch.get("test_model")
        if tm is not None and (not isinstance(tm, str) or not tm.strip()):
            errors.append(f"Channel '{name}': test_model must be a non-empty string")

    return errors


def validate_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            raw = f.read()
        json.loads(raw)
        syntax_ok = True
        syntax_error = ""
    except (json.JSONDecodeError, FileNotFoundError) as e:
        syntax_ok = False
        syntax_error = str(e)

    if not syntax_ok:
        if is_interactive():
            show_info("VALIDATE CONFIGURATION",
                      ["✗ JSON syntax invalid: " + syntax_error])
            return
        print_header("Validate Configuration")
        print(_c(f"✗ JSON syntax invalid: {syntax_error}", "31"))
        return

    data = load_config()
    channels = data.get("channels", [])
    errors = validate_config_data(data)

    if is_interactive():
        lines = ["✓ JSON syntax valid",
                 f"✓ {len(channels)} channels found"]
        if errors:
            lines.append("")
            for e in errors:
                lines.append("✗ " + str(e))
            lines.append("")
            lines.append("Configuration has errors.")
        else:
            lines.append("✓ Channel names unique")
            lines.append("✓ Models valid")
            lines.append("✓ Model mappings valid")
            lines.append("")
            lines.append("Configuration valid.")
        show_info("VALIDATE CONFIGURATION", lines)
        return

    print_header("Validate Configuration")
    print(_c("✓ JSON syntax valid", "32"))
    print(_c(f"✓ {len(channels)} channels found", "32"))

    if errors:
        for e in errors:
            print(_c(f"✗ {e}", "31"))
        print()
        print(_c("Configuration has errors.", "31"))
    else:
        print(_c("✓ Channel names unique", "32"))
        print(_c("✓ Models valid", "32"))
        print(_c("✓ Model mappings valid", "32"))
        print()
        print(_c("Configuration valid.", "32"))


def count_models(data):
    total = 0
    for ch in data.get("channels", []):
        total += len(ch.get("models", []))
    return total


def count_channels(data):
    return len(data.get("channels", []))


def list_channels():
    data = load_config()
    channels = data.get("channels", [])
    if is_interactive():
        total_models = sum(len(ch.get("models", [])) for ch in channels)
        lines = [f"{len(channels)} channels · {total_models} models", ""]
        for i, ch in enumerate(channels, 1):
            name = ch.get("name", "Unknown")
            provider = ch.get("provider", "Unknown")
            models = ch.get("models", [])
            group = ch.get("group", "default")
            weight = ch.get("weight", 1)
            lines.append(f"[{i}] {name}")
            lines.append(f"    Provider : {provider}")
            lines.append(f"    Models   : {len(models)}")
            lines.append(f"    Group    : {group}")
            lines.append(f"    Weight   : {weight}")
            lines.append("")
        if lines:
            lines.pop()
        show_info("LIST CHANNELS", lines or ["(no channels)"])
        return
    print_header("List Channels")
    for i, ch in enumerate(channels, 1):
        name = ch.get("name", "Unknown")
        provider = ch.get("provider", "Unknown")
        models = ch.get("models", [])
        group = ch.get("group", "default")
        weight = ch.get("weight", 1)
        print()
        print(_c(f"[{i}] {name}", "1"))
        print(f"    Provider : {provider}")
        print(f"    Models   : {len(models)}")
        print(f"    Group    : {group}")
        print(f"    Weight   : {weight}")


ESC_SEQ_TIMEOUT = 0.08
NAV_REPEAT_DELAY = 0.03


def _read_key():
    fd = sys.stdin.fileno()
    # Blocking read of the first byte: a quick single press is never missed
    # (no select() race on the initial byte). The short timeout below is used
    # only to complete an ESC sequence once ESC has been received.
    raw = os.read(fd, 1)
    if not raw:
        return None
    ch = raw.decode("utf-8", errors="replace")
    if ch != "\x1b":
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x03":
            return "ctrl-c"
        if ch == "q":
            return "q"
        return ch
    # ESC received: collect the rest of a possible escape sequence as a unit
    # instead of nested per-byte select() races. Arrows arrive as
    # ESC [ A/B/C/D; PageUp/PageDown as ESC [ 5~/6~; Home/End as
    # ESC [ H/F, ESC [ 1~/4~ or ESC O H/F. A standalone Escape key
    # sends only ESC.
    seq = raw
    for _ in range(3):  # at most '[', '5'/'1', '~' etc.
        ready, _, _ = select.select([fd], [], [], ESC_SEQ_TIMEOUT)
        if not ready:
            break
        chunk = os.read(fd, 1)
        if not chunk:
            break
        seq += chunk
        # Complete known sequence: stop waiting immediately, no extra latency.
        if seq in (b"\x1b[A", b"\x1b[B", b"\x1b[C", b"\x1b[D",
                   b"\x1b[H", b"\x1b[F", b"\x1b[5~", b"\x1b[6~",
                   b"\x1b[1~", b"\x1b[4~", b"\x1bOH", b"\x1bOF"):
            break
        if len(seq) >= 4:
            break
        if len(seq) == 2 and seq[1:2] not in (b"[", b"O"):
            break
    if seq == b"\x1b[A":
        return "up"
    if seq == b"\x1b[B":
        return "down"
    if seq == b"\x1b[C":
        return "right"
    if seq == b"\x1b[D":
        return "left"
    if seq == b"\x1b[5~":
        return "pageup"
    if seq == b"\x1b[6~":
        return "pagedown"
    if seq in (b"\x1b[H", b"\x1b[1~", b"\x1bOH"):
        return "home"
    if seq in (b"\x1b[F", b"\x1b[4~", b"\x1bOF"):
        return "end"
    if seq == b"\x1b":
        return "esc"
    if seq.startswith(b"\x1b[") or seq.startswith(b"\x1bO"):
        return "esc"
    try:
        return seq[1:2].decode("utf-8", errors="replace")
    except Exception:
        return "esc"


def select_menu(title, options, selected=0, subtitle=None,
                footer="↑↓ Navigate   Enter Select   q Back",
                header_right="", wrap=True, center=True):
    if not is_interactive() or len(options) == 0:
        for i, opt in enumerate(options, 1):
            print(f"[{i}] {opt}")
        while True:
            try:
                choice = input("\n> ").strip()
                idx = int(choice)
                if 1 <= idx <= len(options):
                    return idx - 1
                print("Invalid selection.")
            except (ValueError, EOFError):
                return None
            except KeyboardInterrupt:
                return None

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    total = len(options)
    offset = 0

    def move(delta):
        nonlocal selected
        if wrap:
            selected = (selected + delta) % total
        else:
            selected = max(0, min(total - 1, selected + delta))

    try:
        tty.setraw(fd)
        hide_cursor()

        def _draw():
            nonlocal offset
            cols, _ = term_size()
            inner = max(10, cols - 2)
            fixed = [str(line) for line in (subtitle or [])]
            if fixed:
                fixed.append("")
            visible = max(1, content_height() - len(fixed))
            offset = clamp_offset(selected, offset, visible, total)
            fits = total <= visible
            width = max(10, inner - 3)
            rows = [_truncate(line, inner - 2) for line in fixed]
            if fits and center:
                plain = [(("> " if i == selected else "  ")
                          + str(options[i])) for i in range(total)]
                block = min(width, max([visible_len(_truncate(p, width))
                                        for p in plain] + [0]))
                lpad = max(0, (inner - block) // 2)
                rows.extend([""] * ((visible - total) // 2))
                for i, text in enumerate(plain):
                    cell = _fit(text, block)
                    if i == selected and USE_COLORS:
                        cell = "\033[7m" + cell + "\033[0m"
                    rows.append(" " * lpad + cell)
            else:
                bar = scrollbar_column(offset, visible, total)
                for k in range(visible):
                    idx = offset + k
                    if idx >= total:
                        rows.append("")
                        continue
                    prefix = "> " if idx == selected else "  "
                    cell = (_fit(prefix + str(options[idx]), width)
                            + bar[k])
                    if idx == selected and USE_COLORS:
                        cell = "\033[7m" + cell + "\033[0m"
                    rows.append(cell)
            pos = f"{selected + 1}/{total}"
            render_frame(title, header_right or pos, rows, footer, pos)

        _draw()

        while True:
            key = _read_key()
            if key is None:
                raise EOFError
            if key == 'ctrl-c':
                raise KeyboardInterrupt
            elif key == 'up':
                move(-1)
                _draw()
                time.sleep(NAV_REPEAT_DELAY)
            elif key == 'down':
                move(1)
                _draw()
                time.sleep(NAV_REPEAT_DELAY)
            elif key == 'pageup':
                visible = max(1, content_height()
                              - (len(subtitle or []) + (1 if subtitle else 0)))
                move(-visible)
                _draw()
            elif key == 'pagedown':
                visible = max(1, content_height()
                              - (len(subtitle or []) + (1 if subtitle else 0)))
                move(visible)
                _draw()
            elif key == 'home':
                selected = 0
                _draw()
            elif key == 'end':
                selected = total - 1
                _draw()
            elif key == 'enter':
                return selected
            elif key in ('q', 'esc'):
                return None
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except Exception:
            pass
        show_cursor()


def select_channel(data=None, title="SELECT CHANNEL", context=None):
    if data is None:
        data = load_config()
    channels = data.get("channels", [])
    if not channels:
        if is_interactive():
            show_info("CHANNEL MANAGER", ["No channels available."])
            return
        print("No channels available.")
        return None

    options = [ch.get('name', 'Unknown') for ch in channels]
    idx = select_menu(title, options,
                      subtitle=([str(context)] if context else None),
                      footer="↑↓ PgUp PgDn Home End   Enter Select   Esc Back",
                      wrap=False, center=False)
    if idx is None:
        return None
    return channels[idx], idx


def find_channel_index(data, name):
    for i, ch in enumerate(data.get("channels", [])):
        if ch.get("name") == name:
            return i
    return -1


def add_model():
    data = load_config()
    channels = data.get("channels", [])
    print_header("Add Model")

    if not channels:
        if is_interactive():
            show_info("CHANNEL MANAGER", ["No channels available."])
            return
        print("No channels available.")
        return

    result = select_channel(data, title="ADD MODEL",
                            context="Select channel")
    if result is None:
        return
    channel, _ = result

    try:
        model_id = ask_text("ADD MODEL", "Model ID:\n> ",
                            subtitle=["Channel", str(channel['name'])])
    except EOFError:
        return
    except KeyboardInterrupt:
        return

    if not model_id:
        if is_interactive():
            show_info("ADD MODEL", ["Error: model ID cannot be empty."])
            return
        print(_c("Error: model ID cannot be empty.", "31"))
        return

    models = channel.get("models", [])
    if model_id in models:
        if is_interactive():
            show_info("ADD MODEL",
                      [f"Error: model '{model_id}' already exists",
                       f"in channel '{channel['name']}'."])
            return
        print(_c(f"Error: model '{model_id}' already exists in channel '{channel['name']}'.", "31"))
        return

    try:
        if is_interactive():
            ok = confirm_screen("ADD MODEL",
                                ["Channel:",
                                 str(channel['name']),
                                 "",
                                 "Model to add:",
                                 str(model_id)])
        else:
            print()
            print(f"Channel:\n{channel['name']}")
            print(f"Model to add:\n{model_id}")
            confirm = input("\nSave? [y/N] ").strip().lower()
            ok = confirm == "y"
    except EOFError:
        return
    except KeyboardInterrupt:
        return

    if not ok:
        if is_interactive():
            show_info("ADD MODEL", ["Aborted."])
            return
        print("Aborted.")
        return

    channel.setdefault("models", []).append(model_id)
    if save_config(data):
        if is_interactive():
            show_info("ADD MODEL", ["✓ Model saved"])
            return
        print(_c("Model added successfully.", "32"))
    else:
        if is_interactive():
            show_info("ADD MODEL", ["Failed to save."])
            return
        print(_c("Failed to save.", "31"))


def remove_model():
    data = load_config()
    channels = data.get("channels", [])
    print_header("Remove Model")

    if not channels:
        if is_interactive():
            show_info("CHANNEL MANAGER", ["No channels available."])
            return
        print("No channels available.")
        return

    result = select_channel(data, title="REMOVE MODEL",
                            context="Select channel")
    if result is None:
        return
    channel, _ = result

    models = channel.get("models", [])
    if not models:
        if is_interactive():
            show_info("REMOVE MODEL", ["No models to remove."])
            return
        print("No models to remove.")
        return

    options = list(models)
    m_idx = select_menu("REMOVE MODEL", options,
                        subtitle=["Channel", str(channel['name']), "",
                                  "Select model"],
                        footer="↑↓ PgUp PgDn Home End   Enter Select   Esc Back",
                        wrap=False, center=False)
    if m_idx is None:
        return

    removed_model = models[m_idx]
    mapping = channel.get("model_mapping", {})

    for alias, target in mapping.items():
        if target == removed_model:
            if is_interactive():
                show_info("REMOVE MODEL",
                          [f"Warning: model '{removed_model}' is referenced",
                           f"by model_mapping as '{alias} -> {target}'.",
                           "Remove the mapping separately",
                           "before removing this model."])
                return
            print()
            print(_c(f"Warning: model '{removed_model}' is referenced by model_mapping as '{alias} -> {target}'.", "33"))
            print(_c("Remove the mapping separately before removing this model.", "33"))
            print("Aborted.")
            return

    try:
        if is_interactive():
            ok = confirm_screen("REMOVE MODEL",
                                [f"Remove model '{removed_model}'",
                                 f"from channel '{channel['name']}'?"])
        else:
            print()
            print(f"Remove model '{removed_model}' from channel '{channel['name']}'?")
            confirm = input("\nSave? [y/N] ").strip().lower()
            ok = confirm == "y"
    except EOFError:
        return
    except KeyboardInterrupt:
        return

    if not ok:
        if is_interactive():
            show_info("REMOVE MODEL", ["Aborted."])
            return
        print("Aborted.")
        return

    models.pop(m_idx)
    if save_config(data):
        if is_interactive():
            show_info("REMOVE MODEL", ["✓ Model removed"])
            return
        print(_c("Model removed successfully.", "32"))
    else:
        if is_interactive():
            show_info("REMOVE MODEL", ["Failed to save."])
            return
        print(_c("Failed to save.", "31"))


def add_channel():
    data = load_config()
    channels = data.get("channels", [])
    print_header("Add Channel")

    options = [label for _, label, _ in PROVIDER_LIST]
    p_idx = select_menu("ADD CHANNEL", options,
                        subtitle=["Step 1 · Select provider"],
                        footer="↑↓ Navigate   Enter Select   Esc Back")
    if p_idx is None:
        return

    provider_label = PROVIDER_LIST[p_idx][1]
    provider_key = PROVIDER_LIST[p_idx][2]
    total_steps = 13 if provider_key is None else 9

    def step_title(n):
        if is_interactive():
            return f"ADD CHANNEL · {n}/{total_steps}"
        return "ADD CHANNEL"

    def wizard_ctx(extra=()):
        lines = [f"Provider  {provider_label}"]
        lines.extend(extra)
        return lines

    if provider_key in PRESETS:
        preset = PRESETS[provider_key]
        provider = provider_key
        base_url = preset["base_url"]
        api_key_env = preset["api_key_env"]
        ptype = preset["type"]
    else:
        try:
            provider = ask_text(step_title(2), "\nProvider identifier:\n> ",
                                subtitle=wizard_ctx())
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        if not provider:
            if is_interactive():
                show_info("ADD CHANNEL",
                          ["Provider identifier cannot be empty."])
                return
            print("Provider identifier cannot be empty.")
            return
        provider_label = provider
        try:
            ptype = ask_text(step_title(3), "Type:\n> ",
                             subtitle=wizard_ctx())
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        try:
            base_url = ask_text(step_title(4), "Base URL:\n> ",
                                subtitle=wizard_ctx())
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        try:
            api_key_env = ask_text(step_title(5), "API key env:\n> ",
                                   subtitle=wizard_ctx())
        except EOFError:
            return
        except KeyboardInterrupt:
            return

    name_step = 6 if provider_key is None else 2
    try:
        channel_name = ask_text(step_title(name_step), "\nChannel name:\n> ",
                                subtitle=wizard_ctx())
    except EOFError:
        return
    except KeyboardInterrupt:
        return
    if not channel_name:
        if is_interactive():
            show_info("ADD CHANNEL", ["Channel name cannot be empty."])
            return
        print("Channel name cannot be empty.")
        return

    existing_names = {ch.get("name") for ch in channels}
    if channel_name in existing_names:
        if is_interactive():
            show_info("ADD CHANNEL",
                      [f"Error: channel name '{channel_name}'",
                       "already exists."])
            return
        print(_c(f"Error: channel name '{channel_name}' already exists.", "31"))
        return

    models_step = name_step + 1
    name_ctx = wizard_ctx([f"Name  {channel_name}"])
    models = []
    if is_interactive():
        while True:
            try:
                listed = [f"  {m}" for m in models]
                sub = name_ctx + [f"Models  {len(models)} selected"]
                if listed:
                    sub = sub + [""] + listed
                m = ask_text(step_title(models_step),
                             "Add model (empty line finishes):",
                             subtitle=sub)
            except EOFError:
                break
            except KeyboardInterrupt:
                return
            if not m:
                break
            models.append(m)
    else:
        print("\nAdd models (enter one per line, empty to finish):")
        while True:
            try:
                m = input("> ").strip()
            except EOFError:
                break
            except KeyboardInterrupt:
                break
            if not m:
                break
            models.append(m)

    if not models:
        if is_interactive():
            show_info("ADD CHANNEL",
                      ["Error: at least one model is required."])
            return
        print(_c("Error: at least one model is required.", "31"))
        return

    models_ctx = name_ctx + [f"Models  {len(models)} selected"]
    group_step = models_step + 1
    try:
        group_input = ask_text(step_title(group_step),
                               "\nGroup (default: default):\n> ",
                               subtitle=models_ctx)
    except EOFError:
        return
    except KeyboardInterrupt:
        return
    group = group_input if group_input else "default"

    try:
        priority_input = ask_text(step_title(group_step + 1),
                                  "Priority (default: 0):\n> ",
                                  subtitle=models_ctx)
    except EOFError:
        return
    except KeyboardInterrupt:
        return
    try:
        priority = int(priority_input)
    except ValueError:
        priority = 0

    try:
        weight_input = ask_text(step_title(group_step + 2),
                                "Weight (default: 1):\n> ",
                                subtitle=models_ctx)
    except EOFError:
        return
    except KeyboardInterrupt:
        return
    try:
        weight = float(weight_input)
        if weight == int(weight):
            weight = int(weight)
    except ValueError:
        weight = 1

    try:
        auto_ban_input = ask_text(step_title(group_step + 3),
                                  "Auto-ban (default: true):\n> ",
                                  subtitle=models_ctx).lower()
    except EOFError:
        return
    except KeyboardInterrupt:
        return
    auto_ban = auto_ban_input != "false" if auto_ban_input else True

    try:
        test_input = ask_text(step_title(group_step + 4),
                              "Test model (optional, Enter to skip):\n> ",
                              subtitle=models_ctx)
    except EOFError:
        return
    except KeyboardInterrupt:
        return
    test_model = test_input if test_input else None

    new_channel = {
        "name": channel_name,
        "provider": provider,
        "type": ptype,
        "base_url": base_url,
        "api_key_env": api_key_env,
        "models": models,
        "group": group,
        "priority": priority,
        "weight": weight,
        "auto_ban": auto_ban,
    }
    if test_model:
        new_channel["test_model"] = test_model

    try:
        if is_interactive():
            review = ["REVIEW", ""]
            review += _kv_lines([
                ("Name", channel_name),
                ("Provider", provider),
                ("Type", ptype),
                ("Base URL", base_url),
                ("API key env", api_key_env),
                ("Group", group),
                ("Priority", priority),
                ("Weight", weight),
                ("Auto-ban", auto_ban),
            ])
            review += ["", "Models"]
            review += [f"  {m}" for m in models]
            if test_model:
                review += ["", f"Test model  {test_model}"]
            ok = confirm_screen(step_title(total_steps), review)
        else:
            print()
            print("Channel preview:")
            print(f"  Name: {channel_name}")
            print(f"  Provider: {provider}")
            print(f"  Type: {ptype}")
            print(f"  Base URL: {base_url}")
            print(f"  API Key Env: {api_key_env}")
            print(f"  Models: {', '.join(models)}")
            print(f"  Group: {group}")
            print(f"  Priority: {priority}")
            print(f"  Weight: {weight}")
            print(f"  Auto-ban: {auto_ban}")
            if test_model:
                print(f"  Test Model: {test_model}")
            confirm = input("\nSave? [y/N] ").strip().lower()
            ok = confirm == "y"
    except EOFError:
        return
    except KeyboardInterrupt:
        return

    if not ok:
        if is_interactive():
            show_info("ADD CHANNEL", ["Aborted."])
            return
        print("Aborted.")
        return

    channels.append(new_channel)
    data["channels"] = channels
    if save_config(data):
        if is_interactive():
            show_info("ADD CHANNEL", ["✓ Channel saved"])
            return
        print(_c("Channel added successfully.", "32"))
    else:
        if is_interactive():
            show_info("ADD CHANNEL", ["Failed to save."])
            return
        print(_c("Failed to save.", "31"))


def edit_mapping():
    data = load_config()
    channels = data.get("channels", [])
    print_header("Edit Model Mapping")

    if not channels:
        if is_interactive():
            show_info("CHANNEL MANAGER", ["No channels available."])
            return
        print("No channels available.")
        return

    result = select_channel(data, title="EDIT MODEL MAPPING",
                            context="Select channel")
    if result is None:
        return
    channel, _ = result

    mapping = channel.get("model_mapping", {})

    if is_interactive():
        current = ["Channel", str(channel['name']), "",
                   "Current mappings:", ""]
        if mapping:
            for alias, target in mapping.items():
                current.append(f"  {alias} -> {target}")
        else:
            current.append("  (none)")
        show_info("EDIT MODEL MAPPING", current)
    else:
        print()
        print(f"Current mappings for {channel['name']}:")
        if mapping:
            for alias, target in mapping.items():
                print(f"  {alias} -> {target}")
        else:
            print("  (none)")

    options = ["Add mapping", "Update mapping", "Remove mapping", "Back"]
    m_idx = select_menu("EDIT MODEL MAPPING", options,
                        footer="↑↓ Navigate   Enter Select   Esc Back")
    if m_idx is None:
        return

    if m_idx == 0:
        try:
            alias = ask_text("ADD MAPPING", "\nAlias:\n> ",
                             subtitle=["Channel", str(channel['name'])])
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        if not alias:
            if is_interactive():
                show_info("ADD MAPPING", ["Alias cannot be empty."])
                return
            print("Alias cannot be empty.")
            return
        try:
            target = ask_text("ADD MAPPING", "Target model:\n> ",
                              subtitle=["Channel", str(channel['name'])])
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        if not target:
            if is_interactive():
                show_info("ADD MAPPING", ["Target model cannot be empty."])
                return
            print("Target model cannot be empty.")
            return

        try:
            if is_interactive():
                ok = confirm_screen("ADD MAPPING", [f"{alias} -> {target}"])
            else:
                print()
                print(f"{alias} -> {target}")
                confirm = input("Save? [y/N] ").strip().lower()
                ok = confirm == "y"
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        if not ok:
            if is_interactive():
                show_info("ADD MAPPING", ["Aborted."])
                return
            print("Aborted.")
            return

        mapping[alias] = target
        channel["model_mapping"] = mapping
        if save_config(data):
            if is_interactive():
                show_info("ADD MAPPING", ["✓ Mapping saved"])
                return
            print(_c("Mapping added successfully.", "32"))
        else:
            if is_interactive():
                show_info("ADD MAPPING", ["Failed to save."])
                return
            print(_c("Failed to save.", "31"))

    elif m_idx == 1:
        if not mapping:
            if is_interactive():
                show_info("UPDATE MAPPING", ["No mappings to update."])
                return
            print("No mappings to update.")
            return
        try:
            alias = ask_text("UPDATE MAPPING", "\nAlias to update:\n> ",
                                subtitle=["Channel", str(channel['name'])])
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        if alias not in mapping:
            if is_interactive():
                show_info("UPDATE MAPPING",
                          [f"No mapping for alias '{alias}'."])
                return
            print(f"No mapping for alias '{alias}'.")
            return
        old_target = mapping[alias]
        try:
            new_target = ask_text(
                "UPDATE MAPPING",
                f"Current: {alias} -> {old_target}\nNew target model:\n> ")
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        if not new_target:
            if is_interactive():
                show_info("UPDATE MAPPING",
                          ["Target model cannot be empty."])
                return
            print("Target model cannot be empty.")
            return
        mapping[alias] = new_target
        try:
            if is_interactive():
                ok = confirm_screen(
                    "UPDATE MAPPING", [f"{alias} -> {new_target}"])
            else:
                confirm = input("Save? [y/N] ").strip().lower()
                ok = confirm == "y"
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        if not ok:
            if is_interactive():
                show_info("UPDATE MAPPING", ["Aborted."])
                return
            print("Aborted.")
            return
        channel["model_mapping"] = mapping
        if save_config(data):
            if is_interactive():
                show_info("UPDATE MAPPING",
                          ["✓ Mapping saved"])
                return
            print(_c("Mapping updated successfully.", "32"))
        else:
            if is_interactive():
                show_info("UPDATE MAPPING", ["Failed to save."])
                return
            print(_c("Failed to save.", "31"))

    elif m_idx == 2:
        if not mapping:
            if is_interactive():
                show_info("REMOVE MAPPING", ["No mappings to remove."])
                return
            print("No mappings to remove.")
            return
        try:
            alias = ask_text("REMOVE MAPPING", "\nAlias to remove:\n> ",
                                subtitle=["Channel", str(channel['name'])])
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        if alias not in mapping:
            if is_interactive():
                show_info("REMOVE MAPPING",
                          [f"No mapping for alias '{alias}'."])
                return
            print(f"No mapping for alias '{alias}'.")
            return
        target = mapping[alias]
        try:
            if is_interactive():
                ok = confirm_screen(
                    "REMOVE MAPPING", [f"Removing: {alias} -> {target}"])
            else:
                print(f"Removing: {alias} -> {target}")
                confirm = input("Save? [y/N] ").strip().lower()
                ok = confirm == "y"
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        if not ok:
            if is_interactive():
                show_info("REMOVE MAPPING", ["Aborted."])
                return
            print("Aborted.")
            return
        del mapping[alias]
        channel["model_mapping"] = mapping
        if save_config(data):
            if is_interactive():
                show_info("REMOVE MAPPING",
                          ["✓ Mapping removed"])
                return
            print(_c("Mapping removed successfully.", "32"))
        else:
            if is_interactive():
                show_info("REMOVE MAPPING", ["Failed to save."])
                return
            print(_c("Failed to save.", "31"))

    elif m_idx == 3:
        return


def main_menu():
    data = load_config()
    channel_count = count_channels(data)
    model_count = count_models(data)

    if not is_interactive():
        print()
        print(_c("New API Channel Manager", "1"))
        print()
        print(f"{channel_count} Channels")
        print(f"{model_count} Models")
        print()
        print("? What do you want to do?")
        print()

    options = ["List channels", "Add model", "Remove model", "Add channel", "Edit model mapping", "Validate configuration", "Exit"]

    with terminal_session() as on_alt:
        while True:
            if on_alt:
                idx = select_menu(
                    "NEW API CHANNEL MANAGER",
                    options,
                    header_right=(f"{channel_count} channels · "
                                  f"{model_count} models"),
                    footer="↑↓ Navigate   Enter Select   q Quit")
            else:
                idx = select_menu("", options)
            if idx is None:
                print("Goodbye.")
                break

            if idx == 0:
                list_channels()
            elif idx == 1:
                add_model()
            elif idx == 2:
                remove_model()
            elif idx == 3:
                add_channel()
            elif idx == 4:
                edit_mapping()
            elif idx == 5:
                validate_config()
            elif idx == 6:
                print("Goodbye.")
                break
            if not on_alt:
                print()
                print("> List channels")
                print("  Add model")
                print("  Remove model")
                print("  Add channel")
                print("  Edit model mapping")
                print("  Validate configuration")
                print("  Exit")
                print()
            else:
                data = load_config()
                channel_count = count_channels(data)
                model_count = count_models(data)


def main():
    try:
        main_menu()
    except KeyboardInterrupt:
        print()
        print("Goodbye.")
    except EOFError:
        print()
        print("Goodbye.")
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
