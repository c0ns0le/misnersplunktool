#!/usr/bin/env python
"""
misnersplunktool.py - Misner Splunk Tool
Copyright (C) 2015-2017 Joe Misner <joe@misner.net>
http://tools.misner.net/

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software Foundation,
Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301  USA

Dependencies:
- Python v2.7.13, https://www.python.org/
- Python module 'splunk-sdk' v1.6.0, https://pypi.python.org/pypi/splunk-sdk
- Python module 'PySide' v1.2.4, https://pypi.python.org/pypi/PySide
- Python module 'misnersplunktoolui.py'
- Python module 'misnersplunkdwrapper.py'
"""

import sys
import os
import socket
import time
import datetime
import math
import ConfigParser
import splunklib.binding as binding
from PySide import QtCore, QtGui
from misnersplunktoolui import Ui_MainWindow
from misnersplunkdwrapper import Splunkd

__version__ = '2017.05.10'

SCRIPT_DIR = os.path.dirname(sys.argv[0])
CONFIG_FILENAME = 'misnersplunktool.conf'
CONFIG_DEFAULT = """
# misnersplunktool.conf -- Misner Splunk Tool configuration file
# Place in same directory as misnersplunktool.exe to import settings

# Main configuration entries
# The default Address, Username, and Password populate these fields when the tool loads
[main]
defaultAddress=localhost:8089
defaultUsername=admin
defaultPassword=changeme

# REST API endpoints populated in the REST API tab's combo box for easy access
# Add sequential entries incrementing from 0
[endpoints]
endpoint.0=/services/server/info
endpoint.1=/services/server/settings

# splunkd locations saved in the Address combo box
# Create separate stanzas for each saved splunkd location, including the ip/host and management port
# Optionally include keys with username and/or password to populate these fields when selected
[splunkd::1.2.3.4:8089]
username=admin
password=changeme

[splunkd::splunk.myhost.com:8089]
username=admin
password=changeme
"""

HELP_TEXT = """
Misner Splunk Tool connects to a Splunk Enterprise or Universal
Forwarder instance via REST API, retrieving the instance's
configurations, input status, apps, and other useful information for
troubleshooting and analysis. This tool's intention is to grant easy
access into remote Splunk instances where shell or web access may not
be available, but the splunkd management port (default 8089) is
accessible.

Edit the included file misnersplunktool.conf located in this
application's directory to specify configurations such as default
hosts, credentials, and REST endpoints. If this file is missing,
navigate to 'File > Build misnersplunktool.conf' and edit this file
with a text editor.

Tooltips have been setup throughout the tool. For additional help,
hover your mouse pointer over different areas of the tool's interface
for more information.
"""

ABOUT_TEXT = """
<html>
<h3>Misner Splunk Tool</h3>
Version %s
<p>
Copyright (C) 2015-2017 Joe Misner &lt;<a href="mailto:joe@misner.net">joe@misner.net</a>&gt;
<a href="http://tools.misner.net/">http://tools.misner.net/</a>
<p>
Splunk is a trademark of Splunk Inc. in the United States and other
countries.
<p>
This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 3 of the License, or
(at your option) any later version.
<p>
This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.
<p>
You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software Foundation,
Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301  USA
<p>
Click the "Show Details" button below for complete license information.
</html>
"""


def fatal_error(txt):
    """Prints error to syserr in standard Unix format with filename and quits"""
    exitcode = "\n%s: error: %s" % (os.path.basename(sys.argv[0]), txt)
    sys.exit(exitcode)


def human_time(*args, **kwargs):
    """Convert datetime.timedelta to human readable value"""
    secs  = float(datetime.timedelta(*args, **kwargs).total_seconds())
    units = [("day", 86400), ("hr", 3600), ("min", 60), ("sec", 1)]
    parts = []
    for unit, mul in units:
        if secs / mul >= 1 or mul == 1:
            if mul > 1:
                n = int(math.floor(secs / mul))
                secs -= n * mul
            else:
                n = secs if secs != int(secs) else int(secs)
            parts.append("%s %s%s" % (n, unit, "" if n == 1 else "s"))
    return " ".join(parts)


def pretty_time_delta(seconds):
    """Returns time delta in easily readable format"""
    output = '-' if seconds < 0 else ''
    seconds = abs(int(seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days > 0:
        output += ' %d day%s' % (days, 's' if days > 1 else '')
    if hours > 0:
        output += ' %d hr%s' % (hours, 's' if hours > 1 else '')
    if minutes > 0:
        output += ' %d min%s' % (minutes, 's' if minutes > 1 else '')
    if seconds > 0:
        output += ' %d sec%s' % (seconds, 's' if seconds > 1 else '')
    return output.strip()


class MainWindow(QtGui.QMainWindow):
    """Object class for the main window"""
    def __init__(self):
        """Executed when the MainWindow() object is created"""
        # GUI Setup
        #  Basics
        QtGui.QMainWindow.__init__(self)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.setFixedSize(self.size())
        self.show()
        self.disconnect()

        #  General tab
        self.ui.tableMessages.setColumnWidth(0, 140)  # Time Created
        self.ui.tableMessages.setColumnWidth(1, 55)   # Severity
        self.ui.tableMessages.setColumnWidth(2, 150)  # Title
        self.ui.tableMessages.setColumnWidth(3, 340)  # Description
        self.ui.tableMessages.sortByColumn(0, QtCore.Qt.AscendingOrder)

        #  Configuration tab
        self.ui.labelHighlighter.setVisible(False)
        self.ui.editConfigurationFind.setVisible(False)
        self.ui.buttonConfigurationMark.setVisible(False)
        self.ui.buttonConfigurationClear.setVisible(False)

        #  Input Status tab
        self.ui.tableFileStatus.setColumnWidth(0, 420)  # Location
        self.ui.tableFileStatus.setColumnWidth(1, 100)  # Type
        self.ui.tableFileStatus.setColumnWidth(2, 50)   # Percent
        self.ui.tableFileStatus.setColumnWidth(3, 70)   # Position
        self.ui.tableFileStatus.setColumnWidth(4, 70)   # Size
        self.ui.tableFileStatus.setColumnWidth(5, 400)  # Parent
        self.ui.tableFileStatus.sortByColumn(0, QtCore.Qt.AscendingOrder)

        self.ui.tableTCP.setColumnWidth(0, 70)   # TCP Type
        self.ui.tableTCP.setColumnWidth(1, 50)   # Port
        self.ui.tableTCP.setColumnWidth(2, 300)  # Source
        self.ui.tableTCP.setColumnWidth(3, 150)  # Time Opened
        self.ui.tableTCP.sortByColumn(0, QtCore.Qt.AscendingOrder)

        self.ui.tableUDP.setColumnWidth(0, 300)  # Source
        self.ui.tableUDP.sortByColumn(0, QtCore.Qt.AscendingOrder)

        self.ui.tableModular.setColumnWidth(0, 420)  # Location
        self.ui.tableModular.setColumnWidth(1, 110)  # Exit Status
        self.ui.tableModular.setColumnWidth(2, 150)  # Opened
        self.ui.tableModular.setColumnWidth(3, 150)  # Closed
        self.ui.tableModular.setColumnWidth(4, 70)   # Total Bytes
        self.ui.tableModular.sortByColumn(0, QtCore.Qt.AscendingOrder)

        self.ui.tableExec.setColumnWidth(0, 420)  # Location
        self.ui.tableExec.setColumnWidth(1, 110)  # Exit Status
        self.ui.tableExec.setColumnWidth(2, 150)  # Opened
        self.ui.tableExec.setColumnWidth(3, 150)  # Closed
        self.ui.tableExec.setColumnWidth(4, 70)   # Total Bytes
        self.ui.tableExec.sortByColumn(0, QtCore.Qt.AscendingOrder)

        #  Apps tab
        self.ui.tableApps.setColumnWidth(0, 50)   # Active
        self.ui.tableApps.setColumnWidth(1, 180)  # Title
        self.ui.tableApps.setColumnWidth(2, 50)   # Version
        self.ui.tableApps.setColumnWidth(3, 180)  # Label
        self.ui.tableApps.setColumnWidth(4, 300)  # Description
        self.ui.tableApps.sortByColumn(1, QtCore.Qt.AscendingOrder)

        #  Indexer Cluster tab
        #   Peers tab
        self.ui.tableClusterPeers.setColumnWidth(0, 200)  # Peer Name
        self.ui.tableClusterPeers.setColumnWidth(1, 50)   # Site
        self.ui.tableClusterPeers.setColumnWidth(2, 100)  # Fully Searchable
        self.ui.tableClusterPeers.setColumnWidth(3, 50)   # Status
        self.ui.tableClusterPeers.setColumnWidth(4, 50)   # Buckets
        self.ui.tableClusterPeers.setColumnWidth(5, 120)  # Location
        self.ui.tableClusterPeers.setColumnWidth(6, 150)  # Last Heartbeat
        self.ui.tableClusterPeers.setColumnWidth(7, 100)  # Replication Port
        self.ui.tableClusterPeers.setColumnWidth(8, 110)  # Base Generation ID
        self.ui.tableClusterPeers.setColumnWidth(9, 250)  # GUID
        self.ui.tableClusterPeers.sortByColumn(0, QtCore.Qt.AscendingOrder)
        #   Indexes tab
        self.ui.tableClusterIndexes.setColumnWidth(0, 150)  # Index Name
        self.ui.tableClusterIndexes.setColumnWidth(1, 100)  # Fully Searchable
        self.ui.tableClusterIndexes.setColumnWidth(2, 150)  # Searchable Data Copies
        self.ui.tableClusterIndexes.setColumnWidth(3, 150)  # Replicated Data Copies
        self.ui.tableClusterIndexes.setColumnWidth(4, 50)   # Buckets
        self.ui.tableClusterIndexes.setColumnWidth(5, 150)  # Cumulative Raw Data Size
        self.ui.tableClusterIndexes.sortByColumn(0, QtCore.Qt.AscendingOrder)
        #   Search Heads tab
        self.ui.tableClusterSearchHeads.setColumnWidth(0, 200)  # Search Head Name
        self.ui.tableClusterSearchHeads.setColumnWidth(1, 50)   # Site
        self.ui.tableClusterSearchHeads.setColumnWidth(2, 100)  # Status
        self.ui.tableClusterSearchHeads.setColumnWidth(3, 150)  # Location
        self.ui.tableClusterSearchHeads.setColumnWidth(4, 250)  # GUID
        self.ui.tableClusterSearchHeads.sortByColumn(0, QtCore.Qt.AscendingOrder)

        #  Search Head Cluster tab
        self.ui.tableSHClusterMembers.setColumnWidth(0, 200)  # Peer Name
        self.ui.tableSHClusterMembers.setColumnWidth(1, 50)   # Site
        self.ui.tableSHClusterMembers.setColumnWidth(2, 50)   # Status
        self.ui.tableSHClusterMembers.setColumnWidth(3, 60)   # Artifacts
        self.ui.tableSHClusterMembers.setColumnWidth(4, 120)  # Location
        self.ui.tableSHClusterMembers.setColumnWidth(5, 150)  # Last Heartbeat
        self.ui.tableSHClusterMembers.setColumnWidth(6, 100)  # Replication Port
        self.ui.tableSHClusterMembers.setColumnWidth(7, 100)  # Restart Required
        self.ui.tableSHClusterMembers.setColumnWidth(8, 250)  # GUID
        self.ui.tableSHClusterMembers.sortByColumn(0, QtCore.Qt.AscendingOrder)

        # Resource Usage tab
        self.ui.progressResourceUsageCPU.setStyleSheet(
            "QProgressBar { border: 2px solid grey; border-radius: 0px; text-align: center; } "
            "QProgressBar::chunk {background-color: #3add36; width: 1px;}")
        self.ui.progressResourceUsageMemory.setStyleSheet(
            "QProgressBar { border: 2px solid grey; border-radius: 0px; text-align: center; } "
            "QProgressBar::chunk {background-color: #3add36; width: 1px;}")
        self.ui.progressResourceUsageSwap.setStyleSheet(
            "QProgressBar { border: 2px solid grey; border-radius: 0px; text-align: center; } "
            "QProgressBar::chunk {background-color: #3add36; width: 1px;}")
        self.ui.tableResourceUsageProcesses.setColumnWidth(0, 70)   # Process
        self.ui.tableResourceUsageProcesses.setColumnWidth(1, 40)   # PID
        self.ui.tableResourceUsageProcesses.setColumnWidth(2, 40)   # PPID
        self.ui.tableResourceUsageProcesses.setColumnWidth(3, 40)   # CPU
        self.ui.tableResourceUsageProcesses.setColumnWidth(4, 40)   # RAM
        self.ui.tableResourceUsageProcesses.setColumnWidth(5, 200)  # Args
        self.ui.tableResourceUsageProcesses.sortByColumn(1, QtCore.Qt.AscendingOrder)
        self.ui.tableResourceUsageDisks.setColumnWidth(0, 170)  # Mount
        self.ui.tableResourceUsageDisks.setColumnWidth(1, 50)   # Type
        self.ui.tableResourceUsageDisks.setColumnWidth(2, 40)   # Used
        self.ui.tableResourceUsageDisks.setColumnWidth(3, 60)   # Total
        self.ui.tableResourceUsageDisks.sortByColumn(0, QtCore.Qt.AscendingOrder)

        # Signals and Slots
        #  Menubar
        self.ui.actionBuildMisnersplunktoolConf.triggered.connect(self.actionBuildMisnersplunktoolConf_triggered)
        #self.ui.actionSaveSplunkInstanceCredentials.triggered.connect(
        #  self.actionSaveSplunkInstanceCredentials_triggered
        #)
        self.ui.actionExit.triggered.connect(self.close)
        self.ui.actionRestartSplunkd.triggered.connect(self.actionRestartSplunkd_clicked)
        self.ui.actionRefreshConfigurations.triggered.connect(self.actionRefreshConfigurations_clicked)
        self.ui.actionChangeDeploymentServer.triggered.connect(self.actionChangeDeploymentServer_clicked)
        self.ui.actionHelp.triggered.connect(self.actionHelp_triggered)
        self.ui.actionAbout.triggered.connect(self.actionAbout_triggered)
        #  Top
        self.ui.comboAddress.activated.connect(self.comboAddress_activated)
        self.ui.comboAddress.lineEdit().returnPressed.connect(self.buttonToggle_clicked)
        self.ui.editUsername.returnPressed.connect(self.buttonToggle_clicked)
        self.ui.editPassword.returnPressed.connect(self.buttonToggle_clicked)
        self.ui.buttonToggle.clicked.connect(self.buttonToggle_clicked)
        self.ui.buttonPoll.clicked.connect(self.poll)
        #  General tab
        self.ui.buttonRestartSplunkd.clicked.connect(self.actionRestartSplunkd_clicked)
        self.ui.buttonRefreshConfigurations.clicked.connect(self.actionRefreshConfigurations_clicked)
        #  Configuration tab
        self.ui.comboConfig.activated.connect(self.comboConfig_activated)
        self.ui.editConfigurationFind.returnPressed.connect(self.buttonConfigurationMark_clicked)
        self.ui.buttonConfigurationMark.clicked.connect(self.buttonConfigurationMark_clicked)
        self.ui.buttonConfigurationClear.clicked.connect(self.buttonConfigurationClear_clicked)

        #  Input Status tab
        #  Apps tab
        #  Cluster tab
        self.ui.checkClusterDataSearchable.clicked.connect(self.checkCluster_clicked)
        self.ui.checkClusterSearchFactorMet.clicked.connect(self.checkCluster_clicked)
        self.ui.checkClusterReplicationFactorMet.clicked.connect(self.checkCluster_clicked)
        self.ui.checkClusterMaintenanceMode.clicked.connect(self.checkCluster_clicked)
        self.ui.checkClusterRollingRestartFlag.clicked.connect(self.checkCluster_clicked)
        self.ui.checkClusterInitializedFlag.clicked.connect(self.checkCluster_clicked)
        self.ui.checkClusterServiceReadyFlag.clicked.connect(self.checkCluster_clicked)
        self.ui.checkClusterIndexingReadyFlag.clicked.connect(self.checkCluster_clicked)
        #  Cluster tab
        self.ui.checkSHClusterInitializedFlag.clicked.connect(self.checkSHCluster_clicked)
        self.ui.checkSHClusterServiceReadyFlag.clicked.connect(self.checkSHCluster_clicked)
        self.ui.checkSHClusterMinimumPeersJoinedFlag.clicked.connect(self.checkSHCluster_clicked)
        self.ui.checkSHClusterDynamicCaptain.clicked.connect(self.checkSHCluster_clicked)
        self.ui.checkSHClusterRollingRestartFlag.clicked.connect(self.checkSHCluster_clicked)
        #  REST API tab
        self.ui.comboRestURI.lineEdit().returnPressed.connect(self.buttonRestSend_clicked)
        self.ui.buttonRestSend.clicked.connect(self.buttonRestSend_clicked)

        # Load defaults
        #self.poll_interval = POLL_INTERVAL

        # Load misnersplunktool.conf configurations
        self.pull_configs()

    def statusbar_msg(self, msg):
        """Sends a message to the statusbar"""
        self.ui.statusbar.showMessage(msg)

    def question_msg_yesno(self, msg):
        dialog_answer = QtGui.QMessageBox.question(self, "Misner Splunk Tool", msg,
                                                   QtGui.QMessageBox.Yes | QtGui.QMessageBox.No)
        if dialog_answer == QtGui.QMessageBox.StandardButton.Yes:
            return True
        else:
            return False

    def information_msg(self, msg):
        QtGui.QMessageBox.information(self, "Misner Splunk Tool", msg)

    def warning_msg(self, msg):
        QtGui.QMessageBox.warning(self, "Misner Splunk Tool", msg)

    def critical_msg(self, msg):
        QtGui.QMessageBox.critical(self, "Misner Splunk Tool", msg)

    def pull_configs(self):
        """Pull in configurations from flat configuration file misnersplunktool.conf"""
        for section in config.sections():
            if section[0:9] == 'splunkd::':
                self.ui.comboAddress.addItem(section[9:])

        if config.has_section('endpoints'):
            endpoint_number = 0
            while config.has_option('endpoints', 'endpoint.%s' % endpoint_number):
                uri = config.get('endpoints', 'endpoint.%s' % endpoint_number)
                self.ui.comboRestURI.addItem(uri)
                endpoint_number += 1

        if config.has_option('main', 'defaultAddress'):
            self.ui.comboAddress.setEditText(config.get('main', 'defaultAddress'))
        if config.has_option('main', 'defaultUsername'):
            self.ui.editUsername.setText(config.get('main', 'defaultUsername'))
        if config.has_option('main', 'defaultPassword'):
            self.ui.editPassword.setText(config.get('main', 'defaultPassword'))
        if config.has_option('main', 'pollInterval'):
            try:
                self.poll_interval = config.getint('main', 'pollInterval')
            except:
                self.warning_msg("Bad poll interval value in configuration, must be an integer")

    def connect(self):
        """Connect to Splunkd"""
        splunk_host = self.ui.comboAddress.currentText().strip()
        splunk_user = self.ui.editUsername.text().strip()
        splunk_pass = self.ui.editPassword.text().strip()

        # Check address, username, and password fields
        if not splunk_host:
            self.warning_msg("Missing Splunk address")
            return
        if not splunk_user:
            self.warning_msg("Missing Splunk username")
            return
        if not splunk_pass:
            self.warning_msg("Missing Splunk password")
            return
        if ':' in splunk_host:
            splunk_host, splunk_port = self.ui.comboAddress.currentText().split(':')
            splunk_port = int(splunk_port)
        else:
            splunk_port = 8089
        if not 0 < splunk_port < 65536:
            self.warning_msg("Invalid port specified")
            return

        # Create Splunk instance
        host = "'%s:%s'" % (splunk_host, splunk_port)
        self.statusbar_msg("Connecting to host %s..." % host)
        try:
            self.splunkd = Splunkd(splunk_host, splunk_port, splunk_user, splunk_pass)
        except binding.AuthenticationError:
            self.warning_msg("Authentication error connecting to host %s" % host)
            return
        except socket.gaierror:
            self.warning_msg("Unable to connect to host %s" % host)
            return
        except socket.error as error:
            self.warning_msg("Unable to connect to host %s:\n"
                             "%s" % (host, error))
            return
        finally:
            self.statusbar_msg('Connection failed')
        self.statusbar_msg('Connected')

        # Toggle GUI fields
        self.ui.comboAddress.setEnabled(False)
        self.ui.editUsername.setEnabled(False)
        self.ui.editPassword.setEnabled(False)
        self.ui.tabWidgetMain.setEnabled(True)
        self.ui.buttonPoll.setEnabled(True)
        self.ui.buttonToggle.setText('Disconnect')

        # Poll Splunk instance
        self.poll()
        self.setWindowTitle('%s - Misner Splunk Tool' % self.splunkd.server_name)
        if 'cluster_master' in self.splunkd.roles:
            self.ui.tabCluster.setEnabled(True)
        else:
            self.ui.tabCluster.setEnabled(False)
        if 'shc_member' in self.splunkd.roles:
            self.ui.tabSHCluster.setEnabled(True)
        else:
            self.ui.tabSHCluster.setEnabled(False)

    def disconnect(self):
        """Disconnect from Splunkd"""
        # Destroy the splunkd instance
        try:
            del self.splunkd
        except AttributeError:
            pass

        # Toggle GUI fields
        self.setWindowTitle('Misner Splunk Tool')
        self.ui.comboAddress.setEnabled(True)
        self.ui.editUsername.setEnabled(True)
        self.ui.editPassword.setEnabled(True)
        self.ui.tabWidgetMain.setEnabled(False)
        self.ui.buttonPoll.setEnabled(False)
        self.ui.buttonToggle.setText('Connect')

        # Reset labels
        #  Top
        self.ui.labelRole.setPixmap(":/blank.png")
        self.ui.labelRole.setToolTip(None)
        self.ui.labelHost.setText('(none)')
        self.ui.labelType.setText('(none)')
        self.ui.labelGUID.setText('(none)')
        self.ui.labelOS.setText('(none)')
        self.ui.labelOS.setToolTip('(none)')
        self.ui.labelSystem.setText('(none)')
        self.ui.labelUptime.setText('(none)')
        self.ui.labelUptime.setToolTip(None)
        #  General tab
        self.ui.tableMessages.setRowCount(0)
        self.ui.labelRestartRequired.setText('?')
        self.ui.labelDeploymentServer.setText('(none)')
        self.ui.labelDeploymentServer.setToolTip(None)
        self.ui.labelClusterMasterHeader.setText('Cluster Master:')
        self.ui.labelClusterMaster.setText('(none)')
        self.ui.labelClusterMaster.setToolTip(None)
        self.ui.labelSHCDeployer.setText('(none)')
        self.ui.labelSHCDeployer.setToolTip(None)
        #  Configuration tab
        self.ui.editConfig.setText(None)
        #  Input Status tab
        self.ui.tableFileStatus.setRowCount(0)
        self.ui.tableTCP.setRowCount(0)
        self.ui.tableUDP.setRowCount(0)
        self.ui.tableModular.setRowCount(0)
        self.ui.tableExec.setRowCount(0)
        self.ui.tableApps.setRowCount(0)
        #  Indexer Cluster tab
        self.ui.checkClusterDataSearchable.setChecked(False)
        self.ui.checkClusterSearchFactorMet.setChecked(False)
        self.ui.checkClusterReplicationFactorMet.setChecked(False)
        self.ui.labelClusterPeersSearchable.setText('? searchable')
        self.ui.labelClusterPeersNotSearchable.setText('? not searchable')
        self.ui.labelClusterIndexesSearchable.setText('? searchable')
        self.ui.labelClusterIndexesNotSearchable.setText('? not searchable')
        self.ui.labelClusterPeersUp.setText('?/? Peers Up')
        self.ui.labelClusterSearchHeadsUp.setText('?/? Search Heads Up')
        self.ui.checkClusterMaintenanceMode.setChecked(False)
        self.ui.checkClusterRollingRestartFlag.setChecked(False)
        self.ui.checkClusterInitializedFlag.setChecked(False)
        self.ui.checkClusterServiceReadyFlag.setChecked(False)
        self.ui.checkClusterIndexingReadyFlag.setChecked(False)
        self.ui.tableClusterPeers.setRowCount(0)
        self.ui.tableClusterIndexes.setRowCount(0)
        self.ui.tableClusterSearchHeads.setRowCount(0)
        #  Search Head Cluster tab
        self.ui.checkSHClusterInitializedFlag.setChecked(False)
        self.ui.checkSHClusterServiceReadyFlag.setChecked(False)
        self.ui.checkSHClusterMinimumPeersJoinedFlag.setChecked(False)
        self.ui.checkSHClusterDynamicCaptain.setChecked(False)
        self.ui.checkSHClusterRollingRestartFlag.setChecked(False)
        self.ui.labelSHClusterCaptain.setText('(none)')
        self.ui.labelSHClusterCaptainElected.setText('(none)')
        self.ui.tableSHClusterMembers.setRowCount(0)
        #  Resource Usage tab
        self.ui.progressResourceUsageCPU.setValue(0)
        self.ui.progressResourceUsageMemory.setValue(0)
        self.ui.labelResourceUsageMemory.setText('(none)')
        self.ui.labelResourceUsageSwapHeader.setText('Swap:')
        self.ui.progressResourceUsageSwap.setValue(0)
        self.ui.labelResourceUsageSwap.setText('(none)')
        self.ui.tableResourceUsageProcesses.setRowCount(0)
        self.ui.tableResourceUsageDisks.setRowCount(0)
        #  REST API tab
        self.ui.editRestResult.setText(None)

        self.statusbar_msg('Disconnected')

    def poll(self):
        """Poll for new Splunkd values"""
        # Check connection with splunkd
        try:
            self.splunkd.service.settings
        except binding.AuthenticationError:
            self.disconnect()
            self.critical_msg('Splunk connection reset')
            return
        except socket.error as e:
            self.disconnect()
            self.critical_msg("Socket error while attempting to poll splunkd:\n"
                              "%s" % e)
            return
        except:
            self.disconnect()
            self.critical_msg('Unknown error while attempting to poll splunkd')
            return

        # Poll splunkd
        try:
            self.statusbar_msg('Polling service info...')
            self.splunkd.poll_service_info()
            self.statusbar_msg('Polling settings...')
            self.splunkd.poll_service_settings()
            self.statusbar_msg('Polling messages...')
            self.splunkd.poll_service_messages()
            self.statusbar_msg('Polling configurations...')
            self.splunkd.get_service_confs()
            self.statusbar_msg('Polling input status...')
            self.splunkd.get_services_admin_inputstatus()
            self.statusbar_msg('Polling apps...')
            self.splunkd.poll_service_apps()
            self.statusbar_msg('Polling cluster master info...')
            self.splunkd.get_services_cluster_master()
            self.statusbar_msg('Polling search head cluster info...')
            self.splunkd.get_services_shcluster()
            self.statusbar_msg('Polling introspection...')
            self.splunkd.get_services_server_status()
        except socket.error as e:
            self.disconnect()
            self.critical_msg("Socket error while attempting to poll splunkd:\n"
                              "%s" % e)
            return

        self.statusbar_msg('Populating GUI...')

        # Setup Splunk icon
        roles = ['Server Roles:']
        for role in self.splunkd.roles:
            roles.append(role)
        self.ui.labelRole.setToolTip('\n'.join(roles))
        if 'universal_forwarder' in self.splunkd.roles:  # also lightweight_forwarder
            self.ui.labelRole.setPixmap(':/forwarder.png')
        elif 'management_console' in self.splunkd.roles:
            self.ui.labelRole.setPixmap(':/managementconsole.png')
        elif 'indexer' in self.splunkd.roles:  # also search_peer, cluster_slave
            self.ui.labelRole.setPixmap(':/indexer.png')
        elif 'deployment_server' in self.splunkd.roles:  # also shc_deployer
            self.ui.labelRole.setPixmap(':/deploymentserver.png')
        elif 'heavyweight_forwarder' in self.splunkd.roles:
            self.ui.labelRole.setPixmap(':/heavyforwarder.png')
        elif 'cluster_master' in self.splunkd.roles:
            self.ui.labelRole.setPixmap(':/masternode.png')
        elif 'license_master' in self.splunkd.roles:
            self.ui.labelRole.setPixmap(':/licenseserver.png')
        elif 'search_head' in self.splunkd.roles:  # also shc_captain, shc_member, cluster_search_head
            self.ui.labelRole.setPixmap(':/searchhead.png')
        elif self.splunkd.mode == 'dedicated forwarder':  # older versions of Splunk don't set a role
            self.ui.labelRole.setPixmap(':/forwarder.png')
        else:
            self.ui.labelRole.setPixmap(':/heavyforwarder.png')

        # Fill in top labels
        self.ui.labelHost.setText(self.splunkd.host)
        self.ui.labelType.setText(self.splunkd.type)
        self.ui.labelGUID.setText(self.splunkd.guid)
        self.ui.labelOS.setText(self.splunkd.os)
        self.ui.labelOS.setToolTip(self.splunkd.os)
        self.ui.labelSystem.setText("%s core%s, %s MB RAM" % (self.splunkd.cores if self.splunkd.cores > 0 else '?',
                                                              '' if self.splunkd.cores == 1 else 's',
                                                              self.splunkd.ram if self.splunkd.ram > 0 else '?'))
        if self.splunkd.startup_time:
            uptime = pretty_time_delta(int(time.time()) - self.splunkd.startup_time)
            start_time = time.strftime("%m/%d/%Y %I:%M:%S %p", time.localtime(float(self.splunkd.startup_time)))
        else:
            uptime = '(unknown)'
            start_time = '(unknown)'
        self.ui.labelUptime.setText(uptime)
        self.ui.labelUptime.setToolTip('splunkd start time: %s' % start_time)

        # Fill in General tab
        restart_required = 'Yes' if self.splunkd.service.restart_required else 'No'
        self.ui.labelRestartRequired.setText(restart_required)
        if 'Enterprise' in self.splunkd.type:
            self.ui.buttonRefreshConfigurations.setEnabled(True)
        else:
            self.ui.buttonRefreshConfigurations.setEnabled(False)
        self.ui.labelDeploymentServer.setText(self.splunkd.deployment_server)
        self.ui.labelDeploymentServer.setToolTip(self.splunkd.deployment_server)
        if self.splunkd.cluster_mode == 'master':
            self.ui.labelClusterMasterHeader.setText('Cluster Master:')
            self.ui.labelClusterMaster.setText('(self)')
        elif self.splunkd.cluster_mode == 'slave':
            self.ui.labelClusterMasterHeader.setText('Peer of Cluster Master:')
            self.ui.labelClusterMaster.setText(self.splunkd.cluster_master_uri)
            self.ui.labelClusterMaster.setToolTip(self.splunkd.cluster_master_uri)
        elif self.splunkd.cluster_mode == 'searchhead':
            self.ui.labelClusterMasterHeader.setText('Search Head of Cluster Master(s):')
            self.ui.labelClusterMaster.setText(self.splunkd.cluster_master_uri)
            self.ui.labelClusterMaster.setToolTip(self.splunkd.cluster_master_uri)
        else:
            self.ui.labelClusterMasterHeader.setText('Cluster Master:')
            self.ui.labelClusterMaster.setText('(none)')
        if self.splunkd.shcluster_deployer:
            self.ui.labelSHCDeployer.setText(self.splunkd.shcluster_deployer)
            self.ui.labelSHCDeployer.setToolTip(self.splunkd.shcluster_deployer)
        else:
            self.ui.labelSHCDeployer.setText('(none)')
        fields = ['time_created', 'severity', 'title', 'description']
        self.table_builder(self.ui.tableMessages, self.splunkd.messages, fields)
        self.ui.tableMessages.resizeRowsToContents()

        # Fill in Configuration tab
        self.ui.comboConfig.clear()
        self.ui.comboConfig.addItems(self.splunkd.configuration_files)
        self.ui.editConfig.clear()
        self.comboConfig_activated()

        # Fill in Input Status tab
        #  Input Status > File Status
        fields = ['location', 'type', 'percent', 'position', 'size', 'parent']
        self.table_builder(self.ui.tableFileStatus, self.splunkd.fileinput_status, fields)

        #  Input Status > TCP
        tcpmonitors = []
        for monitor in self.splunkd.rawtcp_status:
            monitor['tcptype'] = 'Raw'
            tcpmonitors.append(monitor)
        for monitor in self.splunkd.cookedtcp_status:
            monitor['tcptype'] = 'Cooked'
            tcpmonitors.append(monitor)
        fields = ['tcptype', 'port', 'source', 'opened']
        self.table_builder(self.ui.tableTCP, tcpmonitors, fields)

        #  Input Status > UDP
        fields = ['source']
        self.table_builder(self.ui.tableUDP, self.splunkd.udphosts_status, fields)

        #  Input Status > Modular
        fields = ['location', 'exit_desc', 'opened', 'closed', 'bytes']
        self.table_builder(self.ui.tableModular, self.splunkd.modularinput_status, fields)

        #  Input Status > Exec
        fields = ['location', 'exit_desc', 'opened', 'closed', 'bytes']
        self.table_builder(self.ui.tableExec, self.splunkd.execinput_status, fields)

        # Fill in Apps tab
        fields = ['disabled', 'title', 'version', 'label', 'description']
        self.table_builder(self.ui.tableApps, self.splunkd.apps, fields)

        # Fill in Indexer Cluster tab
        self.checkCluster_clicked()
        if 'cluster_master' in self.splunkd.roles:
            peers_unsearchable = len(self.splunkd.cluster_peers) - self.splunkd.cluster_peers_searchable
            self.ui.labelClusterPeersSearchable.setText('%s searchable' % self.splunkd.cluster_peers_searchable)
            self.ui.labelClusterPeersNotSearchable.setText('%s not searchable' % peers_unsearchable)
            indexes_unsearchable = len(self.splunkd.cluster_indexes) - self.splunkd.cluster_indexes_searchable
            self.ui.labelClusterIndexesSearchable.setText('%s searchable' % self.splunkd.cluster_indexes_searchable)
            self.ui.labelClusterIndexesNotSearchable.setText('%s not searchable' % indexes_unsearchable)
            self.ui.labelClusterPeersUp.setText('%s/%s Peers Up' % (self.splunkd.cluster_peers_up,
                                                                    len(self.splunkd.cluster_peers)))
            self.ui.labelClusterSearchHeadsUp.setText('%s/%s Search Heads Up'
                                                      % (self.splunkd.cluster_searchheads_connected,
                                                         len(self.splunkd.cluster_searchheads)))

            fields = ['name', 'site', 'is_searchable', 'status', 'buckets', 'location', 'last_heartbeat',
                      'replication_port', 'base_gen_id', 'guid']
            self.table_builder(self.ui.tableClusterPeers, self.splunkd.cluster_peers, fields)

            fields = ['name', 'is_searchable', 'searchable_data_copies', 'replicated_data_copies',
                      'buckets', 'cumulative_data_size']
            self.table_builder(self.ui.tableClusterIndexes, self.splunkd.cluster_indexes, fields)

            fields = ['name', 'site', 'status', 'location', 'guid']
            self.table_builder(self.ui.tableClusterSearchHeads, self.splunkd.cluster_searchheads, fields)

        # Fill in Search Head Cluster tab
        self.checkSHCluster_clicked()
        if 'shc_member' in self.splunkd.roles:
            self.ui.labelSHClusterCaptain.setText(self.splunkd.shcluster_captainlabel)
            self.ui.labelSHClusterCaptainElected.setText(self.splunkd.shcluster_electedcaptain)

            fields = ['label', 'site', 'status', 'artifacts', 'host_port_pair', 'last_heartbeat', 'replication_port',
                      'restart_required', 'guid']
            self.table_builder(self.ui.tableSHClusterMembers, self.splunkd.shcluster_members, fields)

        # Fill in Resource Usage tab
        if self.splunkd.cpu_usage:
            self.ui.progressResourceUsageCPU.setValue(self.splunkd.cpu_usage)
        if self.splunkd.mem_usage:
            self.ui.progressResourceUsageMemory.setValue(self.splunkd.mem_usage)
            self.ui.labelResourceUsageMemory.setText('%.1f / %.1f GB' % (float(self.splunkd.mem_used) / 1024,
                                                                         float(self.splunkd.mem) / 1024))
        if self.splunkd.swap_usage:
            # On Windows systems, the 'swap' variable is actually Commit Charge
            swap_header = 'Commit:' if 'Windows' in self.splunkd.os else 'Swap:'
            self.ui.labelResourceUsageSwapHeader.setText(swap_header)
            self.ui.progressResourceUsageSwap.setValue(self.splunkd.swap_usage)
            self.ui.labelResourceUsageSwap.setText('%.1f / %.1f GB' % (float(self.splunkd.swap_used) / 1024,
                                                                       float(self.splunkd.swap) / 1024))
        if self.splunkd.splunk_processes:
            fields = ['name', 'pid', 'parent_pid', 'cpu', 'mem', 'args']
            self.table_builder(self.ui.tableResourceUsageProcesses, self.splunkd.splunk_processes, fields)
        if self.splunkd.disk_partitions:
            fields = ['name', 'type', 'used', 'total']
            self.table_builder(self.ui.tableResourceUsageDisks, self.splunkd.disk_partitions, fields)

        # Update status bar with latest poll
        current_local = time.strftime("%m/%d/%Y %I:%M:%S %p", time.localtime())
        self.statusbar_msg("Last poll completed %s" % current_local)

    @staticmethod
    def table_builder(table, collection, fields):
        table.setRowCount(0)
        table.setRowCount(len(collection))
        table.setSortingEnabled(False)  # Fixes bug where rows don't repopulate after a sort
        row = 0
        for entry in collection:
            column = 0
            for field in fields:
                table.setItem(row, column, QtGui.QTableWidgetItem())
                table.item(row, column).setText(entry[field])
                column += 1
            row += 1
        table.setSortingEnabled(True)  # Fixes bug where rows don't repopulate after a sort

    # Qt slots
    def actionBuildMisnersplunktoolConf_triggered(self):
        """File > Configuration > Build misnersplunktool.conf"""
        filename = config_file.replace('/', '\\')
        message = "This will replace '%s' with defaults. Are you sure?" % filename
        if self.question_msg_yesno(message):
            try:
                with open(config_file, 'w') as f:
                    f.write(CONFIG_DEFAULT)
            except:
                self.warning_msg("Unable to write default configuration to '%s'" % filename)

    def actionSaveSplunkInstanceCredentials_triggered(self):
        """File > Configuration > Save Splunk Instance Credentials"""
        filename = config_file.replace('/', '\\')
        address = self.ui.comboAddress.strip()
        username = self.ui.editUsername.strip()
        password = self.ui.editPassword.strip()
        section = '[splunkd::%s]' % address
        try:
            if not config.has_section(section):
                config.add_section(section)
            config.set(section, 'username', username)
            config.set(section, 'password', password)
            with open(config_file, 'wb') as f:
                config.write(f)
        except:
            self.warning_msg("Unable to add Splunk instance credentials to '%s'" % filename)

    def actionHelp_triggered(self):
        """Help > Help dialog box"""
        QtGui.QMessageBox.about(self, "Help", HELP_TEXT)

    def actionAbout_triggered(self):
        """Help > About dialog box"""
        try:
            with open('LICENSE.txt', 'r') as f:
                license = f.read()
        except:
            license = "LICENSE.txt file missing"

        dialog = QtGui.QMessageBox(self)
        dialog.setIconPixmap(':/favorites.png')
        dialog.setWindowTitle("About")
        dialog.setText(ABOUT_TEXT % __version__)
        dialog.setDetailedText(license)
        dialog.exec_()

    def buttonToggle_clicked(self):
        """Toggle the Connect/Disconnect button"""
        try:
            self.splunkd
        except AttributeError:
            self.connect()
        else:
            self.disconnect()

    def comboAddress_activated(self):
        """Select a hostname configured in misnersplunktool.conf, and fill in the username and password if available"""
        section = 'splunkd::%s' % self.ui.comboAddress.currentText()
        if config.has_option(section, 'username'):
            self.ui.editUsername.setText(config.get(section, 'username'))
        if config.has_option(section, 'password'):
            self.ui.editPassword.setText(config.get(section, 'password'))

    def actionRestartSplunkd_clicked(self):
        """Restart splunkd process"""
        # Check connection with splunkd
        try:
            self.splunkd.service.settings
        except binding.AuthenticationError:
            self.disconnect()
            self.critical_msg('Splunk connection reset')
            return

        # Restart splunkd
        try:
            message = "Are you sure you want to restart splunkd on '%s'?" % self.splunkd.host
            if self.question_msg_yesno(message):
                self.splunkd.service.restart()
                self.disconnect()
        except:
            self.critical_msg("Error while attempting to restart splunkd")

    def actionRefreshConfigurations_clicked(self):
        """Refresh configurations, working similar to the web port's /debug/refresh endpoint"""
        # Check connection with splunkd
        try:
            self.splunkd.service.settings
        except binding.AuthenticationError:
            self.disconnect()
            self.critical_msg('Splunk connection reset')
            return

        # Refresh configurations
        try:
            message = "Are you sure you want to refresh configurations on '%s'?" % self.splunkd.host
            if not self.question_msg_yesno(message):
                return
            self.statusbar_msg("Refreshing configurations...")
            output = self.splunkd.refresh_config()
            self.statusbar_msg("")
            dialog = QtGui.QMessageBox(self)
            dialog.setIcon(QtGui.QMessageBox.Information)
            dialog.setWindowTitle("Misner Splunk Tool")
            dialog.setText("Configuration refresh complete.\n\n"
                           "See details below for reload results against each entity.")
            dialog.setDetailedText(output)
            dialog.exec_()
        except Exception, e:
            self.critical_msg("Unable to refresh configuration:\n"
                              "%s" % e)
        except:
            self.critical_msg("Unable to refresh configuration:\n"
                              "Unknown error")

    def comboConfig_activated(self):
        """Poll configuration from splunkd"""
        # Check connection with splunkd
        try:
            self.splunkd.service.settings
        except binding.AuthenticationError:
            self.disconnect()
            self.critical_msg('Splunk connection reset')
            return
        # Pull config
        filename = self.ui.comboConfig.currentText()
        self.statusbar_msg("Polling configuration values for '%s'..." % filename)
        #  Setting html to true (below) returns colors, however also 'resolves' any existing HTML within the values
        data = self.splunkd.get_configuration_kvpairs(filename, html=False)
        self.ui.editConfig.setText(data)
        self.statusbar_msg("Poll for '%s' configuration values complete" % filename)

    def buttonConfigurationMark_clicked(self):
        """Highlight matching text in configuration"""
        cursor = self.ui.editConfig.textCursor()
        format = QtGui.QTextCharFormat()
        format.setForeground(QtGui.QBrush(QtGui.QColor('red')))
        pattern = self.ui.editConfigurationFind.text()
        regex = QtCore.QRegExp(pattern)
        pos = 0
        index = regex.indexIn(self.ui.editConfig.toPlainText(), pos)
        while index != -1:
            cursor.setPosition(index)
            cursor.movePosition(QtGui.QTextCursor.NextCharacter, QtGui.QTextCursor.KeepAnchor, len(pattern))
            cursor.mergeCharFormat(format)
            pos = index + regex.matchedLength()
            index = regex.indexIn(self.ui.editConfig.toPlainText(), pos)

    def buttonConfigurationClear_clicked(self):
        """Clear highlighted text in configuration"""
        self.ui.editConfig.setTextColor(QtGui.QColor('black'))
        #self.ui.editConfig.setStyleSheet('color: black;')
        #cursor = self.ui.editConfig.textCursor()
        #format = QtGui.QTextCharFormat()
        #format.setForeground(QtGui.QBrush(QtGui.QColor('black')))
        #self.ui.editConfig.setCurrentCharFormat(format)

    def actionChangeDeploymentServer_clicked(self):
        """Update which Deployment Server the connected Splunk instance is a client of"""
        # Check connection with splunkd
        try:
            self.splunkd.service.settings
        except binding.AuthenticationError:
            self.disconnect()
            self.critical_msg('Splunk connection reset')
            return

        # Change deployment server
        message = "Enter new Deployment Server URI (i.e. 1.2.3.4:8089)"
        new_deployment_server, dialog_not_cancelled = QtGui.QInputDialog.getText(self, "Misner Splunk Tool", message)
        if dialog_not_cancelled:  # OK was pushed on dialog
            if new_deployment_server:  # Deployment server specified in Input Dialog
                disabled = '0'
                targeturi = new_deployment_server
                message = "Perform the following actions?\n" \
                          "\n" \
                          "- Enable deployment client.\n" \
                          "- Set deployment server URI to '%s'.\n" \
                          "- Restart splunkd on '%s'"\
                          % (new_deployment_server, self.splunkd.host)
            else:  # Deployment server blank in Input Dialog
                disabled = '1'
                targeturi = ''
                message = "Perform the following actions?\n" \
                          "\n" \
                          "- Disable deployment client.\n" \
                          "- Set deployment server URI to blank.\n" \
                          "- Restart splunkd on '%s'"\
                          % self.splunkd.host

            if self.question_msg_yesno(message):
                try:
                    uri = '/services/properties/deploymentclient/target-broker:deploymentServer'
                    body_input = "disabled=%s&targetUri=%s" % (disabled, targeturi)
                    result = self.splunkd.rest_call(uri, method='POST', body_input=body_input)
                    result_type = result['response']['messages']['msg']['type']
                    result_msg = result['response']['messages']['msg']['$text']

                    if result_type != 'INFO':
                        message = "Error while attempting to modify deployment server URI:\n" \
                                  "%s" % result_msg
                        self.critical_msg(message)
                        return
                    elif 'modified 0 key' in result_msg:
                        message = "Splunkd reports no changes made to deployment server URI:\n" \
                                  "%s" % result_msg
                        self.critical_msg(message)
                        return

                    self.splunkd.service.restart()
                    self.disconnect()
                    self.statusbar_msg('Disconnected while splunkd is restarting, try reconnecting in a few moments')
                except:
                    self.critical_msg("Error while attempting to restart splunkd")
            else:
                self.poll()

    def checkCluster_clicked(self):
        """Returns any clicked check boxes in Indexer Cluster tab back to actual values"""
        self.ui.checkClusterDataSearchable.setChecked(self.splunkd.cluster_alldatasearchable)
        self.ui.checkClusterSearchFactorMet.setChecked(self.splunkd.cluster_searchfactormet)
        self.ui.checkClusterReplicationFactorMet.setChecked(self.splunkd.cluster_replicationfactormet)
        self.ui.checkClusterMaintenanceMode.setChecked(self.splunkd.cluster_maintenance)
        self.ui.checkClusterRollingRestartFlag.setChecked(self.splunkd.cluster_rollingrestart)
        self.ui.checkClusterInitializedFlag.setChecked(self.splunkd.cluster_initialized)
        self.ui.checkClusterServiceReadyFlag.setChecked(self.splunkd.cluster_serviceready)
        self.ui.checkClusterIndexingReadyFlag.setChecked(self.splunkd.cluster_indexingready)

    def checkSHCluster_clicked(self):
        """Returns any clicked check boxes in Search Head Cluster tab back to actual values"""
        self.ui.checkSHClusterInitializedFlag.setChecked(self.splunkd.shcluster_initialized)
        self.ui.checkSHClusterServiceReadyFlag.setChecked(self.splunkd.shcluster_serviceready)
        self.ui.checkSHClusterMinimumPeersJoinedFlag.setChecked(self.splunkd.shcluster_minpeersjoined)
        self.ui.checkSHClusterDynamicCaptain.setChecked(self.splunkd.shcluster_dynamiccaptain)
        self.ui.checkSHClusterRollingRestartFlag.setChecked(self.splunkd.shcluster_rollingrestart)

    def buttonRestSend_clicked(self):
        """Sends custom REST API call to splunkd"""
        # Check connection with splunkd
        try:
            self.splunkd.service.settings
        except binding.AuthenticationError:
            self.disconnect()
            self.critical_msg('Splunk connection reset')
            return

        # Send REST API call
        method = self.ui.comboRestMethod.currentText()
        combobox_text = self.ui.comboRestURI.currentText()
        uri = combobox_text
        body_input = self.ui.editRestBodyInput.text()
        parameters = {}

        try:
            if '?' in uri:
                uri, parameter_string = uri.split('?')
                for parameter in parameter_string.split('&'):
                    key, value = parameter.split('=')
                    parameters[key] = value
        except ValueError:
            self.warning_msg("Unable to parse parameters in URI, check formatting")
            return

        # Send REST API query and display results
        try:
            result = self.splunkd.rest_call(uri, method, output_format='plaintext', body_input=body_input, **parameters)
            self.ui.editRestResult.setText(result)
        except:
            return

        # Add to combobox history
        item_total = self.ui.comboRestURI.count()
        items = []
        for item in range(0, item_total):
            items.append(self.ui.comboRestURI.itemText(item))
        if combobox_text not in items:
            self.ui.comboRestURI.addItem(combobox_text)


if __name__ == '__main__':
    # Pull available configs from misnertraptool.conf
    config = ConfigParser.ConfigParser(allow_no_value=True)
    config_file = os.path.join(SCRIPT_DIR, CONFIG_FILENAME)
    if os.path.isfile(config_file):
        try:
            config.read(config_file)
        except ConfigParser.ParsingError, e:
            pass

    # PySide GUI
    app = QtGui.QApplication(sys.argv)
    window = MainWindow()

    sys.exit(app.exec_())
