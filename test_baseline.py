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
        connections2 = {"established": []}
        self.assertEqual(
            baseline.capture_new(baseline.load()[0],
                                {"firefox": connections2}),
            {})
        with open(self.path()) as f:
            self.assertEqual(f.read(), saved1)

    def test_new_snap_gets_baseline_next_launch(self):
        baseline.save_snaps(baseline.capture_new(
            {}, {"firefox": {"established": [established("camera")]}}))
        later = {"thunderbird": {"established": []}}
        new = baseline.capture_new(baseline.load()[0], later)
        self.assertIn("thunderbird", new)
        baseline.save_snaps({**baseline.load()[0], **new})
        self.assertEqual(sorted(baseline.load()[0]),
                         ["firefox", "thunderbird"])

    def test_atomic_write_no_temp_left(self):
        baseline.save_snaps({"firefox": baseline.entry_for(
            {"established": [established("camera")]}, "firefox")})
        self.assertEqual(sorted(os.listdir(self.tmpdir.name)),
                         ["baseline.json", "baseline.json.bak"])

    def test_roundtrip(self):
        entry = baseline.entry_for(
            {"established": [established("camera"),
                             established("network", interface="network")]},
            "firefox")
        baseline.save_snaps({"firefox": entry})
        self.assertEqual(baseline.load()[0]["firefox"], entry)

    def test_entry_shape(self):
        entry = baseline.entry_for(
            {"established": [
                established("camera", slot_snap="core24", slot="cam"),
                established("network")]},
            "firefox")
        self.assertEqual(entry, {"connected": [
            {"plug": "camera", "slot_snap": "core24", "slot": "cam"},
            {"plug": "network", "slot_snap": "snapd", "slot": "network"},
        ]})

    def test_corrupt_file_raises(self):
        with open(self.path(), "w") as f:
            f.write("not json{")
        with self.assertRaises(baseline.BaselineError):
            baseline.load()

    def test_wrong_version_raises(self):
        self.write_raw({"version": 99, "snaps": {}})
        with self.assertRaises(baseline.BaselineError):
            baseline.load()

    def test_version_1_raises(self):
        self.write_raw({"version": 1, "snaps": {
            "firefox": {"connected": ["camera"],
                        "plugs": [], "slots": []}}})
        with self.assertRaises(baseline.BaselineError):
            baseline.load()

    def test_invalid_snap_entry_raises(self):
        good = baseline.entry_for(
            {"established": [established("camera")]}, "firefox")
        for bad in ("a string", {}, {"connected": "no"},
                    {"connected": ["bare-plug"]},
                    {"connected": [{"plug": "x"}]},
                    {"connected": [{"plug": "x", "slot_snap": "s",
                                   "slot": "y", "extra": 1}]},
                    {"connected": [{"plug": "x", "slot_snap": "s",
                                   "slot": None}]}):
            self.write_raw({"version": baseline.BASELINE_VERSION,
                            "snaps": {"firefox": good, "bad": bad}})
            with self.assertRaises(baseline.BaselineError):
                baseline.load()

    def test_missing_file_is_empty(self):
        self.assertEqual(baseline.load(), ({}, False))

    def test_entry_records_connected_state_only(self):
        entry = baseline.entry_for(
            {"established": [established("camera")],
             "undesired": [established("removable-media",
                                       interface="removable-media")]},
            "firefox")
        self.assertEqual([c["plug"] for c in entry["connected"]],
                         ["camera"])

    def test_backup_written_with_main_file(self):
        snaps = {"firefox": baseline.entry_for(
            {"established": [established("camera")]}, "firefox")}
        baseline.save_snaps(snaps)
        backup = self.path() + ".bak"
        self.assertTrue(os.path.exists(backup))
        with open(backup) as f:
            self.assertEqual(json.load(f),
                             {"version": baseline.BASELINE_VERSION,
                              "snaps": snaps})

    def test_backup_content_matches_after_new_snaps(self):
        baseline.save_snaps({"firefox": baseline.entry_for(
            {"established": []}, "firefox")})
        baseline.save_snaps({"firefox": baseline.entry_for(
            {"established": []}, "firefox"),
            "thunderbird": baseline.entry_for(
            {"established": []}, "thunderbird")})
        self.assertEqual(baseline.load()[0], baseline.load()[0])
        with open(self.path() + ".bak") as f:
            self.assertEqual(sorted(json.load(f)["snaps"]),
                             ["firefox", "thunderbird"])

    def test_corrupt_main_with_valid_backup_is_used(self):
        snaps = {"firefox": baseline.entry_for(
            {"established": [established("camera")]}, "firefox")}
        baseline.save_snaps(snaps)
        with open(self.path(), "w") as f:
            f.write("not-json{")
        loaded, used_backup = baseline.load()
        self.assertEqual(loaded, snaps)
        self.assertTrue(used_backup)
        # The corrupt file is left untouched.
        with open(self.path()) as f:
            self.assertEqual(f.read(), "not-json{")

    def test_both_corrupt_raises_and_keeps_files(self):
        baseline.save_snaps({"firefox": baseline.entry_for(
            {"established": []}, "firefox")})
        with open(self.path(), "w") as f:
            f.write("not-json{")
        with open(self.path() + ".bak", "w") as f:
            f.write("also not json")
        with self.assertRaises(baseline.BaselineError):
            baseline.load()
        with open(self.path()) as f:
            self.assertEqual(f.read(), "not-json{")
        with open(self.path() + ".bak") as f:
            self.assertEqual(f.read(), "also not json")

    def test_quarantine_moves_never_deletes(self):
        baseline.save_snaps({"firefox": baseline.entry_for(
            {"established": []}, "firefox")})
        moved = baseline.quarantine_unreadable("20260101-000000")
        self.assertEqual(len(moved), 2)
        self.assertFalse(os.path.exists(self.path()))
        self.assertFalse(os.path.exists(self.path() + ".bak"))
        for target in moved:
            self.assertTrue(os.path.exists(target))
        self.assertTrue(all(
            "baseline.unreadable-20260101-000000" in p for p in moved))

    def test_no_delete_function_exists(self):
        root = os.path.dirname(os.path.abspath(baseline.__file__))
        for name in ("baseline.py", "main.py"):
            with open(os.path.join(root, name)) as f:
                src = f.read()
            for line in src.splitlines():
                stripped = line.strip()
                for forbidden in ("os.remove(", "os.unlink(",
                                   "shutil.rmtree("):
                    if forbidden in stripped:
                        # Only the temp file of a failed atomic write
                        # may be cleaned up, never a baseline file.
                        self.assertIn("tmp", stripped,
                                      "%s in %s deletes a non-temp file"
                                      % (forbidden, name))

    def test_markup_names_survive(self):
        entry = baseline.entry_for(
            {"established": [established("<b>evil</b>&amp;")]},
            "<b>evil</b>&amp;")
        baseline.save_snaps({"<b>evil</b>&amp;": entry})
        self.assertEqual(baseline.load()[0]["<b>evil</b>&amp;"], entry)

    @unittest.skipIf(os.geteuid() == 0,
                     "chmod is ineffective as root")
    def test_save_failure_raises_oserror(self):
        os.environ["GINGER_DATA_DIR"] = os.path.join(
            self.tmpdir.name, "not-writable", "deeper")
        os.chmod(self.tmpdir.name, 0o500)
        try:
            with self.assertRaises(OSError):
                baseline.save_snaps({"firefox": {"connected": []}})
        finally:
            os.chmod(self.tmpdir.name, 0o700)


if __name__ == "__main__":
    unittest.main()
