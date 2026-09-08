#!/usr/bin/env python3

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


TYPE_MAP = {
    "openai": 1,
}


def die(message):
    print(f"[ERROR] {message}", file=sys.stderr)
    sys.exit(1)


def api_request(method, endpoint, payload=None):
    base_url = os.environ["NEW_API_BASE_URL"].rstrip("/")
    token = os.environ["NEW_API_ADMIN_TOKEN"]
    user_id = os.environ["NEW_API_USER_ID"]

    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        base_url + endpoint,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "New-Api-User": user_id,
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        die(f"HTTP {exc.code}: {body}")
    except urllib.error.URLError as exc:
        die(f"Connection failed: {exc.reason}")

    if isinstance(result, dict) and result.get("success") is False:
        die(result.get("message") or "New API returned an error.")

    return result


def get_existing_channels():
    channels = []
    page = 1
    page_size = 100

    while True:
        response = api_request(
            "GET",
            f"/api/channel/?p={page}&page_size={page_size}",
        )

        data = response.get("data", response)

        if isinstance(data, dict):
            items = (
                data.get("items")
                or data.get("channels")
                or data.get("data")
                or []
            )
        elif isinstance(data, list):
            items = data
        else:
            items = []

        if not items:
            break

        channels.extend(items)

        if len(items) < page_size:
            break

        page += 1

    return channels


def desired_state(channel):
    result = {
        "name": channel["name"],
        "type": TYPE_MAP[channel["type"]],
        "base_url": channel.get("base_url", ""),
        "models": sorted(channel.get("models", [])),
        "group": channel.get("group", "default"),
        "priority": channel.get("priority", 0),
        "weight": channel.get("weight", 0),
        "auto_ban": bool(channel.get("auto_ban", True)),
        "model_mapping": channel.get("model_mapping", {}),
    }

    if "test_model" in channel:
        result["test_model"] = channel["test_model"]

    return result


def current_state(channel):
    models = channel.get("models", "")

    if isinstance(models, str):
        models = [x for x in models.split(",") if x]

        model_mapping = channel.get("model_mapping")

    if model_mapping is None:
        model_mapping = {}
    elif isinstance(model_mapping, str):
        try:
            model_mapping = json.loads(model_mapping) if model_mapping else {}
        except json.JSONDecodeError:
            model_mapping = {}

    return {
        "name": channel.get("name", ""),
        "type": channel.get("type"),
        "base_url": channel.get("base_url", ""),
        "models": sorted(models),
        "group": channel.get("group", "default"),
        "priority": channel.get("priority", 0),
        "weight": channel.get("weight", 0),
        "auto_ban": bool(channel.get("auto_ban", 0)),
        "test_model": channel.get("test_model"),
        "model_mapping": model_mapping,
    }


def differences(current, desired):
    return {
        key: (current.get(key), value)
        for key, value in desired.items()
        if current.get(key) != value
    }


def build_payload(channel):
    key_env = channel.get("api_key_env")

    if not key_env:
        die(f"{channel['name']}: api_key_env missing.")

    key = os.environ.get(key_env)

    if not key:
        die(f"{channel['name']}: {key_env} is empty.")

    if channel.get("type") not in TYPE_MAP:
        die(f"{channel['name']}: unsupported type {channel.get('type')}")

    models = channel.get("models", [])

    if not models:
        die(f"{channel['name']}: models list is empty.")

    payload = {
        "name": channel["name"],
        "type": TYPE_MAP[channel["type"]],
        "key": key,
        "base_url": channel.get("base_url", ""),
        "models": ",".join(models),
        "group": channel.get("group", "default"),
        "priority": channel.get("priority", 0),
        "weight": channel.get("weight", 0),
        "auto_ban": 1 if channel.get("auto_ban", True) else 0,
    }

    if "test_model" in channel:
        payload["test_model"] = channel["test_model"]

    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply channel changes to New API",
    )
    args = parser.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(root, "config", "channels.json")

    with open(config_path, encoding="utf-8") as file:
        config = json.load(file)

    existing = get_existing_channels()

    existing_by_name = {
        channel.get("name"): channel
        for channel in existing
        if channel.get("name")
    }

    create_count = 0
    update_count = 0
    skip_count = 0

    print()
    print("Channel sync")
    print("=" * 72)

    for channel in config.get("channels", []):
        name = channel["name"]
        old = existing_by_name.get(name)

        if old is None:
            print(f"[CREATE] {name}")
            create_count += 1

            if args.apply:
                payload = build_payload(channel)

                group = payload.pop("group")

                # New API single-channel creation format.
                result = api_request(
                    "POST",
                    "/api/channel/",
                    {
                        "mode": "single",
                        "channel": {
                            **payload,
                            "groups": [group],
                        },
                    },
                )

                print("         -> created")

            continue

        desired = desired_state(channel)
        diff = differences(current_state(old), desired)

        if not diff:
            print(f"[SKIP]   {name}")
            skip_count += 1
            continue

        print(f"[UPDATE] {name}")
        update_count += 1

        for field, (before, after) in diff.items():
            print(f"         {field}: {before!r} -> {after!r}")

        if args.apply:
            payload = build_payload(channel)
            payload["id"] = old["id"]

            api_request(
                "PUT",
                "/api/channel/",
                payload,
            )

            print("         -> updated")

    print("=" * 72)
    print(f"Create : {create_count}")
    print(f"Update : {update_count}")
    print(f"Skip   : {skip_count}")
    print(f"Total  : {create_count + update_count + skip_count}")

    if not args.apply:
        print()
        print("Dry run only. Use --apply to apply changes.")


if __name__ == "__main__":
    main()
