/*
 * ESP32-C6 LD2410C Radar Sensor - Complete Information Display
 * 
 * Connections for ESP32-C6:
 * LD2410 TX -> GPIO 4 (RX)
 * LD2410 RX -> GPIO 5 (TX)
 * LD2410 VCC -> 5V
 * LD2410 GND -> GND
 * 
 * USB-C used for Serial Monitor
 * 
 * Note: GPIO 24/25 are not suitable for UART on ESP32-C6
 * Use GPIO 4/5 instead (standard UART pins)
 */

#include <Arduino.h>
#include <ld2410.h>

#define MONITOR_SERIAL Serial  // USB Serial
#define RADAR_SERIAL Serial1   // Hardware UART1 on custom pins
#define RADAR_RX_PIN 4
#define RADAR_TX_PIN 5

ld2410 radar;
uint32_t lastReading = 0;
uint32_t lastConfigRead = 0;
bool configDisplayed = false;
bool engineeringMode = false;

void printSeparator() {
  MONITOR_SERIAL.println(F("===================================="));
}

void printConfiguration() {
  printSeparator();
  MONITOR_SERIAL.println(F("SENSOR CONFIGURATION:"));
  printSeparator();
  
  MONITOR_SERIAL.print(F("Max gate: "));
  MONITOR_SERIAL.println(radar.max_gate);
  
  MONITOR_SERIAL.print(F("Max moving gate: "));
  MONITOR_SERIAL.println(radar.max_moving_gate);
  
  MONITOR_SERIAL.print(F("Max stationary gate: "));
  MONITOR_SERIAL.println(radar.max_stationary_gate);
  
  MONITOR_SERIAL.print(F("Sensor idle time: "));
  MONITOR_SERIAL.print(radar.sensor_idle_time);
  MONITOR_SERIAL.println(F(" seconds"));
  
  MONITOR_SERIAL.println(F("\nMotion Sensitivity (per gate):"));
  for(int i = 0; i < 9; i++) {
    MONITOR_SERIAL.print(F("  Gate "));
    MONITOR_SERIAL.print(i);
    MONITOR_SERIAL.print(F(": "));
    MONITOR_SERIAL.println(radar.motion_sensitivity[i]);
  }
  
  MONITOR_SERIAL.println(F("\nStationary Sensitivity (per gate):"));
  for(int i = 0; i < 9; i++) {
    MONITOR_SERIAL.print(F("  Gate "));
    MONITOR_SERIAL.print(i);
    MONITOR_SERIAL.print(F(": "));
    MONITOR_SERIAL.println(radar.stationary_sensitivity[i]);
  }
  printSeparator();
}
void printDetectionInfo() {
  MONITOR_SERIAL.print(F("Presence: "));
  
  if(radar.presenceDetected()) {
    MONITOR_SERIAL.print(F("YES"));
    
    if(radar.stationaryTargetDetected()) {
      MONITOR_SERIAL.print(F(" | Stationary: "));
      MONITOR_SERIAL.print(radar.stationaryTargetDistance());
      MONITOR_SERIAL.print(F("cm E:"));
      MONITOR_SERIAL.print(radar.stationaryTargetEnergy());
    }
    
    if(radar.movingTargetDetected()) {
      MONITOR_SERIAL.print(F(" | Moving: "));
      MONITOR_SERIAL.print(radar.movingTargetDistance());
      MONITOR_SERIAL.print(F("cm E:"));
      MONITOR_SERIAL.print(radar.movingTargetEnergy());
    }
    MONITOR_SERIAL.println();
  } else {
    MONITOR_SERIAL.println(F("NO"));
  }
  
  // Print engineering mode gate data if enabled
  if(engineeringMode) {
    MONITOR_SERIAL.print(F("GATES_MOV:"));
    for(int i = 0; i < 9; i++) {
      MONITOR_SERIAL.print(radar.engineering_moving_energy[i]);
      if(i < 8) MONITOR_SERIAL.print(F(","));
    }
    MONITOR_SERIAL.print(F(" | GATES_STAT:"));
    for(int i = 0; i < 9; i++) {
      MONITOR_SERIAL.print(radar.engineering_stationary_energy[i]);
      if(i < 8) MONITOR_SERIAL.print(F(","));
    }
    MONITOR_SERIAL.println();
  } else {
    // Debug: print engineering mode status every 50 reads
    static int debugCounter = 0;
    if(++debugCounter >= 50) {
      MONITOR_SERIAL.println(F("DEBUG: Engineering mode not enabled"));
      debugCounter = 0;
    }
  }
}

void setup() {
  // Enable USB CDC on ESP32-C6
  #if ARDUINO_USB_MODE
    Serial.begin(115200);
  #endif
  #if ARDUINO_USB_CDC_ON_BOOT
    delay(100);
  #endif
  
  MONITOR_SERIAL.begin(115200);
  delay(2000);  // Wait for USB serial to stabilize
  
  // Enable debug output from radar library
  radar.debug(MONITOR_SERIAL);
  
  printSeparator();
  MONITOR_SERIAL.println(F("ESP32-C6 LD2410C Radar Sensor"));
  printSeparator();
  
  MONITOR_SERIAL.print(F("Radar TX connected to GPIO "));
  MONITOR_SERIAL.println(RADAR_RX_PIN);
  MONITOR_SERIAL.print(F("Radar RX connected to GPIO "));
  MONITOR_SERIAL.println(RADAR_TX_PIN);
  MONITOR_SERIAL.println(F("Initializing radar UART..."));
  
  // Initialize UART1 for radar (GPIO 24 RX, 25 TX)
  RADAR_SERIAL.begin(256000, SERIAL_8N1, RADAR_RX_PIN, RADAR_TX_PIN);
  delay(1000);
  
  MONITOR_SERIAL.println(F("UART initialized, connecting to radar..."));
  
  MONITOR_SERIAL.print(F("\nInitializing LD2410 radar: "));
  
  if(radar.begin(RADAR_SERIAL)) {
    MONITOR_SERIAL.println(F("SUCCESS"));
    
    // Display firmware version
    printSeparator();
    MONITOR_SERIAL.println(F("FIRMWARE INFORMATION:"));
    printSeparator();
    MONITOR_SERIAL.print(F("Version: "));
    MONITOR_SERIAL.print(radar.firmware_major_version);
    MONITOR_SERIAL.print('.');
    MONITOR_SERIAL.print(radar.firmware_minor_version);
    MONITOR_SERIAL.print('.');
    MONITOR_SERIAL.print(radar.firmware_bugfix_version, HEX);
    MONITOR_SERIAL.println();
    // Request configuration
    MONITOR_SERIAL.println(F("\nRequesting configuration..."));
    if(radar.requestCurrentConfiguration()) {
      MONITOR_SERIAL.println(F("Configuration read successfully"));
      delay(500);
      printConfiguration();
      configDisplayed = true;
    } else {
      MONITOR_SERIAL.println(F("Failed to read configuration"));
    }
    
    // Enable engineering mode with retries
    MONITOR_SERIAL.println(F("\nEnabling engineering mode..."));
    delay(1000);  // Wait before engineering mode request
    
    // Enable debug for this section
    radar.debug(MONITOR_SERIAL);
    
    bool eng_success = false;
    for(int attempt = 0; attempt < 3; attempt++) {
      MONITOR_SERIAL.print(F("Attempt "));
      MONITOR_SERIAL.print(attempt + 1);
      MONITOR_SERIAL.print(F("/3... "));
      MONITOR_SERIAL.flush();
      
      if(radar.requestStartEngineeringMode()) {
        MONITOR_SERIAL.println(F("SUCCESS"));
        engineeringMode = true;
        eng_success = true;
        break;
      } else {
        MONITOR_SERIAL.println(F("FAILED"));
        delay(1000);  // Wait before retry
      }
    }
    
    if(!eng_success) {
      MONITOR_SERIAL.println(F("Engineering mode could not be enabled"));
      MONITOR_SERIAL.println(F("Note: Some LD2410 variants may not support engineering mode"));
      MONITOR_SERIAL.println(F("Continuing with basic detection mode..."));
    }
    
    printSeparator();
    MONITOR_SERIAL.println(F("REAL-TIME DETECTION DATA:"));
    MONITOR_SERIAL.println(F("(Updates every 500ms)"));
    MONITOR_SERIAL.println(F("Format: Presence: YES/NO | Stationary: XXcm E:YY | Moving: XXcm E:YY"));
    printSeparator();
    
  } else {
    MONITOR_SERIAL.println(F("FAILED - Check connections"));
  }
}

void loop() {
  // Read radar data in a tight loop to prevent UART buffer overflow
  // Engineering mode frames are 45 bytes and come frequently
  for(int i = 0; i < 10; i++) {
    radar.read();
  }
  
  // Check for commands from Python GUI
  if(MONITOR_SERIAL.available()) {
    String cmd = MONITOR_SERIAL.readStringUntil('\n');
    cmd.trim();
    
    if(cmd == "GET_CONFIG") {
      // Send configuration in parseable format
      MONITOR_SERIAL.println("CONFIG_START");
      for(int i = 0; i < 9; i++) {
        MONITOR_SERIAL.print("SENSITIVITY_MOTION:");
        MONITOR_SERIAL.print(i);
        MONITOR_SERIAL.print(":");
        MONITOR_SERIAL.println(radar.motion_sensitivity[i]);
      }
      for(int i = 0; i < 9; i++) {
        MONITOR_SERIAL.print("SENSITIVITY_STATIC:");
        MONITOR_SERIAL.print(i);
        MONITOR_SERIAL.print(":");
        MONITOR_SERIAL.println(radar.stationary_sensitivity[i]);
      }
      MONITOR_SERIAL.println("CONFIG_END");
    }
  }
  
  if(radar.isConnected()) {
    // Print detection info every 500ms for better responsiveness
    if(millis() - lastReading > 500) {
      lastReading = millis();
      printDetectionInfo();
    }
    
    // Re-request and display config every 30 seconds if not yet displayed
    if(!configDisplayed && millis() - lastConfigRead > 30000) {
      lastConfigRead = millis();
      MONITOR_SERIAL.println(F("\nRetrying configuration read..."));
      if(radar.requestCurrentConfiguration()) {
        delay(500);
        printConfiguration();
        configDisplayed = true;
      }
    }
  } else {
    if(millis() - lastReading > 5000) {
      lastReading = millis();
      MONITOR_SERIAL.println(F("Radar disconnected - Check connections"));
    }
  }
}
