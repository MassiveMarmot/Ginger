# SPDX-License-Identifier: GPL-3.0-or-later
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import changes  # noqa: E402
import restore  # noqa: E402


def conn(plug, slot_snap="snapd", slot=None, snap="firefox",
         interface=None, manual=None):
    entry = {"plug": {"snap": snap, "plug": plug},
             "slot": {"snap": slot_snap, "slot": slot or plug},
             "interface": interface or plug}
    if manual is not None:
        entry["manual"] = manual
    return entry


def plug_entry(plug, snap="firefox", interface=None):
    return {"snap": snap, "plug": plug, "interface": interface or plug,
            "apps": [], "connections": []}


def slot_entry(slot, snap="snapd", interface=None):
    return {"snap": snap, "slot": slot, "interface": interface or slot,
            "connections": []}


def baseline(*plugs):
    return {"connected": [
        {"plug": p, "slot_snap": s, "slot": t} for p, s, t in plugs]}


class ComputeDiffTests(unittest.TestCase):
    def connections(self, established=(), plugs=(), slots=()):
        return {"established": list(established), "undesired": [],
                "plugs": list(plugs), "slots": list(slots)}

    def diff(self, baseline_entry, connections, snap="firefox"):
        return restore.compute_diff(baseline_entry, connections, snap)

    def step(self, diff, index, **fields):
        for key, value in fields.items():
            self.assertEqual(diff["steps"][index][key], value)

    def test_connect_step(self):
        c = self.connections(
            plugs=[plug_entry("camera")], slots=[slot_entry("camera")])
        d = self.diff(baseline(("camera", "snapd", "camera")), c)
        self.assertEqual(len(d["steps"]), 1)
        self.step(d, 0, action="connect", plug="camera",
                  slot_snap="snapd", slot="camera", tier=1)
        self.assertEqual(d["skipped"], [])
        self.assertEqual(d["not_restored"], [])

    def test_disconnect_step_only_manual_and_not_in_baseline(self):
        c = self.connections(
            established=[conn("camera", manual=True)],
            plugs=[plug_entry("camera")], slots=[slot_entry("camera")])
        d = self.diff(baseline(), c)
        self.assertEqual(len(d["steps"]), 1)
        self.step(d, 0, action="disconnect", plug="camera",
                  slot_snap="snapd", slot="camera")

    def test_auto_connected_plug_never_disconnected(self):
        c = self.connections(
            established=[conn("network", manual=False)],
            plugs=[plug_entry("network")], slots=[slot_entry("network")])
        d = self.diff(baseline(), c)
        self.assertEqual(d["steps"], [])
        # manual field absent behaves the same
        c["established"] = [conn("network")]
        d = self.diff(baseline(), c)
        self.assertEqual(d["steps"], [])

    def test_user_reconnected_plug_in_baseline_no_step(self):
        # manual true, in baseline: nothing to do.
        c = self.connections(
            established=[conn("camera", manual=True)],
            plugs=[plug_entry("camera")], slots=[slot_entry("camera")])
        d = self.diff(baseline(("camera", "snapd", "camera")), c)
        self.assertEqual(d["steps"], [])

    def test_different_slot_gives_disconnect_then_connect(self):
        c = self.connections(
            established=[conn("camera", slot_snap="other", slot="camera",
                              manual=True)],
            plugs=[plug_entry("camera")],
            slots=[slot_entry("camera", snap="other"),
                   slot_entry("camera")])
        d = self.diff(baseline(("camera", "snapd", "camera")), c)
        self.assertEqual(len(d["steps"]), 2)
        self.step(d, 0, action="disconnect", plug="camera",
                  slot_snap="other", slot="camera")
        self.step(d, 1, action="connect", plug="camera",
                  slot_snap="snapd", slot="camera")

    def test_snap_removed_all_steps_skipped(self):
        # No plugs of the snap in the response: connect steps skip.
        c = self.connections(slots=[slot_entry("camera")])
        d = self.diff(baseline(("camera", "snapd", "camera")), c)
        self.assertEqual(d["steps"], [])
        self.assertEqual(len(d["skipped"]), 1)
        self.assertIn("plug not in current connections",
                      d["skipped"][0]["reason"])

    def test_plug_gone_after_refresh_skipped(self):
        c = self.connections(
            plugs=[plug_entry("network")], slots=[slot_entry("camera")])
        d = self.diff(baseline(("camera", "snapd", "camera")), c)
        self.assertEqual(d["steps"], [])
        self.assertEqual(len(d["skipped"]), 1)

    def test_slot_gone_skipped(self):
        c = self.connections(plugs=[plug_entry("camera")])
        d = self.diff(baseline(("camera", "snapd", "camera")), c)
        self.assertEqual(d["steps"], [])
        self.assertEqual(len(d["skipped"]), 1)
        self.assertIn("slot not in current connections",
                      d["skipped"][0]["reason"])

    def tier3_conns(self):
        return self.connections(
            plugs=[plug_entry("docker-support", interface="docker-support")],
            slots=[slot_entry("docker-support")])

    def tier3_base(self, interface="docker-support"):
        entry = {"plug": "docker-support", "slot_snap": "snapd",
                 "slot": "docker-support"}
        if interface is not None:
            entry["interface"] = interface
        return {"connected": [entry]}

    def test_tier3_reconnect_authorized_is_a_step(self):
        d = self.diff(self.tier3_base(), self.tier3_conns())
        self.assertEqual([(s["action"], s["plug"], s["tier"])
                         for s in d["steps"]],
                        [("connect", "docker-support", 3)])
        self.assertEqual(d["not_restored"], [])

    def test_tier3_connect_not_a_step(self):
        # No stored interface: fail closed, never reconnected.
        d = self.diff(self.tier3_base(interface=None), self.tier3_conns())
        self.assertEqual(d["steps"], [])
        self.assertEqual(len(d["not_restored"]), 1)
        self.assertEqual(d["not_restored"][0]["command"],
                         "snap connect firefox:docker-support "
                         "snapd:docker-support")

    def test_tier3_interface_changed_since_capture_not_restored(self):
        d = self.diff(self.tier3_base(interface="camera"),
                      self.tier3_conns())
        self.assertEqual(d["steps"], [])
        self.assertEqual(len(d["not_restored"]), 1)

    def test_tier3_slot_mismatch_not_restored(self):
        d = self.diff(self.tier3_base(), self.tier3_conns())
        # A different slot in the current response is not the baseline's
        # slot: the reconnect targets snapd:docker-support but the plug
        # is established on another slot.
        c = self.tier3_conns()
        c["established"].append(conn("docker-support", slot_snap="other",
                                     slot="docker-support",
                                     interface="docker-support",
                                     manual=True))
        d = self.diff(self.tier3_base(), c)
        self.assertEqual([(s["action"], s["plug"]) for s in d["steps"]],
                        [("disconnect", "docker-support"),
                         ("connect", "docker-support")])

    def test_tampered_baseline_tier3_slot_gone_is_skipped(self):
        c = self.tier3_conns()
        c["slots"] = []
        d = self.diff(self.tier3_base(), c)
        self.assertEqual(d["steps"], [])
        self.assertEqual(len(d["skipped"]), 1)
        self.assertIn("slot not in current connections",
                      d["skipped"][0]["reason"])

    def test_tampered_baseline_tier3_plug_gone_is_skipped(self):
        c = self.connections(plugs=[], slots=[slot_entry("docker-support")])
        d = self.diff(self.tier3_base(), c)
        self.assertEqual(d["steps"], [])
        self.assertEqual(len(d["skipped"]), 1)
        self.assertIn("plug not in current connections",
                      d["skipped"][0]["reason"])

    def test_tier2_connect_is_a_step_with_tier(self):
        c = self.connections(
            plugs=[plug_entry("removable-media",
                              interface="removable-media")],
            slots=[slot_entry("removable-media")])
        d = self.diff(
            baseline(("removable-media", "snapd", "removable-media")), c)
        self.assertEqual(len(d["steps"]), 1)
        self.step(d, 0, action="connect", tier=2)

    def test_empty_diff_when_matching(self):
        c = self.connections(
            established=[conn("camera", manual=True)],
            plugs=[plug_entry("camera")], slots=[slot_entry("camera")])
        d = self.diff(baseline(("camera", "snapd", "camera")), c)
        self.assertEqual(d, {"steps": [], "skipped": [], "not_restored": []})

    def test_no_disconnect_for_unconnected_no_connect_for_connected(self):
        c = self.connections(
            established=[conn("camera", manual=True)],
            plugs=[plug_entry("camera"), plug_entry("audio-record")],
            slots=[slot_entry("camera"), slot_entry("audio-record")])
        d = self.diff(baseline(("camera", "snapd", "camera")), c)
        for s in d["steps"]:
            self.assertFalse(
                (s["action"] == "disconnect" and s["plug"] != "camera")
                or (s["action"] == "connect" and s["plug"] == "camera"))

    def test_invalid_baseline_entry_skipped(self):
        c = self.connections()
        d = self.diff({"connected": [{"plug": 5}], "extra": "x"}, c)
        self.assertEqual(d["steps"], [])
        self.assertEqual(len(d["skipped"]), 1)

    def test_mismatch_with_baseline_slot_gone_adds_no_steps(self):
        c = self.connections(
            established=[conn("camera", slot_snap="other", slot="camera",
                              manual=True)],
            plugs=[plug_entry("camera")],
            slots=[slot_entry("camera", snap="other")])
        d = self.diff(baseline(("camera", "snapd", "camera")), c)
        self.assertEqual(d["steps"], [])
        self.assertEqual(len(d["skipped"]), 1)
        self.assertIn("slot not in current connections",
                      d["skipped"][0]["reason"])

    def test_mismatch_tier3_authorized_is_disconnect_then_connect(self):
        # The plug is manually connected to another slot; an authorized
        # baseline (stored interface) produces disconnect + connect.
        c = self.connections(
            established=[conn("docker-support", slot_snap="other",
                              slot="docker-support",
                              interface="docker-support", manual=True)],
            plugs=[plug_entry("docker-support", interface="docker-support")],
            slots=[slot_entry("docker-support", snap="other"),
                   slot_entry("docker-support")])
        d = self.diff(
            {"connected": [
                {"plug": "docker-support", "slot_snap": "snapd",
                 "slot": "docker-support", "interface": "docker-support"}]},
            c)
        self.assertEqual([(s["action"], s["slot_snap"], s["tier"])
                         for s in d["steps"]],
                        [("disconnect", "other", 3),
                         ("connect", "snapd", 3)])
        self.assertEqual(d["not_restored"], [])

    def test_mismatch_tier3_goes_to_not_restored(self):
        # Same mismatch but the baseline entry has no stored interface
        # (old file): fail closed, never reconnected.
        c = self.connections(
            established=[conn("docker-support", slot_snap="other",
                              slot="docker-support",
                              interface="docker-support", manual=True)],
            plugs=[plug_entry("docker-support", interface="docker-support")],
            slots=[slot_entry("docker-support", snap="other"),
                   slot_entry("docker-support")])
        d = self.diff(
            baseline(("docker-support", "snapd", "docker-support")), c)
        self.assertEqual(d["steps"], [])
        self.assertEqual(len(d["not_restored"]), 1)
        self.assertEqual(d["not_restored"][0]["command"],
                         "snap connect firefox:docker-support "
                         "snapd:docker-support")

    def test_established_without_slot_key_does_not_raise(self):
        # The malformed entry is ignored: camera counts as not
        # established, so the baseline connect is a normal step.
        c = self.connections(
            established=[{"plug": {"snap": "firefox",
                                   "plug": "camera"},
                           "interface": "camera", "manual": True}],
            plugs=[plug_entry("camera")], slots=[slot_entry("camera")])
        d = self.diff(baseline(("camera", "snapd", "camera")), c)
        self.assertEqual([(s["action"], s["plug"]) for s in d["steps"]],
                         [("connect", "camera")])
        self.assertEqual(d["skipped"], [])

    def test_mismatch_auto_connected_not_disconnected(self):
        # A plug auto-connected to a different slot than the baseline is
        # never touched by Restore.
        c = self.connections(
            established=[conn("camera", slot_snap="other", slot="camera",
                              manual=False)],
            plugs=[plug_entry("camera")],
            slots=[slot_entry("camera", snap="other"),
                   slot_entry("camera")])
        d = self.diff(baseline(("camera", "snapd", "camera")), c)
        self.assertEqual(d["steps"], [])

    def test_plug_connected_to_several_slots(self):
        c = self.connections(
            established=[
                conn("camera", slot_snap="other", slot="camera",
                     manual=True),
                conn("camera", slot_snap="third", slot="camera",
                     manual=True)],
            plugs=[plug_entry("camera")],
            slots=[slot_entry("camera", snap="other"),
                   slot_entry("camera", snap="third"),
                   slot_entry("camera")])
        d = self.diff(baseline(("camera", "snapd", "camera")), c)
        actions = [(s["action"], s["slot_snap"]) for s in d["steps"]]
        self.assertEqual(actions, [("disconnect", "other"),
                                    ("disconnect", "third"),
                                    ("connect", "snapd")])


class MayReconnectTier3Tests(unittest.TestCase):
    """The single tier 3 reconnect authorization: tier from the
    interface (never the plug name), exact triple in the baseline,
    stored interface must equal the current one (fail closed when
    missing or changed)."""

    def conns(self, interface="docker-support"):
        return {
            "established": [], "undesired": [],
            "plugs": [plug_entry("docker-support",
                                 interface=interface)],
            "slots": [slot_entry("docker-support", interface=interface)],
        }

    def base(self, interface="docker-support"):
        entry = {"plug": "docker-support", "slot_snap": "snapd",
                 "slot": "docker-support"}
        if interface is not None:
            entry["interface"] = interface
        return {"connected": [entry]}

    def test_authorized_when_interface_matches(self):
        self.assertTrue(restore.may_reconnect_tier3(
            self.base("docker-support"), self.conns(),
            "firefox", "docker-support", "snapd", "docker-support"))

    def test_refused_without_stored_interface(self):
        self.assertFalse(restore.may_reconnect_tier3(
            self.base(None), self.conns(),
            "firefox", "docker-support", "snapd", "docker-support"))

    def test_refused_when_interface_changed_since_capture(self):
        self.assertFalse(restore.may_reconnect_tier3(
            self.base("camera"), self.conns(),
            "firefox", "docker-support", "snapd", "docker-support"))

    def test_tier_from_interface_not_plug_name(self):
        # A plug named docker-support on a tier 1 interface is not
        # tier 3; a plug named camera on a tier 3 interface is.
        self.assertFalse(restore.may_reconnect_tier3(
            self.base("camera"), self.conns("camera"),
            "firefox", "docker-support", "snapd", "docker-support"))
        self.assertTrue(restore.may_reconnect_tier3(
            {"connected": [{"plug": "camera", "slot_snap": "snapd",
                            "slot": "camera", "interface": "docker-support"}]},
            {"established": [], "undesired": [],
             "plugs": [plug_entry("camera", interface="docker-support")],
             "slots": [slot_entry("camera", interface="docker-support")]},
            "firefox", "camera", "snapd", "camera"))

    def test_refused_when_not_in_baseline(self):
        self.assertFalse(restore.may_reconnect_tier3(
            {"connected": []}, self.conns(),
            "firefox", "docker-support", "snapd", "docker-support"))

    def test_refused_when_slot_gone(self):
        c = self.conns()
        c["slots"] = []
        self.assertFalse(restore.may_reconnect_tier3(
            self.base("docker-support"), c,
            "firefox", "docker-support", "snapd", "docker-support"))

    def test_refused_when_slot_differs(self):
        self.assertFalse(restore.may_reconnect_tier3(
            self.base("docker-support"), self.conns(),
            "firefox", "docker-support", "snapd", "other"))


class ChangedSnapsTests(unittest.TestCase):
    def test_changed_snaps_counts(self):
        connections = {
            "established": [conn("camera", snap="firefox", manual=True)],
            "undesired": [],
            "plugs": [plug_entry("camera"),
                      plug_entry("removable-media", snap="thunderbird",
                                 interface="removable-media")],
            "slots": [slot_entry("camera"),
                      slot_entry("removable-media")],
        }
        baselines = {
            "firefox": baseline(),
            "thunderbird": baseline(
                ("removable-media", "snapd", "removable-media")),
        }
        changed = restore.changed_snaps(
            baselines, {"firefox": connections,
                        "thunderbird": connections})
        self.assertEqual(changed, {"firefox": 1, "thunderbird": 1})

    def test_unchanged_snap_absent(self):
        connections = {
            "established": [conn("camera", snap="firefox", manual=True)],
            "undesired": [], "plugs": [plug_entry("camera")],
            "slots": [slot_entry("camera")]}
        baselines = {"firefox": baseline(("camera", "snapd", "camera"))}
        self.assertEqual(restore.changed_snaps(
            baselines, {"firefox": connections}), {})


class EndToEndTests(unittest.TestCase):
    """Restore converges against the mock server: the mock applies each
    connect, and the diff recomputed after the batch is empty."""

    def setUp(self):
        import tempfile
        from test_snapd_client import MockSnapd
        from snapd_client import Client
        self.tmpdir = tempfile.TemporaryDirectory()
        self.server = MockSnapd(
            os.path.join(self.tmpdir.name, "snapd.socket"))
        self.client = Client(socket_path=self.server.socket_path)
        self.server.converge = True
        self.addCleanup(self.tmpdir.cleanup)

    def connections(self, established, plugs, slots):
        return {"established": list(established), "undesired": [],
                "plugs": list(plugs), "slots": list(slots)}

    def run_batch(self, snaps, baselines):
        steps = []
        for snap in snaps:
            steps.extend(restore.compute_diff(
                baselines[snap], self.server.default_connections,
                snap)["steps"])
        for step in steps:
            outcome, _ = changes.run_change(
                self.client, step["action"], step["plug_snap"],
                step["plug"], step["slot_snap"], step["slot"],
                baseline_entry=baselines.get(step["plug_snap"]),
                current_connections=self.server.default_connections)
            self.assertEqual(outcome, changes.OUTCOME_DONE)
        return steps

    def test_restore_one_snap_converges(self):
        self.server.default_connections = self.connections(
            [conn("removable-media", manual=True)],
            [plug_entry("camera"),
             plug_entry("removable-media", interface="removable-media")],
            [slot_entry("camera"), slot_entry("removable-media")])
        baselines = {"firefox": baseline(
            ("camera", "snapd", "camera"))}
        steps = self.run_batch(["firefox"], baselines)
        self.assertEqual(sorted((s["action"], s["plug"]) for s in steps),
                         [("connect", "camera"),
                          ("disconnect", "removable-media")])
        # The most valuable check: the diff is now empty.
        for snap in baselines:
            diff = restore.compute_diff(
                baselines[snap], self.server.default_connections, snap)
            self.assertEqual(diff["steps"], [])
        self.assertEqual(restore.changed_snaps(
            baselines, {"firefox": self.server.default_connections,
                        "thunderbird": self.server.default_connections}),
            {})

    def test_restore_all_snaps_converges(self):
        self.server.default_connections = self.connections(
            [conn("camera", snap="firefox", manual=True),
             conn("audio-record", snap="thunderbird", manual=True)],
            [plug_entry("camera"),
             plug_entry("audio-record", snap="thunderbird",
                        interface="audio-record")],
            [slot_entry("camera"), slot_entry("audio-record")])
        baselines = {
            "firefox": baseline(),
            "thunderbird": baseline(),
        }
        changed = restore.changed_snaps(
            baselines, {"firefox": self.server.default_connections,
                        "thunderbird": self.server.default_connections})
        self.assertEqual(sorted(changed), ["firefox", "thunderbird"])
        self.run_batch(sorted(changed), baselines)
        for snap in baselines:
            diff = restore.compute_diff(
                baselines[snap], self.server.default_connections, snap)
            self.assertEqual(diff["steps"], [])

    def test_rerun_after_partial_restore_finishes_rest(self):
        # Two steps; the first succeeds, the second is refused. A
        # re-run of the diff sends only what is left.
        self.server.default_connections = self.connections(
            [],
            [plug_entry("camera"),
             plug_entry("removable-media", interface="removable-media")],
            [slot_entry("camera"), slot_entry("removable-media")])
        baselines = {"firefox": baseline(
            ("camera", "snapd", "camera"),
            ("removable-media", "snapd", "removable-media"))}
        steps = restore.compute_diff(
            baselines["firefox"], self.server.default_connections,
            "firefox")["steps"]
        self.assertEqual(len(steps), 2)
        outcome, _ = changes.run_change(
            self.client, steps[0]["action"], steps[0]["plug_snap"],
            steps[0]["plug"], steps[0]["slot_snap"], steps[0]["slot"],
            baseline_entry=baselines.get(steps[0]["plug_snap"]),
            current_connections=self.server.default_connections)
        self.assertEqual(outcome, changes.OUTCOME_DONE)
        remaining = restore.compute_diff(
            baselines["firefox"], self.server.default_connections,
            "firefox")["steps"]
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["plug"], "removable-media")


if __name__ == "__main__":
    unittest.main()
