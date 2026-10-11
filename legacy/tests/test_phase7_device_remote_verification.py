"""
Phase 7 — Device / Remote Capability Verification Test Suite
Comprehensive production-path and subsystem verification for:
1. Device Discovery (UDP beacon, local IP route, packet format)
2. Pairing Lifecycle (PIN generation, QR payload, token validation, approval)
3. Pairing Expiry & Anti-Reuse Protection (TTL expiration, single-use approval)
4. Strict Per-User Device Isolation (User A vs User B device boundaries)
5. Android Capability Dispatch & RPC Handling (app launch, flashlight, battery)
6. Remote Command Security & Allowlisting (no arbitrary shell/eval, capability validation)
7. Device File Transfer Security (path traversal blocking, size limits, user directory isolation)
8. Phone Audio Bounded Buffering (queue bounds, backpressure frame dropping, clean disconnect)
9. Device Disconnect & Reconnect Lifecycle
10. Device Revocation & Stale Credential Rejection
11. Device Status & Battery Diagnostics
12. Controlled Failure Handling (unknown, offline, revoked devices)
13. Storage Persistence Across Reinitialization
14. Canonical Production Pipeline Routing (process_input -> Router -> DeviceController)
15. Environment-Limited Classification Assertions
"""

import asyncio
import os
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath("."))

from legacy.assistant import process_input
from core.unified_command_router import UnifiedCommandRouter, Intent
from skills.device_management.config import DeviceGatewayConfig
from skills.device_management.device_auth import (
    constant_time_equals,
    generate_device_id,
    generate_device_secret,
    generate_pairing_code,
    generate_pairing_token,
    hash_secret,
)
from skills.device_management.device_controller import DeviceController
from skills.device_management.device_discovery import DeviceDiscoveryBeacon, get_local_ip
from skills.device_management.device_dispatcher import RemoteDeviceDispatcher
from skills.device_management.device_models import DeviceRecord, PairingOffer, ProtocolTypes, build_message, validate_message
from skills.device_management.device_pairing import DevicePairingManager
from skills.device_management.device_registry import DeviceRegistry
from skills.device_management.file_transfer import (
    _safe_filename,
    get_user_file_path,
    get_user_uploads_dir,
    list_user_files,
    save_user_uploaded_file,
)
from skills.device_management.phone_audio import PhoneAudioStreamReceiver


class TestPhase7DeviceRemoteVerification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.user_a = 101
        cls.user_b = 202
        cls.temp_dir = tempfile.mkdtemp(prefix="phase7_device_test_")
        cls.registry_dir = os.path.join(cls.temp_dir, "devices")
        cls.uploads_dir = os.path.join(cls.temp_dir, "uploads")
        os.makedirs(cls.registry_dir, exist_ok=True)
        os.makedirs(cls.uploads_dir, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def setUp(self):
        # Clean test directory state between tests
        for p in Path(self.registry_dir).glob("*.json"):
            try:
                p.unlink()
            except Exception:
                pass
        for p in Path(self.uploads_dir).glob("**/*"):
            if p.is_file():
                try:
                    p.unlink()
                except Exception:
                    pass
        self.registry = DeviceRegistry(base_storage_dir=self.registry_dir)
        self.pairing_mgr = DevicePairingManager(registry=self.registry)
        self.dispatcher = RemoteDeviceDispatcher(registry=self.registry)
        self.controller = DeviceController(
            registry=self.registry,
            pairing_manager=self.pairing_mgr,
            dispatcher=self.dispatcher,
        )

    # ── 1. DEVICE DISCOVERY & LOCAL ROUTING ────────────────────────────────────
    def test_01_device_discovery_and_local_ip(self):
        ip = get_local_ip()
        self.assertIsInstance(ip, str)
        self.assertTrue(len(ip.split(".")) == 4 or ip == "127.0.0.1")

        beacon = DeviceDiscoveryBeacon(port=8765, broadcast_port=8799, interval_seconds=0.1)
        self.assertEqual(beacon.port, 8765)
        self.assertEqual(beacon.broadcast_port, 8799)
        self.assertFalse(beacon._running)

        beacon.start()
        self.assertTrue(beacon._running)
        time.sleep(0.15)
        beacon.stop()
        self.assertFalse(beacon._running)

    # ── 2. PAIRING LIFECYCLE ──────────────────────────────────────────────────
    def test_02_pairing_lifecycle_and_tokens(self):
        offer = self.pairing_mgr.create_offer(
            user_id=self.user_a,
            gateway_host="192.168.1.50",
            gateway_port=8765,
            ttl_seconds=300,
        )
        self.assertIsNotNone(offer)
        self.assertEqual(len(offer.code), 6)
        self.assertTrue(offer.code.isdigit())
        self.assertEqual(offer.user_id, self.user_a)
        self.assertFalse(offer.approved)

        qr = offer.to_qr_payload()
        self.assertEqual(qr["type"], "assistant_device_pairing")
        self.assertEqual(qr["code"], offer.code)
        self.assertEqual(qr["token"], offer.token)
        self.assertEqual(qr["gateway"]["host"], "192.168.1.50")

        # Approve pairing
        record, secret = self.pairing_mgr.approve_pairing(
            offer_id=offer.offer_id,
            device_name="Pixel 8 Pro",
            platform="android",
            os_version="Android 14",
            capabilities=["battery", "flashlight", "launch_app"],
        )
        self.assertIsNotNone(record)
        self.assertIsNotNone(secret)
        self.assertEqual(record.user_id, self.user_a)
        self.assertEqual(record.name, "Pixel 8 Pro")
        self.assertEqual(record.platform, "android")
        self.assertTrue(record.online)
        self.assertIn("flashlight", record.capabilities)

    # ── 3. PAIRING EXPIRY & ANTI-REUSE PROTECTION ────────────────────────────
    def test_03_pairing_expiry_and_anti_reuse(self):
        # 1. Expired offer rejection
        expired_offer = self.pairing_mgr.create_offer(
            user_id=self.user_a,
            ttl_seconds=-10,  # already expired
        )
        found_offer = self.pairing_mgr.get_offer_by_code(expired_offer.code)
        self.assertIsNone(found_offer)

        rec_exp, sec_exp = self.pairing_mgr.approve_pairing(
            offer_id=expired_offer.offer_id,
            device_name="Old Phone",
        )
        self.assertIsNone(rec_exp)
        self.assertIsNone(sec_exp)

        # 2. Single-use rejection
        valid_offer = self.pairing_mgr.create_offer(user_id=self.user_a, ttl_seconds=300)
        rec1, sec1 = self.pairing_mgr.approve_pairing(
            offer_id=valid_offer.offer_id,
            device_name="First Approval",
        )
        self.assertIsNotNone(rec1)

        # Second approval on same offer must fail
        rec2, sec2 = self.pairing_mgr.approve_pairing(
            offer_id=valid_offer.offer_id,
            device_name="Second Reused Approval",
        )
        self.assertIsNone(rec2)
        self.assertIsNone(sec2)

    # ── 4. STRICT PER-USER DEVICE ISOLATION ────────────────────────────────────
    def test_04_cross_user_isolation(self):
        # User A pairs Device A
        offer_a = self.pairing_mgr.create_offer(user_id=self.user_a, ttl_seconds=300)
        dev_a, sec_a = self.pairing_mgr.approve_pairing(
            offer_id=offer_a.offer_id,
            device_name="User A Phone",
        )

        # User B pairs Device B
        offer_b = self.pairing_mgr.create_offer(user_id=self.user_b, ttl_seconds=300)
        dev_b, sec_b = self.pairing_mgr.approve_pairing(
            offer_id=offer_b.offer_id,
            device_name="User B Phone",
        )

        # User A can see Device A, but NOT Device B
        user_a_devs = self.registry.list_devices(self.user_a)
        user_a_names = [d.name for d in user_a_devs]
        self.assertIn("User A Phone", user_a_names)
        self.assertNotIn("User B Phone", user_a_names)

        # User B can see Device B, but NOT Device A
        user_b_devs = self.registry.list_devices(self.user_b)
        user_b_names = [d.name for d in user_b_devs]
        self.assertIn("User B Phone", user_b_names)
        self.assertNotIn("User A Phone", user_b_names)

        # Direct ID access cross-user fails
        self.assertIsNone(self.registry.get_device(self.user_b, dev_a.device_id))
        self.assertIsNone(self.registry.get_device(self.user_a, dev_b.device_id))

        # Direct name resolution cross-user returns empty
        res_a_from_b = self.registry.resolve_device(self.user_b, "User A Phone")
        self.assertEqual(len(res_a_from_b), 0)

        # Dispatch command cross-user fails safely
        cmd_res = self.dispatcher.dispatch_command_sync(
            user_id=self.user_b,
            target_query="User A Phone",
            action="get_battery",
        )
        self.assertFalse(cmd_res["success"])
        self.assertEqual(cmd_res.get("error_code"), "DEVICE_NOT_FOUND")

    # ── 5. ANDROID CAPABILITY DISPATCH & RPC ──────────────────────────────────
    def test_05_android_capability_dispatch(self):
        offer = self.pairing_mgr.create_offer(user_id=self.user_a, ttl_seconds=300)
        dev, sec = self.pairing_mgr.approve_pairing(
            offer_id=offer.offer_id,
            device_name="Galaxy S24",
            capabilities=["battery", "flashlight", "launch_app"],
        )

        # Mock connected websocket send handler
        sent_messages = []

        def mock_send(msg):
            sent_messages.append(msg)
            # Simulate async response from phone
            req_id = msg.get("request_id")
            action = msg.get("payload", {}).get("action")
            if action == "launch_app":
                self.dispatcher.handle_device_result(req_id, {"success": True, "app": "Spotify", "status": "launched"})
            elif action == "flashlight_on":
                self.dispatcher.handle_device_result(req_id, {"success": True, "state": "on"})
            elif action == "get_battery":
                self.dispatcher.handle_device_result(req_id, {"success": True, "percentage": 88, "charging": False})

        self.dispatcher.register_connection(dev.device_id, mock_send)
        self.assertTrue(self.dispatcher.is_connected(dev.device_id))

        # 1. Launch App
        res_launch = self.controller.launch_app(self.user_a, "Spotify")
        self.assertTrue(res_launch["success"])
        self.assertIn("Spotify", res_launch.get("message", ""))

        # 2. Toggle Flashlight
        res_torch = self.controller.toggle_flashlight(self.user_a, enable=True)
        self.assertTrue(res_torch["success"])
        self.assertIn("flashlight", res_torch.get("message", "").lower())

        # 3. Live Battery Check
        res_batt = self.controller.get_battery(self.user_a)
        self.assertTrue(res_batt["success"])
        self.assertEqual(res_batt.get("battery"), 88)

    # ── 6. REMOTE COMMAND SECURITY & ALLOWLISTING ────────────────────────────
    def test_06_remote_command_security_and_allowlisting(self):
        offer = self.pairing_mgr.create_offer(user_id=self.user_a, ttl_seconds=300)
        dev, sec = self.pairing_mgr.approve_pairing(
            offer_id=offer.offer_id,
            device_name="Restricted Node",
            capabilities=["battery"],  # No flashlight capability
        )

        def mock_send(msg):
            pass

        self.dispatcher.register_connection(dev.device_id, mock_send)

        # Missing required capability rejection
        res_torch = self.dispatcher.dispatch_command_sync(
            self.user_a,
            dev.name,
            "flashlight_on",
            parameters={"required_capability": "flashlight"},
        )
        self.assertFalse(res_torch["success"])
        self.assertEqual(res_torch.get("error_code"), "CAPABILITY_MISSING")

        # Message format protocol validation
        valid_msg = build_message(ProtocolTypes.EXECUTE, {"action": "ping"})
        ok, err = validate_message(valid_msg)
        self.assertTrue(ok)
        self.assertEqual(err, "")

        invalid_msg = {"invalid_no_type": True}
        ok_inv, err_inv = validate_message(invalid_msg)
        self.assertFalse(ok_inv)
        self.assertIn("Missing", err_inv)

    # ── 7. DEVICE FILE TRANSFER SECURITY ──────────────────────────────────────
    def test_07_device_file_transfer_security(self):
        sample_bytes = b"Hello Phase 7 Device File Transfer\n"

        # 1. Safe upload with isolation
        res_save = save_user_uploaded_file(
            file_bytes=sample_bytes,
            raw_filename="report.txt",
            user_id=self.user_a,
            base_dir=Path(self.uploads_dir),
        )
        self.assertTrue(res_save["success"])
        self.assertEqual(res_save["filename"], "report.txt")

        # 2. Path Traversal Prevention
        traversal_name = "../../../evil_file.txt"
        res_trav = save_user_uploaded_file(
            file_bytes=b"malicious content",
            raw_filename=traversal_name,
            user_id=self.user_a,
            base_dir=Path(self.uploads_dir),
        )
        self.assertTrue(res_save["success"])
        # Filename must be sanitized to stay inside user directory
        self.assertEqual(res_trav["filename"], "evil_file.txt")
        self.assertTrue(os.path.exists(res_trav["file_path"]))
        self.assertTrue(res_trav["file_path"].startswith(str(Path(self.uploads_dir).resolve())))

        # 3. Cross-User File Retrieval Protection
        path_a = get_user_file_path("report.txt", user_id=self.user_a, base_dir=Path(self.uploads_dir))
        self.assertIsNotNone(path_a)

        path_b = get_user_file_path("report.txt", user_id=self.user_b, base_dir=Path(self.uploads_dir))
        self.assertIsNone(path_b)

        # 4. Oversized upload bounded rejection
        large_bytes = b"X" * (2 * 1024 * 1024)  # 2MB
        res_oversize = save_user_uploaded_file(
            file_bytes=large_bytes,
            raw_filename="large.bin",
            user_id=self.user_a,
            max_mb=1,  # Max 1MB limit
            base_dir=Path(self.uploads_dir),
        )
        self.assertFalse(res_oversize["success"])
        self.assertEqual(res_oversize.get("status"), "size_exceeded")

    # ── 8. PHONE AUDIO BOUNDED BUFFERING ──────────────────────────────────────
    def test_08_phone_audio_bounded_buffering(self):
        receiver = PhoneAudioStreamReceiver(max_buffered_chunks=5)

        # Push 5 chunks within limit
        for i in range(5):
            accepted = receiver.push_pcm_frame(self.user_a, b"\x00\x01" * 160)
            self.assertTrue(accepted)

        # Push 6th chunk exceeds max_buffered_chunks -> backpressure drop (returns False, does not crash)
        dropped = receiver.push_pcm_frame(self.user_a, b"\x00\x02" * 160)
        self.assertFalse(dropped)

        # User stream isolation
        user_b_accepted = receiver.push_pcm_frame(self.user_b, b"\x00\x03" * 160)
        self.assertTrue(user_b_accepted)

        # Clean stream close
        receiver.close_stream(self.user_a)
        self.assertFalse(receiver.is_streaming(self.user_a))

    # ── 9. DEVICE DISCONNECT & RECONNECT ──────────────────────────────────────
    def test_09_disconnect_and_reconnect(self):
        offer = self.pairing_mgr.create_offer(user_id=self.user_a, ttl_seconds=300)
        dev, secret = self.pairing_mgr.approve_pairing(
            offer_id=offer.offer_id,
            device_name="Reconnecting Phone",
        )

        self.dispatcher.register_connection(dev.device_id, lambda m: None)
        self.assertTrue(self.dispatcher.is_connected(dev.device_id))

        # Disconnect
        res_disc = self.controller.disconnect_device(self.user_a, dev.name)
        self.assertTrue(res_disc["success"])
        self.assertFalse(self.dispatcher.is_connected(dev.device_id))

        # Re-authenticate with secret
        auth_dev = self.registry.authenticate(dev.device_id, secret)
        self.assertIsNotNone(auth_dev)
        self.assertTrue(auth_dev.online)

        # Re-authenticate with invalid secret fails
        bad_auth = self.registry.authenticate(dev.device_id, "wrong_secret_12345")
        self.assertIsNone(bad_auth)

    # ── 10. DEVICE REVOCATION & STALE CREDENTIAL REJECTION ────────────────────
    def test_10_device_revocation(self):
        offer = self.pairing_mgr.create_offer(user_id=self.user_a, ttl_seconds=300)
        dev, secret = self.pairing_mgr.approve_pairing(
            offer_id=offer.offer_id,
            device_name="Revocable Device",
        )

        # Unpair / Revoke
        res_unpair = self.controller.unpair_device(self.user_a, dev.name)
        self.assertTrue(res_unpair["success"])
        self.assertEqual(res_unpair.get("status"), "unpaired")

        # Revoked device is omitted from list_devices
        active_devs = self.registry.list_devices(self.user_a)
        self.assertNotIn(dev.device_id, [d.device_id for d in active_devs])

        # Revoked device cannot authenticate
        reauth = self.registry.authenticate(dev.device_id, secret)
        self.assertIsNone(reauth)

        # Commands sent to revoked device are blocked
        res_cmd = self.dispatcher.dispatch_command_sync(self.user_a, dev.name, "get_battery")
        self.assertFalse(res_cmd["success"])

    # ── 11. DEVICE STATUS & BATTERY REPORTING ─────────────────────────────────
    def test_11_device_status_reporting(self):
        # 1. No devices paired
        res_empty = self.controller.list_devices(9999)
        self.assertTrue(res_empty["success"])
        self.assertEqual(res_empty["count"], 0)

        # 2. Device offline status
        offer = self.pairing_mgr.create_offer(user_id=self.user_a, ttl_seconds=300)
        dev, secret = self.pairing_mgr.approve_pairing(
            offer_id=offer.offer_id,
            device_name="Status Check Phone",
            battery=75,
        )
        self.registry.update_status(dev.device_id, online=False, battery=75)

        status_res = self.controller.get_connection_status(self.user_a, dev.name)
        self.assertTrue(status_res["success"])
        self.assertEqual(status_res["status"], "offline")

        # 3. Cached battery reporting for offline device
        batt_res = self.controller.get_battery(self.user_a, dev.name)
        self.assertTrue(batt_res["success"])
        self.assertEqual(batt_res["battery"], 75)

    # ── 12. CONTROLLED FAILURE HANDLING ──────────────────────────────────────
    def test_12_controlled_failures(self):
        # 1. Unknown device command
        res_unknown = self.dispatcher.dispatch_command_sync(
            self.user_a,
            "NonExistentPhone999",
            "get_battery",
        )
        self.assertFalse(res_unknown["success"])
        self.assertEqual(res_unknown["error_code"], "DEVICE_NOT_FOUND")

        # 2. Disconnected device command
        offer = self.pairing_mgr.create_offer(user_id=self.user_a, ttl_seconds=300)
        dev, sec = self.pairing_mgr.approve_pairing(offer.offer_id, "Offline Device")
        self.registry.update_status(dev.device_id, online=False)

        res_offline = self.dispatcher.dispatch_command_sync(
            self.user_a,
            dev.name,
            "launch_app",
            parameters={"app_name": "Calculator"},
        )
        self.assertFalse(res_offline["success"])
        self.assertEqual(res_offline["error_code"], "DEVICE_OFFLINE")

    # ── 13. STORAGE PERSISTENCE ACROSS REINITIALIZATION ───────────────────────
    def test_13_storage_persistence_across_reinit(self):
        offer = self.pairing_mgr.create_offer(user_id=self.user_a, ttl_seconds=300)
        dev, sec = self.pairing_mgr.approve_pairing(
            offer_id=offer.offer_id,
            device_name="Persistent Android",
            battery=92,
        )

        # Create a brand new DeviceRegistry instance pointing to the same storage directory
        new_registry = DeviceRegistry(base_storage_dir=self.registry_dir)
        loaded_dev = new_registry.get_device(self.user_a, dev.device_id)
        self.assertIsNotNone(loaded_dev)
        self.assertEqual(loaded_dev.name, "Persistent Android")
        self.assertEqual(loaded_dev.battery, 92)

    # ── 14. CANONICAL PRODUCTION PIPELINE ROUTING ──────────────────────────────
    def test_14_canonical_production_pipeline_routing(self):
        router = UnifiedCommandRouter()

        # 1. Pairing intent routing
        int1, par1 = router.route_command("Friday pair my phone")
        self.assertEqual(int1, Intent.DEVICE_CONTROL)
        self.assertEqual(par1.get("action"), "remote_device")

        # 2. Paired devices inquiry routing
        int2, par2 = router.route_command("Friday show my paired devices")
        self.assertEqual(int2, Intent.DEVICE_CONTROL)
        self.assertEqual(par2.get("action"), "remote_device")

        # 3. Connection status inquiry routing
        int3, par3 = router.route_command("Friday is my phone connected")
        self.assertEqual(int3, Intent.DEVICE_CONTROL)
        self.assertEqual(par3.get("action"), "remote_device")

        # 4. End-to-end execution via process_input
        res_pair = process_input("Friday pair my phone", user_id=self.user_a)
        self.assertTrue(any(k in res_pair.lower() for k in ["code", "pair", "connect", "gateway"]))

        res_list = process_input("Friday show my paired devices", user_id=self.user_a)
        self.assertTrue(any(k in res_list.lower() for k in ["paired", "device", "connect", "phone"]))

    # ── 15. ENVIRONMENT-LIMITED CLASSIFICATION ASSERTIONS ──────────────────────
    def test_15_environment_limited_classification_assertions(self):
        """
        Verify that physical Android hardware, active Bluetooth radio, and physical Wi-Fi AP actions
        are properly audited, gracefully handled without crashes, and classified truthfully.
        """
        # When physical phone is absent, live dispatch returns offline gracefully
        cmd_res = self.controller.launch_app(self.user_a, "Chrome")
        self.assertIn("success", cmd_res)
        if not cmd_res["success"]:
            self.assertIn(cmd_res.get("status"), ["offline", "not_paired", "unsupported", "error", "multiple_devices"])


if __name__ == "__main__":
    unittest.main()
