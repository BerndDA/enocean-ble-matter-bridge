"""EnOcean carrier: a Pro Micro nRF52840 plugged onto a 2-layer board with a TCM 515.

The Pro Micro brings the nRF52840, USB, its 3.3 V regulator and its 2.4 GHz
antenna; the carrier adds the TCM 515 with the parts its user manual asks for
(v1.22, chapters 2 and 11) and the 868 MHz antenna (whip or u.FL). The
firmware's Pro Micro build runs unchanged: UART0 on P0.09 (TX) / P0.10 (RX)
at 57600 baud, function button on P1.06, LED on the module.

Every part with its pin -> net map and its place on the A3 sheet.
gen_schematic.py turns this into the schematic, check_netlist.py checks
KiCad's netlist against it. Coordinates in 2.54 mm grid units, y down.
"""

G = 2.54
TITLE = "EnOcean carrier: Pro Micro nRF52840 + TCM 515"
COMMENT = "Pro Micro build of firmware/enocean-gateway runs unchanged (BOARD=promicro-uf2)"
LIBS = ["EnOcean", "Modules"]          # project libraries in ../lib

POWER_NETS = {"GND", "+3V3"}
PWR_FLAGS = {
    "GND": (20 * G, 46 * G),
    "VDD_TCM": (120 * G, 16 * G),     # on the VDD_TCM rail
}

FP_R = "Resistor_SMD:R_0805_2012Metric_Pad1.20x1.40mm_HandSolder"
FP_C = "Capacitor_SMD:C_0805_2012Metric_Pad1.18x1.45mm_HandSolder"
FP_L = "Inductor_SMD:L_0805_2012Metric_Pad1.05x1.20mm_HandSolder"
FP_TP = "TestPoint:TestPoint_Pad_D1.5mm"

PARTS = []


def part(ref, lib_id, value, footprint, x, y, nets, dnp=False, lcsc="", mpn="", nc_rest=False, rot=0):
    PARTS.append(dict(ref=ref, lib_id=lib_id, value=value, footprint=footprint,
                      x=x * G, y=y * G, nets=nets, dnp=dnp, lcsc=lcsc, mpn=mpn,
                      nc_rest=nc_rest, rot=rot))


def R(ref, value, x, y, top, bottom, fp=FP_R, **kw):
    part(ref, "Device:R", value, fp, x, y, {"1": top, "2": bottom}, **kw)


def C(ref, value, x, y, top, bottom="GND", **kw):
    part(ref, "Device:C", value, FP_C, x, y, {"1": top, "2": bottom}, **kw)


def TP(ref, net, x, y, fp=FP_TP, value=None):
    part(ref, "Connector:TestPoint", value or net, fp, x, y, {"1": net})


# ---------------------------------------------------------------- Pro Micro nRF52840
# Pins from the USB end: 1-12 left column, 13-24 right column (lib/Modules.kicad_sym).
part("U1", "Modules:ProMicro_nRF52840", "ProMicro nRF52840", "Modules:ProMicro_nRF52840", 50, 40, {
    "3": "GND", "4": "GND", "14": "GND",
    "1": "I2C_SDA",         # P0.06 / P0.08: I2C expansion (J2), 4.7k pull-ups R9 / R10
    "2": "I2C_SCL",
    "18": "PIEZO_P",        # P0.29 / P0.02: piezo (J3) through R7 / R8, driven in antiphase (PWM)
    "19": "PIEZO_N",
    "16": "+3V3",           # VCC: the module's 3.3 V regulator output (nice!nano: off while P0.13 is high)
    "15": "NRESET",         # RST: double-tap for the UF2 bootloader
    "24": "TCM_RX",         # P0.09 UART0 TX -> TCM UART_RX
    "23": "TCM_TX",         # P0.10 UART0 RX <- TCM UART_TX
    "12": "BTN_FUNC",       # P1.06 sw0: hold 6 s for a factory reset
    "22": "LED_R",          # P1.11 / P1.13 / P1.15: status LEDs red / green / yellow, active low;
    "21": "LED_G",          # unused by today's firmware: the pins float and the LEDs stay dark
    "20": "LED_Y",
    "6": "TCM_NRESET",      # P0.20: TCM reset from firmware (unused today; the TCM's pull-up wins)
    "13": None,             # RAW (nice!nano: battery/raw input), not used. The nice!nano v2 has a 13th pin
                            # on each side above the rows (B+ / B-, battery only): no header there, not on this board
}, nc_rest=True, mpn="nice!nano v2 / SuperMini nRF52840 with UF2 bootloader >= 0.6.1")

# ---------------------------------------------------------------- TCM 515
part("U2", "EnOcean:TCM515", "TCM515", "EnOcean:TCM515_HandSolder", 128, 26, {
    "22": "VDD_TCM", "24": "TCM_NRESET", "31": "TCM_NTURBO",
    "20": "TCM_RX", "21": "TCM_TX",
    "2": "RF_868", "25": None, "26": None, "27": None,   # TCM test points: no pads on this board
    "1": "GND", "3": "GND", "6": "GND", "15": "GND", "23": "GND",
}, mpn="EnOcean TCM 515 (S3003-K515), 868.3 MHz")
part("FB1", "Device:FerriteBead", "600R@100MHz", FP_L, 110, 16, {"1": "+3V3", "2": "VDD_TCM"},
     lcsc="C1017", mpn="GZ2012D601TF")              # manual 11.6
C("C1", "22uF", 115, 19, "VDD_TCM", lcsc="C45783", mpn="CL21A226MAQNNNE")       # manual 11.6
C("C2", "100nF", 118, 19, "VDD_TCM", lcsc="C49678", mpn="CC0805KRX7R9BB104")
C("C3", "100nF", 120, 38, "TCM_NRESET", lcsc="C49678", mpn="CC0805KRX7R9BB104")                           # manual 11.8, Figure 20
R("R1", "10k", 110, 30, "VDD_TCM", "TCM_NTURBO", lcsc="C17414", mpn="0805W8F1002T5E")                  # 57600 baud at power-up
part("JP1", "Jumper:SolderJumper_2_Open", "460k8", "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
     110, 35.5, {"1": "TCM_NTURBO", "2": "GND"})                    # closed: 460800 baud (firmware expects 57600)

# 868 MHz: RF_50 -> whip (R2) or u.FL (R3), shunt pad for tuning
C("C4", "DNP", 138, 25, "RF_868", dnp=True)
R("R2", "0", 147, 22, "RF_868", "ANT_868", lcsc="C17477", mpn="0805W8F0000T5E")
R("R3", "0", 141, 25, "RF_868", "RF_UFL", dnp=True, lcsc="C17477", mpn="0805W8F0000T5E")
TP("TP1", "ANT_868", 151, 20, fp="Modules:WhipPad_D3.2mm_Drill1.8mm", value="WHIP 86mm")   # wire up to 1.5 mm
part("J1", "Connector:Conn_Coaxial", "U.FL", "Connector_Coaxial:U.FL_Hirose_U.FL-R-SMT-1_Vertical", 147, 29,
     {"1": "RF_UFL", "2": "GND"}, dnp=True, lcsc="C88374", mpn="U.FL-R-SMT-1(80)")

# ---------------------------------------------------------------- buttons, LED
# SW1: the Pro Micro's reset (press: reset, double-tap: UF2 bootloader).
# SW2: the firmware's function button (hold 6 s: factory reset).
# XKB TS-1187A (5.1 x 5.1 mm): the only tactile switch in JLC's basic library
part("SW1", "Switch:SW_Push", "RESET", "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A", 66, 31, {"1": "NRESET", "2": "GND"},
     lcsc="C318884", mpn="TS-1187A-B-A-B")
part("SW2", "Switch:SW_Push", "FUNC", "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A", 45, 49, {"1": "BTN_FUNC", "2": "GND"},
     lcsc="C318884", mpn="TS-1187A-B-A-B")
# Status LEDs: three single 0805 LEDs, each under its own 3 mm light pipe, all from JLC's basic
# library (no blue LED is basic: it would cost the $3 extended-part fee). Anodes on 3.3 V, each
# cathode through its resistor to a GPIO (low = on), so the firmware sees the same pins as v0.2's
# RGB LED: P1.11 red, P1.13 green, P1.15 yellow (was blue).
# Red and yellow ~2.0 V: 1k -> ~1.3 mA; green (InGaN, ~2.6 V at low current, 430 mcd @ 5 mA): 330R.
FP_R0603 = "Resistor_SMD:R_0603_1608Metric_Pad0.98x0.95mm_HandSolder"
FP_LED = "LED_SMD:LED_0805_2012Metric"
R("R4", "1k", 68.5, 54.5, "LED_R", "LED_RK", fp=FP_R0603, lcsc="C21190", mpn="0603WAF1001T5E")
R("R5", "330", 68.5, 50.5, "LED_G", "LED_GK", fp=FP_R0603, lcsc="C23138", mpn="0603WAF3300T5E")
R("R6", "1k", 68.5, 46.5, "LED_Y", "LED_YK", fp=FP_R0603, lcsc="C21190", mpn="0603WAF1001T5E")
part("D1", "Device:LED", "RED", FP_LED, 75.5, 54.5, {"1": "LED_RK", "2": "+3V3"}, lcsc="C84256", mpn="NCD0805R1")
part("D2", "Device:LED", "GREEN", FP_LED, 75.5, 50.5, {"1": "LED_GK", "2": "+3V3"}, lcsc="C2297", mpn="KT-0805G")
part("D3", "Device:LED", "YELLOW", FP_LED, 75.5, 46.5, {"1": "LED_YK", "2": "+3V3"}, lcsc="C2296", mpn="KT-0805Y")

# Expansion (v0.4): wire pads, no connector bodies, so nothing new stands on the board.
# J2: I2C in Qwiic / STEMMA QT order (GND, 3V3, SDA, SCL) on 2.54 mm holes along the top edge,
# for a sensor or a Qwiic cable soldered on. Pull-ups on the board: breakouts usually bring their
# own (2.2-10k), in parallel that stays fine for 100/400 kHz.
# J3: a piezo transducer in the lid, its wires soldered into two holes. Two GPIOs in antiphase
# double the swing; 100R each limits the edge current into the piezo's capacitance and takes the
# voltage spikes a knock on the piezo produces. The four resistors sit under the Pro Micro.
FP_WIRE2 = "Modules:WirePads_1x02_P2.54mm_Drill0.9mm"
FP_WIRE4 = "Modules:WirePads_1x04_P2.54mm_Drill0.9mm"
R("R7", "100", 68.5, 39.5, "PIEZO_P", "PIEZO_1", fp=FP_R0603, lcsc="C22775", mpn="0603WAF1000T5E")
R("R8", "100", 68.5, 42.5, "PIEZO_N", "PIEZO_2", fp=FP_R0603, lcsc="C22775", mpn="0603WAF1000T5E")
part("J3", "Connector_Generic:Conn_01x02", "PIEZO", FP_WIRE2, 78, 41, {"1": "PIEZO_1", "2": "PIEZO_2"})
R("R9", "4.7k", 35.5, 26, "+3V3", "I2C_SDA", fp=FP_R0603, lcsc="C23162", mpn="0603WAF4701T5E")
R("R10", "4.7k", 29.5, 29, "+3V3", "I2C_SCL", fp=FP_R0603, lcsc="C23162", mpn="0603WAF4701T5E")
part("J2", "Connector_Generic:Conn_01x04", "I2C", FP_WIRE4, 20, 20,
     {"1": "GND", "2": "+3V3", "3": "I2C_SDA", "4": "I2C_SCL"})

part("H1", "Mechanical:MountingHole", "M2", "MountingHole:MountingHole_2.2mm_M2", 8, 54, {})

# ---------------------------------------------------------------- sheet layout
# Symbol rotations on the sheet (degrees CCW) and mirroring; parts not listed stay as drawn.
ROT = {"FB1": 90, "JP1": 270, "R2": 90, "R7": 90, "R8": 90, "R4": 90, "R5": 90, "R6": 90,
       "R9": 270, "R10": 270}
MIRROR = {"J2": "y"}      # pins on the right, toward the Pro Micro, SDA above SCL as on U1
for _p in PARTS:
    _p["rot"] = ROT.get(_p["ref"], _p["rot"])
    _p["mirror"] = MIRROR.get(_p["ref"])

# Frames around the functional blocks: (title, x0, y0, x1, y1) in grid units.
GROUPS = [
    ("Pro Micro nRF52840 (nice!nano v2): buttons, LEDs, I2C, piezo", 5, 9, 86, 63),
    ("TCM 515, 868 MHz", 102, 6, 156, 44),
]
NOTES = [
    ("J2: wire pads, Qwiic pin order", 7, 25),
    ("On two 1x12 headers: USB, 3.3 V regulator and 2.4 GHz antenna on the module", 7, 58.5),
    ("H1: M2 hole, the case's locating peg", 11, 54.6),
    ("J3: piezo in the lid, PIEZO_P / PIEZO_N in antiphase", 7, 60),
    ("LEDs active low: a pin pulled low lights its LED", 7, 61.5),
    ("JP1 open: 57600 baud", 103, 41),
    ("C4, R3, J1 not fitted: whip by default", 131, 41),
]

# Wires: polylines of pin ends ("REF.PIN") and sheet points (grid units), horizontal
# and vertical only. Pins without a wire get a label / power symbol on their end.
WIRES = [
    # --- I2C: J2 (mirrored: 1 GND, 2 3V3, 3 SDA, 4 SCL top to bottom) to U1 pins 1 / 2, pull-ups
    ["J2.1", (23.5, 19)],
    ["J2.2", (26, 20), (26, 17)],
    ["J2.3", (34, 21), (34, 34.5), "U1.1"],
    ["J2.4", (28, 22), (28, 35.5), "U1.2"],
    ["R9.1", (38, 26), (38, 24)],
    ["R10.1", (32, 29), (32, 27)],
    # --- Pro Micro supply pins
    ["U1.3", (39, 36.5), (39, 41)],
    ["U1.4", (39, 37.5)],
    ["U1.14", (59, 35.5)],
    ["U1.16", (80, 37.5), (80, 54.5)],          # VCC down to the LED anodes
    # --- function button
    ["U1.12", (43, 45.5), (43, 49), "SW2.1"],
    ["SW2.2", (49, 49), (49, 50)],
    ["SW1.2", (70, 31), (70, 32)],
    # --- piezo: pins 18 / 19 through R7 / R8 to J3
    ["U1.18", "R7.1"],
    ["U1.19", (65, 40.5), (65, 42.5), "R8.1"],
    ["R7.2", (71, 39.5), (71, 41), "J3.1"],
    ["R8.2", (72, 42.5), (72, 42), "J3.2"],
    # --- status LEDs: pin -> resistor -> cathode, anodes on the VCC rail
    ["U1.20", (63, 41.5), (63, 46.5), "R6.1"],
    ["U1.21", (61, 42.5), (61, 50.5), "R5.1"],
    ["U1.22", (59, 43.5), (59, 54.5), "R4.1"],
    ["R6.2", "D3.1"],
    ["R5.2", "D2.1"],
    ["R4.2", "D1.1"],
    ["D3.2", (80, 46.5)],
    ["D2.2", (80, 50.5)],
    ["D1.2", (80, 54.5)],
    # --- TCM 515: supply through FB1, nTURBO strap, RF_50 -> R2 -> whip / R3 -> u.FL
    [(105, 16), "FB1.1"],
    ["FB1.2", (121, 16), (121, 22), "U2.22"],
    [(115, 16), "C1.1"],
    [(118, 16), "C2.1"],
    ["R1.2", "JP1.1"],
    [(110, 32.5), (113, 32.5)],
    ["U2.2", "R2.1"],
    [(138, 22), "C4.1"],
    [(141, 22), "R3.1"],
    ["R3.2", (141, 29), "J1.1"],
    ["R2.2", (151, 22), "TP1.1"],
]

# Net names put on wires: (net, point, outward direction in degrees). Power nets get a
# power symbol, others a label. Untagged signal clusters get an automatic label.
TAGS = [
    ("GND", (23.5, 19), 0), ("+3V3", (26, 17), 90), ("+3V3", (38, 24), 90), ("+3V3", (32, 27), 90),
    ("GND", (39, 41), 270), ("GND", (59, 35.5), 0), ("+3V3", (80, 37.5), 90),
    ("GND", (49, 50), 270), ("GND", (70, 32), 270),
    ("+3V3", (105, 16), 90), ("VDD_TCM", (113, 16), 90), ("TCM_NTURBO", (113, 32.5), 0),
]

# Footprint-only parts (copper, holes, test pads): not in the BOM.
NOT_IN_BOM = {"JP1", "H1", "J2", "J3"} | {p["ref"] for p in PARTS if p["ref"].startswith("TP")}
for _p in PARTS:
    _p["in_bom"] = _p["ref"] not in NOT_IN_BOM
