#!/usr/bin/env python3
"""Generate an aggregated domain->server index over minecraft_servers/*/manifest.json.

Usage: generate-index.py [OUTPUT_PATH]   (default: ./index.json)

Exits non-zero only on JSON parse errors or a missing required manifest field;
everything else (malformed wildcards, duplicate domain claims) is skipped with
a warning on stderr.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_FIELDS = ("server_name", "nice_name", "direct_ip")

# Common multi-label public suffixes; a host ending in one of these keeps three
# labels as its root domain instead of two (foo.com.br, not com.br). Stdlib-only
# stand-in for the full public suffix list, extend as manifests need it.
MULTI_LABEL_SUFFIXES = frozenset({
    "co.uk", "org.uk", "me.uk", "net.uk", "ac.uk", "gov.uk",
    "com.br", "net.br", "org.br",
    "com.au", "net.au", "org.au",
    "com.ar", "com.mx", "com.co", "com.ve", "com.pe", "com.ec",
    "com.tr", "com.pl", "net.pl", "org.pl", "com.ua",
    "co.za", "co.nz", "co.in", "co.il", "co.id", "co.th",
    "co.jp", "ne.jp", "or.jp", "co.kr",
    "com.sg", "com.my", "com.ph", "com.hk", "com.tw", "com.cn", "net.cn",
    "com.eg", "com.sa", "com.vn",
})


def warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def host_of(value: str) -> str:
    """Lowercase a host and strip a trailing :port if present."""
    host = value.strip().lower()
    if ":" in host:
        head, _, tail = host.rpartition(":")
        if tail.isdigit():
            host = head
    return host


def wildcard_base(entry: str) -> str | None:
    """'%.hypixel.net' -> 'hypixel.net'; None for malformed entries."""
    if not isinstance(entry, str):
        return None
    base = entry.strip().lower()
    for prefix in ("%.", "*."):
        if base.startswith(prefix):
            base = base[len(prefix):]
            break
    base = host_of(base)
    if not base or "%" in base or "*" in base:
        return None
    return base


def root_domain(host: str) -> str:
    """Reduce a host to its registrable root domain: 'eu.minemen.club' -> 'minemen.club'."""
    labels = host.split(".")
    if len(labels) <= 2 or all(l.isdigit() for l in labels):
        return host
    keep = 3 if ".".join(labels[-2:]) in MULTI_LABEL_SUFFIXES else 2
    return ".".join(labels[-keep:])


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("./index.json")
    repo_root = Path(__file__).resolve().parent.parent
    servers_dir = repo_root / "minecraft_servers"

    servers: dict[str, dict] = {}
    domains: dict[str, str] = {}
    direct_claims: list[tuple[str, str]] = []
    wildcard_claims: list[tuple[str, str]] = []
    errors = 0

    for manifest_path in sorted(servers_dir.glob("*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            print(f"error: {manifest_path}: invalid JSON: {exc}", file=sys.stderr)
            errors += 1
            continue

        missing = [f for f in REQUIRED_FIELDS if not manifest.get(f)]
        if missing:
            print(f"error: {manifest_path}: missing required field(s): {', '.join(missing)}",
                  file=sys.stderr)
            errors += 1
            continue

        name = manifest["server_name"]
        folder = manifest_path.parent
        entry = {
            "nice_name": manifest["nice_name"],
            "direct_ip": manifest["direct_ip"],
            "background": (folder / "background.png").is_file(),
            "logo": (folder / "logo.png").is_file(),
            "banner": (folder / "banner.png").is_file(),
        }

        wildcards = manifest.get("server_wildcards")
        if not isinstance(wildcards, list):
            if wildcards is not None:
                warn(f"{name}: server_wildcards is not a list; ignoring")
            wildcards = []
        if wildcards:
            entry["wildcards"] = [w for w in wildcards if isinstance(w, str)]
        servers[name] = entry

        direct = root_domain(host_of(manifest["direct_ip"]))
        if direct:
            direct_claims.append((name, direct))
        else:
            warn(f"{name}: skipping empty domain claim")
        for wildcard in wildcards:
            base = wildcard_base(wildcard)
            if base is None:
                warn(f"{name}: skipping malformed wildcard {wildcard!r}")
            else:
                wildcard_claims.append((name, root_domain(base)))

    # Direct IPs claim their root domain before wildcards do, so a server's own
    # domain can't be shadowed by another server's wildcard on a subdomain of it.
    for name, domain in direct_claims + wildcard_claims:
        if domain in domains and domains[domain] != name:
            warn(f"{name}: domain {domain!r} already claimed by {domains[domain]!r}; keeping first")
        else:
            domains[domain] = name

    index = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "servers": servers,
        "domains": domains,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out_path}: {len(servers)} servers, {len(domains)} domains", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
