"""
LD2410C Radar Monitor GUI v3
Modern UI with line graphs using pyqtgraph
"""

import sys
import re
import serial
import serial.tools.list_ports
from collections import deque
from datetime import datetime
import numpy as np

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                              QHBoxLayout, QLabel, QComboBox, QPushButton, 
                              QTextEdit, QGroupBox, QGridLayout, QSplitter)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QBrush, QPainterPath
import pyqtgraph as pg
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
            
            # Request configuration immediately on connect
            import time
            time.sleep(0.5)  # Wait for ESP32 to be ready
            self.serial_conn.write(b"GET_CONFIG\n")
            
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


class RadarArcWidget(QWidget):
    """Minimal radar arc visualization showing target distance"""
    
    def __init__(self):
        super().__init__()
        self.stationary_distance = 0
        self.moving_distance = 0
        self.presence = False
        self.setMinimumSize(400, 300)
        self.setSizePolicy(self.sizePolicy().Expanding, self.sizePolicy().Expanding)
        
    def update_data(self, presence, stat_dist, mov_dist):
        self.presence = presence
        self.stationary_distance = stat_dist
        self.moving_distance = mov_dist
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        width = self.width()
        height = self.height()
        
        # Radar origin (bottom center)
        origin_x = width // 2
        origin_y = height - 30
        
        # Max range in cm (600 cm = 6 meters)
        max_range = 600
        scale = (height - 60) / max_range
        
        # Background
        painter.fillRect(0, 0, width, height, QColor(25, 25, 35))
        
        # Draw range arcs (every 150cm)
        painter.setPen(QPen(QColor(60, 60, 80), 1))
        for distance in range(150, max_range + 1, 150):
            radius = int(distance * scale)
            painter.drawArc(origin_x - radius, origin_y - radius, 
                          radius * 2, radius * 2, 
                          30 * 16, 120 * 16)
            
            # Distance labels
            painter.setPen(QColor(100, 100, 120))
            painter.setFont(QFont('Arial', 8))
            label_x = origin_x + int(radius * math.cos(math.radians(60)))
            label_y = origin_y - int(radius * math.sin(math.radians(60)))
            painter.drawText(label_x + 5, label_y, f"{distance}cm")
            painter.setPen(QPen(QColor(60, 60, 80), 1))
        
        # Draw angle lines
        for angle in [-60, -30, 0, 30, 60]:
            rad = math.radians(angle)
            end_x = origin_x + int((height - 60) * math.sin(rad))
            end_y = origin_y - int((height - 60) * math.cos(rad))
            painter.drawLine(origin_x, origin_y, end_x, end_y)
        
        # Draw stationary target arc
        if self.presence and self.stationary_distance > 0:
            radius = int(self.stationary_distance * scale)
            painter.setPen(QPen(QColor(100, 150, 255), 4))
            painter.drawArc(origin_x - radius, origin_y - radius,
                           radius * 2, radius * 2,
                           30 * 16, 120 * 16)
            
            # Label
            painter.setFont(QFont('Arial', 9, QFont.Bold))
            painter.drawText(origin_x - 60, 20, f"Stationary: {self.stationary_distance}cm")
        
        # Draw moving target arc
        if self.presence and self.moving_distance > 0:
            radius = int(self.moving_distance * scale)
            painter.setPen(QPen(QColor(255, 100, 100), 4))
            painter.drawArc(origin_x - radius, origin_y - radius,
                           radius * 2, radius * 2,
                           30 * 16, 120 * 16)
            
            # Label
            painter.setFont(QFont('Arial', 9, QFont.Bold))
            painter.drawText(origin_x + 10, 20, f"Moving: {self.moving_distance}cm")
        
        # Draw sensor at origin
        painter.setBrush(QBrush(QColor(0, 200, 0)))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(origin_x - 4, origin_y - 4, 8, 8)
        
        # Status text
        painter.setPen(QColor(0, 255, 0) if self.presence else QColor(100, 100, 100))
        painter.setFont(QFont('Arial', 11, QFont.Bold))
        painter.drawText(10, 20, "DETECTED" if self.presence else "NO TARGET")


class RadarMonitor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.serial_thread = None
        
        # Data buffers for time plots (120 seconds at ~2 updates/sec = 240 points)
        self.max_history = 240
        self.time_data = deque(maxlen=self.max_history)
        self.detection_stat_data = deque(maxlen=self.max_history)
        self.detection_mov_data = deque(maxlen=self.max_history)
        self.photosensitive_data = deque(maxlen=self.max_history)
        self.start_time = datetime.now()
        
        # Current data
        self.moving_energy = [0] * 9
        self.stationary_energy = [0] * 9
        self.moving_sensitivity = [0] * 9
        self.stationary_sensitivity = [0] * 9
        self.current_presence = False
        self.current_stat_dist = 0
        self.current_mov_dist = 0
        
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle('LD2410C Radar Monitor v3')
        self.setGeometry(100, 100, 1400, 900)
        
        # Set dark theme
        pg.setConfigOption('background', (25, 25, 35))
        pg.setConfigOption('foreground', 'w')
        
        # Main widget
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        
        # Connection controls
        conn_group = QGroupBox("Connection")
        conn_layout = QHBoxLayout()
        
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
        conn_group.setLayout(conn_layout)
        main_layout.addWidget(conn_group)
        
        # Main content area
        content_splitter = QSplitter(Qt.Horizontal)
        
        # Left side: Graphs
        left_widget = QWidget()
        left_layout = QVBoxLayout()
        left_widget.setLayout(left_layout)
        # Radar arc visualization
        radar_group = QGroupBox("Radar Detection Range")
        radar_layout = QVBoxLayout()
        radar_layout.setContentsMargins(5, 5, 5, 5)
        self.radar_arc = RadarArcWidget()
        radar_layout.addWidget(self.radar_arc)
        radar_group.setLayout(radar_layout)
        left_layout.addWidget(radar_group, stretch=2)  # Give more space to radar
        
        # Graph grid (2x2)
        graphs_widget = QWidget()
        graphs_layout = QGridLayout()
        graphs_layout.setSpacing(10)
        graphs_widget.setLayout(graphs_layout)
        
        # 1. Moving target sensitivity by distance (0-8 gates = 0-600cm)
        self.moving_plot = pg.PlotWidget(title="Moving Target Energy vs Distance")
        self.moving_plot.setLabel('left', 'Sensitivity / Energy', units='')
        self.moving_plot.setLabel('bottom', 'Distance', units='cm')
        self.moving_plot.setXRange(0, 600)
        self.moving_plot.setYRange(0, 100)
        self.moving_plot.showGrid(x=True, y=True, alpha=0.3)
        self.moving_sensitivity_curve = self.moving_plot.plot(pen=pg.mkPen(color=(255, 255, 0), width=2, style=pg.QtCore.Qt.DashLine), name='Sensitivity')
        self.moving_energy_curve = self.moving_plot.plot(pen=pg.mkPen(color=(255, 100, 100), width=3), name='Energy')
        self.moving_plot.addLegend()
        graphs_layout.addWidget(self.moving_plot, 0, 0)
        
        # 2. Stationary target sensitivity by distance
        self.static_plot = pg.PlotWidget(title="Stationary Target Energy vs Distance")
        self.static_plot.setLabel('left', 'Sensitivity / Energy', units='')
        self.static_plot.setLabel('bottom', 'Distance', units='cm')
        self.static_plot.setXRange(0, 600)
        self.static_plot.setYRange(0, 100)
        self.static_plot.showGrid(x=True, y=True, alpha=0.3)
        self.static_sensitivity_curve = self.static_plot.plot(pen=pg.mkPen(color=(255, 255, 0), width=2, style=pg.QtCore.Qt.DashLine), name='Sensitivity')
        self.static_energy_curve = self.static_plot.plot(pen=pg.mkPen(color=(100, 150, 255), width=3), name='Energy')
        self.static_plot.addLegend()
        graphs_layout.addWidget(self.static_plot, 0, 1)
        
        # 3. Detection range over time
        self.range_plot = pg.PlotWidget(title="Detection Range (Last 120s)")
        self.range_plot.setLabel('left', 'Distance', units='cm')
        self.range_plot.setLabel('bottom', 'Time', units='s')
        self.range_plot.showGrid(x=True, y=True, alpha=0.3)
        self.range_plot.enableAutoRange(axis='y')
        self.range_stat_curve = self.range_plot.plot(pen=pg.mkPen(color=(100, 150, 255), width=2), name='Stationary')
        self.range_mov_curve = self.range_plot.plot(pen=pg.mkPen(color=(255, 100, 100), width=2), name='Moving')
        self.range_plot.addLegend()
        graphs_layout.addWidget(self.range_plot, 1, 0)
        
        # 4. Photosensitive value over time (placeholder - will be 0 until we parse it)
        self.photo_plot = pg.PlotWidget(title="Photosensitive Value (Last 120s)")
        self.photo_plot.setLabel('left', 'Value', units='')
        self.photo_plot.setLabel('bottom', 'Time', units='s')
        self.photo_plot.showGrid(x=True, y=True, alpha=0.3)
        self.photo_plot.setYRange(-10, 270)  # Start with reasonable range for 0-255 values
        self.photo_curve = self.photo_plot.plot(pen=pg.mkPen(color=(150, 255, 150), width=2))
        graphs_layout.addWidget(self.photo_plot, 1, 1)
        
        left_layout.addWidget(graphs_widget, stretch=3)  # Graphs get more space
        
        # Right side: Info and log
        right_widget = QWidget()
        right_layout = QVBoxLayout()
        right_widget.setLayout(right_layout)
        
        # Current status
        status_group = QGroupBox("Current Status")
        status_layout = QGridLayout()
        
        self.presence_label = QLabel("NO TARGET")
        self.presence_label.setStyleSheet("font-size: 14pt; font-weight: bold; color: gray;")
        status_layout.addWidget(QLabel("Presence:"), 0, 0)
        status_layout.addWidget(self.presence_label, 0, 1, 1, 2)
        
        self.stat_label = QLabel("--")
        self.mov_label = QLabel("--")
        status_layout.addWidget(QLabel("Stationary:"), 1, 0)
        status_layout.addWidget(self.stat_label, 1, 1)
        status_layout.addWidget(QLabel("Moving:"), 2, 0)
        status_layout.addWidget(self.mov_label, 2, 1)
        
        status_group.setLayout(status_layout)
        right_layout.addWidget(status_group)
        
        # Log
        log_group = QGroupBox("Data Log")
        log_layout = QVBoxLayout()
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(400)
        log_layout.addWidget(self.log_text)
        
        clear_btn = QPushButton("Clear Log")
        clear_btn.clicked.connect(self.log_text.clear)
        log_layout.addWidget(clear_btn)
        
        log_group.setLayout(log_layout)
        right_layout.addWidget(log_group)
        
        # Add to splitter
        content_splitter.addWidget(left_widget)
        content_splitter.addWidget(right_widget)
        content_splitter.setSizes([1000, 400])
        
        main_layout.addWidget(content_splitter)
        
    def refresh_ports(self):
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.addItem(f"{port.device} - {port.description}")
            
    def toggle_connection(self):
        if self.serial_thread is None or not self.serial_thread.running:
            port_text = self.port_combo.currentText()
            if port_text:
                port = port_text.split(' - ')[0]
                self.serial_thread = SerialReader(port)
                self.serial_thread.data_received.connect(self.process_serial_data)
                self.serial_thread.start()
                self.connect_btn.setText("Disconnect")
                self.log_text.append(f"Connected to {port}")
                self.start_time = datetime.now()
        else:
            self.serial_thread.stop()
            self.serial_thread.wait()
            self.connect_btn.setText("Connect")
            self.log_text.append("Disconnected")
            
    def process_serial_data(self, line):
        # Only log important lines to avoid spam
        if any(x in line for x in ["Presence:", "GATES_", "Version:", "Max gate:", "Motion:", "Stationary:"]):
            self.log_text.append(line)
            # Auto-scroll and limit
            cursor = self.log_text.textCursor()
            cursor.movePosition(cursor.End)
            self.log_text.setTextCursor(cursor)
            
            # Limit log size
            if self.log_text.document().blockCount() > 500:
                cursor.movePosition(cursor.Start)
                cursor.movePosition(cursor.Down, cursor.KeepAnchor, 100)
                cursor.removeSelectedText()
        
        # Parse detection data
        if "Presence:" in line:
            self.parse_detection(line)
        
        # Parse gate energy data
        if "GATES_MOV:" in line:
            self.parse_gate_data(line)
        
        # Parse sensitivity configuration
        if "SENSITIVITY_" in line or "Gate" in line or "Sensitivity" in line:
            self.parse_sensitivity(line)
            
    def parse_detection(self, line):
        # Format: "Presence: YES | Stationary: 38cm E:100 | Moving: 30cm E:100"
        self.current_presence = 'YES' in line
        
        # Parse stationary
        stat_match = re.search(r'Stationary:\s*(\d+)cm\s*E:(\d+)', line)
        if stat_match:
            self.current_stat_dist = int(stat_match.group(1))
        else:
            self.current_stat_dist = 0
            
        # Parse moving
        mov_match = re.search(r'Moving:\s*(\d+)cm\s*E:(\d+)', line)
        if mov_match:
            self.current_mov_dist = int(mov_match.group(1))
        else:
            self.current_mov_dist = 0
        # Update time plot data
        elapsed = (datetime.now() - self.start_time).total_seconds()
        self.time_data.append(elapsed)
        
        # Store stationary and moving distances separately
        self.detection_stat_data.append(self.current_stat_dist)
        self.detection_mov_data.append(self.current_mov_dist)
        
        # Photosensitive placeholder (0 for now)
        self.photosensitive_data.append(0)
        
        self.update_displays()
    
    def parse_gate_data(self, line):
        # Format: "GATES_MOV:0,1,2,3,4,5,6,7,8 | GATES_STAT:0,1,2,3,4,5,6,7,8"
        mov_match = re.search(r'GATES_MOV:([\d,]+)', line)
        stat_match = re.search(r'GATES_STAT:([\d,]+)', line)
        
        if mov_match:
            mov_values = [int(x) for x in mov_match.group(1).split(',')]
            if len(mov_values) == 9:
                self.moving_energy = mov_values
                
        if stat_match:
            stat_values = [int(x) for x in stat_match.group(1).split(',')]
            if len(stat_values) == 9:
                self.stationary_energy = stat_values
        
        self.update_gate_plots()
        
    def update_displays(self):
        # Update radar arc
        self.radar_arc.update_data(self.current_presence, self.current_stat_dist, self.current_mov_dist)
        
        # Update status labels
        if self.current_presence:
            self.presence_label.setText("TARGET DETECTED")
            self.presence_label.setStyleSheet("font-size: 14pt; font-weight: bold; color: #00ff00;")
        else:
            self.presence_label.setText("NO TARGET")
            self.presence_label.setStyleSheet("font-size: 14pt; font-weight: bold; color: gray;")
        
        self.stat_label.setText(f"{self.current_stat_dist} cm" if self.current_stat_dist > 0 else "--")
        self.mov_label.setText(f"{self.current_mov_dist} cm" if self.current_mov_dist > 0 else "--")
        
        # Update time plots
        if len(self.time_data) > 0:
            times = np.array(self.time_data)
            
            # Detection range plot (separate curves for stationary and moving)
            self.range_stat_curve.setData(times, np.array(self.detection_stat_data))
            self.range_mov_curve.setData(times, np.array(self.detection_mov_data))
            
            # Photosensitive plot
            self.photo_curve.setData(times, self.photosensitive_data)
            
    def parse_sensitivity(self, line):
        # Parse new format: "SENSITIVITY_MOTION:0:36" or "SENSITIVITY_STATIC:0:0"
        if line.startswith("SENSITIVITY_MOTION:"):
            parts = line.split(":")
            if len(parts) == 3:
                gate = int(parts[1])
                value = int(parts[2])
                if gate < 9:
                    self.moving_sensitivity[gate] = value
                    if gate == 8:
                        self.update_sensitivity_plots()
        elif line.startswith("SENSITIVITY_STATIC:"):
            parts = line.split(":")
            if len(parts) == 3:
                gate = int(parts[1])
                value = int(parts[2])
                if gate < 9:
                    self.stationary_sensitivity[gate] = value
                    if gate == 8:
                        self.update_sensitivity_plots()
        
        # Also parse old motion/stationary sensitivity format for backward compat
        elif "Gate" in line and ":" in line:
            match = re.search(r'Gate\s+(\d+):\s*(\d+)', line)
            if match:
                gate = int(match.group(1))
                value = int(match.group(2))
                if gate < 9:
                    if hasattr(self, '_parsing_motion_sensitivity') and self._parsing_motion_sensitivity:
                        self.moving_sensitivity[gate] = value
                        if gate == 8:
                            self._parsing_motion_sensitivity = False
                            self.update_sensitivity_plots()
                    elif hasattr(self, '_parsing_stationary_sensitivity') and self._parsing_stationary_sensitivity:
                        self.stationary_sensitivity[gate] = value
                        if gate == 8:
                            self._parsing_stationary_sensitivity = False
                            self.update_sensitivity_plots()
        
        # Set flags when we see the headers
        if "Motion Sensitivity" in line:
            self._parsing_motion_sensitivity = True
            self._parsing_stationary_sensitivity = False
        elif "Stationary Sensitivity" in line:
            self._parsing_motion_sensitivity = False
            self._parsing_stationary_sensitivity = True
    
    def update_sensitivity_plots(self):
        # X-axis: gate distances (0, 75, 150, 225, 300, 375, 450, 525, 600 cm)
        x = np.array([i * 75 for i in range(9)])
        
        # Update moving sensitivity baseline (gray dashed line)
        self.moving_sensitivity_curve.setData(x, self.moving_sensitivity)
        
        # Update stationary sensitivity baseline (gray dashed line)
        self.static_sensitivity_curve.setData(x, self.stationary_sensitivity)
    
    def update_gate_plots(self):
        # X-axis: gate distances
        x = np.array([i * 75 for i in range(9)])
        
        # Update real-time energy (colored solid lines)
        self.moving_energy_curve.setData(x, self.moving_energy)
        self.static_energy_curve.setData(x, self.stationary_energy)
        
    def closeEvent(self, event):
        if self.serial_thread and self.serial_thread.running:
            self.serial_thread.stop()
            self.serial_thread.wait()
        event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # Set dark theme stylesheet
    app.setStyleSheet("""
        QMainWindow, QWidget {
            background-color: #1a1a24;
            color: #e0e0e0;
        }
        QGroupBox {
            border: 1px solid #3c3c50;
            border-radius: 5px;
            margin-top: 10px;
            padding-top: 10px;
            font-weight: bold;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 5px;
            color: #a0a0b0;
        }
        QPushButton {
            background-color: #2d2d3d;
            border: 1px solid #4c4c60;
            border-radius: 3px;
            padding: 5px 15px;
            color: #e0e0e0;
        }
        QPushButton:hover {
            background-color: #3d3d4d;
        }
        QPushButton:pressed {
            background-color: #1d1d2d;
        }
        QComboBox {
            background-color: #2d2d3d;
            border: 1px solid #4c4c60;
            border-radius: 3px;
            padding: 3px;
            color: #e0e0e0;
        }
        QTextEdit {
            background-color: #1e1e28;
            border: 1px solid #3c3c50;
            border-radius: 3px;
            color: #d0d0d0;
            font-family: Consolas, monospace;
            font-size: 9pt;
        }
        QLabel {
            color: #d0d0d0;
        }
    """)
    
    monitor = RadarMonitor()
    monitor.show()
    sys.exit(app.exec_())
