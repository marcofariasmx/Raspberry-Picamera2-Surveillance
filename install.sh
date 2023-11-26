#!/bin/bash

# Update and upgrade packages
sudo apt-get update
sudo apt-get upgrade -y

# Install necessary packages
sudo apt-get install -y tmux
sudo apt-get install -y pip
sudo apt install -y python3-flask
sudo apt install -y python3-picamera2
sudo apt install -y python3-opencv
sudo pip install Adafruit_DHT --break-system-packages

# Get the current username and directory of the script
CURRENT_USER="$USER"
SCRIPT_DIR="$(realpath $(dirname "$0"))"


# Create the tmux starter script
cat <<EOL > $SCRIPT_DIR/start_in_tmux.sh
#!/bin/bash
# Change to the script directory
cd "$SCRIPT_DIR"
# Start the tmux session and run the Python script
tmux new-session -d -s cam_session "sudo python run.py"
EOL

# Make the script executable
chmod +x $SCRIPT_DIR/start_in_tmux.sh

# Add the commands to /etc/rc.local before 'exit 0'
# First, make a backup of the original rc.local
sudo cp /etc/rc.local /etc/rc.local.backup
# Use awk to insert the commands before 'exit 0'
# This disables wifi power management which causes interruptions and automatically runs the camera script at boot up
awk -v user="$CURRENT_USER" -v dir="$SCRIPT_DIR" '/^exit 0/ { print "/sbin/iwconfig wlan0 power off"; print "sudo -u " user " bash " dir "/start_in_tmux.sh &"; } { print; }' /etc/rc.local.backup | sudo tee /etc/rc.local

# Change swappiness permanently
echo "vm.swappiness=5" | sudo tee -a /etc/sysctl.conf

echo "Script execution completed!"
