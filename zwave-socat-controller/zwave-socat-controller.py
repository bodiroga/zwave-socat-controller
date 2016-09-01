#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import os
import sys
import time
import logging
import subprocess
import threading
import json
import paho.mqtt.client as mqtt_client
from lib.openhabBundlesHandler import OpenHABBundlesHandler
logging.basicConfig(filename="/var/log/zwave-socat-controller.log", format='%(asctime)s %(levelname)-8s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


class NodeController(object):

    MAX_TIMEOUT = 24 # hours

    def __init__(self, host="localhost", port=1883, user="", passw="", prefix="/devices"):
        self.mqtt_params = { "host":host, "port":port, "user":user, "passw":passw }
        self.prefix = prefix
        self.detected_nodes = {}
        self.active_nodes = {}
        self.client = mqtt_client.Client("zwave-node-controller")
        self.client.username_pw_set(self.mqtt_params["user"], self.mqtt_params["passw"])
        self.client.connect(self.mqtt_params["host"], self.mqtt_params["port"], 60)
        self.client.subscribe([("{}/+/$fwname".format(self.prefix), 1), ("{}/+/time/last_report".format(self.prefix), 1)])
        self.client.on_message = self.message_handler
        self.client.loop_start()

    def message_handler(self, client, obj, msg):
        if "$fwname" in msg.topic and "zwave-socat-node" in msg.payload:
            node_name = msg.topic.replace(self.prefix+"/","").replace("/$fwname","")
            if node_name not in self.detected_nodes: self.detected_nodes[node_name]= { "binding":node_name }
        if "time/last_report" in msg.topic:
            node_name = msg.topic.replace(self.prefix+"/","").replace("/time/last_report","")
            if node_name in self.detected_nodes: self.detected_nodes[node_name]["last_update"] = int(msg.payload)
        self.process_detected_nodes()

    def process_detected_nodes(self):
        correct_nodes = []
        for node_name, node_info  in self.detected_nodes.iteritems():
            if "last_update" in node_info and int(time.time()) - node_info["last_update"] <= 24*60*60:
                    correct_nodes.append(node_name)
        active_nodes_list = self.active_nodes.keys()
        new_nodes = list(set(correct_nodes) - set(active_nodes_list))
        delete_nodes = list(set(active_nodes_list) - set(correct_nodes))
        for node in new_nodes:
            logger.info("[Controller] Node detected: {}".format(node))
            self.active_nodes[node] = Node(node, self.mqtt_params["host"], self.mqtt_params["port"], self.mqtt_params["user"], self.mqtt_params["passw"], self.prefix)
        for node in delete_nodes:
            logger.info("[Controller] Node deleted: {}".format(node))
            self.active_nodes[node].delete()
            del self.active_nodes[node]


class Node(object):

    KILL_TIME = 3
    obh = OpenHABBundlesHandler()

    def __init__(self, name, host="localhost", port=1883, user="", passw="", prefix="devices"):
        self.mqtt_params = { "host":host, "port":port, "user":user, "passw":passw }
        self.name = name
        self.online = None
        self.local_port = "/dev/" + name
        self.local_socat_status = None
        self.remote_ip = None
        self.remote_port = None
        self.remote_socat_status = None
        self.kill_timer = None
        self.kill_local_port(control_binding=False)
        time.sleep(0.05)

        self.client = mqtt_client.Client("%s-node-handler" % (self.name))
        self.client.username_pw_set(self.mqtt_params["user"], self.mqtt_params["passw"])
        self.client.connect(self.mqtt_params["host"], self.mqtt_params["port"], 60)
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
        logger.error("[%s] Node not healthy..." % (self.name))
        self.kill_local_port()

    def kill_local_port(self, control_binding=True):
        kill_command = "kill -9 $(ps ax | grep \"/usr/bin/socat\" | grep \"%s,\" | grep -v grep | awk \'{print $1}\')" % (self.name)
        if c.openhab_enabled and control_binding:
            if not Node.obh.stop_binding(self.name):
                logger.error("[%s] Binding has failed stopping... Restarting openHAB" % (self.name))
                self.restart_openhab()
            else:
                logger.info("[%s] Binding correctly stopped..." % (self.name))
        error = subprocess.Popen(kill_command, stderr=subprocess.PIPE, shell=True).communicate()[1]
        self.local_socat_status = "false"
        self.kill_timer = None
        if not error: logger.info("[%s] Local port killed..." % (self.name))

    def start_local_port(self, control_binding=True):
        socat_command = "/usr/bin/socat pty,link=%s,echo=0,raw,waitslave,group=dialout,mode=660 tcp:%s:%s" % (self.local_port, self.remote_ip, self.remote_port)
        sh_command = "while true; do %s; done" % (socat_command)
        result = subprocess.Popen(sh_command, shell=True)
        self.local_socat_status = "true"
        logger.info("[%s] Local port started..." % (self.name))
        if c.openhab_enabled and control_binding:
            if not Node.obh.start_binding(self.name):
                logger.error("[%s] Binding has failed starting... Restarting openHAB" % (self.name))
                self.restart_openhab()
            else:
                logger.info("[%s] Binding correctly started..." % (self.name))

    def restart_openhab(self):
        restart_command = "/etc/init.d/openhab restart"
        result = subprocess.Popen(restart_command, shell=True)

    def delete(self):
        self.client.loop_stop()
   
     
class Configuration(object):

    DEFAULT_PREFS = {
        "MQTT_HOST": {"key": "mqtt_host", "val": "localhost"},
        "MQTT_PORT": {"key": "mqtt_port", "val": 1883},
        "MQTT_USERNAME": {"key": "mqtt_username", "val": ""},
        "MQTT_PASSWORD": {"key": "mqtt_password", "val": ""},
        "MQTT_HOMIE_PREFIX": {"key": "mqtt_homie_prefix", "val": "devices"},
        "AUTODISCOVERY_ENABLED": {"key": "autodiscovery_enabled", "val": True},
        "ZWAVE_NETWORKS": {"key": "zwave_networks", "val": ""},
        "OPENHAB_ENABLED": {"key": "openhab_enabled", "val": True},
        "OPENHAB_HOST": {"key": "openhab_host", "val": "localhost"},
    }

    def __init__(self, config_file=""):
        self.config_file = config_file
        if self.config_file == "":
            self.config_file = "{}/{}".format(os.path.dirname(os.path.realpath(__file__)),"configuration.json")
        self.load_configuration(self.config_file)

    def load_configuration(self, config_file):
        config = {}
        config_file = os.path.realpath(config_file)
        try:
            fp = open(config_file)
        except EnvironmentError as e:
            logger.error(e)
            sys.exit(1)
        else:
            try:
                config = json.load(fp)
            except Exception as e:
                logger.error(e)
                sys.exit(1)
            finally:
                fp.close()

        for pref in self.DEFAULT_PREFS:
            key = self.DEFAULT_PREFS[pref]["key"]
            val = os.getenv(
                "HOMIE_" + pref,
                config.get(pref, self.DEFAULT_PREFS[pref]['val'])
            )

            setattr(self, key, val)
    

if __name__ == '__main__':
    try:
        if not os.geteuid() == 0:
            sys.exit("You must run this script as root")    

        logger.info("Starting zwave-socat-controller program...")

        c = Configuration()

        if c.autodiscovery_enabled:
            logger.info("Autodiscovery mode enabled")
            nc = NodeController(c.mqtt_host, c.mqtt_port, c.mqtt_username, c.mqtt_password, c.mqtt_homie_prefix)
        else:
            logger.info("Manual mode enabled for: {}".format(c.zwave_networks))
            for network in c.zwave_networks.split(","):
                Node(network, c.mqtt_host, c.mqtt_port, c.mqtt_username, c.mqtt_password, c.mqtt_homie_prefix)

        sleep_time = 1
        last_check = time.time()
        while(1):
            now = time.time()
            if int(now) % 3600 == 0:
                logger.debug("The main loop is still running...")
            difference = now - last_check
            if difference >= 1.1 * sleep_time:
                logger.error("The program has slept for %s seconds, instead of %s seconds" % (difference, sleep_time))
            last_check = now
            time.sleep(sleep_time)
    except Exception as e:
        logger.error("PANIC ERROR: {}".format(e))
