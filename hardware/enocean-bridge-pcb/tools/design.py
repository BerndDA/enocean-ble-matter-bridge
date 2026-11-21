"""The EnOcean bridge circuit as data: every part, its pin -> net map and its
place on the A3 sheet. gen_schematic.py turns this into the KiCad schematic,
check_netlist.py compares KiCad's netlist against it.

Sources for values: nRF52840 PS v1.11 circuit configuration 3 (Fig. 220,
Table 75) and the 4-component RF match of configuration 7 (Table 83); TCM 515
User Manual v1.22 chapters 2 and 11. See the wiki page EnOcean Bridge PCB.

Coordinates are in mm on the sheet (y down), symbol origins on the 2.54 grid.
"""

G = 2.54

# Nets drawn with KiCad power symbols (power:<name>); all others get net labels.
POWER_NETS = {"GND", "+3V3", "VBUS"}

FP_R0402 = "Resistor_SMD:R_0402_1005Metric"
FP_C0402 = "Capacitor_SMD:C_0402_1005Metric"
FP_C0603 = "Capacitor_SMD:C_0603_1608Metric"
FP_C0805 = "Capacitor_SMD:C_0805_2012Metric"
FP_L0402 = "Inductor_SMD:L_0402_1005Metric"
FP_L0603 = "Inductor_SMD:L_0603_1608Metric"
FP_R0603 = "Resistor_SMD:R_0603_1608Metric"
FP_LED = "LED_SMD:LED_0805_2012Metric"
FP_TP = "TestPoint:TestPoint_Pad_D1.0mm"

PARTS = []


def part(ref, lib_id, value, footprint, x, y, nets, dnp=False, lcsc="", mpn="", nc_rest=False, rot=0):
    PARTS.append(dict(ref=ref, lib_id=lib_id, value=value, footprint=footprint,
                      x=x * G, y=y * G, nets=nets, dnp=dnp, lcsc=lcsc, mpn=mpn,
                      nc_rest=nc_rest, rot=rot))


def R(ref, value, x, y, top, bottom, fp=FP_R0402, **kw):
    part(ref, "Device:R", value, fp, x, y, {"1": top, "2": bottom}, **kw)


def C(ref, value, x, y, top, bottom="GND", fp=FP_C0402, **kw):
    part(ref, "Device:C", value, fp, x, y, {"1": top, "2": bottom}, **kw)


def L(ref, value, x, y, top, bottom, fp=FP_L0402, **kw):
    part(ref, "Device:L", value, fp, x, y, {"1": top, "2": bottom}, **kw)


def TP(ref, net, x, y, fp=FP_TP, value=None):
    part(ref, "Connector:TestPoint", value or net, fp, x, y, {"1": net})


# ---------------------------------------------------------------- USB, power
part("J1", "Connector:USB_C_Receptacle_USB2.0_16P", "USB-C", "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
     124, 68, {
         "A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
         "A5": "CC1", "B5": "CC2",
         "A6": "USB_DP", "B6": "USB_DP", "A7": "USB_DM", "B7": "USB_DM",
         "A8": None, "B8": None,
         "A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND",
         "SH": "USB_SHIELD",
     }, lcsc="C165948", mpn="HRO TYPE-C-31-M-12")
R("R1", "5.1k", 124, 90, "CC1", "GND")
R("R2", "5.1k", 128, 90, "CC2", "GND")
R("R3", "1M", 127, 83, "USB_SHIELD", "GND")
C("C1", "10nF", 121, 83, "USB_SHIELD", "GND")
part("U3", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6", 137, 67,
     {"1": "USB_DM", "6": "USB_DM", "3": "USB_DP", "4": "USB_DP", "5": "VBUS", "2": "GND"},
     lcsc="C3029034", mpn="USBLC6-2SC6")
# XC6206 (JLC basic, no EN pin): 200 mA, max 6 V in; plenty for USB 5 V and < 60 mA
part("U2", "Regulator_Linear:XC6206PxxxMR", "XC6206P332MR", "Package_TO_SOT_SMD:SOT-23-3", 151, 62,
     {"3": "VBUS", "1": "GND", "2": "+3V3"}, lcsc="C5446", mpn="XC6206P332MR-G")
C("C2", "4.7uF", 145, 65, "VBUS", fp=FP_C0603)
C("C3", "4.7uF", 157, 65, "+3V3", fp=FP_C0603)
R("R4", "0", 137, 78, "VBUS", "VBUS_NRF")               # 0 ohm: the PS's optional 2.2 ohm VBUS series R is no JLC basic part
C("C14", "4.7uF", 141, 84, "VBUS_NRF", fp=FP_C0603)     # C21

# ---------------------------------------------------------------- nRF52840
NRF = {
    # supply (configuration 3: VDDH tied to VDD, DCCH unconnected)
    "B1": "+3V3", "A22": "+3V3", "AD14": "+3V3", "AD23": "+3V3", "W1": "+3V3",
    "Y2": "+3V3", "AB2": None,
    "B7": "GND", "F23": "GND", "EP": "GND",
    "C1": "DEC1", "D23": "DEC3", "B5": "DEC4_6", "E24": "DEC4_6", "N24": None,
    "AC5": "DECUSB", "A18": None, "B3": None,
    "B24": "XC1", "A23": "XC2", "D2": None, "F2": None,
    "H23": "RF_ANT",
    # USB
    "AD2": "VBUS_NRF", "AD4": "USB_DM", "AD6": "USB_DP",
    # Pro Micro pin contract (firmware/enocean-gateway/boards/promicro_nrf52840_common.dtsi)
    "L24": "TCM_RX",        # P0.09 UART0 TX -> TCM UART_RX
    "J24": "TCM_TX",        # P0.10 UART0 RX <- TCM UART_TX
    "B19": "LED_R",         # P1.11 / P1.13 / P1.15: status LEDs red / green / yellow, active low,
    "A16": "LED_G",         # as on the EnMT carrier: BOARD=enmt drives them (PWR / LINK / RX)
    "A14": "LED_Y",
    "R24": "BTN_FUNC",      # P1.06 sw0
    "AC13": "NRESET",       # P0.18 nRESET
    "AD16": "TCM_NRESET",   # P0.20, new: TCM reset from firmware
    "AC24": "SWDIO", "AA24": "SWDCLK", "AD22": "SWO",
}
part("U1", "MCU_Nordic:nRF52840", "nRF52840-QIAA", "Package_DFN_QFN:Nordic_AQFN-73-1EP_7x7mm_P0.5mm",
     96, 58, NRF, nc_rest=True, lcsc="C3606858", mpn="NRF52840-QIAA-F-R7")

# decoupling, one cap per pin (PS reference designators in comments)
C("C4", "100nF", 83, 24, "DEC1")                        # C5
C("C5", "100pF", 80, 24, "DEC3")                        # C11
C("C6", "1uF", 77, 24, "DEC4_6", fp=FP_C0603)           # C15
C("C8", "4.7uF", 74, 24, "DECUSB", fp=FP_C0603)         # C20
C("C9", "1uF", 101, 24, "+3V3", fp=FP_C0603)            # C14 at VDD B1
C("C10", "100nF", 104, 24, "+3V3")                      # C12 at VDD A22
C("C11", "100nF", 107, 24, "+3V3")                      # C7 at VDD AD14
C("C12", "100nF", 110, 24, "+3V3")                      # C8 at VDD AD23
C("C13", "4.7uF", 113, 24, "+3V3", fp=FP_C0603)         # C6 at VDD W1

# 32 MHz crystal (X1, C1, C2 in the PS)
part("Y1", "Device:Crystal_GND24", "32MHz 8pF", "Crystal:Crystal_SMD_2016-4Pin_2.0x1.6mm", 70, 66,
     {"1": "XC1", "3": "XC2", "2": "GND", "4": "GND"}, lcsc="C5189005", mpn="ABM11W-32.0000MHZ-8-D1X-T3")
C("C15", "12pF", 66, 70, "XC1")
C("C16", "12pF", 74, 70, "XC2")
# No 32.768 kHz crystal: the firmware runs the LF clock from the RC oscillator, like the
# Pro Micro, and XL2 (F2) can't escape the aQFN at JLC's 0.1 mm minimum anyway.

# RF: 4-component match at the ANT pin, then the 50 ohm line to the PCB antenna
C("C19", "1.0pF", 70, 43, "RF_ANT")                     # C3
L("L1", "4.7nH", 64, 40, "RF_ANT", "RF_M1", lcsc="C97989", mpn="LQG15HN4N7S02D", rot=270)
C("C20", "1.2pF", 60, 43, "RF_M1")                      # C4
L("L2", "2.2nH", 56, 40, "RF_M1", "RF_ANT_2G4", lcsc="C162540", mpn="LQG15HS2N2B02D", rot=270)   # L5
part("AE1", "Device:Antenna_Shield", "2.4GHz PCB", "RF_Antenna:Texas_SWRA117D_2.4GHz_Left", 48, 34,
     {"1": "RF_ANT_2G4", "2": "GND"})

# ---------------------------------------------------------------- TCM 515
part("U4", "EnOcean:TCM515", "TCM515", "EnOcean:TCM515", 139, 24, {
    "22": "VDD_TCM", "24": "TCM_NRESET", "31": "TCM_NTURBO",
    "20": "TCM_RX", "21": "TCM_TX",
    "2": "RF_868", "25": None, "26": None, "27": None,   # TCM TP1-3: no test pads
    "1": "GND", "3": "GND", "6": "GND", "15": "GND", "23": "GND",
}, mpn="TCM 515 (hand-solder, not at JLC)")
part("FB1", "Device:FerriteBead", "600R@100MHz", FP_L0603, 123, 14, {"1": "+3V3", "2": "VDD_TCM"},
     mpn="742863160 or eq.", rot=90)
C("C23", "22uF", 128, 17, "VDD_TCM", fp=FP_C0805)
C("C24", "100nF", 131, 17, "VDD_TCM")
C("C25", "100nF", 134, 36, "TCM_NRESET")                # manual Figure 20
R("R6", "10k", 122, 36, "VDD_TCM", "TCM_NTURBO")
part("JP1", "Jumper:SolderJumper_2_Open", "460k8", "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
     122, 41.5, {"1": "TCM_NTURBO", "2": "GND"}, rot=270)
R("R7", "0", 150, 20, "RF_868", "ANT_868", rot=90)      # whip
TP("TP1", "ANT_868", 156, 17, fp="TestPoint:TestPoint_THTPad_D2.0mm_Drill1.0mm", value="WHIP 86mm")

# ---------------------------------------------------------------- UI, debug
# XKB TS-1187A (5.1 x 5.1 mm): JLC basic, the same buttons as the EnMT carrier
part("SW1", "Switch:SW_Push", "RESET", "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A", 14, 20,
     {"1": "NRESET", "2": "GND"}, lcsc="C318884", mpn="TS-1187A-B-A-B")
part("SW2", "Switch:SW_Push", "FUNC", "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A", 14, 28,
     {"1": "BTN_FUNC", "2": "GND"}, lcsc="C318884", mpn="TS-1187A-B-A-B")
# Status LEDs, the same parts and wiring as the EnMT carrier (all JLC basic): anodes on 3.3 V,
# cathodes through the resistors to the pins; a pin pulled low lights its LED.
R("R9", "1k", 21, 34, "LED_R", "LED_RK", fp=FP_R0603, lcsc="C21190", mpn="0603WAF1001T5E", rot=270)
R("R10", "330", 21, 38, "LED_G", "LED_GK", fp=FP_R0603, lcsc="C23138", mpn="0603WAF3300T5E", rot=270)
R("R11", "1k", 21, 42, "LED_Y", "LED_YK", fp=FP_R0603, lcsc="C21190", mpn="0603WAF1001T5E", rot=270)
part("D1", "Device:LED", "RED", FP_LED, 13, 34, {"1": "LED_RK", "2": "+3V3"}, lcsc="C84256", mpn="NCD0805R1", rot=180)
part("D2", "Device:LED", "GREEN", FP_LED, 13, 38, {"1": "LED_GK", "2": "+3V3"}, lcsc="C2297", mpn="KT-0805G", rot=180)
part("D3", "Device:LED", "YELLOW", FP_LED, 13, 42, {"1": "LED_YK", "2": "+3V3"}, lcsc="C2296", mpn="KT-0805Y", rot=180)
# SWD: 2 x 5 pin header, 1.27 mm (ARM Cortex 10-pin), for the flat cable from the nRF52840 DK's
# Debug out (P19). Pin 1 VTref (the DK senses the target voltage), pin 9 GND detect (tells the DK
# a target is connected), pin 7 key. Hand-soldered.
part("J3", "Connector_Generic:Conn_02x05_Odd_Even", "SWD 10-pin",
     "Connector_PinHeader_1.27mm:PinHeader_2x05_P1.27mm_Vertical", 16, 52,
     {"1": "+3V3", "2": "SWDIO", "3": "GND", "4": "SWDCLK", "5": "GND", "6": "SWO",
      "7": None, "8": None, "9": "GND", "10": "NRESET"})


# ---------------------------------------------------------------- sheet layout
# Frames around the functional blocks: (title, x0, y0, x1, y1) in grid units.
GROUPS = [
    ("Buttons, LEDs, SWD", 5, 12, 36, 60),
    ("nRF52840 (PS config 3), 32 MHz crystal, 2.4 GHz match", 42, 12, 117, 92),
    ("TCM 515, 868 MHz", 118, 8, 160, 47),
    ("USB-C, ESD, 3.3 V LDO", 118, 50, 160, 97),
]
NOTES = [
    ("LEDs active low, as on the EnMT carrier: BOARD=enmt", 6, 46.5),
    ("Match at the ANT pin (PS config 7), then 50 ohm to the PCB antenna", 44, 49),
    ("No 32.768 kHz crystal: LF clock from the RC oscillator", 44, 77),
    ("open: 57600 baud", 126, 42.6),
]

# Wires: polylines of pin ends ("REF.PIN") and sheet points (grid units), horizontal
# and vertical only. Pins without a wire get a label / power symbol on their end.
WIRES = [
    # --- buttons, LED, SWD
    ["SW1.2", (18, 20), (18, 21)],
    ["SW2.2", (18, 28), (18, 29)],
    [(9, 34), (9, 42)],
    [(9, 34), "D1.2"],
    [(9, 38), "D2.2"],
    [(9, 42), "D3.2"],
    ["D1.1", "R9.2"],
    ["D2.1", "R10.2"],
    ["D3.1", "R11.2"],
    ["J3.1", (13, 50), (13, 49)],
    ["J3.3", (12, 51)],
    ["J3.5", (12, 52)],
    ["J3.9", (12, 54)],
    [(12, 51), (12, 55)],
    # --- nRF52840 decoupling: DEC pins to the caps on the left, VDD/VDDH to the right
    ["U1.C1", (88, 21), (83, 21), "C4.1"],
    ["U1.D23", (90, 20), (80, 20), "C5.1"],
    ["U1.B5", (91, 19)],
    ["U1.E24", (93, 19), (77, 19), "C6.1"],
    ["U1.AC5", (94, 18), (74, 18), "C8.1"],
    ["U1.B1", (96, 21), (113, 21)],
    ["U1.Y2", (97, 21)],
] + [[(x, 21), f"C{n}.1"] for n, x in ((9, 101), (10, 104), (11, 107), (12, 110), (13, 113))] + [
    ["U1.B7", (96, 88)],
    ["U1.F23", (97, 88), (96, 88)],
    # --- 32 MHz crystal
    ["U1.B24", (66, 56), "C15.1"],
    ["Y1.1", (66, 66)],
    ["U1.A23", (74, 60), "C16.1"],
    ["Y1.3", (74, 66)],
    # --- 2.4 GHz: ANT -> C19 / L1 -> C20 / L2 -> antenna
    ["U1.H23", "L1.1"],
    [(70, 40), "C19.1"],
    ["L1.2", "L2.1"],
    [(60, 40), "C20.1"],
    ["L2.2", (48, 40), "AE1.1"],
    # --- TCM 515: supply through FB1, RF_50 -> R7 -> whip, nTURBO strap
    [(120, 14), "FB1.1"],
    ["FB1.2", (134, 14), "U4.22"],
    [(128, 14), "C23.1"],
    [(131, 14), "C24.1"],
    ["U4.2", "R7.1"],
    ["R7.2", (156, 20), "TP1.1"],
    ["R6.2", "JP1.1"],
    [(122, 38.5), (125, 38.5)],
    # --- USB-C: VBUS rail to ESD, C2 and the LDO; D+/D- pairs to the ESD array
    ["J1.A4", "U2.3"],
    [(137, 62), "U3.5"],
    [(145, 62), "C2.1"],
    ["U2.2", (159, 62)],
    [(157, 62), "C3.1"],
    ["J1.A7", "U3.1"],
    ["J1.B7", (131, 68), (131, 67)],
    ["J1.A6", (133, 69), (133, 68), "U3.3"],
    ["J1.B6", (133, 70), (133, 69)],
    ["J1.SH", (121, 80), "C1.1"],
    [(121, 80), (127, 80), "R3.1"],
    ["R4.2", (137, 81), (144, 81)],
    [(141, 81), "C14.1"],
]

# Net names put on wires: (net, point, outward direction in degrees). Power nets get a
# power symbol, others a label. Untagged signal clusters get an automatic label.
TAGS = [
    ("GND", (18, 21), 270), ("GND", (18, 29), 270), ("+3V3", (9, 34), 90),
    ("+3V3", (13, 49), 90), ("GND", (12, 55), 270),
    ("+3V3", (96, 21), 90), ("GND", (96, 88), 270),
    ("+3V3", (120, 14), 90),
    ("TCM_NTURBO", (125, 38.5), 0), ("VDD_TCM", (125, 14), 0),
    ("VBUS", (134, 62), 90), ("+3V3", (159, 62), 90),
]

# Nets that need a PWR_FLAG (no power-output pin drives them); placed at (x, y) mm.
PWR_FLAGS = {
    "GND": (30 * G, 57 * G),
    "VBUS": (141 * G, 62 * G),
    "VBUS_NRF": (144 * G, 81 * G),
    "VDD_TCM": (133 * G, 14 * G),
}

# ---------------------------------------------------------------- JLCPCB part numbers
# (value, footprint) -> (LCSC, MPN) for parts that didn't name one above.
# Checked against jlcsearch.tscircuit.com on 2026-11-18; "basic" = JLC basic library.
JLC = {
    ("100nF", FP_C0402): ("C1525", "CL05B104KO5NNNC"),        # basic
    ("10nF", FP_C0402): ("C15195", "CL05B103KB5NNNC"),        # basic
    ("100pF", FP_C0402): ("C1546", "0402CG101J500NT"),        # basic
    ("12pF", FP_C0402): ("C1547", "0402CG120J500NT"),         # basic
    ("820pF", FP_C0402): ("C2929132", "FN15N821J500PNG"),     # DNP anyway
    ("1.0pF", FP_C0402): ("C72134", "GJM1555C1H1R0WB01D"),    # +-0.05 pF
    ("1.2pF", FP_C0402): ("C85877", "GJM1555C1H1R2CB01D"),  # +-0.25 pF, Murata high-Q (+-0.1/0.05 pF not stocked)
    ("1uF", FP_C0603): ("C15849", "CL10A105KB8NNNC"),         # basic
    ("4.7uF", FP_C0603): ("C19666", "CL10A475KO8NNNC"),       # basic
    ("22uF", FP_C0805): ("C45783", "CL21A226MAQNNNE"),        # basic, 25 V
    ("5.1k", FP_R0402): ("C25905", "0402WGF5101TCE"),         # basic
    ("10k", FP_R0402): ("C25744", "0402WGF1002TCE"),          # basic
    ("1k", FP_R0402): ("C11702", "0402WGF1001TCE"),           # basic
    ("1M", FP_R0402): ("C26083", "0402WGF1004TCE"),           # basic
    ("0", FP_R0402): ("C17168", "0402WGF0000TCE"),            # basic
    ("600R@100MHz", FP_L0603): ("C1002", "GZ1608D601TF"),     # basic, 600 ohm @ 100 MHz, 200 mA
    ("LED", "LED_SMD:LED_0603_1608Metric"): ("C2286", "KT-0603R"),   # basic, red
}
for _p in PARTS:
    if not _p["lcsc"] and (_p["value"], _p["footprint"]) in JLC:
        _p["lcsc"], _mpn = JLC[(_p["value"], _p["footprint"])]
        _p["mpn"] = _p["mpn"] or _mpn

# Footprint-only parts (copper, holes, test pads): not in the BOM, not assembled.
NOT_IN_BOM = {"AE1", "JP1", "J3"} | {p["ref"] for p in PARTS if p["ref"].startswith("TP")}
for _p in PARTS:
    _p["in_bom"] = _p["ref"] not in NOT_IN_BOM
