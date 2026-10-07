# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
import tempfile
import unittest

import baseline


def established(plug, snap="firefox", slot_snap="snapd", slot=None,
                interface="camera"):
    return {"plug": {"snap": snap, "plug": plug},
            "slot": {"snap": slot_snap, "slot": slot or plug},
            "interface": interface}


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.prev = os.environ.get("GINGER_DATA_DIR")
        os.environ["GINGER_DATA_DIR"] = self.tmpdir.name

    def tearDown(self):
        if self.prev is None:
            del os.environ["GINGER_DATA_DIR"]
        else:
            os.environ["GINGER_DATA_DIR"] = self.prev
        self.tmpdir.cleanup()

    def path(self):
        return os.path.join(self.tmpdir.name, "baseline.json")

    def write_raw(self, data):
        with open(self.path(), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_written_once_never_overwritten(self):
        connections = {"established": [established("camera")]}
        first = baseline.capture_new({}, {"firefox": connections})
        baseline.save_snaps(first)
        with open(self.path()) as f:
            saved1 = f.read()
        # user disconnects camera outside Ginger; relaunch
        connections2 = {"established": []}
        self.assertEqual(
            baseline.capture_new(baseline.load(), {"firefox": connections2}),
            {})
        with open(self.path()) as f:
            self.assertEqual(f.read(), saved1)

    def test_new_snap_gets_baseline_next_launch(self):
        baseline.save_snaps(baseline.capture_new(
            {}, {"firefox": {"established": [established("camera")]}}))
        later = {"thunderbird": {"established": []}}
        new = baseline.capture_new(baseline.load(), later)
        self.assertIn("thunderbird", new)
        baseline.save_snaps({**baseline.load(), **new})
        self.assertEqual(sorted(baseline.load()),
                         ["firefox", "thunderbird"])

    def test_atomic_write_no_temp_left(self):
        baseline.save_snaps({"firefox": baseline.entry_for(
            {"established": [established("camera")]}, "firefox")})
        self.assertEqual(sorted(os.listdir(self.tmpdir.name)),
                         ["baseline.json"])

    def test_roundtrip(self):
        entry = baseline.entry_for(
            {"established": [established("camera"),
                             established("network", interface="network")]},
            "firefox")
        baseline.save_snaps({"firefox": entry})
        self.assertEqual(baseline.load()["firefox"], entry)

    def test_corrupt_file_raises(self):
        with open(self.path(), "w") as f:
            f.write("not json{")
        with self.assertRaises(baseline.BaselineError):
            baseline.load()

    def test_wrong_version_raises(self):
        self.write_raw({"version": 99, "snaps": {}})
        with self.assertRaises(baseline.BaselineError):
            baseline.load()

    def test_tampered_snaps_raises(self):
        self.write_raw({"version": 1, "snaps": "evil"})
        with self.assertRaises(baseline.BaselineError):
            baseline.load()

    def test_tampered_entries_skipped(self):
        good = baseline.entry_for(
            {"established": [established("camera")]}, "firefox")
        self.write_raw({"version": 1, "snaps": {
            "firefox": good,
            "bad": "not-a-dict",
            "bad2": {"connected": "no-list"}}})
        loaded = baseline.load()
        self.assertEqual(loaded, {"firefox": good})

    def test_missing_file_is_empty(self):
        self.assertEqual(baseline.load(), {})

    def test_entry_records_connected_state_only(self):
        entry = baseline.entry_for(
            {"established": [established("camera")],
             "undesired": [established("removable-media",
                                       interface="removable-media")]},
            "firefox")
        self.assertEqual(entry["connected"], ["camera"])
        self.assertNotIn("removable-media", entry["connected"])

    def test_forget_deletes_file(self):
        baseline.save_snaps({"firefox": baseline.entry_for(
            {"established": []}, "firefox")})
        self.assertTrue(baseline.forget())
        self.assertFalse(os.path.exists(self.path()))
        self.assertFalse(baseline.forget())

    def test_markup_names_survive(self):
        entry = baseline.entry_for(
            {"established": [established("<b>evil</b>&amp;")]},
            "<b>evil</b>&amp;")
        baseline.save_snaps({"<b>evil</b>&amp;": entry})
        self.assertEqual(baseline.load()["<b>evil</b>&amp;"], entry)


if __name__ == "__main__":
    unittest.main()
