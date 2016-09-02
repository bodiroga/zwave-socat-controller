#!/usr/bin/python
import time
import re
import subprocess
import sys
import logging

logger = logging.getLogger(__name__)

class OpenHABBundlesHandler(object):

    def __init__(self, host="127.0.0.1", port=5555, telnet_delay=".5", command_timeout=10):
        self.host = host
        self.port = port
        self.telnet_delay = telnet_delay
        self.command_timeout = command_timeout
        self.zwave_bindings = None
        self.openhab_online = None
        self.last_update = 0
        self.update_zwave_bundles_info()

    def update_zwave_bundles_info(self, forced=False):
        if not forced and time.time() - self.last_update < 15: return

        ss_command = "{ echo 'ss'; sleep %s; } | telnet %s %s" % (self.telnet_delay, self.host, self.port)
        ss_response = subprocess.Popen(ss_command, stdout=subprocess.PIPE, shell=True).communicate()[0]

        if ss_response == "Trying 127.0.0.1...\n":
            self.openhab_online = False
        else:
            self.openhab_online = True

        zwaves_info_search = re.compile(ur'(\d{2,4})\s+(\w+)\s+org.openhab.binding.(zwave\d*)')
        zwaves_info = re.findall(zwaves_info_search, ss_response)

        if not zwaves_info: return
        result = {}
        for zwave_info in zwaves_info:
            result[zwave_info[2]] = { "id":zwave_info[0] , "status":zwave_info[1] }

        self.zwave_bindings = result
        self.last_update = time.time()

    def start_bundle_by_id(self, bundle_id):
        self.update_zwave_bundles_info()
        if not self.openhab_online: return 1
        name = self.get_binding_by_bundle(bundle_id)
        if (self.get_binding_realtime_state(name) == "ACTIVE"):
            self.stop_bundle_by_id(bundle_id)
        command = """{ echo 'start "%s"'; sleep %s; } | telnet %s %s""" % (bundle_id, self.telnet_delay, self.host, self.port)
        start_response = subprocess.Popen(command, stdout=subprocess.PIPE, shell=True).communicate()[0]
        start_time = time.time()
        while(self.get_binding_realtime_state(name) != "ACTIVE"):
            if time.time() - start_time > self.command_timeout: return 0
            time.sleep(.5)
        logger.debug("[{0}] Binding started in {1} seconds".format(name,time.time() - start_time))
        return 1

    def stop_bundle_by_id(self, bundle_id):
        self.update_zwave_bundles_info()
        if not self.openhab_online: return 1
        name = self.get_binding_by_bundle(bundle_id)
        command = """{ echo 'stop "%s"'; sleep %s; } | telnet %s %s""" % (bundle_id, self.telnet_delay, self.host, self.port)
        stop_response = subprocess.Popen(command, stdout=subprocess.PIPE, shell=True).communicate()[0]
        start_time = time.time()
        while(self.get_binding_realtime_state(name) != "RESOLVED"):
            if time.time() - start_time > self.command_timeout: return 0
            time.sleep(.5)
        logger.debug("[{0}] Binding stopped in {1} seconds".format(name,time.time() - start_time))
        return 1

    def stop_binding(self, name):
        self.update_zwave_bundles_info()
        if not self.openhab_online: return 1
        if name in self.zwave_bindings: id = self.zwave_bindings[name]["id"]
        else: return 1
        return self.stop_bundle_by_id(id)

    def start_binding(self, name):
        self.update_zwave_bundles_info()
        if not self.openhab_online: return 1
        if name in self.zwave_bindings: id = self.zwave_bindings[name]["id"]
        else: return 1
        return self.start_bundle_by_id(id)

    def get_binding_by_bundle(self, id):
        self.update_zwave_bundles_info()
        if not self.openhab_online: return None
        for name, config in self.zwave_bindings.iteritems():
            if config["id"] == id: return name
        return None

    def get_binding_realtime_state(self, name):
        self.update_zwave_bundles_info(forced=True)
        if not self.openhab_online: return None
        return self.zwave_bindings[name]["status"]
