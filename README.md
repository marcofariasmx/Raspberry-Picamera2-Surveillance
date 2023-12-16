# Raspberry-Picamera2-Surveillance
This projects uses Flask as a webserver that lets you see a low resolution live stream (640 x 480 px) while taking higher resolution images every minute (1640 x 1232 px). It also autoadjusts exposure for night photography as well, sacrificing fps.

It utilizes Python's Picamera2 library.


Environment conditions:
----------------------
-Raspberry Pi Zero 2W / Raspberry Pi 4 (8GB).

-Raspberry Pi OS: Debian Bookworm 64 bit

-Python 3.11.2

-Picamera module v2 / v3


-------------------------
Install with:

git clone https://github.com/marcofariasmx/Raspberry-Picamera2-Surveillance.git

cd Raspberry-Picamera2-Surveillance

chmod +x install.sh

bash install.sh


* * *

Raspberry Pi Automatic Reboot Setup
===================================

This document provides instructions for setting up an automatic reboot on a Raspberry Pi. The configuration schedules the Raspberry Pi to reboot every three days at 6 AM.

Prerequisites
-------------

*   Access to the Raspberry Pi's terminal.
*   Basic understanding of using the command line.

Instructions
------------

### Setting up a Cron Job for Reboot

1.  **Open Terminal**: Access the terminal on your Raspberry Pi.
    
2.  **Edit Root's Crontab**: To schedule a reboot, edit the crontab file for the root user to ensure proper permissions.
    
    Run the following command:
    
    bashCopy code
    
    `sudo crontab -e`
    
    This opens the crontab file for the root user.
    
3.  **Add Cron Job**: In the crontab file, add the line below to schedule the automatic reboot:
    
    bashCopy code
    
    `0 6 */3 * * /sbin/reboot now`
    
    This command sets the Raspberry Pi to reboot at 6:00 AM every three days.
    
    *   `0 6`: Indicates 6:00 AM (0 minutes past the 6th hour).
    *   `*/3 * *`: Every third day of every month and every day of the week.
4.  **Save and Exit**: Save the changes and exit the editor. If using `nano`, press `CTRL+X`, then `Y` to confirm, and `Enter` to save.
    
5.  **Verify Cron Job**: To check that your cron job is correctly set up, list all scheduled jobs:
    
    bashCopy code
    
    `sudo crontab -l`
    
    This displays all cron jobs for the root user, including the new reboot schedule.
    

Notes
-----

*   Ensure this scheduled reboot aligns with your use case and does not disrupt critical services.
*   To modify or remove this schedule, repeat steps 2 and 3, altering or commenting out the relevant line.

* * *

This format is commonly used in Markdown files (`.md`) and should be compatible with most documentation systems that support Markdown. You can copy this content directly into your README file.