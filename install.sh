#!/bin/bash

## Global variables
name="zwave-socat-controller"


## Making sure only root can run our script
if [[ $EUID -ne 0 ]]; then
   echo -e "This script must be run as root" 1>&2
   exit 1
fi


## MQTT broker parameters
echo -e "\n-- MQTT broker parameters -- "
echo -e "Hostname or IP address of the MQTT broker: "
read host;
echo -e "Username of the MQTT broker: "
read username;
echo -e "Password of the MQTT broker: "
read password;

echo -e "\n-- Parameters summary --"
echo -e "HOST: $host, USERNAME: $username, PASSWORD: $password "
read -p "Do you want to continue? (y/N)? " choice
	case "$choice" in
	  y|Y|s|S ) echo -e "\nStarting the installation process...";;
	  * ) echo -e "\nInstallation aborted"; exit;;
	esac


## Installing the required programs
echo -e '\nInstalling the required programs...'
apt-get update
apt-get --assume-yes install git python python-pip jq socat mosquitto >/dev/null
pip install paho-mqtt


## Cloning the github repository
cd /tmp
if [ -d "$name" ]; then
	echo -e "\nThe github repository already exists, let's make a 'git pull'..."
	cd $name
	git pull
else
	echo -e "\nCloning the github repository..."
	git clone https://github.com/bodiroga/$name.git
	cd $name
fi


## Moving the program files to the root directory
cp -rf $name /root


## Adding the start script file
echo -e '\nAdding the start script file...'
cp -rf init.d/* /etc/init.d/
chmod +x /etc/init.d/$name
update-rc.d $name defaults


## Editing the configuration.json file
echo -e '\nEditing the configuration.json file'
cd /root
cd $name
cp configuration_default.json configuration.json
if [[ ! -z "${host// }" ]]; then
   jq --arg _host $host  '. | .MQTT_HOST=$_host' configuration.json > tmp.$$.json && mv tmp.$$.json configuration.json
fi
if [[ ! -z "${username// }" ]]; then
   jq --arg _user $username '. | .MQTT_USERNAME=$_user' configuration.json > tmp.$$.json && mv tmp.$$.json configuration.json
fi
if [[ ! -z "${password// }" ]]; then
   jq --arg _pass $password '. | .MQTT_PASSWORD=$_pass' configuration.json > tmp.$$.json && mv tmp.$$.json configuration.json
fi
rm -rf tmp.*.json


## Removing the git repository
echo
read -p "Do you want to remove the git repository from your computer (y/N)? " choice
case "$choice" in
  y|Y|s|S ) echo -e "Deleting the git repository..."; rm -rf /tmp/$name;;
  * ) echo -e "Keeping the git repository...";;
esac


## Start the program
echo
read -p "Do you want to start the program now (y/N)? " choice
case "$choice" in
  y|Y|s|S ) echo -e "Starting the program..."; /etc/init.d/$name restart;;
  * ) echo -e "You can start the program typing '/etc/init.d/$name start'";;
esac


## Done
echo -e "\nDone."
