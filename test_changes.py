# SPDX-License-Identifier: GPL-3.0-or-later
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_snapd_client import MockSnapd

import changes
from snapd_client import Client, SnapdError


class ConfirmationTests(unittest.TestCase):
    def test_disconnect_always_confirms(self):
        for tier in (1, 2, 3):
            self.assertTrue(
                changes.needs_confirmation("disconnect", "camera", tier))

    def test_tier1_connect_no_confirmation(self):
        self.assertFalse(changes.needs_confirmation("connect", "camera", 1))

    def test_tier2_connect_confirms(self):
        self.assertTrue(
            changes.needs_confirmation("connect", "removable-media", 2))

    def test_tier3_never_connects(self):
        # tier 3 connect is never offered by the UI; if reached,
        # confirmation is required
        self.assertTrue(
            changes.needs_confirmation("connect", "docker-support", 3))

    def test_unknown_interface_tier2_confirms(self):
        self.assertTrue(
            changes.needs_confirmation("connect", "never-heard-of-it", 2))

    def test_disconnect_hint_for_desktop_interfaces(self):
        body = changes.confirmation_body("disconnect", "wayland",
                                         "wayland", 1)
        self.assertIn("may stop working", body)

    def test_no_disconnect_hint_for_camera(self):
        body = changes.confirmation_body("disconnect", "camera", "camera", 1)
        self.assertNotIn("may stop working", body)

    def test_removable_media_warning(self):
        body = changes.confirmation_body("connect", "removable-media",
                                         "removable-media", 2)
        self.assertIn("/media", body)
        self.assertIn("network shares", body)

    def test_markup_in_plug_name_stays_plain(self):
        body = changes.confirmation_body("connect", "<b>evil</b>&amp;",
                                         "removable-media", 2)
        self.assertIn("<b>evil</b>&amp;", body)


class RunChangeTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.socket_path = os.path.join(self.tmpdir.name, "snapd.socket")
        self.server = MockSnapd(self.socket_path)
        self.client = Client(socket_path=self.socket_path)

    def tearDown(self):
        self.server.stop()
        self.tmpdir.cleanup()

    def test_202_then_done(self):
        self.server.change_script["1"] = [
            {"status": "Done", "ready": True, "err": None,
             "summary": "done"}]
        outcome, message = changes.run_change(
            self.client, "connect", "firefox", "camera", "snapd", "camera")
        self.assertEqual(outcome, changes.OUTCOME_DONE)
        self.assertIsNone(message)
        path, body, allowed = self.server.posts[0]
        self.assertEqual(path, "/v2/interfaces")
        self.assertTrue(allowed)
        self.assertEqual(body["action"], "connect")

    def test_change_error(self):
        self.server.change_script["1"] = [
            {"status": "Error", "ready": True, "err": "cannot connect",
             "summary": "failed"}]
        outcome, message = changes.run_change(
            self.client, "connect", "firefox", "camera", "snapd", "camera")
        self.assertEqual(outcome, changes.OUTCOME_ERROR)
        self.assertIn("cannot connect", message)

    def test_auth_cancelled(self):
        self.server.interface_responses.append((403, {
            "type": "error", "status-code": 403,
            "result": {"message": "auth cancelled",
                       "kind": "auth-cancelled"}}))
        outcome, message = changes.run_change(
            self.client, "disconnect", "firefox", "camera", "snapd",
            "camera")
        self.assertEqual(outcome, changes.OUTCOME_CANCELLED)
        self.assertIsNone(message)

    def test_401_login_required(self):
        self.server.interface_responses.append((401, {
            "type": "error", "status-code": 401,
            "result": {"message": "access denied",
                       "kind": "login-required"}}))
        outcome, message = changes.run_change(
            self.client, "connect", "firefox", "camera", "snapd", "camera")
        self.assertEqual(outcome, changes.OUTCOME_ERROR)
        self.assertIn("access denied", message)

    def test_request_timeout(self):
        self.server.delay = 5
        outcome, message = changes.run_change(
            self.client, "connect", "firefox", "camera", "snapd", "camera",
            timeout=1)
        self.assertEqual(outcome, changes.OUTCOME_TIMEOUT)
        self.assertIsNone(message)
        self.server.delay = 0


if __name__ == "__main__":
    unittest.main()
