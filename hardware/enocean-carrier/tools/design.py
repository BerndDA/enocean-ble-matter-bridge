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
    "GND": (20 * G, 100 * G),
    "VDD_TCM": (26 * G, 100 * G),
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
part("U1", "Modules:ProMicro_nRF52840", "ProMicro nRF52840", "Modules:ProMicro_nRF52840", 40, 40, {
    "3": "GND", "4": "GND", "14": "GND",
    "16": "+3V3",           # VCC: the module's 3.3 V regulator output (nice!nano: off while P0.13 is high)
    "15": "NRESET",         # RST: double-tap for the UF2 bootloader
    "24": "TCM_RX",         # P0.09 UART0 TX -> TCM UART_RX
    "23": "TCM_TX",         # P0.10 UART0 RX <- TCM UART_TX
    "12": "BTN_FUNC",       # P1.06 sw0: hold 6 s for a factory reset
    "22": "LED_R",          # P1.11 / P1.13 / P1.15: RGB LED, active low (common anode);
    "21": "LED_G",          # unused by today's firmware: the pins float and the LED stays dark
    "20": "LED_B",
    "6": "TCM_NRESET",      # P0.20: TCM reset from firmware (unused today; the TCM's pull-up wins)
    "13": None,             # B+ (battery), not used
}, nc_rest=True, mpn="nice!nano v2 / SuperMini nRF52840 with UF2 bootloader >= 0.6.1")

# ---------------------------------------------------------------- TCM 515
part("U2", "EnOcean:TCM515", "TCM515", "EnOcean:TCM515", 100, 40, {
    "22": "VDD_TCM", "24": "TCM_NRESET", "31": "TCM_NTURBO",
    "20": "TCM_RX", "21": "TCM_TX",
    "2": "RF_868", "25": None, "26": None, "27": None,   # TCM test points: no pads on this board
    "1": "GND", "3": "GND", "6": "GND", "15": "GND", "23": "GND",
}, mpn="EnOcean TCM 515 (S3003-K515), 868.3 MHz")
part("FB1", "Device:FerriteBead", "600R@100MHz", FP_L, 76, 30, {"1": "+3V3", "2": "VDD_TCM"},
     lcsc="C1017", mpn="GZ2012D601TF")              # manual 11.6
C("C1", "22uF", 80, 30, "VDD_TCM", lcsc="C45783", mpn="CL21A226MAQNNNE")       # manual 11.6
C("C2", "100nF", 84, 30, "VDD_TCM", lcsc="C49678", mpn="CC0805KRX7R9BB104")
C("C3", "100nF", 80, 46, "TCM_NRESET", lcsc="C49678", mpn="CC0805KRX7R9BB104")                           # manual 11.8, Figure 20
R("R1", "10k", 84, 52, "VDD_TCM", "TCM_NTURBO", lcsc="C17414", mpn="0805W8F1002T5E")                  # 57600 baud at power-up
part("JP1", "Jumper:SolderJumper_2_Open", "460k8", "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
     78, 56, {"1": "TCM_NTURBO", "2": "GND"})                    # closed: 460800 baud (firmware expects 57600)

# 868 MHz: RF_50 -> whip (R2) or u.FL (R3), shunt pad for tuning
C("C4", "DNP", 120, 34, "RF_868", dnp=True)
R("R2", "0", 124, 34, "RF_868", "ANT_868", lcsc="C17477", mpn="0805W8F0000T5E")
R("R3", "0", 128, 34, "RF_868", "RF_UFL", dnp=True, lcsc="C17477", mpn="0805W8F0000T5E")
TP("TP1", "ANT_868", 124, 44, fp="Modules:WhipPad_D3.2mm_Drill1.8mm", value="WHIP 86mm")   # wire up to 1.5 mm
part("J1", "Connector:Conn_Coaxial", "U.FL", "Connector_Coaxial:U.FL_Hirose_U.FL-R-SMT-1_Vertical", 134, 42,
     {"1": "RF_UFL", "2": "GND"}, dnp=True, lcsc="C88374", mpn="U.FL-R-SMT-1(80)")

# ---------------------------------------------------------------- buttons, LED
# SW1: the Pro Micro's reset (press: reset, double-tap: UF2 bootloader).
# SW2: the firmware's function button (hold 6 s: factory reset).
# XKB TS-1187A (5.1 x 5.1 mm): the only tactile switch in JLC's basic library
part("SW1", "Switch:SW_Push", "RESET", "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A", 14, 30, {"1": "NRESET", "2": "GND"},
     lcsc="C318884", mpn="TS-1187A-B-A-B")
part("SW2", "Switch:SW_Push", "FUNC", "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A", 14, 40, {"1": "BTN_FUNC", "2": "GND"},
     lcsc="C318884", mpn="TS-1187A-B-A-B")
# RGB status LED, common anode on 3.3 V; each cathode through its resistor to a GPIO (low = on).
# Red has the lower forward voltage, so it gets the larger resistor: about 1.3 / 1.8 / 1.8 mA.
FP_R0603 = "Resistor_SMD:R_0603_1608Metric_Pad0.98x0.95mm_HandSolder"
R("R4", "1k", 60, 66, "LED_R", "LED_RK", fp=FP_R0603, lcsc="C21190", mpn="0603WAF1001T5E")
R("R5", "330", 64, 66, "LED_G", "LED_GK", fp=FP_R0603, lcsc="C23138", mpn="0603WAF3300T5E")
R("R6", "330", 68, 66, "LED_B", "LED_BK", fp=FP_R0603, lcsc="C23138", mpn="0603WAF3300T5E")
part("D1", "Device:LED_BAGR", "RGB", "Modules:LED_RGB_3528_TZ_S4-3528RGBTA-A", 64, 80,
     {"1": "LED_BK", "2": "+3V3", "3": "LED_GK", "4": "LED_RK"}, lcsc="C2827321", mpn="S4-3528RGBTA-A")

part("H1", "Mechanical:MountingHole", "M2", "MountingHole:MountingHole_2.2mm_M2", 10, 90, {})
part("H2", "Mechanical:MountingHole", "M2", "MountingHole:MountingHole_2.2mm_M2", 16, 90, {})

# Footprint-only parts (copper, holes, test pads): not in the BOM.
NOT_IN_BOM = {"JP1", "H1", "H2"} | {p["ref"] for p in PARTS if p["ref"].startswith("TP")}
for _p in PARTS:
    _p["in_bom"] = _p["ref"] not in NOT_IN_BOM
