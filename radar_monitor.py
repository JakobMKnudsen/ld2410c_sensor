"""
LD2410C Radar Monitor GUI
Connects to ESP32-C6 via serial and displays radar data with visualization
"""

import sys
import re
import serial
import serial.tools.list_ports
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                              QHBoxLayout, QLabel, QComboBox, QPushButton, 
                              QTextEdit, QGroupBox, QGridLayout, QSplitter)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QBrush
import math


class SerialReader(QThread):
    """Thread for reading serial data"""
    data_received = pyqtSignal(str)
    
    def __init__(self, port, baudrate=115200):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.running = False
        self.serial_conn = None
        
    def run(self):
        try:
            self.serial_conn = serial.Serial(self.port, self.baudrate, timeout=1)
            self.running = True
            
            while self.running:
                if self.serial_conn.in_waiting:
                    try:
                        line = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                        if line:
                            self.data_received.emit(line)
                    except Exception as e:
                        self.data_received.emit(f"Read error: {e}")
        except Exception as e:
            self.data_received.emit(f"Serial error: {e}")
            
    def stop(self):
        self.running = False
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()


class GateEnergyWidget(QWidget):
    """Widget to display per-gate energy levels as a bar graph"""
    
    def __init__(self):
        super().__init__()
        self.moving_energy = [0] * 9
        self.stationary_energy = [0] * 9
        self.setMinimumSize(600, 350)
        self.setSizePolicy(self.sizePolicy().Expanding, self.sizePolicy().Expanding)
        
    def update_data(self, moving, stationary):
        self.moving_energy = moving
        self.stationary_energy = stationary
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        width = self.width()
        height = self.height()
        
        # Background
        painter.fillRect(0, 0, width, height, QColor(20, 20, 30))
        
        # Title
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont('Arial', 12, QFont.Bold))
        painter.drawText(10, 25, "Gate Energy Levels (0-8 gates, ~75cm per gate)")
        
        # Graph area with more bottom margin for labels
        graph_x = 50
        graph_y = 50
        graph_width = width - 100
        graph_height = height - 100
        
        # Draw grid lines
        painter.setPen(QPen(QColor(60, 60, 80), 1))
        for i in range(0, 101, 20):
            y = graph_y + graph_height - (i * graph_height // 100)
            painter.drawLine(graph_x, y, graph_x + graph_width, y)
            painter.setPen(QColor(100, 100, 120))
            painter.setFont(QFont('Arial', 8))
            painter.drawText(graph_x - 30, y + 4, f"{i}")
            painter.setPen(QPen(QColor(60, 60, 80), 1))
        
        # Draw axes
        painter.setPen(QPen(QColor(150, 150, 170), 2))
        painter.drawLine(graph_x, graph_y, graph_x, graph_y + graph_height)
        painter.drawLine(graph_x, graph_y + graph_height, graph_x + graph_width, graph_y + graph_height)
        
        # Bar width
        bar_width = graph_width // 20
        gate_spacing = graph_width // 9
        
        # Draw bars for each gate
        for i in range(9):
            x = graph_x + (i * gate_spacing) + gate_spacing // 2
            
            # Stationary (blue)
            stat_val = self.stationary_energy[i]
            stat_height = int((stat_val / 100.0) * graph_height)
            painter.fillRect(x - bar_width - 2, graph_y + graph_height - stat_height,
                           bar_width, stat_height, QColor(100, 150, 255))
            
            # Moving (red)
            mov_val = self.moving_energy[i]
            mov_height = int((mov_val / 100.0) * graph_height)
            painter.fillRect(x + 2, graph_y + graph_height - mov_height,
                           bar_width, mov_height, QColor(255, 100, 100))
            
            # Gate label
            painter.setPen(QColor(200, 200, 220))
            painter.setFont(QFont('Arial', 10, QFont.Bold))
            painter.drawText(x - 10, graph_y + graph_height + 20, f"G{i}")
            
            # Distance label (~75cm per gate)
            distance_cm = i * 75
            painter.setFont(QFont('Arial', 8))
            painter.drawText(x - 18, graph_y + graph_height + 38, f"{distance_cm}cm")
        
        # Legend
        painter.fillRect(width - 180, 10, 15, 15, QColor(100, 150, 255))
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont('Arial', 9))
        painter.drawText(width - 160, 22, "Stationary")
        
        painter.fillRect(width - 180, 30, 15, 15, QColor(255, 100, 100))
        painter.drawText(width - 160, 42, "Moving")


class RadarWidget(QWidget):
    """Custom widget to draw radar visualization"""
    
    def __init__(self):
        super().__init__()
        self.stationary_distance = 0
        self.stationary_energy = 0
        self.moving_distance = 0
        self.moving_energy = 0
        self.presence = False
        self.setMinimumSize(500, 400)
        self.setSizePolicy(self.sizePolicy().Expanding, self.sizePolicy().Expanding)
        
    def update_data(self, presence, stat_dist, stat_energy, mov_dist, mov_energy):
        self.presence = presence
        self.stationary_distance = stat_dist
        self.stationary_energy = stat_energy
        self.moving_distance = mov_dist
        self.moving_energy = mov_energy
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Get widget dimensions
        width = self.width()
        height = self.height()
        
        # Radar origin (bottom center)
        origin_x = width // 2
        origin_y = height - 50
        
        # Max range in cm (6 meters = 600 cm)
        max_range = 600
        scale = (height - 100) / max_range
        
        # Draw background
        painter.fillRect(0, 0, width, height, QColor(20, 20, 30))
        
        # Draw range arcs (every 100cm)
        painter.setPen(QPen(QColor(60, 60, 80), 1))
        for distance in range(100, max_range + 1, 100):
            radius = int(distance * scale)
            # Draw arc from -60° to +60° (120° total)
            painter.drawArc(origin_x - radius, origin_y - radius, 
                          radius * 2, radius * 2, 
                          30 * 16, 120 * 16)  # Qt uses 1/16th degree units
            
            # Draw distance labels
            painter.setPen(QColor(100, 100, 120))
            painter.setFont(QFont('Arial', 8))
            label_x = origin_x + int(radius * math.cos(math.radians(60)))
            label_y = origin_y - int(radius * math.sin(math.radians(60)))
            painter.drawText(label_x + 5, label_y, f"{distance}cm")
        
        # Draw angle lines (every 30°)
        painter.setPen(QPen(QColor(60, 60, 80), 1))
        for angle in [-60, -30, 0, 30, 60]:
            rad = math.radians(angle)
            end_x = origin_x + int((height - 100) * math.sin(rad))
            end_y = origin_y - int((height - 100) * math.cos(rad))
            painter.drawLine(origin_x, origin_y, end_x, end_y)
        
        # Draw coverage area fill
        painter.setBrush(QBrush(QColor(30, 40, 60, 50)))
        painter.setPen(Qt.NoPen)
        painter.drawPie(origin_x - (height - 100), origin_y - (height - 100),
                       (height - 100) * 2, (height - 100) * 2,
                       30 * 16, 120 * 16)
        
        # Draw stationary target
        if self.presence and self.stationary_distance > 0:
            radius = int(self.stationary_distance * scale)
            # Draw as a blue arc
            painter.setBrush(QBrush(QColor(100, 150, 255, 150)))
            painter.setPen(QPen(QColor(100, 150, 255), 3))
            painter.drawPie(origin_x - radius, origin_y - radius,
                           radius * 2, radius * 2,
                           30 * 16, 120 * 16)
            
            # Label
            painter.setPen(QColor(150, 200, 255))
            painter.setFont(QFont('Arial', 10, QFont.Bold))
            painter.drawText(origin_x - 50, origin_y - radius - 10,
                           f"Stationary: {self.stationary_distance}cm")
        
        # Draw moving target
        if self.presence and self.moving_distance > 0:
            radius = int(self.moving_distance * scale)
            # Draw as a red arc
            painter.setBrush(QBrush(QColor(255, 100, 100, 150)))
            painter.setPen(QPen(QColor(255, 100, 100), 3))
            painter.drawPie(origin_x - radius, origin_y - radius,
                           radius * 2, radius * 2,
                           30 * 16, 120 * 16)
            
            # Label
            painter.setPen(QColor(255, 150, 150))
            painter.setFont(QFont('Arial', 10, QFont.Bold))
            painter.drawText(origin_x + 10, origin_y - radius - 10,
                           f"Moving: {self.moving_distance}cm")
        
        # Draw radar sensor at origin
        painter.setBrush(QBrush(QColor(0, 255, 0)))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(origin_x - 5, origin_y - 5, 10, 10)
        
        # Draw status text
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont('Arial', 12, QFont.Bold))
        status = "TARGET DETECTED" if self.presence else "NO TARGET"
        color = QColor(0, 255, 0) if self.presence else QColor(150, 150, 150)
        painter.setPen(color)
        painter.drawText(10, 30, status)
        
        # Draw angle labels
        painter.setPen(QColor(150, 150, 170))
        painter.setFont(QFont('Arial', 9))
        painter.drawText(20, height - 20, "-60°")
        painter.drawText(width // 2 - 10, height - 20, "0°")
        painter.drawText(width - 50, height - 20, "+60°")


class RadarMonitor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.serial_thread = None
        self.config_data = {}
        self.current_data = {
            'presence': False,
            'stat_dist': 0,
            'stat_energy': 0,
            'mov_dist': 0,
            'mov_energy': 0
        }
        self.gate_data = {
            'moving': [0] * 9,
            'stationary': [0] * 9
        }
        
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle('LD2410C Radar Monitor')
        self.setGeometry(100, 100, 1400, 900)
        self.setMinimumSize(1200, 800)
        
        # Main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        
        # Connection controls
        conn_group = QGroupBox("Connection")
        conn_layout = QHBoxLayout()
        conn_group.setLayout(conn_layout)
        
        self.port_combo = QComboBox()
        self.refresh_ports()
        conn_layout.addWidget(QLabel("Port:"))
        conn_layout.addWidget(self.port_combo)
        
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        conn_layout.addWidget(self.refresh_btn)
        
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connection)
        conn_layout.addWidget(self.connect_btn)
        
        conn_layout.addStretch()
        main_layout.addWidget(conn_group)
        
        # Splitter for main content
        splitter = QSplitter(Qt.Horizontal)
        
        # Left side: Radar visualization
        left_widget = QWidget()
        left_layout = QVBoxLayout()
        left_widget.setLayout(left_layout)
        
        self.radar_widget = RadarWidget()
        left_layout.addWidget(self.radar_widget)
        
        # Gate energy graph
        gate_group = QGroupBox("Gate Energy Levels (Engineering Mode)")
        gate_layout = QVBoxLayout()
        gate_layout.setContentsMargins(5, 5, 5, 5)
        gate_group.setLayout(gate_layout)
        
        self.gate_widget = GateEnergyWidget()
        gate_layout.addWidget(self.gate_widget)
        
        left_layout.addWidget(gate_group, stretch=1)
        
        # Current detection info
        detect_group = QGroupBox("Current Detection")
        detect_layout = QGridLayout()
        detect_group.setLayout(detect_layout)
        
        self.presence_label = QLabel("NO TARGET")
        self.presence_label.setStyleSheet("font-size: 14pt; font-weight: bold;")
        detect_layout.addWidget(QLabel("Presence:"), 0, 0)
        detect_layout.addWidget(self.presence_label, 0, 1)
        
        self.stat_dist_label = QLabel("-- cm")
        self.stat_energy_label = QLabel("--")
        detect_layout.addWidget(QLabel("Stationary Distance:"), 1, 0)
        detect_layout.addWidget(self.stat_dist_label, 1, 1)
        detect_layout.addWidget(QLabel("Energy:"), 1, 2)
        detect_layout.addWidget(self.stat_energy_label, 1, 3)
        
        self.mov_dist_label = QLabel("-- cm")
        self.mov_energy_label = QLabel("--")
        detect_layout.addWidget(QLabel("Moving Distance:"), 2, 0)
        detect_layout.addWidget(self.mov_dist_label, 2, 1)
        detect_layout.addWidget(QLabel("Energy:"), 2, 2)
        detect_layout.addWidget(self.mov_energy_label, 2, 3)
        
        left_layout.addWidget(detect_group)
        
        # Right side: Configuration and Log
        right_widget = QWidget()
        right_layout = QVBoxLayout()
        right_widget.setLayout(right_layout)
        
        # Configuration display
        config_group = QGroupBox("Sensor Configuration")
        config_layout = QGridLayout()
        config_group.setLayout(config_layout)
        config_group.setMaximumHeight(250)
        
        self.config_text = QTextEdit()
        self.config_text.setReadOnly(True)
        self.config_text.setMaximumHeight(200)
        config_layout.addWidget(self.config_text, 0, 0)
        
        right_layout.addWidget(config_group)
        
        # Data log
        log_group = QGroupBox("Data Log")
        log_layout = QVBoxLayout()
        log_group.setLayout(log_layout)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        # setMaximumBlockCount doesn't exist in QTextEdit, we'll manage size manually
        log_layout.addWidget(self.log_text)
        
        clear_log_btn = QPushButton("Clear Log")
        clear_log_btn.clicked.connect(self.log_text.clear)
        log_layout.addWidget(clear_log_btn)
        
        right_layout.addWidget(log_group)
        
        # Add to splitter
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([800, 600])
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        
        main_layout.addWidget(splitter)
        
    def refresh_ports(self):
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.addItem(f"{port.device} - {port.description}")
            
    def toggle_connection(self):
        if self.serial_thread is None or not self.serial_thread.running:
            # Connect
            port_text = self.port_combo.currentText()
            if port_text:
                port = port_text.split(' - ')[0]
                self.serial_thread = SerialReader(port)
                self.serial_thread.data_received.connect(self.process_serial_data)
                self.serial_thread.start()
                self.connect_btn.setText("Disconnect")
                self.log_text.append(f"Connected to {port}")
        else:
            # Disconnect
            self.serial_thread.stop()
            self.serial_thread.wait()
            self.connect_btn.setText("Connect")
            self.log_text.append("Disconnected")
            
    def process_serial_data(self, line):
        # Add to log
        self.log_text.append(line)
        
        # Parse configuration data
        if "Max gate:" in line:
            match = re.search(r"Max gate:\s*(\d+)", line)
            if match:
                self.config_data['max_gate'] = match.group(1)
                self.update_config_display()
        elif "Max moving gate:" in line:
            match = re.search(r"Max moving gate:\s*(\d+)", line)
            if match:
                self.config_data['max_moving_gate'] = match.group(1)
                self.update_config_display()
        elif "Max stationary gate:" in line:
            match = re.search(r"Max stationary gate:\s*(\d+)", line)
            if match:
                self.config_data['max_stationary_gate'] = match.group(1)
                self.update_config_display()
        elif "Sensor idle time:" in line:
            match = re.search(r"Sensor idle time:\s*(\d+)", line)
            if match:
                self.config_data['idle_time'] = match.group(1)
                self.update_config_display()
        elif "firmware version:" in line or "Version:" in line:
            self.config_data['firmware'] = line.split(':')[1].strip()
            self.update_config_display()
            
        # Parse detection data
        if "Presence:" in line:
            self.parse_detection(line)
        
        # Parse gate energy data
        if "GATES_MOV:" in line:
            self.parse_gate_data(line)
            
    def parse_detection(self, line):
        # Format: "Presence: YES | Stationary: 38cm E:100 | Moving: 30cm E:100"
        self.current_data['presence'] = 'YES' in line
        
        # Parse stationary
        stat_match = re.search(r'Stationary:\s*(\d+)cm\s*E:(\d+)', line)
        if stat_match:
            self.current_data['stat_dist'] = int(stat_match.group(1))
            self.current_data['stat_energy'] = int(stat_match.group(2))
        else:
            self.current_data['stat_dist'] = 0
            self.current_data['stat_energy'] = 0
            
        # Parse moving
        mov_match = re.search(r'Moving:\s*(\d+)cm\s*E:(\d+)', line)
        if mov_match:
            self.current_data['mov_dist'] = int(mov_match.group(1))
            self.current_data['mov_energy'] = int(mov_match.group(2))
        else:
            self.current_data['mov_dist'] = 0
            self.current_data['mov_energy'] = 0
            
        self.update_display()
    
    def parse_gate_data(self, line):
        # Format: "GATES_MOV:0,1,2,3,4,5,6,7,8 | GATES_STAT:0,1,2,3,4,5,6,7,8"
        mov_match = re.search(r'GATES_MOV:([\d,]+)', line)
        stat_match = re.search(r'GATES_STAT:([\d,]+)', line)
        
        if mov_match:
            mov_values = [int(x) for x in mov_match.group(1).split(',')]
            if len(mov_values) == 9:
                self.gate_data['moving'] = mov_values
                
        if stat_match:
            stat_values = [int(x) for x in stat_match.group(1).split(',')]
            if len(stat_values) == 9:
                self.gate_data['stationary'] = stat_values
        
        # Update gate visualization
        self.gate_widget.update_data(self.gate_data['moving'], self.gate_data['stationary'])
        
    def update_display(self):
        # Update radar visualization
        self.radar_widget.update_data(
            self.current_data['presence'],
            self.current_data['stat_dist'],
            self.current_data['stat_energy'],
            self.current_data['mov_dist'],
            self.current_data['mov_energy']
        )
        
        # Update text labels
        if self.current_data['presence']:
            self.presence_label.setText("TARGET DETECTED")
            self.presence_label.setStyleSheet("font-size: 14pt; font-weight: bold; color: green;")
        else:
            self.presence_label.setText("NO TARGET")
            self.presence_label.setStyleSheet("font-size: 14pt; font-weight: bold; color: gray;")
            
        self.stat_dist_label.setText(f"{self.current_data['stat_dist']} cm")
        self.stat_energy_label.setText(str(self.current_data['stat_energy']))
        self.mov_dist_label.setText(f"{self.current_data['mov_dist']} cm")
        self.mov_energy_label.setText(str(self.current_data['mov_energy']))
        
    def update_config_display(self):
        config_text = "SENSOR CONFIGURATION\n" + "="*40 + "\n"
        if 'firmware' in self.config_data:
            config_text += f"Firmware: {self.config_data['firmware']}\n"
        if 'max_gate' in self.config_data:
            config_text += f"Max Gate: {self.config_data['max_gate']}\n"
        if 'max_moving_gate' in self.config_data:
            config_text += f"Max Moving Gate: {self.config_data['max_moving_gate']}\n"
        if 'max_stationary_gate' in self.config_data:
            config_text += f"Max Stationary Gate: {self.config_data['max_stationary_gate']}\n"
        if 'idle_time' in self.config_data:
            config_text += f"Idle Time: {self.config_data['idle_time']} seconds\n"
            
        self.config_text.setText(config_text)
        
    def closeEvent(self, event):
        if self.serial_thread and self.serial_thread.running:
            self.serial_thread.stop()
            self.serial_thread.wait()
        event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    monitor = RadarMonitor()
    monitor.show()
    sys.exit(app.exec_())
