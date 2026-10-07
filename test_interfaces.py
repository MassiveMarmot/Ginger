# SPDX-License-Identifier: GPL-3.0-or-later
import unittest

import interfaces


def conn(plug, slot_snap="snapd", slot=None, interface=None, manual=None):
    c = {"plug": {"snap": "firefox", "plug": plug},
         "slot": {"snap": slot_snap, "slot": slot or plug},
         "interface": interface or plug}
    if manual is not None:
        c["manual"] = manual
    return c


def connections(plugs, established=(), undesired=(), slots=()):
    return {"plugs": plugs, "established": list(established),
            "undesired": list(undesired), "slots": list(slots)}


class TierTests(unittest.TestCase):
    def test_tier_lookup(self):
        self.assertEqual(interfaces.tier_for("camera"), 1)
        self.assertEqual(interfaces.tier_for("removable-media"), 2)
        self.assertEqual(interfaces.tier_for("docker-support"), 3)

    def test_unknown_interface_defaults_to_tier_2(self):
        self.assertEqual(interfaces.tier_for("never-heard-of-it"), 2)

    def test_hidden_content(self):
        self.assertTrue(interfaces.is_hidden("content"))
        self.assertFalse(interfaces.is_hidden("camera"))


class DeriveTests(unittest.TestCase):
    def plug(self, name, interface=None):
        return {"snap": "firefox", "plug": name,
                "interface": interface or name, "apps": [],
                "connections": []}

    def slot(self, name="camera", snap="snapd", interface=None):
        return {"snap": snap, "slot": name,
                "interface": interface or name, "connections": []}

    def test_states(self):
        c = connections(
            [self.plug("camera"), self.plug("removed", "removable-media"),
             self.plug("auto"), self.plug("orphan")],
            established=[conn("camera", manual=True),
                         conn("auto", manual=None)],
            undesired=[conn("removed", manual=True)],
            slots=[self.slot("camera"), self.slot("removable-media")])
        plugs = {p["name"]: p for p in interfaces.derive_plugs(c, "firefox")}
        self.assertEqual(plugs["camera"]["state"], "Manually connected")
        self.assertTrue(plugs["camera"]["connected"])
        self.assertEqual(plugs["auto"]["state"], "Connected")
        self.assertTrue(plugs["auto"]["connected"])
        self.assertEqual(plugs["removed"]["state"], "Manually disconnected")
        self.assertFalse(plugs["removed"]["connected"])
        self.assertEqual(plugs["orphan"]["state"], "Disconnected")
        self.assertFalse(plugs["orphan"]["connected"])
        self.assertEqual(plugs["orphan"]["n_slots"], 0)

    def test_manually_disconnected_without_slot(self):
        # pcscd-style: manual plug, no slot; disconnected is in neither
        c = connections([self.plug("pcscd")], undesired=[])
        plugs = interfaces.derive_plugs(c, "firefox")
        self.assertEqual(plugs[0]["state"], "Disconnected")
        self.assertEqual(plugs[0]["n_slots"], 0)

    def test_hidden_content_plug(self):
        c = connections(
            [self.plug("gtk-3-themes", "content"), self.plug("camera")])
        names = [p["name"] for p in interfaces.derive_plugs(c, "firefox")]
        self.assertEqual(names, ["camera"])
        names = [p["name"] for p in interfaces.derive_plugs(
            c, "firefox", show_all=True)]
        self.assertEqual(names, ["camera", "gtk-3-themes"])

    def test_sort_tier_then_name(self):
        c = connections(
            [self.plug("camera"), self.plug("network"),
             self.plug("removable-media"), self.plug("docker-support",
                                                    "docker-support")],
            slots=[self.slot("camera"), self.slot("network"),
                   self.slot("removable-media")])
        order = [(p["tier"], p["name"])
                 for p in interfaces.derive_plugs(c, "firefox")]
        self.assertEqual(order, [(1, "camera"), (1, "network"),
                                 (2, "removable-media"),
                                 (3, "docker-support")])

    def test_only_one_compatible_slot_offered(self):
        c = connections(
            [self.plug("content-plug", "content")],
            slots=[self.slot("s1", "a", "content"),
                   self.slot("s2", "b", "content")])
        plugs = interfaces.derive_plugs(c, "firefox", show_all=True)
        self.assertEqual(plugs[0]["slot"], None)
        self.assertEqual(plugs[0]["n_slots"], 2)

    def test_single_slot_matched(self):
        c = connections(
            [self.plug("camera")], slots=[self.slot("camera", "snapd")])
        plugs = interfaces.derive_plugs(c, "firefox")
        self.assertEqual(plugs[0]["slot"], ("snapd", "camera"))

    def test_connected_slot_comes_from_established(self):
        c = connections(
            [self.plug("camera")],
            established=[conn("camera", slot_snap="core24", slot="cam",
                              manual=True)],
            slots=[])
        plugs = interfaces.derive_plugs(c, "firefox")
        self.assertEqual(plugs[0]["conn_slot"], ("core24", "cam"))
        self.assertTrue(plugs[0]["connected"])

    def test_other_snaps_ignored(self):
        c = connections(
            [{"snap": "thunderbird", "plug": "camera",
              "interface": "camera", "apps": [], "connections": []}],
            established=[{"plug": {"snap": "thunderbird", "plug": "camera"},
                         "slot": {"snap": "snapd", "slot": "camera"},
                         "interface": "camera"}])
        self.assertEqual(interfaces.derive_plugs(c, "firefox"), [])

    def test_malformed_entries_ignored(self):
        c = connections(["junk", {"snap": "firefox"}, None])
        self.assertEqual(interfaces.derive_plugs(c, "firefox"), [])

    def test_counts(self):
        c = connections(
            [self.plug("camera"), self.plug("removed", "removable-media"),
             self.plug("orphan")],
            established=[conn("camera")],
            undesired=[conn("removed")],
            slots=[self.slot("camera"), self.slot("removable-media")])
        self.assertEqual(interfaces.counts(c, "firefox"), (1, 1))

    def test_markup_names_not_special(self):
        c = connections(
            [self.plug("<b>evil</b>&amp;")],
            established=[conn("<b>evil</b>&amp;")])
        plugs = interfaces.derive_plugs(c, "firefox")
        self.assertEqual(plugs[0]["name"], "<b>evil</b>&amp;")


if __name__ == "__main__":
    unittest.main()
