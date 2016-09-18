#!/usr/bin/python
import time
import re
import subprocess
import os
import logging

logger = logging.getLogger(__name__)


class OpenHABHandler(object):

    def __init__(self, host="127.0.0.1", port=5555, telnet_delay=".4", command_timeout=10):
        self.host = host
        self.port = port
        self.telnet_delay = telnet_delay
        self.command_timeout = command_timeout
        self.installed_addons = []
        self.zwave_bindings = {}
        self.openhab_online = None
        self.openhab_state = ""
        self.last_update = 0
        self.__update_openhab_information()
        self.__update_installed_addons()

    # Public methods

    def stop_binding(self, name):
        self.__update_openhab_information()
        if not self.openhab_online:
            return 1
        if name in self.zwave_bindings:
            bundle_id = self.zwave_bindings[name]["id"]
        else:
            return 1
        return self.__stop_bundle_by_id(bundle_id)

    def start_binding(self, name):
        self.__update_openhab_information()
        if not self.openhab_online:
            return 1
        if name in self.zwave_bindings:
            bundle_id = self.zwave_bindings[name]["id"]
        else:
            return 1
        return self.__start_bundle_by_id(bundle_id)

    def reboot_openhab(self, timeout=90):
        restart_time = time.time()
        self.openhab_state = "stopping"
        self.__update_installed_addons()
        subprocess.Popen("/etc/init.d/openhab restart", stdout=subprocess.PIPE, shell=True)
        while not self.openhab_online or not self.openhab_state == "started":
            self.__update_openhab_information(forced=True)
            time.sleep(0.2)
            if time.time() > restart_time + timeout:
                break
        if time.time() > restart_time + timeout:
            logger.error("[openHABHandler] Timeout restarting openHAB (> {} seconds)".format(timeout))

    # Private methods

    def __ss_result(self):
        ss_command = "{{ echo 'ss'; sleep {0}; }} | telnet {1} {2} 2>/dev/null".format(self.telnet_delay, self.host,
                                                                                       self.port)
        return subprocess.Popen(ss_command, stdout=subprocess.PIPE, shell=True).communicate()[0]

    def __update_installed_addons(self):
        addons_folder = "/usr/share/openhab/addons"

        self.installed_addons = [addon.replace(".jar", "").split("-")[0].split("_")[0] for addon in
                                 os.listdir(addons_folder) if ".jar" in addon]

    def __update_openhab_information(self, forced=False):
        if not forced and time.time() - self.last_update < 15:
            return

        ss_response = self.__ss_result()

        self.openhab_online = (ss_response != "Trying 127.0.0.1...\n")

        if not self.openhab_online:
            if self.openhab_state == "stopping":
                self.openhab_state = "starting"
            return

        if self.__has_openhab_completely_started(ss_response) and self.openhab_state == "starting":
            self.openhab_state = "started"

        zwaves_info_search = re.compile(ur'(\d{2,4})\s+(\w+)\s+org.openhab.binding.(zwave\d*)')
        zwaves_info = re.findall(zwaves_info_search, ss_response)

        if not zwaves_info:
            return

        self.zwave_bindings = {}
        for zwave_info in zwaves_info:
            self.zwave_bindings[zwave_info[2]] = {"id": zwave_info[0], "status": zwave_info[1]}

        self.last_update = time.time()

    def __has_openhab_completely_started(self, ss=None):
        bundles_to_check = ["org.openhab.model.item", "org.openhab.model.persistence", "org.openhab.model.rule",
                            "org.openhab.model.script", "org.openhab.model.sitemap"] + self.installed_addons

        if not ss:
            ss = self.__ss_result()
        for bundle in bundles_to_check:
            if "ACTIVE" != self.__get_bundle_status(bundle, ss):
                return False
        return True

    def __get_bundle_status(self, bundle_name, ss=None):
        if not ss:
            ss = self.__ss_result()

        bundle_search = re.compile(ur'\d{{2,4}}\s+(\w+)\s+{0}'.format(bundle_name))
        bundle_search_result = re.search(bundle_search, ss)

        if bundle_search_result:
            return bundle_search_result.group(1)
        return ""

    def __start_bundle_by_id(self, bundle_id):
        self.__update_openhab_information()
        if not self.openhab_online:
            return 1
        name = self.__get_binding_by_bundle(bundle_id)
        if self.__get_binding_realtime_state(name) == "ACTIVE":
            self.__stop_bundle_by_id(bundle_id)
        command = """{ echo 'start "%s"'; sleep %s; } | telnet %s %s 2>/dev/null""" % \
                  (bundle_id, self.telnet_delay, self.host, self.port)
        subprocess.Popen(command, stdout=subprocess.PIPE, shell=True).communicate()[0]
        start_time = time.time()
        while self.__get_binding_realtime_state(name) != "ACTIVE":
            if time.time() - start_time > self.command_timeout:
                return 0
            time.sleep(.5)
        logger.debug("[{0}] Binding started in {1} seconds".format(name, time.time() - start_time))
        return 1

    def __stop_bundle_by_id(self, bundle_id):
        self.__update_openhab_information()
        if not self.openhab_online:
            return 1
        name = self.__get_binding_by_bundle(bundle_id)
        command = """{ echo 'stop "%s"'; sleep %s; } | telnet %s %s 2>/dev/null""" % \
                  (bundle_id, self.telnet_delay, self.host, self.port)
        subprocess.Popen(command, stdout=subprocess.PIPE, shell=True).communicate()[0]
        start_time = time.time()
        while self.__get_binding_realtime_state(name) != "RESOLVED":
            if time.time() - start_time > self.command_timeout:
                return 0
            time.sleep(.5)
        logger.debug("[{0}] Binding stopped in {1} seconds".format(name, time.time() - start_time))
        return 1

    def __get_binding_by_bundle(self, bundle_id):
        self.__update_openhab_information()
        if not self.openhab_online:
            return None
        for name, config in self.zwave_bindings.iteritems():
            if config["id"] == bundle_id:
                return name
        return None

    def __get_binding_realtime_state(self, name):
        self.__update_openhab_information(forced=True)
        if not self.openhab_online:
            return None
        return self.zwave_bindings[name]["status"]
