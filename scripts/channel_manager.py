#!/usr/bin/env python3

import json
import os
import select
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
    print()
    print(_c(title, "1"))
    print("=" * 60)


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
    print_header("Validate Configuration")

    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            raw = f.read()
        json.loads(raw)
        print(_c("✓ JSON syntax valid", "32"))
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(_c(f"✗ JSON syntax invalid: {e}", "31"))
        return

    data = load_config()
    channels = data.get("channels", [])
    print(_c(f"✓ {len(channels)} channels found", "32"))

    errors = validate_config_data(data)

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
    # instead of nested per-byte select() races. Up/Down/Right/Left arrive as
    # ESC [ A/B/C/D; a standalone Escape key sends only ESC.
    seq = raw
    for _ in range(2):  # at most '[' + final byte
        ready, _, _ = select.select([fd], [], [], ESC_SEQ_TIMEOUT)
        if not ready:
            break
        chunk = os.read(fd, 1)
        if not chunk:
            break
        seq += chunk
        # Complete known sequence: stop waiting immediately, no extra latency.
        if seq in (b"\x1b[A", b"\x1b[B", b"\x1b[C", b"\x1b[D"):
            break
        if len(seq) >= 3:
            break
        if len(seq) == 2 and seq[1:2] != b"[":
            break
    if seq == b"\x1b[A":
        return "up"
    if seq == b"\x1b[B":
        return "down"
    if seq == b"\x1b[C":
        return "right"
    if seq == b"\x1b[D":
        return "left"
    if seq == b"\x1b":
        return "esc"
    if seq.startswith(b"\x1b["):
        return "esc"
    try:
        return seq[1:2].decode("utf-8", errors="replace")
    except Exception:
        return "esc"


def select_menu(title, options, selected=0):
    if not sys.stdin.isatty() or len(options) == 0:
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

    try:
        tty.setraw(fd)

        def _draw(sel):
            n_lines = 1 + len(options)
            for _ in range(n_lines):
                sys.stdout.write('\033[1A')
                sys.stdout.write('\r\033[2K')
            sys.stdout.write(title + '\r\n')
            for i, opt in enumerate(options):
                if i == sel:
                    sys.stdout.write(f'> {opt}\r\n')
                else:
                    sys.stdout.write(f'  {opt}\r\n')
            sys.stdout.flush()

        _draw(selected)

        while True:
            key = _read_key()
            if key == 'ctrl-c':
                raise KeyboardInterrupt
            elif key == 'up':
                selected = (selected - 1) % len(options)
                _draw(selected)
                time.sleep(NAV_REPEAT_DELAY)
            elif key == 'down':
                selected = (selected + 1) % len(options)
                _draw(selected)
                time.sleep(NAV_REPEAT_DELAY)
            elif key == 'enter':
                return selected
            elif key in ('q', 'esc'):
                return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        sys.stdout.write('\n')
        sys.stdout.flush()


def select_channel(data=None):
    if data is None:
        data = load_config()
    channels = data.get("channels", [])
    if not channels:
        print("No channels available.")
        return None

    options = [ch.get('name', 'Unknown') for ch in channels]
    idx = select_menu("Select channel:", options)
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
        print("No channels available.")
        return

    result = select_channel(data)
    if result is None:
        return
    channel, _ = result

    try:
        model_id = input("Model ID:\n> ").strip()
    except EOFError:
        return
    except KeyboardInterrupt:
        return

    if not model_id:
        print(_c("Error: model ID cannot be empty.", "31"))
        return

    models = channel.get("models", [])
    if model_id in models:
        print(_c(f"Error: model '{model_id}' already exists in channel '{channel['name']}'.", "31"))
        return

    print()
    print(f"Channel:\n{channel['name']}")
    print(f"Model to add:\n{model_id}")

    try:
        confirm = input("\nSave? [y/N] ").strip().lower()
    except EOFError:
        return
    except KeyboardInterrupt:
        return

    if confirm != "y":
        print("Aborted.")
        return

    channel.setdefault("models", []).append(model_id)
    if save_config(data):
        print(_c("Model added successfully.", "32"))
    else:
        print(_c("Failed to save.", "31"))


def remove_model():
    data = load_config()
    channels = data.get("channels", [])
    print_header("Remove Model")

    if not channels:
        print("No channels available.")
        return

    result = select_channel(data)
    if result is None:
        return
    channel, _ = result

    models = channel.get("models", [])
    if not models:
        print("No models to remove.")
        return

    options = list(models)
    m_idx = select_menu("Select model to remove:", options)
    if m_idx is None:
        return

    removed_model = models[m_idx]
    mapping = channel.get("model_mapping", {})

    for alias, target in mapping.items():
        if target == removed_model:
            print()
            print(_c(f"Warning: model '{removed_model}' is referenced by model_mapping as '{alias} -> {target}'.", "33"))
            print(_c("Remove the mapping separately before removing this model.", "33"))
            print("Aborted.")
            return

    print()
    print(f"Remove model '{removed_model}' from channel '{channel['name']}'?")

    try:
        confirm = input("\nSave? [y/N] ").strip().lower()
    except EOFError:
        return
    except KeyboardInterrupt:
        return

    if confirm != "y":
        print("Aborted.")
        return

    models.pop(m_idx)
    if save_config(data):
        print(_c("Model removed successfully.", "32"))
    else:
        print(_c("Failed to save.", "31"))


def add_channel():
    data = load_config()
    channels = data.get("channels", [])
    print_header("Add Channel")

    options = [label for _, label, _ in PROVIDER_LIST]
    p_idx = select_menu("Select provider:", options)
    if p_idx is None:
        return

    _, _, provider_key = PROVIDER_LIST[p_idx]

    if provider_key in PRESETS:
        preset = PRESETS[provider_key]
        provider = provider_key
        base_url = preset["base_url"]
        api_key_env = preset["api_key_env"]
        ptype = preset["type"]
    else:
        try:
            provider = input("\nProvider identifier:\n> ").strip()
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        if not provider:
            print("Provider identifier cannot be empty.")
            return
        try:
            ptype = input("Type:\n> ").strip()
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        try:
            base_url = input("Base URL:\n> ").strip()
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        try:
            api_key_env = input("API key env:\n> ").strip()
        except EOFError:
            return
        except KeyboardInterrupt:
            return

    try:
        channel_name = input("\nChannel name:\n> ").strip()
    except EOFError:
        return
    except KeyboardInterrupt:
        return
    if not channel_name:
        print("Channel name cannot be empty.")
        return

    existing_names = {ch.get("name") for ch in channels}
    if channel_name in existing_names:
        print(_c(f"Error: channel name '{channel_name}' already exists.", "31"))
        return

    models = []
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
        print(_c("Error: at least one model is required.", "31"))
        return

    try:
        group_input = input("\nGroup (default: default):\n> ").strip()
    except EOFError:
        return
    except KeyboardInterrupt:
        return
    group = group_input if group_input else "default"

    try:
        priority_input = input("Priority (default: 0):\n> ").strip()
    except EOFError:
        return
    except KeyboardInterrupt:
        return
    try:
        priority = int(priority_input)
    except ValueError:
        priority = 0

    try:
        weight_input = input("Weight (default: 1):\n> ").strip()
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
        auto_ban_input = input("Auto-ban (default: true):\n> ").strip().lower()
    except EOFError:
        return
    except KeyboardInterrupt:
        return
    auto_ban = auto_ban_input != "false" if auto_ban_input else True

    try:
        test_input = input("Test model (optional, Enter to skip):\n> ").strip()
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

    try:
        confirm = input("\nSave? [y/N] ").strip().lower()
    except EOFError:
        return
    except KeyboardInterrupt:
        return

    if confirm != "y":
        print("Aborted.")
        return

    channels.append(new_channel)
    data["channels"] = channels
    if save_config(data):
        print(_c("Channel added successfully.", "32"))
    else:
        print(_c("Failed to save.", "31"))


def edit_mapping():
    data = load_config()
    channels = data.get("channels", [])
    print_header("Edit Model Mapping")

    if not channels:
        print("No channels available.")
        return

    result = select_channel(data)
    if result is None:
        return
    channel, _ = result

    mapping = channel.get("model_mapping", {})

    print()
    print(f"Current mappings for {channel['name']}:")
    if mapping:
        for alias, target in mapping.items():
            print(f"  {alias} -> {target}")
    else:
        print("  (none)")

    options = ["Add mapping", "Update mapping", "Remove mapping", "Back"]
    m_idx = select_menu("Mapping actions:", options)
    if m_idx is None:
        return

    if m_idx == 0:
        try:
            alias = input("\nAlias:\n> ").strip()
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        if not alias:
            print("Alias cannot be empty.")
            return
        try:
            target = input("Target model:\n> ").strip()
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        if not target:
            print("Target model cannot be empty.")
            return

        print()
        print(f"{alias} -> {target}")
        try:
            confirm = input("Save? [y/N] ").strip().lower()
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        if confirm != "y":
            print("Aborted.")
            return

        mapping[alias] = target
        channel["model_mapping"] = mapping
        if save_config(data):
            print(_c("Mapping added successfully.", "32"))
        else:
            print(_c("Failed to save.", "31"))

    elif m_idx == 1:
        if not mapping:
            print("No mappings to update.")
            return
        try:
            alias = input("\nAlias to update:\n> ").strip()
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        if alias not in mapping:
            print(f"No mapping for alias '{alias}'.")
            return
        old_target = mapping[alias]
        print(f"Current: {alias} -> {old_target}")
        try:
            new_target = input("New target model:\n> ").strip()
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        if not new_target:
            print("Target model cannot be empty.")
            return
        mapping[alias] = new_target
        try:
            confirm = input("Save? [y/N] ").strip().lower()
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        if confirm != "y":
            print("Aborted.")
            return
        channel["model_mapping"] = mapping
        if save_config(data):
            print(_c("Mapping updated successfully.", "32"))
        else:
            print(_c("Failed to save.", "31"))

    elif m_idx == 2:
        if not mapping:
            print("No mappings to remove.")
            return
        try:
            alias = input("\nAlias to remove:\n> ").strip()
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        if alias not in mapping:
            print(f"No mapping for alias '{alias}'.")
            return
        target = mapping[alias]
        print(f"Removing: {alias} -> {target}")
        try:
            confirm = input("Save? [y/N] ").strip().lower()
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        if confirm != "y":
            print("Aborted.")
            return
        del mapping[alias]
        channel["model_mapping"] = mapping
        if save_config(data):
            print(_c("Mapping removed successfully.", "32"))
        else:
            print(_c("Failed to save.", "31"))

    elif m_idx == 3:
        return


def main_menu():
    data = load_config()
    channel_count = count_channels(data)
    model_count = count_models(data)

    print()
    print(_c("New API Channel Manager", "1"))
    print()
    print(f"{channel_count} Channels")
    print(f"{model_count} Models")
    print()
    print("? What do you want to do?")
    print()

    options = ["List channels", "Add model", "Remove model", "Add channel", "Edit model mapping", "Validate configuration", "Exit"]

    while True:
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
