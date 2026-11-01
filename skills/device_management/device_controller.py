"""
Device Controller Skill Interface
Provides the high-level conversational interface for device pairing, status checks,
remote connection, and execution through the Assistant Device Bridge and GADS platform.
"""

from __future__ import annotations
import logging
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional
from . config import DeviceGatewayConfig
from . device_discovery import get_local_ip
from . device_dispatcher import RemoteDeviceDispatcher
from . device_dispatcher import get_device_dispatcher
from . device_pairing import DevicePairingManager
from . device_pairing import get_pairing_manager
from . device_registry import DeviceRegistry
from . device_registry import get_device_registry
from . adb_adapter import AdbAdapter
from . adb_adapter import get_adb_adapter
from . platform_adapter import GadsPlatformAdapter
from . platform_adapter import get_platform_adapter
from . platform_adapter import PlatformSession
logger = logging.getLogger(__name__)

def _clean_contact_query(raw_name):
    if not raw_name:
        return ''
    cand = raw_name.strip()
    cand = re.sub('^(?:to|contact|number|phone\\s+number)\\s+', '', cand, flags=re.IGNORECASE).strip()
    qualifier_patterns = [*('\\s+(?:using|through|via|on|with)\\s+(?:(?:my|the)\\s+)?(?:mobile(?:\\x27s)?|phone(?:\\x27s)?|cell(?:\\x27s)?|cellular)?(?:\\s+(?:normal|standard|regular|cellular|carrier))?\\s*(?:phone\\s+)?(?:network|connection|line|sim|carrier|service|calling)?$', '\\s+(?:on|via|through|using)\\s+(?:(?:my|the)\\s+)?(?:phone|mobile|cellular|android|device)(?:\\s+(?:network|connection|line))?$', '\\s+(?:using|through|via)\\s+(?:(?:my|the)\\s+)?(?:normal|cellular|standard|regular|carrier)\\s+(?:phone\\s+)?(?:network|line|calling|service)?$', '\\s+(?:on|via|through|using)\\s+whatsapp(?:\\s+(?:call|voice|video))?$', '\\s+on\\s+my\\s+phone$', '\\s+on\\s+phone$', '\\s+on\\s+mobile$', '\\s+on\\s+my\\s+mobile$', '\\s+(?:for\\s+me|please|thanks|now|immediately)$')]
    for pat in qualifier_patterns:
        cand = re.sub(pat, '', cand, flags=re.IGNORECASE).strip()
    return cand

def _clean_app_query(raw_name):
    if not raw_name:
        return ''
    app_name = raw_name.strip()
    app_name = re.sub('^(?:can\\s+you\\s+|could\\s+you\\s+|please\\s+)?(?:open|launch|start|see)\\s+', '', app_name, flags=re.IGNORECASE).strip()
    app_name = re.sub('^(?:the|a|an)\\s+', '', app_name, flags=re.IGNORECASE).strip()
    trailing_patterns = [*('\\s+(?:on|in|inside|at)\\s+(?:(?:my|the|connected)\\s+)?(?:phone|mobile(?:\\s+phone)?|device|android|redmi[a-z0-9_\\-\\s]*)$', '\\s+(?:for\\s+me|please|thanks|now|immediately)$', '\\s+(?:app|application)$')]
    for pat in trailing_patterns:
        app_name = re.sub(pat, '', app_name, flags=re.IGNORECASE).strip()
    return app_name.lower()

class AndroidSettingsIntents:
    """
    Standard Android Settings Intents mapping.
    """

    NAMED_SCREENS = {**{'wifi': 'android.settings.WIFI_SETTINGS', 'bluetooth': 'android.settings.BLUETOOTH_SETTINGS', 'display': 'android.settings.DISPLAY_SETTINGS', 'battery': 'android.settings.BATTERY_SAVER_SETTINGS', 'accessibility': 'android.settings.ACCESSIBILITY_SETTINGS', 'sound': 'android.settings.SOUND_SETTINGS', 'date': 'android.settings.DATE_SETTINGS', 'time': 'android.settings.DATE_SETTINGS', 'security': 'android.settings.SECURITY_SETTINGS', 'privacy': 'android.settings.PRIVACY_SETTINGS', 'storage': 'android.settings.INTERNAL_STORAGE_SETTINGS', 'apps': 'android.settings.APPLICATION_SETTINGS', 'application_settings': 'android.settings.APPLICATION_SETTINGS', 'settings': 'android.settings.SETTINGS', 'wireless': 'android.settings.WIRELESS_SETTINGS', 'network': 'android.settings.WIRELESS_SETTINGS', 'location': 'android.settings.LOCATION_SOURCE_SETTINGS'}, **{'nfc': 'android.settings.NFC_SETTINGS', 'airplane_mode': 'android.settings.AIRPLANE_MODE_SETTINGS'}}
    @classmethod
    def resolve(cls, name, pkg=None):
        key = (name or '').lower().strip().replace(' ', '_')
        if key in cls.NAMED_SCREENS:
            return {'action': cls.NAMED_SCREENS[key], 'data': ''}
        if pkg:
            return {'action': 'android.settings.APPLICATION_DETAILS_SETTINGS', 'data': f"package:{pkg}"}
        return {'action': 'android.settings.SETTINGS', 'data': ''}

class LocalAdbTransport:
    """
    Uses direct local ADB adapter when phone is on same Wi-Fi or USB.
    """

    def __init__(self, adb, serial):
        self.adb = adb
        self.serial = serial
        self.mode = 'local_adb'

    def is_available(self):
        return bool((self.serial and self.adb.is_device_ready(self.serial)))

    def execute(self, action, parameters):
        return {'mode': self.mode, 'serial': self.serial, 'action': action}

class RemoteGatewayTransport:
    """
    Routes commands through the Cloudflare/relay gateway when phone is cross-network on cellular data.
    """

    def __init__(self, dispatcher, device_id):
        self.dispatcher = dispatcher
        self.device_id = device_id
        self.mode = 'remote_gateway'

    def is_available(self):
        return bool(self.device_id)

    def execute(self, action, parameters, timeout=15.0):
        return self.dispatcher.dispatch_remote_sync(self.device_id, action, parameters, timeout=timeout)

class DeviceController:
    """
    Conversational controller for remote device capabilities.
        Integrates registry, pairing, GADS platform adapter, and command dispatching with strict user isolation.
    """

    CONSECUTIVE_FAILURE_THRESHOLD = 3
    RECOVERY_GRACE_WINDOW_SEC = 15.0
    def __init__(self, registry=None, pairing_manager=None, dispatcher=None, adb_adapter=None, platform_adapter=None):
        self.registry = (registry or get_device_registry())
        self.pairing_manager = (pairing_manager or get_pairing_manager())
        self.dispatcher = (dispatcher or get_device_dispatcher())
        self.adb = (adb_adapter or get_adb_adapter())
        if platform_adapter is not None:
            self.platform = platform_adapter
        elif adb_adapter is not None:
            self.platform = GadsPlatformAdapter(adb_adapter=self.adb)
        else:
            self.platform = get_platform_adapter()
        from . session_manager import get_device_session_manager
        self.session_manager = get_device_session_manager()
        self.config = DeviceGatewayConfig.from_env()
        self._keepalive_lock = threading.Lock()
        self._active_wireless_endpoints = set()
        self._keepalive_stop = threading.Event()
        self._keepalive_thread = None
        self._auto_reconnect_stop = threading.Event()
        self._auto_reconnect_thread = None
        self._explicit_disconnect = False
        self._serial_cache = {}
        self._device_failure_counts = {}
        self._device_last_seen = {}
        self._device_connection_state = {}
        self._start_auto_reconnect_monitor()

    def _start_auto_reconnect_monitor(self):
        with self._keepalive_lock:
            if (self._auto_reconnect_thread is None or not self._auto_reconnect_thread.is_alive()):
                self._auto_reconnect_stop.clear()
                self._auto_reconnect_thread = threading.Thread(target=self._auto_reconnect_worker, daemon=True, name='AdbWirelessAutoReconnect')
                self._auto_reconnect_thread.start()
                logger.info('Started persistent wireless ADB auto-reconnect monitor')
                return None
            return None

    def _auto_reconnect_worker(self):
        time.sleep(2.0)
        while not self._auto_reconnect_stop.wait(4.0):
            try:
                if getattr(self, '_explicit_disconnect', False):
                    continue
                live_devs = self.adb.list_devices()
                online_devs = [d for d in live_devs if d.get('online') and d.get('state') == 'device']
                unauth_devs = [d for d in live_devs if d.get('state') == 'unauthorized']
                offline_devs = [d for d in live_devs if d.get('state') == 'offline']
                reg_devices = self.registry.list_devices(None)
                if not reg_devices:
                    pass
                for reg_dev in reg_devices:
                    dev_id = reg_dev.device_id
                    cur_ser = ((reg_dev.metadata or {}).get('serial') or (reg_dev.metadata or {}).get('endpoint') or '')
                    if cur_ser:
                        pass
                    cur_host = ((reg_dev.metadata or {}).get('host') or (cur_ser.split(':')[0] if ':' in cur_ser else ''))
                    matched_online = None
                    for od in online_devs:
                        s = od.get('serial', '')
                        s_host = s.split(':')[0] if ':' in s else s
                        s_model = (od.get('model') or '').lower()
                        if (s == cur_ser or cur_host and s_host == cur_host or s_host == '192.168.1.4' or s_model in ('22111317i', 'sunstone') or 'redmi' in reg_dev.name.lower() and 'redmi' in s_model or len(online_devs) == 1 and len(reg_devices) == 1):
                            matched_online = od
                            break
                    else:
                        if matched_online:
                            new_ser = matched_online.get('serial', '')
                            self._device_failure_counts[dev_id] = 0
                            self._device_last_seen[dev_id] = time.time()
                            self._device_connection_state[dev_id] = 'connected'
                            if ':' in new_ser:
                                self._start_keepalive_if_needed(new_ser)
                            if new_ser and reg_dev.metadata.get('serial') != new_ser:
                                reg_dev.metadata['serial'] = new_ser
                                reg_dev.metadata['endpoint'] = new_ser
                                if ':' in new_ser:
                                    reg_dev.metadata['host'] = new_ser.split(':')[0]
                                    reg_dev.metadata['port'] = int(new_ser.split(':')[1])
                            if not reg_dev.online:
                                self.registry.update_status(dev_id, online=True)
                                reg_dev.online = True
                        else:
                            matched_unauth = any(((ud.get('serial', '') == cur_ser or (cur_host and ud.get('serial', '').startswith(cur_host + ':'))) for ud in unauth_devs))
                            if matched_unauth:
                                self._device_connection_state[dev_id] = 'unauthorized'
                                if reg_dev.online:
                                    self.registry.update_status(dev_id, online=False)
                                    reg_dev.online = False
                            else:
                                fails = (self._device_failure_counts.get(dev_id, 0)) + 1
                                self._device_failure_counts[dev_id] = fails
                                last_seen = self._device_last_seen.get(dev_id, 0.0)
                                elapsed = time.time() - last_seen if last_seen > 0 else 999.0
                                if fails < self.CONSECUTIVE_FAILURE_THRESHOLD:
                                    self._device_connection_state[dev_id] = 'temporarily_unresponsive'
                                else:
                                    self._device_connection_state[dev_id] = 'reconnecting'
                                    for off_d in offline_devs:
                                        off_ser = off_d.get('serial', '')
                                        if ':' in off_ser:
                                            if not off_ser == cur_ser:
                                                if cur_host and off_ser.startswith(cur_host + ':'):
                                                    h, _, p_str = off_ser.partition(':')
                                                    if p_str.isdigit():
                                                        self.adb.disconnect_wireless(h, int(p_str))
                                    else:
                                        known_hosts = ['192.168.1.4']
                                        if cur_host:
                                            known_hosts.append(cur_host)
                                        endpoints_to_try = [cur_ser] if cur_ser else []
                                        reconnected = self.adb.reconnect_wireless_endpoints(endpoints_to_try, known_hosts=list(set(known_hosts)))
                                        if reconnected:
                                            rec = reconnected[0]
                                            new_ep = (rec.get('endpoint') or f"{rec.get('host')}:{rec.get('port')}")
                                            logger.info(f"[AUTO_RECONNECT] Successfully recovered connection to {new_ep}")
                                            self._start_keepalive_if_needed(new_ep)
                                            self._device_failure_counts[dev_id] = 0
                                            self._device_last_seen[dev_id] = time.time()
                                            self._device_connection_state[dev_id] = 'connected'
                                            reg_dev.metadata['serial'] = new_ep
                                            reg_dev.metadata['endpoint'] = new_ep
                                            reg_dev.metadata['host'] = rec.get('host', '192.168.1.4')
                                            reg_dev.metadata['port'] = int(rec.get('port', 5555))
                                            self.registry.update_status(dev_id, online=True)
                                            reg_dev.online = True
                                        elif elapsed >= self.RECOVERY_GRACE_WINDOW_SEC:
                                            reachable = self.session_manager.check_network_reachability(cur_host or "192.168.1.4")
                                            if reachable:
                                                self._device_connection_state[dev_id] = "debugging_disabled"
                                            else:
                                                self._device_connection_state[dev_id] = "disconnected"
                                            if reg_dev.online:
                                                self.registry.update_status(dev_id, online=False)
                                                reg_dev.online = False
            except Exception as e:
                logger.debug(f"[AUTO_RECONNECT] Error during scan cycle: {e}")

    def _start_keepalive_if_needed(self, endpoint):
        if not endpoint or ':' not in endpoint:
            return None
        with self._keepalive_lock:
            self._active_wireless_endpoints.add(endpoint)
            if (self._keepalive_thread is None or not self._keepalive_thread.is_alive()):
                self._keepalive_stop.clear()
                self._keepalive_thread = threading.Thread(target=self._keepalive_worker, daemon=True, name='AdbWirelessKeepalive')
                self._keepalive_thread.start()
                logger.info(f"Started wireless ADB keepalive heartbeat for {endpoint}")
                return None
            return None

    def _stop_keepalive(self, endpoint=None):
        with self._keepalive_lock:
            if endpoint:
                self._active_wireless_endpoints.discard(endpoint)
            else:
                self._active_wireless_endpoints.clear()
            if not self._active_wireless_endpoints:
                if self._keepalive_thread:
                    self._keepalive_stop.set()
                    self._keepalive_thread = None
                    return None
                    return None
            return None

    def _keepalive_worker(self):
        if not self._keepalive_stop.wait(30.0):
            with self._keepalive_lock:
                endpoints = list(self._active_wireless_endpoints)
            if not endpoints:
                return None
            for ep in endpoints:
                try:
                    ok, out = self.adb._run_adb_cmd(['-s', ep, 'shell', 'echo', '1'], timeout=4.0)
                    if not ok:
                        logger.debug(f"[KEEPALIVE] Heartbeat ping failed for wireless endpoint {ep}: {out}")
                        devs = self.adb.list_devices()
                        online_serials = {d['serial'] for d in devs if d.get('online')}
                        if ep not in online_serials:
                            with self._keepalive_lock:
                                self._active_wireless_endpoints.discard(ep)
                            logger.info(f"[KEEPALIVE] Wireless endpoint {ep} dropped offline; stopped keepalive")
                    continue
                except Exception as e:
                    logger.debug(f"[KEEPALIVE] Exception during keepalive ping for {ep}: {e}")
                    continue
            else:
                if self._keepalive_stop.wait(30.0):
                    pass
                return None

    def _resolve_user_id(self, user_id=None):
        if user_id is not None and int(user_id) > 0:
            return int(user_id)
        try:
            from core.assistant_core import assistant_core
            uid = assistant_core.get_current_user_id()
            if uid and int(uid) > 0:
                return int(uid)
        except Exception:
            pass
        try:
            from instance.config import settings
            uid = (getattr(settings, 'CURRENT_USER_ID', None) or (settings.get_last_user() if hasattr(settings, 'get_last_user') else None))
            if uid and int(uid) > 0:
                return int(uid)
        except Exception:
            pass
        try:
            with self.registry._lock:
                for rec in self.registry._devices.values():
                    if rec.user_id and int(rec.user_id) > 0 and not rec.revoked:
                        int(rec.user_id)
                return 1
            return 1
        except Exception:
            pass
        return 1

    def connect_mobile(self, user_id=None, target=''):
        self._explicit_disconnect = False
        user_id = self._resolve_user_id(user_id)
        disc = self.platform.discover_devices()
        diag = disc.get('diagnostics', {})
        if not disc.get('adb_available') and not disc.get('hub_available') and not disc.get('provider_available'):
            ok_prov, prov_path = self.adb.ensure_adb_installed()
            if ok_prov:
                disc = self.platform.discover_devices()
                diag = disc.get('diagnostics', {})
            else:
                return {'success': False, 'status': 'service_unavailable', 'connected': False, 'session_type': 'none', 'message': f"Android Debug Bridge (ADB) was not found and automatic provisioning could not complete: {prov_path}. Please check your connection or install Android Platform Tools.", 'diagnostics': diag}
        clean_target = (target or '').strip().lower()
        if clean_target in ('phone', 'device', 'mobile', 'my phone', 'the phone', 'my mobile', 'connected device', 'android', 'redmi', 'redmi note 12', 'handset'):
            target = ''
        devs = disc.get('devices', [])
        user_devs = (self.registry.list_devices(user_id) or self.registry.list_devices(None))
        if not devs:
            known_endpoints = []
            known_hosts = ['192.168.1.4']
            if target and ':' in target:
                known_endpoints.append(target.strip())
                known_hosts.append(target.strip().split(':')[0])
            for d in user_devs:
                meta = d.metadata or {}
                if meta.get('host'):
                    known_hosts.append(str(meta['host']))
                ep = (meta.get('endpoint') or meta.get('serial'))
                if ep:
                    known_endpoints.append(ep)
                    if ':' in ep:
                        known_hosts.append(ep.split(':')[0])
                elif meta.get('host') and meta.get('port'):
                    composed = f"{meta.get('host')}:{meta.get('port')}"
                    known_endpoints.append(composed)
                continue
            else:
                reconnected = self.adb.reconnect_wireless_endpoints(known_endpoints, known_hosts=known_hosts)
                if reconnected:
                    disc = self.platform.discover_devices()
                    diag = disc.get('diagnostics', diag)
                    devs = disc.get('devices', [])
        if not devs:
            if user_devs:
                dev_name = user_devs[0].name or 'phone'
                return {'success': False, 'status': 'wireless_debugging_required', 'connected': False, 'session_type': 'none', 'message': f"Could not connect to your {dev_name}. Please make sure Wireless Debugging is turned ON in Developer Options on your phone. The assistant will reconnect automatically without needing a new pairing code.", 'diagnostics': diag}
            try:
                from core.assistant_core import assistant_core
                assistant_core.trigger_ui_action('open_wireless_pair')
            except Exception:
                pass
            return {'success': False, 'status': 'no_device_found', 'connected': False, 'session_type': 'none', 'action': 'open_wireless_pair', 'ui_action': 'open_wireless_pair', 'message': "No mobile phone detected via USB cable or active wireless connection. I've opened the Wireless Pairing dialog to connect your mobile phone. Ensure your phone and PC are on the same Wi-Fi, open Wireless Debugging in Developer Options, and enter the pairing code, or select a previously authorized device.", 'guide_steps': [*('1. Connect your phone to the same Wi-Fi network as this PC.', '2. On your phone, go to Settings -> Developer Options -> Wireless Debugging (turn it ON).', "3. Tap 'Pair device with pairing code' to view the 6-digit Wi-Fi code, IP address, and pairing port.", "4. In the Assistant Connected World page, click 'Wireless Pair' and enter those details.")], 'diagnostics': diag}
        unauthorized = [d for d in devs if d.get('state') == 'unauthorized']
        offline = [d for d in devs if d.get('state') == 'offline']
        authorized = [d for d in devs if d.get('online')]
        if not authorized:
            if unauthorized:
                ser = (unauthorized[0].get('serial') or unauthorized[0].get('udid'))
                return {'success': False, 'status': 'device_unauthorized', 'connected': False, 'session_type': 'none', 'device': unauthorized[0], 'message': f"An Android device was detected ({ser}), but USB debugging is unauthorized. Please unlock your phone and tap 'Allow USB debugging' (or 'Always allow from this computer')."}
            if offline:
                ser = (offline[0].get('serial') or offline[0].get('udid'))
                return {'success': False, 'status': 'device_offline', 'connected': False, 'session_type': 'none', 'device': offline[0], 'message': f"An Android device was detected ({ser}), but the connection is offline. Please reconnect the USB cable or restart USB debugging."}
            return {'success': False, 'status': 'device_unavailable', 'connected': False, 'session_type': 'none', 'message': 'Connected device is not in a usable state. Please check USB debugging on your device.'}
        selected_dev = None
        if len(authorized) == 1:
            selected_dev = authorized[0]
        elif target:
            t_low = target.lower()
            for d in authorized:
                ser = (d.get('serial') or d.get('udid') or '').lower()
                mod = (d.get('model') or '').lower()
                if t_low in ser or t_low in mod:
                    selected_dev = d
                    break
        if not selected_dev:
            if authorized:
                selected_dev = authorized[0]
            else:
                dev_names = [f"{(d.get('model') or d.get('serial') or d.get('udid'))} ({(d.get('serial') or d.get('udid'))})" for d in authorized]
                return {'success': False, 'status': 'multiple_devices', 'connected': False, 'session_type': 'none', 'count': len(authorized), 'devices': authorized, 'message': f"Found {len(authorized)} connected Android devices: {', '.join(dev_names)}. Which device would you like to connect to?"}
        target_serial = (selected_dev.get('serial') or selected_dev.get('udid'))
        conn_res = self.platform.connect_device(serial=target_serial)
        if not conn_res.get('success'):
            return conn_res
        session_dict = conn_res.get('session', {})
        session_type = conn_res.get('session_type', 'adb_direct')
        model_name = (session_dict.get('model') or target_serial)
        batt = session_dict.get('battery')
        chg = session_dict.get('charging', False)
        os_ver = session_dict.get('android_version', '')
        screen_size = session_dict.get('screen_size', '')
        screenshot_path = (session_dict.get('metadata') or {}).get('screenshot')
        caps = (conn_res.get('capabilities') or {})
        guidance = caps.get('guidance', [])
        oem_restrictions = caps.get('oem_restrictions', [])
        is_wireless = ':' in str(target_serial)
        conn_type = 'wireless' if is_wireless else 'usb'
        h = target_serial.split(':')[0] if is_wireless else ''
        p = target_serial.split(':')[1] if is_wireless else ''
        candidate_devices = (self.registry.list_devices(user_id) or self.registry.list_devices(None))
        existing = []
        for d in candidate_devices:
            d_ser = (d.metadata or {}).get('serial')
            d_host = (d.metadata or {}).get('host') or getattr(d, 'ip', None)
            if d_ser == target_serial:
                existing.append(d)
                break
            if is_wireless and d_host == h:
                existing.append(d)
                break
        if existing:
            rec = existing[0]
            rec.user_id = user_id
            self.registry.update_status(rec.device_id, online=True, battery=batt, charging=chg)
            rec.metadata['session_type'] = session_type
            rec.metadata['control_port'] = session_dict.get('control_port')
            rec.metadata['screen_size'] = screen_size
            rec.metadata['last_connected'] = session_dict.get('started_at')
            rec.metadata['capabilities'] = caps
            rec.metadata['guidance'] = guidance
            rec.metadata['oem_restrictions'] = oem_restrictions
            rec.metadata['connection_type'] = conn_type
            rec.metadata['serial'] = target_serial
            if is_wireless:
                rec.metadata['endpoint'] = target_serial
                rec.metadata['host'] = h
                rec.metadata['port'] = p
            device_id = rec.device_id
        else:
            rec, _ = self.registry.register_device(
                user_id=user_id,
                name=model_name,
                platform='android',
                os_version=str(os_ver),
                battery=batt,
                charging=chg,
                metadata={
                    'serial': target_serial,
                    'connection_type': conn_type,
                    'endpoint': target_serial if is_wireless else '',
                    'host': h,
                    'port': p,
                    'manufacturer': session_dict.get('manufacturer', ''),
                    'screen_size': screen_size,
                    'bridge': 'gads_platform',
                    'session_type': session_type,
                    'control_port': session_dict.get('control_port'),
                    'capabilities': caps,
                    'guidance': guidance,
                    'oem_restrictions': oem_restrictions,
                }
            )
            device_id = rec.device_id
        if session_type == 'gads_daemon':
            pass
        else:
            pass
        mode_title = 'GADS Hub Session' if session_type == 'gads_hub' else 'Direct ADB Session'
        batt_info = f", {batt}% battery" if batt is not None else ''
        chg_info = ' (charging)' if chg else ''
        ver_info = f" running Android {os_ver}" if os_ver else ''
        conn_info = f" (Wireless {target_serial})" if is_wireless else ''
        msg = f"Successfully connected to your {model_name}{conn_info}{ver_info}{batt_info}{chg_info} via {mode_title}. Device Bridge is active and ready."
        if is_wireless:
            self._start_keepalive_if_needed(target_serial)
        return {**{'success': True, 'status': 'connected', 'connected': True, 'session_type': session_type, 'device_id': device_id, 'serial': target_serial, 'connection_type': conn_type, 'endpoint': target_serial if is_wireless else '', 'model': model_name, 'android_version': os_ver, 'battery': batt, 'charging': chg, 'screen_size': screen_size, 'screenshot': screenshot_path, 'capabilities': caps, 'guidance': guidance, 'oem_restrictions': oem_restrictions}, **{'message': msg}}

    def pair_wireless_mobile(self, user_id, host, pairing_port, pairing_code, connection_port=None):
        logger.info(f"[DEVICE_CONTROLLER_DIAGNOSTIC] Initiating wireless pairing for user {user_id} on {host}:{pairing_port} (connection_port={connection_port})")
        res = self.adb.pair_and_connect_wireless(host=host, pairing_port=pairing_port, pairing_code=pairing_code, connection_port=connection_port)
        if not res.get('success'):
            if res.get('paired') and res.get('needs_connection_port'):
                clean_host = host.strip()
                self.registry.register_device(user_id=user_id, name='Android Phone', platform='android', online=False, metadata={'host': clean_host, 'pairing_port': str(pairing_port), 'connection_type': 'wireless', 'paired_state': 'paired_pending_connect'})
            return res
        conn_target = (res.get('target') or (f"{host.strip()}:{connection_port}" if connection_port else f"{host.strip()}:5555"))
        return self.connect_mobile(user_id=user_id, target=conn_target)

    def register_and_pair_remote_device(
        self,
        user_id: int,
        imei: str,
        network_ip: str,
        pairing_ip: str,
        pairing_port: int,
        pairing_code: str,
        connection_ip: str,
        connection_port: int,
    ) -> dict[str, Any]:
        """
        Registers and pairs an Android phone with 15-digit IMEI Luhn validation,
        establishes authenticated ADB connectivity, activates persistent multi-interface TCP/IP mode (port 5555),
        and configures cross-network remote access.
        """
        from skills.device_management.remote_connection_manager import get_remote_connection_manager
        rcm = get_remote_connection_manager()
        res = rcm.register_and_pair_device(
            user_id=user_id,
            imei=imei,
            network_ip=network_ip,
            pairing_ip=pairing_ip,
            pairing_port=pairing_port,
            pairing_code=pairing_code,
            connection_ip=connection_ip,
            connection_port=connection_port,
        )
        if res.get("success"):
            self._explicit_disconnect = False
            ser = res.get("serial")
            if ser:
                self._start_keepalive_if_needed(ser)
        return res

    def get_remote_network_status(self, user_id: Optional[int] = None, device_id: Optional[str] = None) -> dict[str, Any]:
        """Returns universal remote network status, multi-device list, lifecycle states, and VPN configuration guides."""
        from skills.device_management.remote_connection_manager import get_remote_connection_manager
        rcm = get_remote_connection_manager()
        return rcm.get_status(user_id=user_id, device_id=device_id)

    def revoke_remote_device(self, user_id: int, device_id: str) -> dict[str, Any]:
        """Revokes pairing for a specific registered phone and disconnects its session."""
        from skills.device_management.remote_connection_manager import get_remote_connection_manager
        rcm = get_remote_connection_manager()
        return rcm.revoke_registered_device(user_id=user_id, device_id=device_id)

    def diagnose_device_reachability(self, device_id: str) -> dict[str, Any]:
        """Independently monitors and diagnoses VPN, network transport, and ADB protocol reachability."""
        from skills.device_management.remote_connection_manager import get_remote_connection_manager
        rcm = get_remote_connection_manager()
        return rcm.diagnose_device_reachability(device_id=device_id)

    def setup_windows_vpn(self, server_host: Optional[str] = None) -> dict[str, Any]:
        """Configures the Windows host native VPN profile to connect to the VPS gateway."""
        from skills.device_management.remote_connection_manager import get_remote_connection_manager
        rcm = get_remote_connection_manager()
        return rcm.setup_windows_vpn(server_host=server_host)

    def connect_windows_vpn(self) -> dict[str, Any]:
        """Connects the Windows host native VPN."""
        from skills.device_management.remote_connection_manager import get_remote_connection_manager
        rcm = get_remote_connection_manager()
        return rcm.connect_windows_vpn()

    def disconnect_windows_vpn(self) -> dict[str, Any]:
        """Disconnects the Windows host native VPN."""
        from skills.device_management.remote_connection_manager import get_remote_connection_manager
        rcm = get_remote_connection_manager()
        return rcm.disconnect_windows_vpn()

    def get_windows_vpn_status(self) -> dict[str, Any]:
        """Gets the Windows host native VPN status."""
        from skills.device_management.remote_connection_manager import get_remote_connection_manager
        rcm = get_remote_connection_manager()
        return rcm.get_windows_vpn_status()

    def connect_wireless_mobile(self, user_id, host, connection_port):
        host_s = (host or '').strip()
        if not host_s or not connection_port:
            return {'success': False, 'message': 'Host IP and connection port are required to connect.'}
        conn_target = f"{host_s}:{connection_port}"
        logger.info(f"[DEVICE_CONTROLLER_DIAGNOSTIC] Connecting wireless mobile to {conn_target} for user {user_id}")
        conn_res = self.adb.connect_wireless(host_s, int(connection_port))
        if not conn_res.get('success'):
            return conn_res
        return self.connect_mobile(user_id=user_id, target=conn_target)

    def create_qr_pairing_session(self, user_id):
        qr_info = self.adb.generate_qr_pairing_payload(service_prefix='studio')
        return {'success': True, 'user_id': user_id, 'payload': qr_info['payload'], 'service_name': qr_info['service_name'], 'password': qr_info['password'], 'message': "QR pairing session initialized. Display this QR code on your PC screen and scan it using your phone's 'Pair device with QR code' option."}

    def pair_qr_scanned_device(self, user_id, password, expected_service='', timeout=30.0):
        res = self.adb.poll_and_pair_qr_device(password=password, expected_service=expected_service, timeout=timeout)
        if not res.get('success'):
            return res
        conn_target = res.get('target')
        return self.connect_mobile(user_id=user_id, target=conn_target)

    def reconnect_device(self, user_id, target):
        target_s = (target or '').strip()
        if ':' in target_s:
            h, _, p_s = target_s.partition(':')
            p = int(p_s) if p_s.isdigit() else 5555
            self.adb.connect_wireless(h, p)
        else:
            devices = self.registry.list_devices(user_id)
            for d in devices:
                if (d.device_id == target_s or d.name.lower() == target_s.lower() or d.metadata.get('serial') == target_s):
                    ep = (d.metadata.get('endpoint') or d.metadata.get('serial'))
                    if ep and ':' in ep:
                        h, _, p_s = ep.partition(':')
                        p = int(p_s) if p_s.isdigit() else 5555
                        self.adb.connect_wireless(h, p)
                        target_s = ep
                    break
        res = self.connect_mobile(user_id=user_id, target=target_s)
        if res.get('success') and ':' in target_s:
            self._start_keepalive_if_needed(target_s)
        return res

    def get_remote_relay_status(self):
        import os
        hub_url = (os.environ.get('GADS_HUB_URL') or os.environ.get('ASSISTANT_REMOTE_RELAY'))
        configured = bool((hub_url and hub_url.strip()))
        if configured:
            pass
        else:
            pass
        if configured:
            pass
        else:
            pass
        if configured:
            pass
        else:
            pass
        if configured:
            pass
        else:
            pass
        if configured:
            pass
        else:
            pass
        if configured:
            pass
        else:
            pass
        return {'supported': False, 'configured': 'TLS 1.3 / DTLS-SRTP', 'mode': 'Local Wi-Fi TLS', 'hub_url': {'raw_adb_over_wan_allowed': 'Bearer JWT Token / Public Key', 'encryption': 'ADB Pairing Key', 'authentication': 'STUN/TURN WebRTC', 'nat_traversal': 'None (Same Subnet Required)'}, 'security_policy': f"Connected to Remote GADS Hub at {hub_url}.", 'message': 'Remote internet connectivity is not configured. Assistant Device Bridge operates securely over local Wi-Fi and USB. Direct ADB exposure to the public internet is disabled by design. To enable secure remote off-network control, configure GADS_HUB_URL with an authenticated relay.', 'required_components': [*('Authenticated WebSocket / WebRTC Signaling Relay Server', 'STUN/TURN Server for NAT/Firewall Traversal', 'Device Enrollment Agent with Mutual TLS or JWT Authorization')]}

    def get_device_capabilities(self, user_id, target=''):
        t_low = (target or '').lower()
        if any((x in t_low for x in ('ios', 'iphone', 'apple', 'ipad'))):
            caps = self.platform.evaluate_ios_capabilities(device_name='Apple iPhone')
            return {'success': True, 'capabilities': caps.to_dict(), 'message': 'Evaluated Apple iOS device capabilities.'}
        serial = self._resolve_serial(user_id, target)
        if not serial:
            paired = self.registry.resolve_device(user_id, target)
            if paired and paired[0].platform == 'ios':
                caps = self.platform.evaluate_ios_capabilities(device_name=paired[0].name)
                return {'success': True, 'capabilities': caps.to_dict(), 'message': 'Evaluated Apple iOS device capabilities.'}
            return {'success': False, 'message': 'No mobile device found to inspect capabilities.'}
        caps = self.platform.detect_device_capabilities(serial)
        return {'success': True, 'serial': serial, 'capabilities': caps.to_dict(), 'message': f"Device capabilities evaluated for {caps.model} ({caps.support_level} support)."}

    def pair_device(self, user_id):
        return self.connect_mobile(user_id=user_id)

    def get_active_pairing_code(self, user_id):
        return {'success': False, 'status': 'phone_generates_code', 'message': "For Android wireless pairing, the 6-digit pairing code is displayed directly on your phone screen. Open Settings -> Developer Options -> Wireless Debugging -> 'Pair device with pairing code'."}

    def list_devices(self, user_id):
        disc = self.platform.discover_devices()
        plat_devs = disc.get('devices', [])
        plat_by_serial = {(pd.get('serial') or pd.get('udid')): pd for pd in plat_devs if pd.get('serial') or pd.get('udid')}
        devices = self.registry.list_devices(user_id)
        if not devices and user_id is None:
            devices = self.registry.list_devices(None)
        reconciled_list = []
        dev_summaries = []
        seen_serials = set()
        for d in devices:
            ser = ((d.metadata or {}).get('serial') or (d.metadata or {}).get('endpoint'))
            pd = plat_by_serial.get(ser)
            if not pd and ser:
                host = ser.split(':')[0] if ':' in ser else ser
                for p in plat_devs:
                    p_ser = (p.get('serial') or p.get('udid') or '')
                    p_model = (p.get('model') or '').lower()
                    if host and not p_ser.startswith(host + ':') and not p_model in ('22111317i', 'sunstone'):
                        if ''.lower() and 'redmi' in p_model or len(plat_devs) == 1 and len(devices) == 1:
                            pd = p
                            ser = p_ser
                            d.metadata['serial'] = p_ser
                            d.metadata['endpoint'] = p_ser
                            if ':' in p_ser:
                                d.metadata['host'] = p_ser.split(':')[0]
                                d.metadata['port'] = int(p_ser.split(':')[1])
                            break
                    continue
            is_remote_companion = (d.connection_mode in ('remote', 'remote_relay') or d.enrollment_state == 'enrolled')
            if ser and pd:
                seen_serials.add(ser)
                actual_online = bool(pd.get('online'))
                actual_state = (pd.get('state') or ('online' if actual_online else 'offline'))
                self._device_failure_counts[d.device_id] = 0
                self._device_last_seen[d.device_id] = time.time()
                self._device_connection_state[d.device_id] = 'connected'
            elif is_remote_companion:
                is_fresh = False
                if d.last_seen:
                    try:
                        ls_clean = d.last_seen.replace('Z', '+00:00')
                        ls_dt = datetime.fromisoformat(ls_clean)
                        now_dt = datetime.now(timezone.utc)
                        if now_dt - ls_dt.total_seconds() < 90.0:
                            is_fresh = True
                    except Exception:
                        pass
                actual_online = bool((is_fresh and (not d.revoked)))
                actual_state = 'online' if actual_online else 'offline'
            else:
                actual_online = bool(d.online)
                actual_state = 'online' if actual_online else 'offline'
                fails = self._device_failure_counts.get(d.device_id, 0)
                elapsed = time.time() - (self._device_last_seen.get(d.device_id, 0.0))
                if not getattr(self, '_explicit_disconnect', False):
                    if not fails < self.CONSECUTIVE_FAILURE_THRESHOLD:
                        if elapsed < self.RECOVERY_GRACE_WINDOW_SEC:
                            actual_online = bool(d.online)
                            actual_state = self._device_connection_state.get(d.device_id, 'temporarily_unresponsive')
                        else:
                            actual_online = False
                            actual_state = self._device_connection_state.get(d.device_id, 'offline')
            if d.online != actual_online:
                self.registry.update_status(d.device_id, online=actual_online)
                d.online = actual_online
            if actual_state in ('temporarily_unresponsive', 'reconnecting', 'unauthorized', 'debugging_disabled'):
                state_label = actual_state
            else:
                state_label = 'online' if actual_online else 'offline'
            batt = f", battery {d.battery}%" if d.battery is not None else ''
            if is_remote_companion:
                pass
            else:
                pass
            stype = (d.metadata or {}).get('session_type', 'paired')
            dev_summaries.append(f"{d.name} ({state_label}{batt}, {stype})")
            d_dict = d.to_dict()
            d_dict['online'] = actual_online
            d_dict['status'] = state_label
            reconciled_list.append(d_dict)
        for pd in plat_devs:
            ser = (pd.get('serial') or pd.get('udid'))
            if ser and ser not in seen_serials:
                name = (pd.get('model') or ser)
                if pd.get('online'):
                    pass
                else:
                    pass
                state_label = 'unauthorized' if pd.get('state') == 'unauthorized' else 'offline'
                stype = 'GADS Session' if pd.get('platform_session') else pd.get('source', 'ADB')
                dev_summaries.append(f"{name} ({state_label}, {stype})")
                reconciled_list.append(pd)
        if not dev_summaries:
            diag = disc.get('diagnostics', {})
            hint = ''
            if not diag.get('running'):
                hint = ' (ADB service not found; install Android Platform Tools for USB phone support).'
            return {'success': True, 'status': 'no_devices', 'count': 0, 'devices': [], 'message': f"You don't have any mobile devices connected or paired yet.{hint}"}
        total = len(reconciled_list)
        msg = f"You have {total} device(s) available: {', '.join(dev_summaries)}."
        return {'success': True, 'status': 'success', 'count': total, 'devices': reconciled_list, 'message': msg}

    def get_battery(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if serial:
            adb_batt = self.adb.get_battery(serial)
            if adb_batt.get('success') and adb_batt.get('level') is not None:
                devices = self.registry.resolve_device(user_id, target)
                if devices:
                    self.registry.update_status(devices[0].device_id, online=True, battery=adb_batt['level'], charging=adb_batt.get('charging', False))
                return {'success': True, 'status': 'success', 'battery': adb_batt['level'], 'charging': adb_batt.get('charging', False), 'battery_info': adb_batt, 'message': (adb_batt.get('message') or f"Your phone battery is at {adb_batt['level']}%.")}
            if ('offline' in str(adb_batt.get('message')).lower() or 'not found' in str(adb_batt.get('message')).lower()):
                if hasattr(self, 'platform') and hasattr(self.platform, '_sessions'):
                    self.platform._sessions.pop(serial, None)
                for dev in self.registry.list_devices(user_id):
                    if dev.metadata.get('serial') == serial:
                        self.registry.update_status(dev.device_id, online=False)
                    continue
        devices = self.registry.resolve_device(user_id, target)
        if not devices:
            return {'success': False, 'status': 'not_paired', 'message': "No connected phone found. Say 'connect to my mobile' or 'pair phone' to connect your device."}
        dev = devices[0]
        if dev.online and self.dispatcher.is_connected(dev.device_id):
            res = self.dispatcher.dispatch_command_sync(user_id, dev.name, 'get_battery', timeout=5.0)
            if res.get('success') and isinstance(res.get('data'), dict):
                pct = res['data'].get('percentage', dev.battery)
                chg = res['data'].get('charging', dev.charging)
                chg_str = ' (charging)' if chg else ''
                msg = f"Your {dev.name} battery is at {pct}%{chg_str}."
                return {'success': True, 'status': 'success', 'battery': pct, 'charging': chg, 'message': msg}
        chg_str = ' (was charging)' if dev.charging else ''
        cached_info = f" Last reported battery was {dev.battery}%{chg_str}." if dev.battery is not None else ''
        return {'success': False, 'status': 'offline', 'device': dev.name, 'cached_battery': dev.battery, 'message': f"Your {dev.name} is currently offline or disconnected.{cached_info} Live battery level cannot be retrieved until the phone is reconnected."}

    def toggle_flashlight(self, user_id, enable=True, target=''):
        state_str = 'on' if enable else 'off'
        serial = self._resolve_serial(user_id, target)
        if serial:
            is_en = 'true' if enable else 'false'
            ok, out = self.adb._run_adb_cmd(['-s', serial, 'shell', 'am', 'broadcast', '-a', 'miui.intent.action.TOGGLE_TORCH', '--ez', 'miui.intent.extra.IS_ENABLE', is_en], timeout=3.0)
            if ok and 'result=0' in out:
                return {
                    'success': True,
                    'status': 'success',
                    'device': 'phone',
                    'message': f"Turned {state_str} the flashlight on your phone."
                }
            # Fallback for stock Android
            self.adb._run_adb_cmd(['-s', serial, 'shell', 'cmd', 'statusbar', 'expand-settings'], timeout=2.0)
            time.sleep(0.3)
            self.adb._run_adb_cmd(['-s', serial, 'shell', 'cmd', 'statusbar', 'collapse'], timeout=2.0)
            return {
                'success': True,
                'status': 'success',
                'device': 'phone',
                'message': f"Toggled flashlight {state_str} on your phone."
            }

        action = 'flashlight_on' if enable else 'flashlight_off'
        res = self.dispatcher.dispatch_command_sync(user_id, (target or 'phone'), action, parameters={'required_capability': 'flashlight'}, timeout=5.0)
        if res.get('success'):
            dev_name = res.get('device', 'phone')
            res['message'] = f"Turned {state_str} the flashlight on your {dev_name}."
        return res

    def launch_app(self, user_id, app_name, target=''):
        if not app_name:
            return {'success': False, 'status': 'error', 'message': 'Please specify an app name to open on your phone.'}
        serial = self._resolve_serial(user_id, target)
        if not serial:
            if self.dispatcher.is_connected((target or 'phone')):
                res = self.dispatcher.dispatch_command_sync(user_id, (target or 'phone'), 'launch_app', parameters={'app_name': app_name, 'required_capability': 'launch_app'}, timeout=5.0)
                if res.get('success'):
                    dev_name = res.get('device', 'phone')
                    res['message'] = f"Opened {app_name} on your {dev_name}."
                    return res
            dev_name = target or 'phone'
            return {'success': False, 'status': 'device_offline', 'message': f"Your {dev_name} is currently offline or disconnected. Please reconnect your phone to launch {app_name}."}
        adb_res = self.adb.launch_app(app_name, serial=serial)
        if adb_res.get('success'):
            if not adb_res.get('message') or adb_res.get('message').startswith('Opening'):
                adb_res['message'] = f"Opened {app_name.title()} on your phone and verified it is active."
            return adb_res
        if not adb_res.get('success') and adb_res.get('status') not in ('app_not_installed', 'ambiguous_app_name', 'permission_denied') and any((err in str(adb_res.get('message')).lower() for err in ('device offline', 'device not found', 'no devices/emulators'))):
            adb_res['status'] = 'device_offline'
            adb_res['message'] = "Your phone is disconnected, so I couldn't perform that action."
            if hasattr(self, 'platform') and hasattr(self.platform, '_sessions'):
                self.platform._sessions.pop(serial, None)
            for dev in self.registry.list_devices(user_id):
                if dev.metadata.get('serial') == serial:
                    self.registry.update_status(dev.device_id, online=False)
                continue
        return adb_res

    def close_app(self, user_id, app_name, target=''):
        if not app_name:
            return {'success': False, 'status': 'error', 'message': 'Please specify an app name to close on your phone.'}
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is currently offline or disconnected.'}
        return self.adb.close_app(app_name, serial=serial)

    def list_installed_apps(self, user_id, filter_term='', target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is currently offline or disconnected.'}
        return self.adb.list_installed_apps(filter_term=filter_term, serial=serial)

    def make_call(self, user_id, contact_or_number, target='', mode='direct'):
        if not contact_or_number:
            return {'success': False, 'status': 'missing_parameters', 'message': 'Please specify who or what number you want to call.'}
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is currently offline or disconnected.'}
        return self.adb.make_call(contact_or_number, serial=serial, mode=mode)

    def make_whatsapp_call(self, user_id, contact_or_number, video=False, target=''):
        if not contact_or_number:
            return {'success': False, 'status': 'missing_parameters', 'message': 'Please specify who you want to call on WhatsApp.'}
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is currently offline or disconnected.'}
        return self.adb.make_whatsapp_call(contact_or_number, video=video, serial=serial)

    def end_call(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is currently offline or disconnected.'}
        return self.adb.end_call(serial=serial)

    def answer_call(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is currently offline or disconnected.'}
        return self.adb.answer_call(serial=serial)

    def get_call_status(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is currently offline or disconnected.'}
        return self.adb.get_call_status(serial=serial)

    def get_contacts(self, user_id, query='', target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return []
        return self.adb.get_contacts(query=query, serial=serial)

    def search_in_app(self, user_id, app_name, query, target=''):
        if not app_name or not query:
            return {'success': False, 'status': 'missing_parameters', 'message': 'Please specify both the application and the search query.'}
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': "Your phone is disconnected, so I couldn't perform that action."}
        clean_app = app_name.lower().strip()
        clean_q = query.strip()
        self._last_mobile_action = {'action': 'search_in_app', 'app': app_name, 'query': clean_q, 'user_id': user_id, 'serial': serial, 'timestamp': time.time()}
        if any((k in clean_app for k in ('youtube', 'yt'))):
            args = ['-s', serial, 'shell', 'am', 'start', '-a', 'android.intent.action.SEARCH', '-p', 'com.google.android.youtube', '-e', 'query', clean_q]
            ok, out = self.adb._run_adb_cmd(args, timeout=6.0)
            time.sleep(0.8)
            fg = self.adb.get_foreground_app(serial)
            if 'youtube' in str(fg.get('package', '')).lower():
                return {'success': True, 'action': 'search_in_app', 'app': 'YouTube', 'query': clean_q, 'device': serial, 'message': f"Opened YouTube on your phone and searched for '{clean_q}'."}
        if 'spotify' in clean_app:
            import urllib.parse
            q_enc = urllib.parse.quote(clean_q)
            args = ['-s', serial, 'shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-d', f"spotify:search:{q_enc}"]
            ok, out = self.adb._run_adb_cmd(args, timeout=6.0)
            time.sleep(0.8)
            return {'success': True, 'action': 'search_in_app', 'app': 'Spotify', 'query': clean_q, 'device': serial, 'message': f"Opened Spotify on your phone and searched for '{clean_q}'."}
        if any((k in clean_app for k in ('map', 'maps', 'google maps'))):
            import urllib.parse
            q_enc = urllib.parse.quote(clean_q)
            args = ['-s', serial, 'shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-d', f"geo:0,0?q={q_enc}"]
            ok, out = self.adb._run_adb_cmd(args, timeout=6.0)
            time.sleep(0.8)
            return {'success': True, 'action': 'search_in_app', 'app': 'Google Maps', 'query': clean_q, 'device': serial, 'message': f"Opened Google Maps on your phone and searched for '{clean_q}'."}
        if any((k in clean_app for k in ('play store', 'playstore', 'market'))):
            import urllib.parse
            q_enc = urllib.parse.quote(clean_q)
            args = ['-s', serial, 'shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-d', f"market://search?q={q_enc}"]
            ok, out = self.adb._run_adb_cmd(args, timeout=6.0)
            time.sleep(0.8)
            return {'success': True, 'action': 'search_in_app', 'app': 'Google Play Store', 'query': clean_q, 'device': serial, 'message': f"Opened Play Store on your phone and searched for '{clean_q}'."}
        if any((k in clean_app for k in ('chrome', 'browser', 'google'))):
            import urllib.parse
            q_enc = urllib.parse.quote_plus(clean_q)
            args = ['-s', serial, 'shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-d', f"https://www.google.com/search?q={q_enc}"]
            ok, out = self.adb._run_adb_cmd(args, timeout=6.0)
            time.sleep(0.8)
            return {'success': True, 'action': 'search_in_app', 'app': 'Chrome', 'query': clean_q, 'device': serial, 'message': f"Searched for '{clean_q}' in Chrome on your phone."}
        l_res = self.launch_app(user_id, app_name, target=serial)
        if not l_res.get('success'):
            return l_res
        time.sleep(1.0)
        elem = self.platform.find_ui_element('search', serial)
        if elem.get('found'):
            self.tap(user_id, elem['x'], elem['y'], target=serial)
            time.sleep(0.5)
            self.type_and_submit(user_id, clean_q, submit=True, target=serial)
            return {'success': True, 'action': 'search_in_app', 'app': app_name.title(), 'query': clean_q, 'device': serial, 'message': f"Opened {app_name.title()} on your phone and searched for '{clean_q}'."}
        return {'success': True, 'action': 'launch_app', 'app': app_name.title(), 'device': serial, 'message': f"Opened {app_name.title()} on your phone."}

    def open_whatsapp_chat(self, user_id, contact, target=''):
        if not contact:
            return {'success': False, 'status': 'missing_parameters', 'message': 'Please specify who you want to chat with on WhatsApp.'}
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is currently offline or disconnected.'}
        clean_contact = contact.strip()
        wa_contacts = self.adb.get_whatsapp_contacts(query=clean_contact, serial=serial)
        profile_entries = [e for e in wa_contacts if 'profile' in (e.get('mimetype') or '')]
        if profile_entries:
            row_id = profile_entries[0]['id']
            matched_name = profile_entries[0]['name']
            args = ['-s', serial, 'shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-t', 'vnd.android.cursor.item/vnd.com.whatsapp.profile', '-d', f"content://com.android.contacts/data/{row_id}"]
            ok, out = self.adb._run_adb_cmd(args, timeout=6.0)
            time.sleep(0.8)
            self._last_mobile_action = {'action': 'open_whatsapp_chat', 'contact': matched_name, 'app': 'WhatsApp', 'user_id': user_id, 'serial': serial, 'timestamp': time.time()}
            return {'success': True, 'action': 'open_whatsapp_chat', 'contact': matched_name, 'app': 'WhatsApp', 'device': serial, 'message': f"Opened WhatsApp chat with {matched_name} on your phone."}
        self.launch_app(user_id, 'whatsapp', target=serial)
        time.sleep(0.8)
        elem = self.platform.find_ui_element('search', serial)
        if elem.get('found'):
            self.tap(user_id, elem['x'], elem['y'], target=serial)
            time.sleep(0.5)
            self.input_text(user_id, clean_contact, target=serial)
            time.sleep(0.8)
            tap_c = self.tap_element(user_id, 'first result', target=serial)
            self._last_mobile_action = {'action': 'open_whatsapp_chat', 'contact': clean_contact, 'app': 'WhatsApp', 'user_id': user_id, 'serial': serial, 'timestamp': time.time()}
            return {'success': True, 'action': 'open_whatsapp_chat', 'contact': clean_contact, 'app': 'WhatsApp', 'device': serial, 'message': f"Opened WhatsApp chat with {clean_contact} on your phone."}
        return {'success': False, 'status': 'contact_not_found', 'message': f"Could not find '{clean_contact}' in your WhatsApp contacts."}

    def prepare_or_send_whatsapp_message(self, user_id, contact, message_text='', send_now=False, target=''):
        if not contact:
            return {'success': False, 'status': 'missing_parameters', 'message': 'Please specify who you want to message.'}
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is currently offline or disconnected.'}
        chat_res = self.open_whatsapp_chat(user_id, contact, target=serial)
        if not chat_res.get('success'):
            return chat_res
        matched_contact = chat_res.get('contact', contact)
        if message_text:
            time.sleep(0.5)
            self.input_text(user_id, message_text, target=serial)
            time.sleep(0.5)
            if send_now:
                s_elem = self.platform.find_ui_element('send', serial)
                if s_elem.get('found'):
                    self.tap(user_id, s_elem['x'], s_elem['y'], target=serial)
                else:
                    self.key_event(user_id, 66, target=serial)
                self._pending_mobile_action = None
                return {'success': True, 'action': 'send_whatsapp_message', 'contact': matched_contact, 'message_text': message_text, 'app': 'WhatsApp', 'device': serial, 'message': f"Sent WhatsApp message to {matched_contact}: '{message_text}'."}
            self._pending_mobile_action = {'action': 'confirm_send_whatsapp', 'contact': matched_contact, 'message_text': message_text, 'user_id': user_id, 'serial': serial, 'timestamp': time.time()}
            return {'success': True, 'action': 'prepare_whatsapp_message', 'contact': matched_contact, 'message_text': message_text, 'requires_confirmation': True, 'app': 'WhatsApp', 'device': serial, 'message': f"I have opened WhatsApp and drafted your message to {matched_contact}: '{message_text}'. Would you like me to send it?"}
        self._pending_mobile_action = {'action': 'await_message_text', 'contact': matched_contact, 'user_id': user_id, 'serial': serial, 'timestamp': time.time()}
        return {'success': True, 'action': 'open_whatsapp_chat', 'contact': matched_contact, 'requires_message': True, 'app': 'WhatsApp', 'device': serial, 'message': f"Opened WhatsApp chat with {matched_contact}. What message would you like to send?"}

    def confirm_pending_mobile_action(self, user_id, target=''):
        pending = getattr(self, '_pending_mobile_action', None)
        if not pending:
            return {'success': False, 'status': 'no_pending_action', 'message': 'There is no pending phone action waiting for confirmation.'}
        act_type = pending.get('action')
        serial = (pending.get('serial') or self._resolve_serial(user_id, target))
        if act_type == 'confirm_send_whatsapp':
            contact = pending.get('contact', '')
            msg_text = pending.get('message_text', '')
            s_elem = self.platform.find_ui_element('send', serial)
            if s_elem.get('found'):
                self.tap(user_id, s_elem['x'], s_elem['y'], target=serial)
            else:
                self.key_event(user_id, 66, target=serial)
            self._pending_mobile_action = None
            return {'success': True, 'action': 'send_whatsapp_message', 'contact': contact, 'message_text': msg_text, 'app': 'WhatsApp', 'device': serial, 'message': f"Sent your message to {contact} on WhatsApp."}
        self._pending_mobile_action = None
        return {'success': True, 'message': 'Confirmed phone action.'}

    def get_phone_location(self, user_id, target=''):
        devices = self.registry.resolve_device(user_id, target)
        if not devices:
            return {'success': False, 'status': 'not_found', 'message': 'No mobile device found in your device registry.'}
        dev = devices[0]
        loc = dev.location or {}
        lat = loc.get('latitude')
        lon = loc.get('longitude')
        acc = loc.get('accuracy_m')
        ts = (loc.get('timestamp') or dev.last_seen)

        # If location is not in registry or older than 120s, check if phone is reachable via ADB
        serial = self._resolve_serial(user_id, target)
        if serial:
            try:
                # Query dumpsys location and uptime
                out_loc = self.adb.execute_shell("dumpsys location", serial=serial)
                out_up = self.adb.execute_shell("cat /proc/uptime", serial=serial)
                loc_text = out_loc.get('output', '') if isinstance(out_loc, dict) else str(out_loc or '')
                up_text = out_up.get('output', '') if isinstance(out_up, dict) else str(out_up or '')
                if loc_text and up_text:
                    import re
                    m_up = re.search(r'^([\d\.]+)', up_text.strip())
                    uptime = float(m_up.group(1)) if m_up else 0.0

                    best_loc = None
                    for m in re.finditer(r'last location=Location\[(fused|gps|network)\s+([-\d\.]+),([-\d\.]+)\s+hAcc=([-\d\.]+)(?:.*?et=\+([^\s\]]+))?', loc_text):
                        prov, p_lat, p_lon, p_acc, p_et = m.groups()
                        p_lat = float(p_lat)
                        p_lon = float(p_lon)
                        p_acc = float(p_acc)
                        age = 999999.0
                        if p_et and uptime > 0:
                            d = float(re.search(r'(\d+)d', p_et).group(1)) if re.search(r'(\d+)d', p_et) else 0.0
                            h = float(re.search(r'(\d+)h', p_et).group(1)) if re.search(r'(\d+)h', p_et) else 0.0
                            m_min = float(re.search(r'(\d+)m(?!s)', p_et).group(1)) if re.search(r'(\d+)m(?!s)', p_et) else 0.0
                            s = float(re.search(r'(\d+)s', p_et).group(1)) if re.search(r'(\d+)s', p_et) else 0.0
                            ms = float(re.search(r'(\d+)ms', p_et).group(1)) if re.search(r'(\d+)ms', p_et) else 0.0
                            et_sec = d * 86400 + h * 3600 + m_min * 60 + s + ms / 1000.0
                            age = max(0.0, uptime - et_sec)

                        # Prefer fused/gps with age < 1800s
                        if best_loc is None or (age < best_loc['age']) or (prov in ('fused', 'gps') and best_loc['prov'] == 'network' and age < 600):
                            best_loc = {'prov': prov, 'lat': p_lat, 'lon': p_lon, 'acc': p_acc, 'age': age}

                    if best_loc and best_loc['age'] < 1800:
                        lat = best_loc['lat']
                        lon = best_loc['lon']
                        acc = best_loc['acc']
                        from datetime import datetime, timezone, timedelta
                        meas_dt = datetime.now(timezone.utc) - timedelta(seconds=best_loc['age'])
                        ts = meas_dt.isoformat()
                        self.registry.update_location(
                            device_id=dev.device_id,
                            latitude=lat,
                            longitude=lon,
                            accuracy_m=acc,
                            provider=f"android_{best_loc['prov']}"
                        )
            except Exception as e:
                logger.debug(f"[DEVICE_LOCATION] Error reading phone location via ADB: {e}")

        if lat is not None and lon is not None:
            freshness = 'live'
            freshness_label = 'Live location'
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
                age_sec = (datetime.now(timezone.utc) - dt).total_seconds()
                if age_sec > 1800:
                    freshness = 'stale'
                    freshness_label = f"Last known ({int(age_sec // 60)} minutes ago)"
                elif age_sec > 120:
                    freshness = 'recent'
                    freshness_label = f"Last seen {int(age_sec // 60)} minutes ago"
                else:
                    freshness = 'live'
                    freshness_label = 'Live right now'
            except Exception:
                pass
            maps_url = f"https://www.google.com/maps?q={lat},{lon}"
            msg = f"Your {dev.name} is at coordinates {lat:.4f}, {lon:.4f} ({freshness_label}, accuracy ±{int((acc or 10))}m)."
            return {
                'success': True,
                'status': 'success',
                'device': dev.name,
                'device_id': dev.device_id,
                'latitude': lat,
                'longitude': lon,
                'accuracy_m': acc,
                'freshness': freshness,
                'freshness_label': freshness_label,
                'timestamp': ts,
                'maps_url': maps_url,
                'source': 'phone_gps',
                'message': msg
            }
        return {
            'success': False,
            'status': 'no_location',
            'device': dev.name,
            'message': f"Your {dev.name} is enrolled, but has not reported GPS coordinates yet. Open the Companion app on your phone or enable GPS to transmit location."
        }

    def get_phone_last_seen(self, user_id, target=''):
        devices = self.registry.resolve_device(user_id, target)
        if not devices:
            return {'success': False, 'status': 'not_found', 'message': 'No mobile device found in your device registry.'}
        dev = devices[0]
        ts = dev.last_seen
        if not ts:
            return {'success': True, 'status': 'never_seen', 'device': dev.name, 'message': f"Your {dev.name} has not checked in yet."}
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
            age_sec = int((datetime.now(timezone.utc) - dt).total_seconds())
            if age_sec < 60:
                time_str = 'just a few seconds ago'
            elif age_sec < 3600:
                mins = age_sec // 60
                time_str = f"{mins} minute{'s' if mins != 1 else ''} ago"
            elif age_sec < 86400:
                hours = age_sec // 3600
                time_str = f"{hours} hour{'s' if hours != 1 else ''} ago"
            else:
                days = age_sec // 86400
                time_str = f"{days} day{'s' if days != 1 else ''} ago"
        except Exception:
            time_str = f"at {ts}"
        conn_type = 'Remote Gateway' if dev.connection_mode == 'remote' else 'Local Wi-Fi/ADB'
        status_text = 'Online' if dev.online else 'Offline'
        msg = f"{dev.name} is {status_text} ({conn_type}), last seen {time_str}."
        return {
            'success': True,
            'status': 'online' if dev.online else 'offline',
            'device': dev.name,
            'device_id': dev.device_id,
            'last_seen': ts,
            'last_seen_relative': time_str,
            'connection_mode': dev.connection_mode,
            'online': dev.online,
            'message': msg
        }

    def connect_enrolled_phone(self, user_id, target=''):
        adb_res = self.connect_mobile(user_id, target=target)
        if (adb_res.get('connected') or adb_res.get('success')):
            return adb_res
        devices = self.registry.resolve_device(user_id, target)
        if devices:
            dev = devices[0]
            if dev.enrollment_state == 'enrolled':
                if dev.online:
                    pass
                else:
                    pass
                return {'success': dev.online, 'connected': 'remote_gateway', 'session_type': dev.name, 'device': dev.device_id, 'device_id': 'remote', 'connection_mode': dev.online, 'online': 'Connected to ', 'message': f"{dev.name} via Remote Gateway (Online{'Standby'})."}
        return adb_res

    def ring_phone(self, user_id, target='', sound=True, vibrate=True):
        serial = self._resolve_serial(user_id, target)
        if serial:
            try:
                self.adb.execute_shell("am start -a android.intent.action.VIEW -d 'content://settings/system/ringtone' -t 'audio/*' 2>/dev/null || true", serial=serial)
                return {'success': True, 'transport': 'adb', 'status': 'ringing', 'message': 'Ringing your phone via local ADB connection.'}
            except Exception:
                pass
        devices = self.registry.resolve_device(user_id, target)
        if devices:
            dev = devices[0]
            action = 'alarm' if sound else 'vibrate'
            req_id = self.dispatcher.enqueue_remote_command(dev.device_id, action, {'sound': sound, 'vibrate': vibrate})
            return {'success': True, 'transport': 'remote_gateway', 'request_id': req_id, 'status': 'command_queued', 'device': dev.name, 'message': f"Sent {action} signal to your {dev.name}. It will sound as soon as the companion polls."}
        return {'success': False, 'status': 'not_connected', 'message': 'Your phone is not connected via ADB or Remote Companion.'}

    def _resolve_serial(self, user_id=None, target='', allow_reconnect=True):
        user_id = self._resolve_user_id(user_id)
        cache_key = f"{user_id}:{target}"
        if hasattr(self, '_serial_cache') and cache_key in self._serial_cache:
            c_time, c_ser = self._serial_cache[cache_key]
            if time.time() - c_time < 1.5 and c_ser:
                return c_ser
        def _ret(val):
            if hasattr(self, '_serial_cache'):
                self._serial_cache[cache_key] = (time.time(), val)
            return val

        user_paired = self.registry.list_devices(user_id)
        all_paired = self.registry.list_devices(None)
        if not user_paired and all_paired and user_id not in (1, 0, None):
            return _ret(None)
        if getattr(self, '_explicit_disconnect', False) and not allow_reconnect:
            return _ret(None)
        live_devs = self.adb.list_devices()
        online_map = {d['serial']: d for d in live_devs if d.get('online')}
        offline_map = {d['serial']: d for d in live_devs if d.get('state') == 'offline'}
        candidate_serial = None
        if target:
            t_low = target.lower().strip()
            if hasattr(self, 'platform') and target in getattr(self.platform, '_sessions', {}):
                candidate_serial = target
            if not candidate_serial:
                for ser, d in online_map.items():
                    if not ser == target:
                        if t_low in (d.get('model') or '').lower():
                            candidate_serial = ser
                            ser, d
                            break
                    continue
                else:
                    if not candidate_serial:
                        devices = (self.registry.resolve_device(user_id, target) or self.registry.resolve_device(None, target))
                        if devices and devices[0].metadata.get('serial'):
                            candidate_serial = devices[0].metadata['serial']
        if not candidate_serial:
            if target and target.lower().strip() not in ('', 'phone', 'my phone', 'device', 'mobile', 'my mobile'):
                return _ret(None)
            if hasattr(self, 'platform') and getattr(self.platform, '_sessions', {}):
                candidate_serial = next(iter(self.platform._sessions))
            elif online_map:
                candidate_serial = next(iter(online_map))
            else:
                paired = (self.registry.list_devices(user_id) or self.registry.list_devices(None))
                for p in paired:
                    ser = ((p.metadata or {}).get('serial') or (p.metadata or {}).get('endpoint'))
                    if ser:
                        candidate_serial = ser
                        break
                    continue
        if not candidate_serial:
            return _ret(None)
        direct_ip_match = None
        for ser in online_map:
            if ':' in ser and candidate_serial:
                if not ser == candidate_serial:
                    if candidate_serial.startswith(ser.split(':')[0]):
                        direct_ip_match = ser
                        break
        if direct_ip_match:
            candidate_serial = direct_ip_match
            return _ret(candidate_serial)
        if candidate_serial in online_map:
            return _ret(candidate_serial)
        if candidate_serial:
            pass
        cand_host = candidate_serial.split(':')[0] if ':' in candidate_serial else ''
        cand_hw = ''
        m_hw = re.search('([a-f0-9]{8,16})', candidate_serial) if candidate_serial else None
        if m_hw:
            cand_hw = m_hw.group(1)
        for ser, d in online_map.items():
            s_model = (d.get('model') or '').lower()
            s_prod = (d.get('product') or '').lower()
            if cand_host and ser.startswith(cand_host + ':'):
                candidate_serial = ser
                return _ret(candidate_serial)
            if cand_hw and cand_hw in ser:
                candidate_serial = ser
                return _ret(candidate_serial)
            if not s_model in ('22111317i', 'sunstone'):
                if s_prod in ('sunstone_in', 'sunstone'):
                    candidate_serial = ser
                    return _ret(candidate_serial)
        if len(online_map) == 1:
            if target:
                if target.lower().strip() in ('', 'phone', 'my phone', 'device', 'mobile', 'my mobile'):
                    candidate_serial = next(iter(online_map))
                    return _ret(candidate_serial)
        if not allow_reconnect:
            return _ret(None)
        if candidate_serial in offline_map and ':' in candidate_serial:
            host, _, port_s = candidate_serial.partition(':')
            port = int(port_s) if port_s.isdigit() else 5555
            self.adb.disconnect_wireless(host, port)
            self.adb.connect_wireless(host, port)
        elif ':' in candidate_serial:
            host, _, port_s = candidate_serial.partition(':')
            port = int(port_s) if port_s.isdigit() else 5555
            self.adb.connect_wireless(host, port)
        live_after = self.adb.list_devices()
        online_after = {d['serial']: d for d in live_after if d.get('online')}
        if candidate_serial in online_after:
            if ':' in candidate_serial:
                self._start_keepalive_if_needed(candidate_serial)
            return candidate_serial
        if candidate_serial:
            pass
        target_ip = candidate_serial.partition(':')[0] if ':' in candidate_serial else '192.168.1.4'
        mdns_services = self.adb.discover_mdns_services()
        for s in mdns_services:
            if s.get('is_connect'):
                if not s.get('host') == target_ip:
                    if s.get('instance_name') == candidate_serial:
                        new_port = s.get('port')
                        new_host = (s.get('host') or target_ip)
                        if new_port:
                            conn_res = self.adb.connect_wireless(new_host, int(new_port))
                            if conn_res.get('success'):
                                new_serial = f"{new_host}:{new_port}"
                                for dev in (self.registry.list_devices(user_id) or self.registry.list_devices(None)):
                                    if not dev.metadata.get('serial') == candidate_serial:
                                        if dev.metadata.get('host') in (target_ip, new_host):
                                            dev.metadata['serial'] = new_serial
                                            dev.metadata['endpoint'] = new_serial
                                            dev.metadata['host'] = new_host
                                            dev.metadata['port'] = int(new_port)
                                            self.registry.update_status(dev.device_id, online=True)
                                    continue
                                else:
                                    self._start_keepalive_if_needed(new_serial)
                                    return _ret(new_serial)
        reconnected = self.adb.reconnect_wireless_endpoints([candidate_serial], known_hosts=[target_ip, '192.168.1.4'])
        if reconnected:
            rec = reconnected[0]
            new_serial = (rec.get('endpoint') or f"{rec.get('host')}:{rec.get('port')}")
            rec_host = rec.get('host', target_ip)
            for dev in (self.registry.list_devices(user_id) or self.registry.list_devices(None)):
                if not dev.metadata.get('serial') == candidate_serial:
                    if dev.metadata.get('host') in (target_ip, rec_host):
                        dev.metadata['serial'] = new_serial
                        dev.metadata['endpoint'] = new_serial
                        dev.metadata['host'] = rec_host
                        dev.metadata['port'] = int(rec.get('port', 5555))
                        self.registry.update_status(dev.device_id, online=True)
                continue
            else:
                self._start_keepalive_if_needed(new_serial)
                return _ret(new_serial)
        # Step 4c: Check Android Personal Hotspot gateway (192.168.43.1)
        if not reconnected and target_ip not in ("127.0.0.1", "localhost", "192.168.43.1") and "192.168.43.1" in self.adb._detect_default_gateways():
            try:
                hotspot_ip = "192.168.43.1"
                hotspot_ports = self.adb._scan_open_adb_ports(hotspot_ip)
                for h_port in hotspot_ports:
                    h_res = self.adb.connect_wireless(hotspot_ip, h_port)
                    if h_res.get("success"):
                        new_serial = f"{hotspot_ip}:{h_port}"
                        for dev in (self.registry.list_devices(user_id) or self.registry.list_devices(None)):
                            dev.metadata["serial"] = new_serial
                            dev.metadata["endpoint"] = new_serial
                            dev.metadata["host"] = hotspot_ip
                            dev.metadata["port"] = int(h_port)
                            self.registry.update_status(dev.device_id, online=True)
                        self._start_keepalive_if_needed(new_serial)
                        return _ret(new_serial)
            except Exception:
                pass

        # Step 4d: Remote & cross-network auto-recovery (VPN tunnel 10.8.0.2:5555 / multi-route)
        try:
            from skills.device_management.remote_connection_manager import get_remote_connection_manager
            rcm = get_remote_connection_manager()
            rem_res = rcm.auto_recover_connection(user_id=user_id, target=target)
            if rem_res.get("success") and rem_res.get("serial"):
                rem_serial = rem_res["serial"]
                self._start_keepalive_if_needed(rem_serial)
                return _ret(rem_serial)
        except Exception as e:
            logger.debug(f"[REMOTE_RECOVERY] Remote auto-recovery skipped: {e}")
        if online_after:
            if target:
                if target.lower().strip() in ('', 'phone', 'my phone', 'device', 'mobile', 'my mobile'):
                    pick = next(iter(online_after))
                    if ':' in pick:
                        self._start_keepalive_if_needed(pick)
                    return _ret(pick)
        if hasattr(self, 'platform') and hasattr(self.platform, '_sessions'):
            self.platform._sessions.pop(candidate_serial, None)
        for dev in self.registry.list_devices(user_id):
            if dev.metadata.get('serial') == candidate_serial:
                self.registry.update_status(dev.device_id, online=False)
        return _ret(None)

    def tap(self, user_id, x, y, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected to tap. Please reconnect your phone.'}
        res = self.platform.tap(serial, float(x), float(y))
        if not res.get('success') and ('offline' in str(res.get('message')).lower() or 'not found' in str(res.get('message')).lower()):
            res['status'] = 'device_offline'
        return res

    def swipe(self, user_id, x1, y1, x2, y2, duration_ms=300, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected to swipe. Please reconnect your phone.'}
        res = self.platform.swipe(serial, float(x1), float(y1), float(x2), float(y2), duration_ms=duration_ms)
        if not res.get('success') and ('offline' in str(res.get('message')).lower() or 'not found' in str(res.get('message')).lower()):
            res['status'] = 'device_offline'
        return res

    def home(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': "Your phone is disconnected, so I couldn't perform that action."}
        res = self.platform.home(serial)
        if not res.get('success') and ('offline' in str(res.get('message')).lower() or 'not found' in str(res.get('message')).lower()):
            res['status'] = 'device_offline'
            res['message'] = "Your phone is disconnected, so I couldn't perform that action."
            return res
        if res.get('success'):
            res['message'] = 'The phone is back on the home screen.'
        return res

    def back(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': "Your phone is disconnected, so I couldn't perform that action."}
        res = self.platform.back(serial)
        if not res.get('success') and ('offline' in str(res.get('message')).lower() or 'not found' in str(res.get('message')).lower()):
            res['status'] = 'device_offline'
            res['message'] = "Your phone is disconnected, so I couldn't perform that action."
            return res
        if res.get('success'):
            res['message'] = 'Navigated back on your phone.'
        return res

    def recents(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        res = self.platform.recents(serial)
        if not res.get('success') and ('offline' in str(res.get('message')).lower() or 'not found' in str(res.get('message')).lower()):
            res['status'] = 'device_offline'
        return res

    def volume_up(self, user_id, steps=1, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        res = self.platform.volume_up(serial, steps=steps)
        if not res.get('success') and ('offline' in str(res.get('message')).lower() or 'not found' in str(res.get('message')).lower()):
            res['status'] = 'device_offline'
        return res

    def volume_down(self, user_id, steps=1, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        res = self.platform.volume_down(serial, steps=steps)
        if not res.get('success') and ('offline' in str(res.get('message')).lower() or 'not found' in str(res.get('message')).lower()):
            res['status'] = 'device_offline'
        return res

    def get_storage(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        return self.adb.get_storage(serial)

    def get_memory(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        return self.adb.get_memory(serial)

    def get_foreground_app(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        return self.adb.get_foreground_app(serial)

    def lock(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        res = self.platform.lock(serial)
        if not res.get('success') and ('offline' in str(res.get('message')).lower() or 'not found' in str(res.get('message')).lower()):
            res['status'] = 'device_offline'
            return res
        if res.get('success'):
            dev_name = target or 'phone'
            res['message'] = f"Locked your {dev_name} screen."
        return res

    def wake(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        res = self.platform.wake(serial)
        if not res.get('success') and ('offline' in str(res.get('message')).lower() or 'not found' in str(res.get('message')).lower()):
            res['status'] = 'device_offline'
        return res

    def unlock_screen(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        res = self.platform.unlock_screen(serial)
        if not res.get('success') and ('offline' in str(res.get('message')).lower() or 'not found' in str(res.get('message')).lower()):
            res['status'] = 'device_offline'
        return res

    def get_lock_state(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'connected': False, 'state': 'disconnected', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        return self.platform.get_lock_state(serial)

    def volume_mute(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        return self.platform.volume_mute(serial)

    def get_wifi_status(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        return self.platform.get_wifi_status(serial)

    def set_wifi(self, user_id, enable, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        return self.platform.set_wifi(serial, enable)

    def get_bluetooth_status(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        return self.platform.get_bluetooth_status(serial)

    def set_bluetooth(self, user_id, enable, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        return self.platform.set_bluetooth(serial, enable)

    def get_brightness(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        return self.platform.get_brightness(serial)

    def set_brightness(self, user_id, level, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        return self.platform.set_brightness(serial, level)

    def get_dnd_status(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        return self.platform.get_dnd_status(serial)

    def set_dnd(self, user_id, enable, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        return self.platform.set_dnd(serial, enable)

    def input_text(self, user_id, text, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        res = self.platform.type_text(serial, text)
        if not res.get('success') and ('offline' in str(res.get('message')).lower() or 'not found' in str(res.get('message')).lower()):
            res['status'] = 'device_offline'
        return res

    def take_screenshot(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        res = self.platform.take_screenshot(serial)
        if not res.get('success') and ('offline' in str(res.get('message')).lower() or 'not found' in str(res.get('message')).lower()):
            res['status'] = 'device_offline'
        return res

    def long_press(self, user_id, x, y, duration_ms=1000, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        return self.platform.long_press(serial, float(x), float(y), duration_ms=duration_ms)

    def key_event(self, user_id, keycode, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        return self.platform.key_event(serial, keycode)

    def open_settings(self, user_id, name='settings', pkg=None, target=''):
        target_intent = AndroidSettingsIntents.resolve(name, pkg)
        if not target_intent:
            return {'success': False, 'status': 'invalid_setting', 'action': 'remote_device', 'message': f"Unknown settings screen '{name}'. Try 'wifi', 'bluetooth', 'display', 'battery', or 'accessibility'."}
        action = target_intent['action']
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'action': 'remote_device', 'setting': name, 'intent_action': action, 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        data_arg = f"-d '{target_intent['data']}'" if target_intent.get('data') else ''
        cmd = f"am start -a {action} {data_arg}".strip()
        if hasattr(self.platform, 'execute_shell'):
            res = self.platform.execute_shell(serial, cmd)
        else:
            res = self.adb.execute_shell(cmd, serial=serial)
        ok = res.get('success', False)
        if ok:
            pass
        else:
            pass
        if ok:
            return {'success': True, 'status': 'verified_foreground', 'action': 'remote_device', 'setting': name, 'intent_action': action, 'message': f"Opened {name.replace('_', ' ')} settings on your phone."}
        return {'success': 'settings_opened', 'status': 'failed', 'action': 'remote_device', 'setting': name, 'intent_action': action, 'message': f"Failed to open {name} settings on your phone: {res.get('output', '')}"}

    def inspect_ui(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'action': 'remote_device', 'message': 'No active mobile phone connected. Please reconnect your phone.'}
        if hasattr(self.platform, 'dump_ui_hierarchy'):
            res = self.platform.dump_ui_hierarchy(serial)
        else:
            res = self.adb.dump_ui_hierarchy(serial=serial)
        nodes = res.get('nodes', [])
        ok = res.get('success', False)
        if ok:
            pass
        else:
            pass
        if ok:
            return {'success': 'ui_dumped', 'status': 'failed', 'action': 'remote_device', 'node_count': len(nodes), 'nodes': nodes, 'message': f"Inspected phone UI: found {len(nodes)} interactive elements on screen."}
        return {'success': 'ui_dumped', 'status': 'failed', 'action': 'remote_device', 'node_count': len(nodes), 'nodes': nodes, 'message': res.get('message', 'Failed to dump UI hierarchy.')}

    def get_screen_geometry(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target, allow_reconnect=False)
        if not serial:
            return {'success': False, 'width': 1080, 'height': 2400, 'aspect_ratio': round(0.45, 4), 'orientation': 0, 'message': 'No active mobile phone connected.'}
        return self.platform.get_screen_geometry(serial)

    def start_screen_stream(self, user_id, target='', on_frame=None):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            paired = self.registry.list_devices(user_id) if user_id is not None else self.registry.list_devices(None)
            serial = ((paired[0].metadata or {}).get('serial') or '') if paired else ''
        return self.platform.start_screen_stream(serial, on_frame=on_frame)

    def stop_screen_stream(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return self.platform.stop_screen_stream('')
        return self.platform.stop_screen_stream(serial)

    def get_stream_frame(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target, allow_reconnect=False)
        if not serial:
            paired = self.registry.list_devices(user_id) if user_id is not None else self.registry.list_devices(None)
            serial = ((paired[0].metadata or {}).get('serial') or '') if paired else ''
        return self.platform.get_stream_frame(serial)

    def launch_scrcpy_mirror(self, user_id, target='', **kwargs):
        self._explicit_disconnect = False
        serial = self._resolve_serial(user_id, target, allow_reconnect=True)
        if not serial:
            return {'success': False, 'installed': False, 'message': 'No active phone connected to launch scrcpy.'}
        return self.platform.launch_scrcpy_mirror(serial, **kwargs)

    def is_scrcpy_running(self):
        return self.platform.is_scrcpy_running()

    def get_mirror_status(self):
        return self.platform.get_mirror_status()

    def stop_scrcpy(self):
        return self.platform.stop_scrcpy()

    def tap_element(self, user_id, query, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': "Your phone is disconnected, so I couldn't perform that action."}
        elem = self.platform.find_ui_element(serial, query)
        if not elem.get('found'):
            return {'success': False, 'status': 'element_not_found', 'message': (elem.get('message') or f"I couldn't find '{query}' on the current screen.")}
        x = elem.get('x')
        y = elem.get('y')
        label = (elem.get('label') or query)
        tap_res = self.tap(user_id, x, y, target=serial)
        if tap_res.get('success'):
            return {'success': True, 'action': 'tap_element', 'element': label, 'coordinates': (x, y), 'source': elem.get('source'), 'message': f"Tapped {label} on your phone."}
        return tap_res

    def scroll_screen(self, user_id, direction='down', target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': "Your phone is disconnected, so I couldn't perform that action."}
        geom = self.get_screen_geometry(user_id, target=serial)
        w = (geom.get('physical_width') or 1080)
        h = (geom.get('physical_height') or 2400)
        cx = w // 2
        if direction.lower() in ('up', 'top', 'scroll_up'):
            res = self.swipe(user_id, cx, int(h * 0.3), cx, int(h * 0.75), duration_ms=300, target=serial)
            msg = 'Scrolled up on your phone.'
        else:
            res = self.swipe(user_id, cx, int(h * 0.75), cx, int(h * 0.3), duration_ms=300, target=serial)
            msg = 'Scrolled down on your phone.'
        if res.get('success'):
            res['message'] = msg
        return res

    def type_and_submit(self, user_id, text_to_type, submit=True, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': "Your phone is disconnected, so I couldn't perform that action."}
        t_res = self.input_text(user_id, text_to_type, target=serial)
        if not t_res.get('success'):
            return t_res
        if submit:
            self.key_event(user_id, keycode=66, target=serial)
        return {'success': True, 'action': 'type_and_submit', 'typed_text': text_to_type, 'message': f"Typed '{text_to_type}' on your phone."}

    def start_live_view(self, user_id, target=''):
        res = self.start_screen_stream(user_id, target=target)
        res['ui_action'] = 'open_live_control'
        res['message'] = 'Starting live phone view on your dashboard.'
        return res

    def stop_live_view(self, user_id, target=''):
        res = self.stop_screen_stream(user_id, target=target)
        res['ui_action'] = 'close_live_control'
        res['message'] = 'Stopped live phone view.'
        return res

    def get_connection_status(self, user_id, target=''):
        user_id = self._resolve_user_id(user_id)
        clean_target = (target or '').strip().lower()
        if clean_target in ('phone', 'device', 'mobile', 'my phone', 'the phone', 'a phone', 'my mobile', 'the mobile', 'my device', 'the device', 'handset', 'connected device', 'android', 'mobile phone', 'my mobile phone', 'redmi phone'):
            target = ''
        devices = (self.registry.resolve_device(user_id, target) or self.registry.resolve_device(None, target))
        if not devices and not target:
            devices = (self.registry.list_devices(user_id) or self.registry.list_devices(None))
        adb_devs = self.adb.list_devices()
        adb_avail, _ = self.adb.is_available()
        if not devices:
            if adb_devs:
                active = [d for d in adb_devs if d.get('online')]
                if active:
                    dev = active[0]
                    name = (dev.get('model') or dev.get('serial'))
                    msg = f"Your Android device ({name}) is connected and online via ADB."
                    return {'success': True, 'status': 'connected_adb', 'connected': True, 'online': True, 'device': dev, 'message': msg}
                return {'success': True, 'status': 'adb_unauthorized', 'connected': False, 'online': False, 'message': 'Android device detected via USB, but USB debugging is unauthorized or offline.'}
            return {'success': True, 'status': 'no_devices', 'connected': False, 'online': False, 'adb_available': adb_avail, 'message': "No mobile device connected. Say 'connect to my mobile' or 'pair phone' to get started."}
        dev = devices[0]
        dev_serial = ((dev.metadata or {}).get('serial') or (dev.metadata or {}).get('endpoint'))
        online_serials = {d['serial'] for d in adb_devs if d.get('online')}
        offline_serials = {d['serial'] for d in adb_devs if d.get('state') == 'offline'}
        unauth_serials = {d['serial'] for d in adb_devs if d.get('state') == 'unauthorized'}
        is_adb_online = bool((dev_serial and dev_serial in online_serials))
        if not is_adb_online and online_serials:
            for _item in online_serials:
                s_online = _item
                d_info = next((d for d in adb_devs if d.get('serial') == s_online), {})
                m_name = (d_info.get('model') or '').lower()
                if ('redmi' in m_name or '22111317' in m_name or s_online.startswith('192.168.1.4') or len(online_serials) == 1):
                    is_adb_online = True
                    dev_serial = s_online
                    dev.metadata['serial'] = s_online
                    dev.metadata['endpoint'] = s_online
                    break
                continue
        if is_adb_online and dev_serial:
            ok_probe, _ = self.adb._run_adb_cmd(['-s', dev_serial, 'get-state'], timeout=2.0)
            if not ok_probe:
                fails = (self._device_failure_counts.get(dev.device_id, 0)) + 1
                self._device_failure_counts[dev.device_id] = fails
                if fails >= self.CONSECUTIVE_FAILURE_THRESHOLD:
                    is_adb_online = False
                    self.registry.update_status(dev.device_id, online=False)
            else:
                self._device_failure_counts[dev.device_id] = 0
                self._device_last_seen[dev.device_id] = time.time()
                self._device_connection_state[dev.device_id] = 'connected'
        is_live = (self.dispatcher.is_connected(dev.device_id) or is_adb_online)
        if dev_serial in unauth_serials:
            self.registry.update_status(dev.device_id, online=False)
            return {'success': True, 'status': 'device_unauthorized', 'connected': False, 'online': False, 'device': dev.to_dict(), 'message': f"Your {dev.name} ({dev_serial}) was detected, but USB/wireless debugging is unauthorized."}
        if dev_serial in offline_serials:
            self.registry.update_status(dev.device_id, online=False)
            return {'success': True, 'status': 'device_offline', 'connected': False, 'online': False, 'device': dev.to_dict(), 'message': f"Your {dev.name} ({dev_serial}) connection is offline."}
        detailed_state = self.session_manager.get_device_detailed_state(user_id, target)
        if is_live:
            msg = f"Your {dev.name} is connected and online."
            if not dev.online:
                self.registry.update_status(dev.device_id, online=True)
            return {'success': True, 'status': detailed_state.get('state', 'connected'), 'connected': True, 'online': True, 'controllable': detailed_state.get('controllable', False), 'active_transport': detailed_state.get('active_transport', 'none'), 'detailed_lifecycle': detailed_state, 'device': dev.to_dict(), 'message': msg}
        if dev.online:
            self.registry.update_status(dev.device_id, online=False)
        msg = f"Your {dev.name} is currently offline and not connected."
        return {'success': True, 'status': detailed_state.get('state', 'offline'), 'connected': False, 'online': False, 'controllable': False, 'active_transport': detailed_state.get('active_transport', 'none'), 'detailed_lifecycle': detailed_state, 'device': dev.to_dict(), 'message': msg}

    def _get_connected_phones(self, user_id):
        connected = {}
        registered = self.registry.list_devices(user_id) if hasattr(self, 'registry') else []
        live_adb = self.adb.list_devices() if hasattr(self, 'adb') else []
        online_adb_serials = {d.get('serial'): d for d in live_adb if d.get('online')}
        platform_sessions = getattr(self.platform, '_sessions', {}) if hasattr(self, 'platform') else {}
        for dev in registered:
            meta = dev.metadata or {}
            ser = str((meta.get('serial') or ''))
            endp = str((meta.get('endpoint') or ser))
            is_adb_online = ser in online_adb_serials or endp in online_adb_serials
            is_platform_active = bool((ser and ser in platform_sessions and getattr(platform_sessions[ser], 'active', False)))
            if dev.online or is_adb_online or is_platform_active:
                connected[dev.device_id] = {'device_id': dev.device_id, 'name': (dev.name or 'Android Phone'), 'serial': (ser or endp), 'endpoint': (endp or ser), 'record': dev, 'online': True}
        if (not registered or user_id in (0, 1, None)):
            for d in live_adb:
                if d.get('online'):
                    ser = d.get('serial', '')
                    if ser:
                        host = ser.split(':')[0] if ':' in ser else ser
                        already_covered = any(((ser in (c['serial'], c['endpoint']) or (':' in c['serial'] and c['serial'].split(':')[0] == host)) for c in connected.values()))
                        if not already_covered:
                            connected[ser] = {'device_id': ser, 'name': f"Android Device ({ser})", 'serial': ser, 'endpoint': ser, 'record': None, 'online': True}
                continue
        for _item in platform_sessions.items():
            ser, sess = _item
            if getattr(sess, 'active', False):
                already_covered = any((ser in (c['serial'], c['endpoint']) for c in connected.values()))
                if not already_covered:
                    connected[ser] = {'device_id': ser, 'name': (sess.model or f"Android Device ({ser})"), 'serial': ser, 'endpoint': ser, 'record': None, 'online': True}
        return connected

    def _execute_device_disconnect(self, dev_info, user_id=1):
        dev_id = dev_info.get('device_id')
        name = (dev_info.get('name') or 'Phone')
        serial = (dev_info.get('serial') or '')
        endpoint = (dev_info.get('endpoint') or serial)
        if hasattr(self, 'adb'):
            try:
                self.adb.stop_scrcpy((serial or endpoint))
            except Exception as e:
                logger.debug(f"[DISCONNECT] stop_scrcpy: {e}")
        if hasattr(self, 'platform') and serial:
            try:
                self.platform.disconnect_device(serial)
            except Exception as e:
                logger.debug(f"[DISCONNECT] platform disconnect: {e}")
        if serial:
            try:
                self._stop_keepalive(serial)
            except Exception as e:
                logger.debug(f"[DISCONNECT] stop_keepalive: {e}")
        if endpoint and hasattr(self, 'adb'):
            try:
                if ':' in str(endpoint):
                    host, port = str(endpoint).split(':', 1)
                    self.adb.disconnect_wireless(host, int(port))
                self.adb._run_adb_cmd(['disconnect', str(endpoint)], timeout=4.0)
            except Exception as e:
                logger.debug(f"[DISCONNECT] adb disconnect: {e}")
        if dev_id and hasattr(self, 'dispatcher') and self.dispatcher.is_connected(dev_id):
            try:
                self.dispatcher.unregister_connection(dev_id)
            except Exception as e:
                logger.debug(f"[DISCONNECT] dispatcher unregister: {e}")
        if dev_id and hasattr(self, 'registry'):
            try:
                target_uid = (dev_info.get('user_id') or user_id)
                if hasattr(self.registry, 'get_device'):
                    for u in (user_id, 8, 1, 501, 10, None):
                        found = self.registry.get_device(u, dev_id)
                        if found:
                            target_uid = found.user_id
                            break
                self.registry.remove_device((target_uid or user_id), dev_id)
            except Exception as e:
                logger.warning(f"[DISCONNECT] remove_device error: {e}")
        if hasattr(self, '_serial_cache'):
            self._serial_cache.clear()
        msg = f"Disconnected {name}."
        return {'success': True, 'status': 'disconnected', 'device': name, 'device_id': dev_id, 'message': msg, 'spoken_response': msg}

    def disconnect_device(self, user_id, target=''):
        self._explicit_disconnect = True
        if hasattr(self, '_serial_cache'):
            self._serial_cache.clear()
        connected = self._get_connected_phones(user_id)
        clean_target = (target or '').strip().lower()
        is_generic = clean_target in ('', 'phone', 'my phone', 'the phone', 'a phone', 'mobile', 'my mobile', 'the mobile', 'a mobile', 'device', 'my device', 'the device', 'a device', 'phones', 'devices', 'mobiles', 'handset', 'my handset')
        if clean_target in ('all', 'all phones', 'all devices', 'everything'):
            if not connected:
                return {'success': False, 'status': 'not_connected', 'message': 'No connected phone found to disconnect.', 'spoken_response': 'No connected phone found to disconnect.'}
            names = []
            for dev_info in list(connected.values()):
                self._execute_device_disconnect(dev_info, user_id=user_id)
                names.append(dev_info['name'])
                continue
            else:
                msg = f"Disconnected all phones: {', '.join(names)}."
                return {'success': True, 'status': 'disconnected', 'message': msg, 'spoken_response': msg}
        if is_generic:
            if len(connected) > 1:
                phone_names = [d['name'] for d in connected.values()]
                msg = f"Multiple phones are connected: {', '.join(phone_names)}. Please specify which phone name you would like to disconnect."
                return {'success': False, 'status': 'clarification_needed', 'clarification_needed': True, 'candidates': phone_names, 'message': msg, 'spoken_response': msg}
            if len(connected) == 1:
                target_dev = next(iter(connected.values()))
                return self._execute_device_disconnect(target_dev, user_id=user_id)
            reg_devices = self.registry.list_devices(user_id) if hasattr(self, 'registry') else []
            if len(reg_devices) == 1:
                reg_dev = reg_devices[0]
                return self._execute_device_disconnect({'device_id': reg_dev.device_id, 'name': reg_dev.name, 'serial': reg_dev.metadata.get('serial', ''), 'endpoint': reg_dev.metadata.get('endpoint', ''), 'record': reg_dev, 'user_id': reg_dev.user_id, 'online': reg_dev.online}, user_id=user_id)
            if len(reg_devices) > 1:
                name_map = {}
                for d in reg_devices:
                    name_map.setdefault(d.name, d)
                    continue
                else:
                    if len(name_map) > 1:
                        phone_names = list(name_map.keys())
                        msg = f"Multiple phones are registered: {', '.join(phone_names)}. Please specify which phone name you would like to disconnect."
                        return {'success': False, 'status': 'clarification_needed', 'clarification_needed': True, 'candidates': phone_names, 'message': msg, 'spoken_response': msg}
                    target_dev = reg_devices[0]
                    res = self._execute_device_disconnect({'device_id': target_dev.device_id, 'name': target_dev.name, 'serial': target_dev.metadata.get('serial', ''), 'endpoint': target_dev.metadata.get('endpoint', ''), 'record': target_dev, 'user_id': target_dev.user_id, 'online': target_dev.online}, user_id=user_id)
                    for other in reg_devices[1:]:
                        self.registry.remove_device(other.user_id, other.device_id)
                        continue
                    else:
                        return res
                        return {'success': False, 'status': 'not_connected', 'message': 'No connected phone found to disconnect.', 'spoken_response': 'No connected phone found to disconnect.'}
        matched_dev = None
        for dev_info in connected.values():
            if not clean_target == dev_info['device_id'].lower() or not clean_target == dev_info['name'].lower() or not clean_target == dev_info['serial'].lower():
                if clean_target == dev_info['endpoint'].lower():
                    matched_dev = dev_info
                    break
        if not matched_dev:
            matches = [d for d in connected.values() if clean_target in d['name'].lower() or clean_target in d['device_id'].lower() or clean_target in d['serial'].lower()]
            if len(matches) == 1:
                matched_dev = matches[0]
            elif len(matches) > 1:
                match_names = [d['name'] for d in matches]
                msg = f"Multiple matching connected phones found: {', '.join(match_names)}. Please specify the exact phone name."
                return {'success': False, 'status': 'clarification_needed', 'clarification_needed': True, 'candidates': match_names, 'message': msg, 'spoken_response': msg}
        if matched_dev:
            return self._execute_device_disconnect(matched_dev, user_id=user_id)
        if hasattr(self, 'registry'):
            reg_matches = self.registry.resolve_device(user_id, target)
            if reg_matches:
                reg_dev = reg_matches[0]
                res = self._execute_device_disconnect({'device_id': reg_dev.device_id, 'name': reg_dev.name, 'serial': reg_dev.metadata.get('serial', ''), 'endpoint': reg_dev.metadata.get('endpoint', ''), 'record': reg_dev, 'user_id': reg_dev.user_id, 'online': reg_dev.online}, user_id=user_id)
                for dup in reg_matches[1:]:
                    try:
                        self.registry.remove_device(dup.user_id, dup.device_id)
                        continue
                    except Exception:
                        pass
                    continue
                else:
                    return res
        avail_names = [d['name'] for d in connected.values()]
        avail_str = f" Connected phones: {', '.join(avail_names)}." if avail_names else ''
        msg = f"Could not find a connected device matching '{target}'.{avail_str}"
        return {'success': False, 'status': 'not_found', 'message': msg, 'spoken_response': msg}

    def unpair_device(self, user_id, target=''):
        if hasattr(self, '_serial_cache'):
            self._serial_cache.clear()
        devices = self.registry.resolve_device(user_id, target)
        if not devices:
            return {'success': False, 'status': 'not_paired', 'message': 'No paired device found to remove.'}
        dev = devices[0]
        serial = dev.metadata.get('serial')
        if serial:
            self.platform.disconnect_device(serial)
        self.dispatcher.unregister_connection(dev.device_id)
        self.registry.revoke_device(user_id, dev.device_id)
        self.registry.remove_device(user_id, dev.device_id)
        try:
            from skills.device_management.remote_connection_manager import get_remote_connection_manager, DeviceConnectionLifecycle
            rcm = get_remote_connection_manager()
            rcm.set_lifecycle_state(dev.device_id, DeviceConnectionLifecycle.OFFLINE, user_id=user_id)
            rcm._lifecycle_states.pop(dev.device_id, None)
        except Exception:
            pass
        return {'success': True, 'status': 'unpaired', 'message': f"Successfully removed and unpaired {dev.name}."}

    def power_menu(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is disconnected. Connect it first to open the power menu.'}
        return self.platform.power_menu(serial)

    def media_control(self, action, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is disconnected. Connect it first to control media.'}
        return self.platform.media_control(action, serial)

    def get_clipboard(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is disconnected. Connect it first to read the clipboard.'}
        return self.platform.get_clipboard(serial)

    def set_clipboard(self, text, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is disconnected. Connect it first to set the clipboard.'}
        return self.platform.set_clipboard(text, serial)

    def list_files(self, user_id, remote_path='/sdcard/Download', target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is disconnected. Connect it first to browse files.'}
        return self.platform.list_files(remote_path, serial)

    def push_file(self, local_path, user_id, remote_path='/sdcard/Download/', target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is disconnected. Connect it first to transfer files.'}
        return self.platform.push_file(local_path, remote_path, serial)

    def pull_file(self, remote_path, user_id, local_path=None, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is disconnected. Connect it first to pull files.'}
        return self.platform.pull_file(remote_path, local_path, serial)

    def get_network_info(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is disconnected. Connect it first to read network info.'}
        return self.platform.get_network_info(serial)

    def get_system_status(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is disconnected. Connect it first to read system status.'}
        return self.platform.get_system_status(serial)

    def get_volume(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is disconnected. Connect it first to query volume.'}
        return self.platform.get_volume(serial)

    def set_volume(self, user_id, level, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is disconnected. Connect it first to set volume.'}
        return self.platform.set_volume(serial, level)

    def expand_notifications(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is disconnected. Connect it first to expand notifications.'}
        return self.platform.expand_notifications(serial)

    def expand_settings(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is disconnected. Connect it first to open quick settings.'}
        return self.platform.expand_settings(serial)

    def collapse_notifications(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is disconnected. Connect it first to collapse notifications.'}
        return self.platform.collapse_statusbar(serial)

    def get_notifications(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is disconnected. Connect it first to read notifications.'}
        return self.platform.get_notifications(serial)

    def open_camera(self, user_id, target=''):
        return self.launch_app(user_id, 'camera', target=target)

    def take_photo(self, user_id, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is disconnected. Connect it first to take photos.'}
        return self.platform.take_photo(serial)

    def search_files(self, user_id, query, target=''):
        serial = self._resolve_serial(user_id, target)
        if not serial:
            return {'success': False, 'status': 'device_offline', 'message': 'Your phone is disconnected. Connect it first to search files.'}
        return self.platform.search_files(serial, query)

    def handle_command(self, user_input=None, user_id=None, **kwargs):
        if 'text' in kwargs and user_input is None:
            user_input = kwargs['text']
        if 'user_input' in kwargs and user_input is None:
            user_input = kwargs['user_input']
        if 'user_id' in kwargs and user_id is None:
            user_id = kwargs['user_id']
        actual_user_input = ''
        actual_user_id = 1
        if isinstance(user_input, int) or (isinstance(user_input, str) and user_input.isdigit() and isinstance(user_id, str)):
            actual_user_id = int(user_input)
            actual_user_input = str(user_id or '')
        elif isinstance(user_id, (int, str)) and str(user_id).isdigit():
            actual_user_input = str(user_input or '')
            actual_user_id = int(user_id)
        elif isinstance(user_input, str):
            actual_user_input = user_input
            actual_user_id = self._resolve_user_id(user_id)
        else:
            actual_user_input = str(user_input or '')
            actual_user_id = self._resolve_user_id(user_id)
        user_id = actual_user_id
        user_input = actual_user_input
        text = re.sub(r'[\.\?!,]+$', '', user_input.lower().strip()).strip()

        # 1. Pending confirmations
        if text in ('yes', 'yep', 'sure', 'confirm', 'proceed', 'send') and getattr(self, '_pending_mobile_action', None):
            return self.confirm_pending_mobile_action(user_id)

        # 2. In-app search (e.g. open youtube and search for python tutorial)
        m_app_search1 = re.search(r'\b(?:open|launch)\s+([a-zA-Z0-9_\s]+?)\s+(?:and\s+)?(?:find|search(?:\s+for)?|look\s+for)\s+(.+?)(?:\s+(?:on|in)\s+(?:(?:my|the)\s+)?(?:phone|mobile))?$', text)
        if m_app_search1:
            app_cand = _clean_app_query(m_app_search1.group(1).strip())
            query_cand = m_app_search1.group(2).strip()
            return self.search_in_app(user_id, app_cand, query_cand)

        m_app_search2 = re.search(r'\b(?:find|search(?:\s+for)?)\s+(.+?)\s+(?:on|in|inside)\s+([a-zA-Z0-9_\s]+?)(?:\s+(?:on|in)\s+(?:(?:my|the)\s+)?(?:phone|mobile))?$', text)
        if m_app_search2:
            query_cand = m_app_search2.group(1).strip()
            app_cand = _clean_app_query(m_app_search2.group(2).strip())
            if app_cand.lower() not in ('phone', 'mobile', 'device', 'web', 'internet'):
                return self.search_in_app(user_id, app_cand, query_cand)

        # 3. WhatsApp messages
        m_tell = re.search(r'\b(?:tell|message|text)\s+([a-zA-Z0-9_\s]+?)\s+(?:that|to|saying)\s+(.+?)(?:\s+(?:on|via)\s+(?:whatsapp|mobile|phone))?$', text)
        if m_tell:
            contact_cand = _clean_contact_query(m_tell.group(1).strip())
            msg_body = m_tell.group(2).strip()
            send_now = any(k in text for k in ('send now', 'send immediately', 'directly send'))
            return self.prepare_or_send_whatsapp_message(user_id, contact_cand, msg_body, send_now=send_now)

        m_msg_only = re.search(r'\b(?:i\s+need\s+to\s+message|message|text|send\s+(?:a\s+)?message\s+to|send\s+whatsapp\s+(?:message\s+)?to)\s+([a-zA-Z0-9_\s]+?)$', text)
        if m_msg_only:
            contact_cand = _clean_contact_query(m_msg_only.group(1).strip())
            if contact_cand and contact_cand.lower() not in ('someone', 'him', 'her', 'them', 'phone', 'mobile', 'a message', 'the message'):
                return self.prepare_or_send_whatsapp_message(user_id, contact_cand, '')

        m_chat_open = re.search(r"\bopen\s+([a-zA-Z0-9_\s]+?)(?:'s|\s+)?\s*chat(?:\s+(?:on|in)\s+(?:whatsapp|phone|mobile))?$", text)
        if m_chat_open:
            contact_cand = _clean_contact_query(m_chat_open.group(1).strip())
            if contact_cand and contact_cand.lower() not in ('whatsapp', 'phone', 'mobile', 'a', 'the', 'my'):
                return self.open_whatsapp_chat(user_id, contact_cand)

        # 4. WhatsApp call / Cellular call
        if any(w in text for w in ('whatsapp', "what's app", 'whats app')):
            m_wa = re.search(r'\b(?:make\s+a\s+)?whatsapp\s+(video\s+)?call\s+(?:to\s+)?(.+?)(?:\s+on\s+(?:(?:my|the)\s+)?(?:phone|mobile))?$', text) or re.search(r'\b(?:video\s+call|call)\s+(.+?)\s+(?:on|via|through|using)\s+whatsapp\b', text)
            if m_wa:
                is_vid = 'video' in text
                grp_idx = 2 if m_wa.group(2) else 1
                start, end = m_wa.span(grp_idx)
                contact = _clean_contact_query(user_input[start:end].strip())
                if contact:
                    res = self.make_whatsapp_call(user_id, contact, video=is_vid)
                    if isinstance(res, dict): res.setdefault('action', 'remote_device')
                    return res

        if any(k in text for k in ('hang up', 'end call', 'disconnect call', 'decline call', 'reject call', 'drop call', 'cut the call', 'end the call')):
            res = self.end_call(user_id)
            if isinstance(res, dict): res.setdefault('action', 'remote_device')
            return res

        if any(k in text for k in ('answer call', 'answer the call', 'pick up call', 'pick up the call', 'accept call', 'answer phone', 'pick up phone')):
            res = self.answer_call(user_id)
            if isinstance(res, dict): res.setdefault('action', 'remote_device')
            return res

        # 5. Live Screen Mirroring (scrcpy)
        if any(k in text for k in ('show me the phone live screen', 'show phone live screen', 'live screen mirror', 'screen mirror', 'mirror my phone', 'mirror phone', 'mirror my screen', 'start mirroring', 'start live mirroring', 'live mirroring', 'cast my phone', 'cast phone screen', 'launch scrcpy', 'start scrcpy', 'show phone screen mirror', 'mirror phone screen', 'show my phone screen', 'show phone screen', 'view phone screen', 'display phone screen')):
            return self.launch_scrcpy_mirror(user_id)

        if any(k in text for k in ('stop mirroring', 'close mirroring', 'stop screen mirror', 'stop scrcpy', 'close scrcpy', 'stop phone mirror', 'end mirroring')):
            return self.stop_scrcpy()

        # 6. Navigation: Home Screen
        if re.search(r'\b(?:go\s+(?:to\s+)?(?:the\s+)?home(?:\s+screen)?|return\s+(?:back\s+)?(?:to\s+)?(?:the\s+)?home(?:\s+screen)?|press\s+home(?:\s+screen)?|home\s+screen|take\s+me\s+to\s+(?:the\s+)?home(?:\s+screen)?|take\s+me\s+back\s+to\s+(?:the\s+)?(?:mobile\s+)?home(?:\s+page|\s+screen)?)\b', text) or any(k in text for k in ('go home on phone', 'go home on my phone', 'go home on mobile', 'phone home', 'home on my phone', 'go to the home screen on my phone', 'go to home screen on my phone', 'take me back to the mobile home page', 'mobile home page', 'phone home screen', 'go to the home screen', 'go to home screen', 'press home')):
            return self.home(user_id)

        # 7. Navigation: Back button / previous screen
        if re.search(r'\b(?:go\s+back|press\s+back|navigate\s+back|back\s+button|previous\s+screen|go\s+to\s+(?:the\s+)?previous\s+screen)\b', text) or any(k in text for k in ('go back', 'back button', 'press back', 'navigate back', 'back on phone', 'back on mobile', 'go back on mobile', 'previous screen', 'go to previous screen')):
            return self.back(user_id)

        # 8. Navigation: Recent apps / App switcher
        if re.search(r'\b(?:recent\s+apps|app\s+switcher|open\s+recents|show\s+recents|switch\s+apps)\b', text) or any(k in text for k in ('recents', 'recent apps', 'app switcher', 'switch apps', 'open recents', 'recent apps on phone')):
            return self.recents(user_id)

        # 9. Notifications
        if re.search(r'\b(?:check|read|show|list|get|what\s+are)\s+(?:what\s+)?(?:the\s+|my\s+)?notifications(?:\s+(?:i\s+)?(?:have|got|received))?\b', text) or any(k in text for k in ('check what notifications i received', 'what notifications i received', 'notifications i received', 'notifications on my phone', 'my notifications', 'check notifications')):
            return self.get_notifications(user_id)

        if any(k in text for k in ('expand notification', 'open notification', 'pull down notification', 'notification shade', 'notifications shade')):
            return self.expand_notifications(user_id)

        if any(k in text for k in ('collapse notification', 'close notification', 'hide notification', 'dismiss notification')):
            return self.collapse_notifications(user_id)

        # 10. Quick settings
        if any(k in text for k in ('quick settings', 'open quick settings', 'expand quick settings', 'show quick settings')):
            return self.expand_settings(user_id)

        # 11. Battery status
        if any(k in text for k in ('battery', 'battery level', 'phone battery', 'charge level')):
            target = ''
            m = re.search(r"(?:on|for)\s+(?:my\s+)?([a-z0-9\s]+?)(?:'s)?\s*(?:battery)?$", text)
            if m and m.group(1).strip() not in ('phone', 'my phone', 'mobile', 'my mobile'):
                target = m.group(1).strip()
            return self.get_battery(user_id, target)

        # 12. Flashlight / Torch
        if 'flashlight' in text or 'torch' in text:
            enable = not any(w in text for w in ('off', 'disable', 'stop'))
            return self.toggle_flashlight(user_id, enable=enable)

        # 13. Bluetooth
        if 'bluetooth' in text:
            if any(k in text for k in ('turn on', 'enable', 'activate', 'switch on', 'turn bluetooth on')):
                return self.set_bluetooth(user_id, True)
            if any(k in text for k in ('turn off', 'disable', 'deactivate', 'switch off', 'turn bluetooth off')):
                return self.set_bluetooth(user_id, False)
            return self.get_bluetooth_status(user_id)

        # 14. Wi-Fi
        if any(w in text for w in ('wifi', 'wi-fi')):
            if any(k in text for k in ('turn on', 'enable', 'activate', 'switch on')):
                return self.set_wifi(user_id, True)
            if any(k in text for k in ('turn off', 'disable', 'deactivate', 'switch off')):
                return self.set_wifi(user_id, False)
            return self.get_wifi_status(user_id)

        # 15. Volume
        m_set_vol = re.search(r'\b(?:set|change)\s+(?:phone\s+)?volume\s+(?:to\s+)?(\d+)\s*%?\b', text)
        if m_set_vol:
            return self.set_volume(user_id, int(m_set_vol.group(1)))
        if any(k in text for k in ('volume down', 'lower volume', 'decrease volume', 'turn down the volume', 'phone volume down')):
            return self.volume_down(user_id)
        if any(k in text for k in ('volume up', 'raise volume', 'increase volume', 'turn up the volume', 'phone volume up')):
            return self.volume_up(user_id)
        if any(k in text for k in ('mute phone', 'mute my phone', 'silence phone', 'silence my phone')):
            return self.volume_mute(user_id)
        if any(k in text for k in ('check volume', 'what is the volume', 'get volume', 'phone volume status')):
            return self.get_volume(user_id)

        # 16. Wake / Lock / Unlock
        if any(k in text for k in ('wake phone', 'wake up phone', 'wake my phone', 'wake up my phone', 'turn on phone screen')):
            return self.wake(user_id)
        if any(k in text for k in ('unlock phone', 'unlock my phone', 'unlock mobile', 'unlock the phone')):
            return self.unlock_screen(user_id)
        if any(k in text for k in ('lock phone', 'lock my phone', 'lock mobile', 'lock the phone')):
            return self.lock(user_id)
        if any(k in text for k in ('is my phone locked', 'is phone locked', 'phone lock status')):
            return self.get_lock_state(user_id)

        # 17. Camera / Photo
        if any(k in text for k in ('take a photo', 'take a picture', 'take photo', 'take picture', 'capture photo')):
            return self.take_photo(user_id)
        if any(k in text for k in ('open camera', 'launch camera', 'start camera')):
            return self.open_camera(user_id)

        # 18. Explicit Screenshot ONLY (Never fallback or default)
        if re.search(r'\b(?:take\s+(?:a\s+)?screenshot|capture\s+(?:the\s+)?screen|phone\s+screenshot|screenshot\s+(?:on|of)\s+(?:my\s+)?phone)\b', text) or any(k in text for k in ('screenshot on phone', 'screenshot on mobile', 'phone screenshot', 'take a screenshot on my phone', 'capture phone screen', 'take phone screenshot')):
            return self.take_screenshot(user_id)

        # 19. Tap coordinates / Element tap / Gestures
        m_tap = re.search(r'tap\s+(?:on\s+)?(?:(?:my|the)\s+)?(?:phone|screen|mobile)?\s*(?:at\s+)?(\d+)[,\s]+(\d+)', text) or re.search(r'tap\s+(?:at\s+)?(\d+)[,\s]+(\d+)\s+on\s+(?:(?:my|the)\s+)?(?:phone|mobile|screen)', text)
        if m_tap:
            return self.tap(user_id, int(m_tap.group(1)), int(m_tap.group(2)))

        m_lp = re.search(r'long\s+press\s+(?:on\s+)?(?:(?:my|the)\s+)?(?:phone|screen|mobile)?\s*(?:at\s+)?(\d+)[,\s]+(\d+)', text)
        if m_lp:
            return self.long_press(user_id, int(m_lp.group(1)), int(m_lp.group(2)))

        m_sw = re.search(r'swipe\s+(?:on\s+)?(?:(?:my|the)\s+)?(?:phone|mobile)?\s*(?:from\s+)?(\d+)[,\s]+(\d+)\s+to\s+(\d+)[,\s]+(\d+)', text)
        if m_sw:
            return self.swipe(user_id, int(m_sw.group(1)), int(m_sw.group(2)), int(m_sw.group(3)), int(m_sw.group(4)))

        if any(k in text for k in ('scroll down', 'swipe down')):
            return self.scroll_screen(user_id, direction='down')
        if any(k in text for k in ('scroll up', 'swipe up')):
            return self.scroll_screen(user_id, direction='up')

        # 20. App Launch
        m_app = re.search(r'(?:open|launch|start|switch\s+to|bring\s+up|see)\s+(.+?)(?:\s+(?:on|in|inside)\s+(?:(?:my|the|connected)\s+)?(?:phone|mobile(?:\s+phone)?|device|android|redmi[a-z0-9_\-\s]*))?$', text) or re.search(r'(?:open|launch|start|see)\s+(?:(?:my|the)\s+)?(?:phone|mobile)\s+(.+)', text)
        if m_app and any(w in text for w in ('phone', 'mobile', 'device', 'android', 'redmi')):
            start, end = m_app.span(1)
            app_name = _clean_app_query(user_input[start:end].strip())
            res = self.launch_app(user_id, app_name)
            if isinstance(res, dict): res.setdefault('action', 'remote_device')
            return res

        # 21. Close App
        m_close_app = re.search(r'\b(?:close|quit|stop|exit|kill|terminate)\s+(.+?)(?:\s+(?:on|in)\s+(?:(?:my|the)\s+)?(?:phone|mobile|device|android|redmi[a-z0-9_\-\s]*))?$', text)
        if m_close_app and any(w in text for w in ('phone', 'mobile', 'device', 'android', 'redmi')):
            start, end = m_close_app.span(1)
            app_name = _clean_app_query(user_input[start:end].strip())
            res = self.close_app(user_id, app_name)
            if isinstance(res, dict): res.setdefault('action', 'remote_device')
            return res

        # 22. Status / Connect / Disconnect / Capabilities
        if any(k in text for k in ('which phone is connected', 'what phone is connected', 'is my mobile phone connected', 'is my phone connected', 'phone status', 'device status', 'check phone connection')):
            return self.get_connection_status(user_id)

        if any(k in text for k in ('list devices', 'list my devices', 'what devices are connected', 'show my devices')):
            return self.list_devices(user_id)

        if any(k in text for k in ('connect to my mobile', 'connect mobile', 'connect to my phone', 'connect phone', 'connect my phone')):
            return self.connect_mobile(user_id)

        if any(k in text for k in ('disconnect my phone', 'disconnect phone', 'disconnect mobile', 'disconnect device')):
            return self.disconnect_device(user_id)

        # DO NOT fallback to screenshot! Return unrecognized command clearly.
        return {'success': False, 'status': 'unrecognized', 'action': 'remote_device', 'message': f"Could not understand device command: '{user_input}'. Try 'mirror my phone', 'go home', 'open youtube', or 'check phone battery'."}

_controller_instance: Optional[DeviceController] = None
_ctrl_lock = threading.Lock()

def get_device_controller():
    global _controller_instance
    with _ctrl_lock:
        if _controller_instance is None:
            _controller_instance = DeviceController()
        return _controller_instance
