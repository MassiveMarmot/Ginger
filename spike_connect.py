#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Spike: print snapd's real response for one connect or disconnect.

Not part of the app. Read-only by default; a mutation is sent only with
--yes. Prints each request before sending it. One plug and one slot per
request, the polkit header on mutations only.

Usage:
  python3 spike_connect.py SNAP PLUG SLOT_SNAP SLOT --connect|--disconnect [--yes]
"""
import argparse
import json
import sys

from snapd_client import Client, SnapdError


def show(label, value):
    print("%s: %s" % (label, json.dumps(value, sort_keys=True))
          if not isinstance(value, str) else "%s: %s" % (label, value))


def main():
    parser = argparse.ArgumentParser(
        description="Print snapd's real response for one interface change")
    parser.add_argument("snap")
    parser.add_argument("plug")
    parser.add_argument("slot_snap")
    parser.add_argument("slot")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--connect", action="store_true")
    group.add_argument("--disconnect", action="store_true")
    parser.add_argument("--yes", action="store_true",
                        help="actually send the mutation")
    args = parser.parse_args()
    action = "connect" if args.connect else "disconnect"

    client = Client()
    query = "/v2/connections?select=all&snap=" + args.snap
    print("GET " + query)
    try:
        result = client.list_connections(args.snap)
    except SnapdError as e:
        show("HTTP error", e.message)
        show("kind", e.kind)
        return 1
    established = ["%s:%s" % (c["plug"]["snap"], c["plug"]["plug"])
                   for c in result.get("established", [])]
    print("Connected now (established plugs): %s" %
          (", ".join(established) or "none"))

    if not args.yes:
        print("Read-only run. Re-run with --yes to send the %s." % action)
        return 0

    body = {"action": action,
            "plugs": [{"snap": args.snap, "plug": args.plug}],
            "slots": [{"snap": args.slot_snap, "slot": args.slot}]}
    print("POST /v2/interfaces (X-Allow-Interaction: true)")
    print(json.dumps(body, sort_keys=True))
    try:
        result = client.change_interface(action, args.snap, args.plug,
                                         args.slot_snap, args.slot)
    except SnapdError as e:
        show("HTTP status", e.status_code)
        show("kind", e.kind)
        show("message", e.message)
        return 1
    show("raw response", client.last_response)
    show("change id", result.get("change"))
    change_id = result.get("change")
    if change_id:
        try:
            change = client.wait_for_change(change_id)
        except SnapdError as e:
            show("poll result", e.message)
            return 1
        show("change status", change.get("status"))
        show("change summary", change.get("summary"))
    inverse = "disconnect" if action == "connect" else "connect"
    print("To restore the original state, run the inverse action with "
          "snap %s: sudo snap %s %s:%s %s:%s"
          % (inverse, inverse, args.snap, args.plug,
             args.slot_snap, args.slot))
    return 0


if __name__ == "__main__":
    sys.exit(main())
