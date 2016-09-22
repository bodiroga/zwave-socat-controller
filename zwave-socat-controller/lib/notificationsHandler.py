#!/usr/bin/python
import paho.mqtt.publish as mqtt_publish
import datetime
import json

enabled = True
mqtt_host = "localhost"
mqtt_port = 1883
mqtt_user = ""
mqtt_password = ""
mqtt_auth = {'username': mqtt_user, 'password': mqtt_password}
mqtt_topic = "notifications/zwave-socat-controller"


def enable():
    global enabled
    enabled = True


def disable():
    global enabled
    enabled = False


def is_enabled():
    global enabled
    return enabled


def set_broker_parameters(broker_parameters):
    if isinstance(broker_parameters, dict):
        return
    global mqtt_host, mqtt_port, mqtt_user, mqtt_password, mqtt_auth
    mqtt_host = broker_parameters.host
    mqtt_port = broker_parameters.port
    mqtt_user = broker_parameters.user
    mqtt_password = broker_parameters.passw
    mqtt_auth = {'username': broker_parameters.user, 'password': broker_parameters.passw}


def set_broker_host(host):
    global mqtt_host
    mqtt_host = host


def set_broker_port(port):
    global mqtt_port
    mqtt_port = port


def set_broker_user(user):
    global mqtt_user
    mqtt_user = user


def set_broker_password(password):
    global mqtt_password
    mqtt_password = password


def set_broker_auth(user, password):
    global mqtt_user, mqtt_password, mqtt_auth
    mqtt_user = user
    mqtt_password = password
    mqtt_auth = {'username': user, 'password': password}


def set_notification_topic(topic):
    global mqtt_topic
    mqtt_topic = topic


def send_notification(notification):
    if is_enabled():
        if not isinstance(notification, dict):
            return

        mqtt_publish.single(topic=mqtt_topic, payload=json.dumps(notification),
                            hostname=mqtt_host, port=mqtt_port, auth=mqtt_auth)
