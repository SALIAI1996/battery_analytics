## Battery Analytics — HC-05 Bluetooth + Streamlit + Plotly

Real-time battery monitoring dashboard using an **HC-05 Bluetooth module** (Classic Bluetooth / Serial Port Profile).

Works on **macOS, Windows, and Linux**.

### How it works

```
Battery MCU ──UART──▶ HC-05 ──Bluetooth SPP──▶ macOS/Linux/Windows
                                                    │
                                              Serial port
                                        (/dev/tty.HC-05 or COM3)
                                                    │
                                          Python backend (pyserial)
                                                    │
                                          Streamlit + Plotly UI
```

### What you get
- **MAC address pairing** — enter HC-05 MAC address directly to pair and connect
- **Bluetooth scan** — discover nearby Bluetooth devices
- **Serial port discovery** — lists all ports; pick your HC-05
- **Live streaming** — reads UART lines from HC-05, parses battery data
- **Per-cell voltages** — shows V1, V2, V3, V4… individually
- **Pack metrics** — total voltage, current, temperature, SOC
- **Serial test** — diagnose if data is coming from HC-05 before connecting
- **Simulation mode** — works without hardware for testing
- **Reconnection** — auto-retries if HC-05 disconnects
- **Responsive** — works on phones/tablets/laptops via browser

### Quickstart

```bash
cd /Users/bajiraosali/Desktop/Battery_analytics
python -m venv .venv
source .venv/bin/activate          # macOS/Linux
# .venv\Scripts\activate           # Windows
pip install -r requirements.txt
```

### Streamlit Community Cloud

1. **Main file:** `frontend/app.py` (not the repo root).
2. **Python:** 3.11+ recommended.
3. The UI **starts FastAPI inside the same app** so `localhost:8004` works on Cloud (no second service).
4. **Optional secrets** (app settings → Secrets): `BACKEND_URL` = your API URL if you host the backend elsewhere; or `NO_EMBED_FASTAPI=true` with `BACKEND_URL` pointing to that API.

### Pair HC-05 with your OS


**macOS:**
1. System Settings → Bluetooth → Pair (PIN `1234`)
2. Serial port appears as `/dev/tty.HC-05` or `/dev/tty.HC-05-DevB`
3. Or use the **Pair by MAC** feature in the app sidebar
4. Requires `blueutil`: `brew install blueutil`

**Windows:**
1. Settings → Bluetooth & devices → Add device → Bluetooth
2. Select HC-05, enter PIN `1234`
3. Open Device Manager → Ports (COM & LPT) to find the COM port (e.g. `COM3`)
4. Use that COM port in the app

**Linux:**
1. `bluetoothctl pair 00:23:09:01:5A:78` → enter PIN `1234`
2. `bluetoothctl trust 00:23:09:01:5A:78`
3. `sudo rfcomm bind 0 00:23:09:01:5A:78`
4. Use `/dev/rfcomm0` as the serial port

### Start the app

**Terminal 1 — Backend:**
```bash
uvicorn backend.api:app --reload --reload-dir backend --port 8004
```

**Terminal 2 — Frontend:**
```bash
streamlit run frontend/app.py
```

### In the UI

**Option A — Pair by MAC (easiest):**
1. Enter HC-05 MAC address (e.g. `00:23:09:01:5A:78`)
2. Click **Pair & Connect**
3. App auto-discovers the serial port and starts streaming

**Option B — Manual:**
1. Click **Scan ports**
2. Select your HC-05 serial port
3. Set baud rate (default 9600, must match your MCU)
4. Click **Connect**

**Troubleshooting no data:**
1. Use the **Test Serial Port** button to check if raw bytes arrive
2. If no data, your MCU isn't sending — check wiring and firmware

### Data format from your MCU

Your MCU should send **one ASCII line per sample** over UART to the HC-05, ending with `\n`. Supported formats:

**CSV (simplest):**
```
3.65,3.64,3.66,3.63
```
→ Interpreted as cell voltages V1–V4. Pack voltage = sum.

**Key:value pairs:**
```
V1:3.65,V2:3.64,V3:3.66,V4:3.63,I:2.1,T:28.5,SOC:87
```

**JSON:**
```json
{"V1":3.65,"V2":3.64,"V3":3.66,"V4":3.63,"current":2.1,"temp":28.5,"soc":87}
```

**Simple 3-value (pack only):**
```
52.6,2.1,28.5
```
→ Interpreted as pack voltage, current, temperature.

### PIC 16F877A Example (XC8 / MPLAB X)

**Wiring:**
```
PIC 16F877A          HC-05
-----------          -----
RC6 (TX)  ────────▶  RXD
RC7 (RX)  ◀────────  TXD  (optional, for commands)
GND       ────────▶  GND
+5V       ────────▶  VCC
```

Battery cells connect to ADC channels AN0–AN3 (pins RA0–RA3) via voltage dividers.

**Firmware (XC8 C):**
```c
#include <xc.h>
#include <stdio.h>

#pragma config FOSC = HS    // 20MHz crystal
#pragma config WDTE = OFF
#pragma config PWRTE = ON
#pragma config BOREN = ON
#pragma config LVP = OFF

#define _XTAL_FREQ 20000000

void UART_Init(void) {
    TRISC6 = 0;          // TX pin output
    TRISC7 = 1;          // RX pin input
    SPBRG = 31;          // 9600 baud @ 20MHz
    TXSTA = 0x24;        // TX enabled, high speed
    RCSTA = 0x90;        // Serial port enabled, continuous receive
}

void UART_SendChar(char c) {
    while (!TXIF);
    TXREG = c;
}

void UART_SendString(const char *s) {
    while (*s) UART_SendChar(*s++);
}

unsigned int ADC_Read(unsigned char channel) {
    ADCON0 = (channel << 3) | 0x01;  // Select channel, ADC ON
    __delay_us(20);
    GO_nDONE = 1;
    while (GO_nDONE);
    return ((ADRESH << 8) + ADRESL);
}

void main(void) {
    char buf[80];
    TRISA = 0xFF;        // Port A as input (ADC)
    ADCON1 = 0x80;       // Right justified, all analog

    UART_Init();
    __delay_ms(500);

    while (1) {
        unsigned int v1 = ADC_Read(0);  // AN0 = Cell 1
        unsigned int v2 = ADC_Read(1);  // AN1 = Cell 2
        unsigned int v3 = ADC_Read(2);  // AN2 = Cell 3
        unsigned int v4 = ADC_Read(3);  // AN3 = Cell 4

        // Send as CSV: raw ADC values (app auto-converts to voltage)
        sprintf(buf, "%u,%u,%u,%u\r\n", v1, v2, v3, v4);
        UART_SendString(buf);

        __delay_ms(500);
    }
}
```

The app auto-detects raw ADC values (integers 0–1023) and converts them using:
`voltage = (ADC / 1023) * Vref * divider_ratio`

To calibrate, set environment variables before starting the backend:
```bash
export ADC_VREF=5.0      # PIC reference voltage (default 5.0V)
export ADC_DIVIDER=3.0    # Voltage divider ratio (e.g., 3:1 for 15V battery)
```

### Arduino example

```cpp
void loop() {
  float v1 = readCell(1);
  float v2 = readCell(2);
  float v3 = readCell(3);
  float v4 = readCell(4);
  float current = readCurrent();
  float temp = readTemp();

  Serial.print("V1:"); Serial.print(v1, 3);
  Serial.print(",V2:"); Serial.print(v2, 3);
  Serial.print(",V3:"); Serial.print(v3, 3);
  Serial.print(",V4:"); Serial.print(v4, 3);
  Serial.print(",I:"); Serial.print(current, 2);
  Serial.print(",T:"); Serial.println(temp, 1);

  delay(200);
}
```

### Troubleshooting

| Problem | Fix |
|---------|-----|
| HC-05 not in port list | Pair it first in OS Bluetooth settings |
| "Permission denied" on port | macOS: try `/dev/cu.HC-05` instead. Linux: `sudo chmod 666 /dev/rfcomm0` or add user to `dialout` group |
| Port opens but no data | MCU not sending data. Check wiring: MCU TX → HC-05 RX, GND → GND |
| Data shows but all zeros | Baud rate mismatch — try 9600, 38400, or 115200 |
| Port busy | Another app has the port open (close Arduino IDE serial monitor, etc.) |
| Windows: COM port not found | Check Device Manager → Ports (COM & LPT) after pairing |
| macOS: blueutil not found | Run `brew install blueutil` |
