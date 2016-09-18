#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import os
import sys
import time
import logging
import subprocess
import threading
import urllib2
import re
import json
import zipfile
import signal
import paho.mqtt.client as mqtt_client
from lib.openhabHandler import OpenHABHandler
logging.basicConfig(filename="/var/log/zwave-socat-controller.log", format='%(asctime)s %(levelname)-8s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


class MqttBrokerParameters(object):

    def __init__(self, host="localhost", port=1883, user="", passw=""):
        self.host = host
        self.port = port
        self.user = user
        self.passw = passw


class ZWaveBindingsHandler(object):

    def __init__(self, default_file="/etc/default/openhab", configuration_folder="/etc/openhab/configurations", addons_folder="/usr/share/openhab/addons", habmin_folder="/usr/share/openhab/webapps/habmin"):
        self.ghh = GitHubInfoHandler()
        self.configuration_folder = configuration_folder
        self.addons_folder = addons_folder
        self.habmin_folder = habmin_folder
        self.webapps_folder = "/".join(self.habmin_folder.split("/")[0:-1])
        self.default_file = default_file
        logger.debug("[ZWaveHandler] Service started")

    def __install_addon_from_url(self, url):
        addon_name = url.split("/")[-1].split("?")[0]
        page = urllib2.urlopen(url)
        file = page.read()
        with open(self.addons_folder + "/" + addon_name, 'wb') as f:
            f.write(file)
        logger.info("[ZWaveHandler] '{}' binding installed".format(addon_name.split(".")[3].split("_")[0]))

    def __install_habmin_html_files(self):
        url = "https://github.com/cdjackson/HABmin/archive/master.zip"
        file_name = url.split("/")[-1]
        file = urllib2.urlopen(url).read()
        zip_file_path = self.webapps_folder + "/" + file_name
        with open(zip_file_path, 'wb') as f:
            f.write(file)
        zip_ref = zipfile.ZipFile(zip_file_path, 'r')
        zip_ref.extractall(self.webapps_folder)
        zip_ref.close()
        os.rename(self.webapps_folder + "/HABmin-master", self.webapps_folder + "/habmin")
        os.remove(zip_file_path)

    def __install_habmin_extension_html_files(self):
        url = self.ghh.get_habmin_extension_url_by_name()
        file_name = url.split("/")[-1]
        file = urllib2.urlopen(url).read()
        zip_file_path = self.webapps_folder + "/" + file_name
        with open(zip_file_path, 'wb') as f:
            f.write(file)
        zip_ref = zipfile.ZipFile(zip_file_path, 'r')
        zip_ref.extractall(self.webapps_folder)
        zip_ref.close()
        os.remove(zip_file_path)

    def restart_openhab(self):
        restart_command = "/etc/init.d/openhab restart"
        result = subprocess.Popen(restart_command, stdout=subprocess.PIPE, shell=True)

    def update(self, zwave_bindings):
        reboot = self.update_jars(zwave_bindings)
        reboot = self.update_configuration_file(zwave_bindings) or reboot
        reboot = self.update_default_file(zwave_bindings) or reboot
        logger.debug("[ZWaveHandler] Update finished")
        if reboot:
            logger.info("[ZwaveHandler] Configuration changed, restarting openHAB")
            self.restart_openhab()

    def update_jars(self, zwave_bindings):
        def get_zwave_bindings_numbers(list):
            return [1 if number == "" else int(number) for number in [binding.strip("zwave") for binding in list]]

        def set_zwave_bindings_from_numbers(numbers):
            return ["zwave" if number == 1 else "zwave"+str(number) for number in numbers]

        def set_zwave_binding_from_number(number):
            if not number: return None
            return "zwave"+str(number) if number>1 else "zwave"

        max_zwave_bindings_number = max_installed_zwave_bindings_number = installed_habmin_version_number = 0
        installed_habmin = installed_habmin_version = habmin_binding_to_install = habmin_binding_to_uninstall = None
        zwave_bindings_to_install = []
        zwave_bindings_to_uninstall = []
        installed_jars_text = ",".join(os.listdir(self.addons_folder))

        zwave_bindings_numbers = get_zwave_bindings_numbers(zwave_bindings)
        if zwave_bindings_numbers:
            max_zwave_bindings_number = max(zwave_bindings_numbers)

        zwave_pattern = re.compile(ur'(org\.openhab\.binding.(zwave\d*)[^\,]*\.jar)')
        installed_zwave_bindings = {result[1]:result[0] for result in re.findall(zwave_pattern, installed_jars_text)}
        installed_zwave_bindings_numbers = get_zwave_bindings_numbers(installed_zwave_bindings.keys())
        if installed_zwave_bindings_numbers:
            max_installed_zwave_bindings_number = max(installed_zwave_bindings_numbers)

        future_zwave_bindings_numbers = range(1,max_zwave_bindings_number+1)
        future_zwave_bindings = set_zwave_bindings_from_numbers(future_zwave_bindings_numbers)

        if max_zwave_bindings_number >= max_installed_zwave_bindings_number:
            zwave_bindings_to_install_numbers = list(set(future_zwave_bindings_numbers) - set(installed_zwave_bindings_numbers))
            zwave_bindings_to_install = set_zwave_bindings_from_numbers(zwave_bindings_to_install_numbers)
        else:
            zwave_bindings_to_uninstall_numbers = list(set(installed_zwave_bindings_numbers)-set(future_zwave_bindings_numbers))
            zwave_bindings_to_uninstall = set_zwave_bindings_from_numbers(zwave_bindings_to_uninstall_numbers)

        habmin_pattern = re.compile(ur'(org\.openhab\.io\.habmin[^\,]*\.jar)')

        installed_habmin_search = re.search(habmin_pattern, installed_jars_text)

        if installed_habmin_search:
            installed_habmin = installed_habmin_search.group(0)
            habmin_version_pattern = re.compile(ur'(zwave[\d+]*)')
            result = re.search(habmin_version_pattern, installed_habmin)
            installed_habmin_version = "zwave"
            if result:
                installed_habmin_version = result.group(0)
                installed_habmin_version_number = get_zwave_bindings_numbers([installed_habmin_version])[0]

        if max_zwave_bindings_number != installed_habmin_version_number:
            habmin_binding_to_install = set_zwave_binding_from_number(max_zwave_bindings_number)
            habmin_binding_to_uninstall = installed_habmin_version

        # ZWave bindings installation
        zwave_bindings_to_install_threads = []
        for binding in zwave_bindings_to_install:
            try:
                url = self.ghh.get_zwave_url_by_name(binding)
                zwave_bindings_to_install_threads.append(threading.Thread(target=self.__install_addon_from_url, args=(url,)))
            except KeyError:
                logger.error("[ZWaveHandler] '{}' binding cannot be installed".format(binding))
        for thread in zwave_bindings_to_install_threads: thread.start()
        for thread in zwave_bindings_to_install_threads: thread.join()
        # ZWave bindings uninstallation
        for binding in zwave_bindings_to_uninstall:
            os.remove(self.addons_folder + "/" + installed_zwave_bindings[binding])
            logger.info("[ZWaveHandler] '{}' binding uninstalled".format(binding))
        # HABmin binding installation
        if habmin_binding_to_install:
            try:
                self.__install_addon_from_url(self.ghh.get_habmin_url_by_name(habmin_binding_to_install))
            except KeyError:
                habmin_binding_to_uninstall = None
                logger.error("[ZWaveHandler] '{}' habmin cannot be installed".format(habmin_binding_to_install))
        # HABmin binding uninstallation
        if habmin_binding_to_uninstall:
            os.remove(self.addons_folder + "/" + installed_habmin)
            logger.debug("[ZWaveHandler] '{}' habmin uninstalled".format(habmin_binding_to_uninstall))
        # HABmin web files installation
        if not os.path.isdir(self.habmin_folder):
            self.__install_habmin_html_files()
            logger.debug("[ZWaveHandler] HABmin html files installed")
        # HABmin extended web files installation
        if not os.path.isfile(self.habmin_folder + "/extension_installed"):
            self.__install_habmin_extension_html_files()
            logger.debug("[ZWaveHandler] HABmin extension html files installed")
        if zwave_bindings_to_install or zwave_bindings_to_uninstall or habmin_binding_to_uninstall or habmin_binding_to_install:
            return True
        return False

    def update_configuration_file(self, zwave_bindings):
        openhab_configuration_path = self.configuration_folder + "/openhab.cfg"
        openhab_configuration_default_path = self.configuration_folder + "/openhab_default.cfg"
        reboot = False

        path = openhab_configuration_path
        if not os.path.exists(openhab_configuration_path): path = openhab_configuration_default_path
        with open(path, 'r') as f:
            content = f.read()

        zwave_section_pattern = re.compile(ur'\#+\s+Z-Wave\s+Binding\s+\#+(.*)\n#+\s+Nikobus', re.DOTALL)
        result = re.search(zwave_section_pattern, content)

        content_searchable = content
        if result: content_searchable = result.group(1)

        n_content_searchable = content_searchable
        for binding in zwave_bindings:
            binding_port = "/dev/{}".format(binding)
            pattern = re.compile(ur'[^\#]{}:port=(.*)\n'.format(binding))
            result = re.search(pattern, n_content_searchable)
            if result:
                if binding_port != result.group(1):
                    n_content_searchable = n_content_searchable.replace(result.group(0), "\n{0}:port={1}\n".format(binding, binding_port))
                    reboot = True
            else:
                n_content_searchable += "{0}:port=/dev/{0}\n".format(binding)
                reboot = True

        if content_searchable == n_content_searchable:
            logger.debug("[ZWaveHandler] Configuration file not updated")
            return reboot

        content = content.replace(content_searchable, n_content_searchable)

        with open(openhab_configuration_path, 'w') as f:
            f.write(content)
        logger.info("[ZWaveHandler] Configuration file updated")
        return reboot

    def update_default_file(self, zwave_bindings):
        zwave_ports = ["/dev/{}".format(binding) for binding in zwave_bindings]
        configured_serial_ports = []
        java_args_keyword = "JAVA_ARGS="
        serial_keyword = "-Dgnu.io.rxtx.SerialPorts="

        with open(self.default_file, 'r') as f:
            content = f.read()

        for line in content.splitlines():
            if java_args_keyword in line:
                old_line = line
                java_args = line.strip(java_args_keyword).replace('"','').split(" ")

                configured_other_java_args = [arg for arg in java_args if serial_keyword not in arg]
                __configured_serial_ports = [arg.strip(serial_keyword) for arg in java_args if serial_keyword in arg]
                if __configured_serial_ports:
                    configured_serial_ports = __configured_serial_ports[0].split(":")

                configured_zwave_ports = [port for port in configured_serial_ports if "zwave" in port]
                configured_other_ports = [port for port in configured_serial_ports if "zwave" not in port]

                reboot = zwave_ports > configured_zwave_ports

                new_serial_ports = ":".join(zwave_ports + configured_other_ports)
                new_serial_ports_text = serial_keyword + new_serial_ports
                new_java_args = " ".join([new_serial_ports_text] + configured_other_java_args)
                new_line = java_args_keyword + '"' + new_java_args + '"'
                break

        if old_line == new_line:
            logger.debug("[ZWaveHandler] Default file not updated")
            return reboot

        content = content.replace(old_line, new_line)

        with open(self.default_file, 'w') as f:
            f.write(content)

        logger.info("[ZWaveHandler] Default file updated")
        return reboot


class GitHubInfoHandler(object):

    USER = "bodiroga"
    PROJECT = "openhab-distributed-zwaves"
    ZWAVE_FOLDER = "zwave"
    HABMIN_FOLDER = "habmin"
    UPDATE_PERIOD = 12 # hours

    def __init__(self):
        logger.debug("[GitHubInfoHandler] Service started")
        self.update_thread = None
        self.zwaves_bindings_info = {}
        self.habmin_bindings_info = {}
        self.last_update = None
        self.update_bindings_info_periodically()

    def get_zwaves_bindings_info(self):
        return self.zwaves_bindings_info

    def get_habmin_bindings_info(self):
        return self.habmin_binding_info

    def get_zwave_info_by_name(self, name):
        try:
            return self.zwaves_bindings_info[name]
        except KeyError:
            logger.error("[GitHubInfoHandler] '{}' binding info not available".format(name))
            raise

    def get_habmin_info_by_name(self, name):
        try:
            return self.habmin_bindings_info[name]
        except KeyError:
            logger.error("[GitHubInfoHandler] '{}' habmin info not available".format(name))
            raise

    def get_zwave_url_by_name(self, name):
        try:
            return self.zwaves_bindings_info[name]["url"]
        except KeyError:
            logger.error("[GitHubInfoHandler] '{}' binding not available".format(name))
            raise

    def get_habmin_url_by_name(self, name):
        try:
            return self.habmin_bindings_info[name]["url"]
        except KeyError:
            logger.error("[GitHubInfoHandler] '{}' habmin not available".format(name))
            raise

    def get_habmin_extension_url_by_name(self):
        return "https://github.com/{}/{}/blob/master/{}/habmin.zip?raw=true".format(self.USER, self.PROJECT, self.HABMIN_FOLDER)

    def update_bindings_info(self):
        self.update_zwaves_bindings_info()
        self.update_habmin_bindings_info()
        self.last_update = time.time()
        logger.debug("[GitHubInfoHandler] Bindings repository info updated")

    def update_bindings_info_periodically(self, period=UPDATE_PERIOD):
        self.update_bindings_info()
        self.update_thread = threading.Timer(period*60*60, self.update_bindings_info_periodically)
        self.update_thread.daemon = True
        self.update_thread.start()

    def update_zwaves_bindings_info(self):
        url = "https://github.com/{}/{}/tree/master/{}".format(self.USER, self.PROJECT, self.ZWAVE_FOLDER)
        zwave_binding_pattern = re.compile(ur'\"(\/{0}\/{1}\/blob\/master\/{2}\/org\.openhab\.binding\.([^\s]*)\_([\d\.]*)\(([\d\.\-]*)\)\.jar)\"'.format(self.USER, self.PROJECT, self.ZWAVE_FOLDER))

        try:
            page = urllib2.urlopen(url).read()
        except urllib2.URLError:
            return

        bindings = re.findall(zwave_binding_pattern, page)

        for binding in bindings:
            name = binding[1]
            version = binding[2]
            date = binding[3]
            url = "https://github.com{}?raw=true".format(binding[0])
            self.zwaves_bindings_info[name] = { "version":version, "date":date, "url":url }

    def update_habmin_bindings_info(self):
        url = "https://github.com/{}/{}/tree/master/{}".format(self.USER, self.PROJECT, self.HABMIN_FOLDER)
        habmin_binding_pattern = re.compile(ur'\"(\/{0}\/{1}\/blob\/master\/{2}\/org\.openhab\.io\.habmin\_([^\s]*)\_([\d\.]*)\(([\d\.\-]*)\)\.jar)\"'.format(self.USER, self.PROJECT, self.HABMIN_FOLDER))

        try:
            page = urllib2.urlopen(url).read()
        except urllib2.URLError:
            return

        bindings = re.findall(habmin_binding_pattern, page)

        for binding in bindings:
            url = "https://github.com{}?raw=true".format(binding[0])
            name = binding[1]
            version = binding[2]
            date = binding[3]
            self.habmin_bindings_info[name] = { "version":version, "date":date, "url":url }


class NodeController(object):

    MAX_TIMEOUT = 24 # hours

    def __init__(self, mqtt_params=MqttBrokerParameters(), prefix="/devices", openhab_control_enabled=True):
        self.mqtt_params = mqtt_params
        self.prefix = prefix
        self.openhab_control_enabled = openhab_control_enabled
        self.detected_nodes = {}
        self.active_nodes = {}
        if self.openhab_control_enabled: self.zbh = ZWaveBindingsHandler()
        self.timer = None
        self.client = mqtt_client.Client("zwave-node-controller")
        self.client.username_pw_set(self.mqtt_params.user, self.mqtt_params.passw)
        self.client.connect(self.mqtt_params.host, self.mqtt_params.port, 60)
        self.client.subscribe([("{}/+/$fwname".format(self.prefix), 1), ("{}/+/time/last_report".format(self.prefix), 1)])
        self.client.on_message = self.message_handler
        self.client.loop_start()
        logger.debug("[Controller] Service started")

    def message_handler(self, client, obj, msg):
        if "$fwname" in msg.topic and "zwave-socat-node" in msg.payload:
            node_name = msg.topic.replace(self.prefix+"/","").replace("/$fwname","")
            if node_name not in self.detected_nodes: self.detected_nodes[node_name]= { "binding":node_name }
        if "time/last_report" in msg.topic:
            node_name = msg.topic.replace(self.prefix+"/","").replace("/time/last_report","")
            if node_name in self.detected_nodes: self.detected_nodes[node_name]["last_update"] = int(msg.payload)
        if self.timer is not None:
            self.timer.cancel()
        self.timer = threading.Timer(0.5, self.process_detected_nodes)
        self.timer.start()

    def process_detected_nodes(self):
        correct_nodes = []
        for node_name, node_info in self.detected_nodes.iteritems():
            if "last_update" in node_info and int(time.time()) - node_info["last_update"] <= self.MAX_TIMEOUT*60*60:
                correct_nodes.append(node_name)
        active_nodes_list = self.active_nodes.keys()
        new_nodes = list(set(correct_nodes) - set(active_nodes_list))
        delete_nodes = list(set(active_nodes_list) - set(correct_nodes))
        for node in new_nodes:
            logger.info("[Controller] Node detected: {}".format(node))
        for node in delete_nodes:
            logger.info("[Controller] Node deleted: {}".format(node))
        if self.openhab_control_enabled and (new_nodes or delete_nodes):
            self.zbh.update(correct_nodes)
        for node in new_nodes:
            self.active_nodes[node] = Node(node, self.mqtt_params, self.prefix, self.openhab_control_enabled)
        for node in delete_nodes:
            self.active_nodes[node].delete()
            del self.active_nodes[node]
        self.timer = None


class Node(object):

    KILL_TIME = 3
    restart_timer = None
    openhab_control_enabled = None
    oh = None

    def __init__(self, name, mqtt_params=MqttBrokerParameters(), prefix="devices", openhab_control_enabled=True):
        self.mqtt_params = mqtt_params
        self.name = name
        self.online = None
        self.local_port = "/dev/" + name
        self.local_socat_status = None
        self.remote_ip = self.remote_port = self.remote_socat_status = None
        if not Node.openhab_control_enabled: Node.openhab_control_enabled = openhab_control_enabled
        if not Node.oh and Node.openhab_control_enabled: Node.oh = OpenHABHandler()
        self.kill_timer = None
        self.kill_local_port(control_binding=False)
        time.sleep(0.05)

        self.client = mqtt_client.Client("%s-node-handler" % (self.name))
        self.client.username_pw_set(self.mqtt_params.user, self.mqtt_params.passw)
        self.client.connect(self.mqtt_params.host, self.mqtt_params.port, 60)
        self.client.subscribe("{0}/{1}/#".format(prefix,self.name), 0)
        self.client.on_message = self.mqtt_message_handler
        self.client.loop_start()

    def mqtt_message_handler(self, client, obj, msg):
        if "$online" in msg.topic:
            if msg.payload == "false": self.remote_socat_status = "false"
            self.online = msg.payload
            logger.debug("[%s] Node online: %s" % (self.name, msg.payload))
        if "$localip" in msg.topic: self.remote_ip = msg.payload
        if "socat/port" in msg.topic: self.remote_port = msg.payload
        if "socat/status" in msg.topic:
            self.remote_socat_status = msg.payload
            logger.debug("[%s] Remote socat status: %s" % (self.name, msg.payload))
        self.handle_socat_connection()

    def handle_socat_connection(self):
        if not self.online or not self.remote_socat_status: return
        node_healthy = str(self.online == "true" and self.remote_socat_status == "true").lower()
        # Special case where the timer is active
        if self.kill_timer:
            if node_healthy == "true":
                logger.warning("[%s] Fake node death, not killing the local port..." % (self.name))
                self.kill_timer.cancel()
                self.kill_timer = None
            return
        # There is a mismatch between the local socat status and the remote socat status
        if self.local_socat_status != node_healthy: # There is a mismatch between the local socat status and the remote socat status
            # The remote socat is online, so we start the local socat
            if node_healthy == "true":
                if self.local_port and self.remote_ip and self.remote_port:
                    logger.info("[%s] Node healthy..." % (self.name))
                    self.start_local_port()
            # The remote socat is offline, so we kill the local socat
            else:
                self.kill_timer = threading.Timer(self.KILL_TIME, self.mark_as_not_healthy)
                self.kill_timer.start()

    def mark_as_not_healthy(self):
        logger.warning("[%s] Node not healthy..." % (self.name))
        self.kill_local_port()

    def kill_local_port(self, control_binding=True):
        kill_command = "kill -9 $(ps ax | grep \"/usr/bin/socat\" | grep \"%s,\" | grep -v grep | awk \'{print $1}\')" % (self.name)
        if Node.openhab_control_enabled and control_binding:
            if not Node.oh.stop_binding(self.name):
                logger.error("[%s] Binding has failed stopping... Restarting openHAB" % (self.name))
                self.restart_openhab()
            else:
                logger.debug("[%s] Binding correctly stopped..." % (self.name))
        error = subprocess.Popen(kill_command, stderr=subprocess.PIPE, shell=True).communicate()[1]
        error = False
        self.local_socat_status = "false"
        self.kill_timer = None
        if not error: logger.debug("[%s] Local port killed..." % (self.name))

    def start_local_port(self, control_binding=True):
        socat_command = "/usr/bin/socat pty,link=%s,echo=0,raw,waitslave,group=dialout,mode=660 tcp:%s:%s" % (self.local_port, self.remote_ip, self.remote_port)
        sh_command = "while true; do %s; done" % (socat_command)
        result = subprocess.Popen(sh_command, shell=True)
        self.local_socat_status = "true"
        logger.debug("[%s] Local port started..." % (self.name))
        if Node.openhab_control_enabled and control_binding:
            if not Node.oh.start_binding(self.name):
                logger.error("[%s] Binding has failed starting... Restarting openHAB" % (self.name))
                self.restart_openhab()
            else:
                logger.debug("[%s] Binding correctly started..." % (self.name))

    def restart_openhab(self):
        if Node.restart_timer:
            Node.restart_timer.cancel()
        Node.restart_timer = threading.Timer(1, self.__restart_openhab)
        Node.restart_timer.start()

    def __restart_openhab(self):
        restart_command = "/etc/init.d/openhab restart"
        result = threading.Timer(1, subprocess.Popen(restart_command, stdout=subprocess.PIPE, shell=True))
        logger.debug("[Node] openHAB restarted")
        Node.restart_timer = None

    def delete(self):
        self.client.loop_stop()


def load_configuration(config_file=None):
    if not config_file:
        config_file = "{}/{}".format(os.path.dirname(os.path.realpath(__file__)),"configuration.json")

    try:
        with open(config_file) as f:
            config = json.load(f)
        return config
    except EnvironmentError as err:
        logger.error("[Configuration] No configuration file provided")
        sys.exit(1)
    except ValueError as err:
        logger.error("[Configuration] Syntax error in the configuration file")
        sys.exit(1)


if __name__ == '__main__':
    try:
        if not os.geteuid() == 0:
            sys.exit("You must run this script as root")
            logger.error("[Main] You must run this script as root")

        logger.info("[Main] Starting zwave-socat-controller program...")

        config = load_configuration()
        mqtt_params = MqttBrokerParameters(config["MQTT_HOST"], config["MQTT_PORT"], config["MQTT_USERNAME"], config["MQTT_PASSWORD"])

        if config["AUTODISCOVERY_ENABLED"]:
            logger.info("[Main] Autodiscovery mode enabled, searching for nodes...")
            nc = NodeController(mqtt_params, config["MQTT_HOMIE_PREFIX"], config["OPENHAB_CONTROL_ENABLED"])
        else:
            zwave_networks = config["ZWAVE_NETWORKS"].split(",") if config["ZWAVE_NETWORKS"] != "" else []
            logger.info("[Main] Manual mode enabled for: {}".format(zwave_networks))
            if config["OPENHAB_CONTROL_ENABLED"]:
                zbh = ZWaveBindingsHandler()
                zbh.update(zwave_networks)
            for network in zwave_networks:
                Node(network, mqtt_params, config["MQTT_HOMIE_PREFIX"], config["OPENHAB_CONTROL_ENABLED"])

        signal.pause()
    except KeyboardInterrupt:
        logger.info("[Main] Stopping the script manually...")
    except Exception as e:
        logger.error("[Error] {}".format(e))
