"""The EnOcean bridge circuit as data: every part, its pin -> net map and its
place on the A3 sheet. gen_schematic.py turns this into the KiCad schematic,
check_netlist.py compares KiCad's netlist against it.

Sources for values: nRF52840 PS v1.11 circuit configuration 3 (Fig. 220,
Table 75) and the 4-component RF match of configuration 7 (Table 83); TCM 515
User Manual v1.22 chapters 2 and 11. See ../DESIGN.md.

Coordinates are in mm on the sheet (y down), symbol origins on the 2.54 grid.
"""

G = 2.54

# Nets drawn with KiCad power symbols (power:<name>); all others get net labels.
POWER_NETS = {"GND", "+3V3", "VBUS"}

# Nets that need a PWR_FLAG (no power-output pin drives them); placed at (x, y).
PWR_FLAGS = {
    "GND": (30 * G, 108 * G),
    "VBUS": (36 * G, 108 * G),
    "VBUS_NRF": (42 * G, 108 * G),
    "VDD_TCM": (48 * G, 108 * G),
}

FP_R0402 = "Resistor_SMD:R_0402_1005Metric"
FP_C0402 = "Capacitor_SMD:C_0402_1005Metric"
FP_C0603 = "Capacitor_SMD:C_0603_1608Metric"
FP_C0805 = "Capacitor_SMD:C_0805_2012Metric"
FP_L0402 = "Inductor_SMD:L_0402_1005Metric"
FP_L0603 = "Inductor_SMD:L_0603_1608Metric"
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
     14, 22, {
         "A4": "VBUS_USB", "A9": "VBUS_USB", "B4": "VBUS_USB", "B9": "VBUS_USB",
         "A5": "CC1", "B5": "CC2",
         "A6": "USB_DP", "B6": "USB_DP", "A7": "USB_DM", "B7": "USB_DM",
         "A8": None, "B8": None,
         "A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND",
         "SH": "USB_SHIELD",
     }, lcsc="C165948", mpn="HRO TYPE-C-31-M-12")
R("R1", "5.1k", 26, 40, "CC1", "GND")
R("R2", "5.1k", 30, 40, "CC2", "GND")
R("R3", "1M", 6, 40, "USB_SHIELD", "GND")
C("C1", "10nF", 10, 40, "USB_SHIELD", "GND")
part("F1", "Device:Polyfuse", "500mA", "Fuse:Fuse_0805_2012Metric", 34, 14, {"1": "VBUS_USB", "2": "VBUS"},
     lcsc="C269104", mpn="SMD0805B050TF")
part("U3", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6", 42, 30,
     {"1": "USB_DM", "6": "USB_DM", "3": "USB_DP", "4": "USB_DP", "5": "VBUS", "2": "GND"},
     lcsc="C3029034", mpn="USBLC6-2SC6")
part("U2", "Regulator_Linear:AP2112K-3.3", "AP2112K-3.3", "Package_TO_SOT_SMD:SOT-23-5", 54, 14,
     {"1": "VBUS", "3": "VBUS", "2": "GND", "4": None, "5": "+3V3"}, lcsc="C51118", mpn="AP2112K-3.3TRG1")
C("C2", "4.7uF", 44, 14, "VBUS", fp=FP_C0603)
C("C3", "4.7uF", 64, 14, "+3V3", fp=FP_C0603)

# ---------------------------------------------------------------- nRF52840
NRF = {
    # supply (configuration 3: VDDH tied to VDD, DCCH unconnected)
    "B1": "+3V3", "A22": "+3V3", "AD14": "+3V3", "AD23": "+3V3", "W1": "+3V3",
    "Y2": "+3V3", "AB2": None,
    "B7": "GND", "F23": "GND", "EP": "GND",
    "C1": "DEC1", "D23": "DEC3", "B5": "DEC4_6", "E24": "DEC4_6", "N24": "DEC5",
    "AC5": "DECUSB", "A18": None, "B3": None,
    "B24": "XC1", "A23": "XC2", "D2": None, "F2": None,
    "H23": "RF_ANT",
    # USB
    "AD2": "VBUS_NRF", "AD4": "USB_DM", "AD6": "USB_DP",
    # Pro Micro pin contract (firmware/enocean-gateway/boards/promicro_nrf52840_common.dtsi)
    "L24": "TCM_RX",        # P0.09 UART0 TX -> TCM UART_RX
    "J24": "TCM_TX",        # P0.10 UART0 RX <- TCM UART_TX
    "AD10": "LED",          # P0.15 led0
    "R24": "BTN_FUNC",      # P1.06 sw0
    "AC13": "NRESET",       # P0.18 nRESET
    "AD16": "TCM_NRESET",   # P0.20, new: TCM reset from firmware
    "AC24": "SWDIO", "AA24": "SWDCLK", "AD22": "SWO",
}
part("U1", "MCU_Nordic:nRF52840", "nRF52840-QIAA", "Package_DFN_QFN:Nordic_AQFN-73-1EP_7x7mm_P0.5mm",
     88, 60, NRF, nc_rest=True, lcsc="C3606858", mpn="NRF52840-QIAA-F-R7")

# decoupling, one cap per pin (PS reference designators in comments)
C("C4", "100nF", 60, 40, "DEC1")                        # C5
C("C5", "100pF", 63, 40, "DEC3")                        # C11
C("C6", "1uF", 66, 40, "DEC4_6", fp=FP_C0603)           # C15
C("C7", "820pF", 69, 40, "DEC5", dnp=True)              # C9, not needed on Fxx
C("C8", "4.7uF", 72, 40, "DECUSB", fp=FP_C0603)         # C20
C("C9", "1uF", 60, 52, "+3V3", fp=FP_C0603)             # C14 at VDD B1
C("C10", "100nF", 63, 52, "+3V3")                       # C12 at VDD A22
C("C11", "100nF", 66, 52, "+3V3")                       # C7 at VDD AD14
C("C12", "100nF", 69, 52, "+3V3")                       # C8 at VDD AD23
C("C13", "4.7uF", 72, 52, "+3V3", fp=FP_C0603)          # C6 at VDD W1
R("R4", "2.2", 60, 66, "VBUS", "VBUS_NRF")              # optional series R on VBUS
C("C14", "4.7uF", 64, 66, "VBUS_NRF", fp=FP_C0603)      # C21

# 32 MHz crystal (X1, C1, C2 in the PS)
part("Y1", "Device:Crystal_GND24", "32MHz 8pF", "Crystal:Crystal_SMD_2016-4Pin_2.0x1.6mm", 120, 22,
     {"1": "XC1", "3": "XC2", "2": "GND", "4": "GND"}, lcsc="C5189005", mpn="ABM11W-32.0000MHZ-8-D1X-T3")
C("C15", "12pF", 115, 30, "XC1")
C("C16", "12pF", 125, 30, "XC2")
# No 32.768 kHz crystal: the firmware runs the LF clock from the RC oscillator, like the
# Pro Micro, and XL2 (F2) can't escape the aQFN at JLC's 0.1 mm minimum anyway.

# RF: 4-component match at the ANT pin, then the 50 ohm line, pi tuning pads, PCB antenna
C("C19", "1.0pF", 112, 62, "RF_ANT")                    # C3
L("L1", "4.7nH", 116, 62, "RF_ANT", "RF_M1", lcsc="C97989", mpn="LQG15HN4N7S02D")
C("C20", "1.2pF", 120, 62, "RF_M1")                     # C4
L("L2", "2.2nH", 124, 62, "RF_M1", "RF_2G4", lcsc="C162540", mpn="LQG15HS2N2B02D")   # L5
C("C21", "DNP", 128, 62, "RF_2G4", dnp=True)            # pi tuning
R("R5", "0", 132, 62, "RF_2G4", "RF_ANT_2G4")           # pi tuning, series
C("C22", "DNP", 136, 62, "RF_ANT_2G4", dnp=True)        # pi tuning
part("AE1", "Device:Antenna_Shield", "2.4GHz PCB", "RF_Antenna:Texas_SWRA117D_2.4GHz_Right", 142, 58,
     {"1": "RF_ANT_2G4", "2": "GND"})

# ---------------------------------------------------------------- TCM 515
part("U4", "EnOcean:TCM515", "TCM515", "EnOcean:TCM515", 136, 86, {
    "22": "VDD_TCM", "24": "TCM_NRESET", "31": "TCM_NTURBO",
    "20": "TCM_RX", "21": "TCM_TX",
    "2": "RF_868", "25": "TCM_TP1", "26": "TCM_TP2", "27": "TCM_TP3",
    "1": "GND", "3": "GND", "6": "GND", "15": "GND", "23": "GND",
}, mpn="TCM 515 (hand-solder, not at JLC)")
part("FB1", "Device:FerriteBead", "600R@100MHz", FP_L0603, 112, 74, {"1": "+3V3", "2": "VDD_TCM"},
     mpn="742863160 or eq.")
C("C23", "22uF", 115, 74, "VDD_TCM", fp=FP_C0805)
C("C24", "100nF", 118, 74, "VDD_TCM")
C("C25", "100nF", 121, 74, "TCM_NRESET")                # manual Figure 20
R("R6", "10k", 124, 74, "VDD_TCM", "TCM_NTURBO")
part("JP1", "Jumper:SolderJumper_2_Open", "460k8", "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
     116, 82, {"1": "TCM_NTURBO", "2": "GND"})
C("C26", "DNP", 148, 76, "RF_868", dnp=True)            # tuning shunt
R("R7", "0", 152, 76, "RF_868", "ANT_868")              # whip
R("R8", "0", 156, 76, "RF_868", "RF_UFL", dnp=True)     # u.FL instead of whip
TP("TP1", "ANT_868", 152, 86, fp="TestPoint:TestPoint_THTPad_D2.0mm_Drill1.0mm", value="WHIP 86mm")
part("J2", "Connector:Conn_Coaxial", "U.FL", "Connector_Coaxial:U.FL_Hirose_U.FL-R-SMT-1_Vertical", 157, 90,
     {"1": "RF_UFL", "2": "GND"}, dnp=True, lcsc="C88374", mpn="U.FL-R-SMT-1(80)")

# ---------------------------------------------------------------- UI, debug
part("SW1", "Switch:SW_Push", "RESET", "Button_Switch_SMD:SW_Push_1P1T_NO_CK_KMR2", 14, 70,
     {"1": "NRESET", "2": "GND"})
part("SW2", "Switch:SW_Push", "FUNC", "Button_Switch_SMD:SW_Push_1P1T_NO_CK_KMR2", 14, 78,
     {"1": "BTN_FUNC", "2": "GND"})
R("R9", "1k", 28, 70, "LED", "LED_A")
part("D1", "Device:LED", "LED", "LED_SMD:LED_0603_1608Metric", 28, 80, {"2": "LED_A", "1": "GND"}, rot=90)
part("J3", "Connector_Generic:Conn_02x03_Odd_Even", "TC2030 SWD",
     "Connector:Tag-Connect_TC2030-IDC-NL_2x03_P1.27mm_Vertical", 42, 72,
     {"1": "+3V3", "2": "SWDIO", "3": "NRESET", "4": "SWDCLK", "5": "GND", "6": "SWO"})

for i, net in enumerate(["+3V3", "GND", "VBUS", "SWDIO", "SWDCLK", "TCM_TX", "TCM_RX",
                         "TCM_NRESET", "TCM_TP1", "TCM_TP2", "TCM_TP3"]):
    TP(f"TP{i + 2}", net, 10 + 6 * i, 94)

part("H1", "Mechanical:MountingHole", "M2", "MountingHole:MountingHole_2.2mm_M2", 10, 104, {})
part("H2", "Mechanical:MountingHole", "M2", "MountingHole:MountingHole_2.2mm_M2", 16, 104, {})

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
    ("1.2pF", FP_C0402): ("", "GJM1555C1H1R2WB01D (not found at JLC search; any 1.2 pF +-0.1 pF C0G 0402)"),
    ("1uF", FP_C0603): ("C15849", "CL10A105KB8NNNC"),         # basic
    ("4.7uF", FP_C0603): ("C19666", "CL10A475KO8NNNC"),       # basic
    ("22uF", FP_C0805): ("C45783", "CL21A226MAQNNNE"),        # basic, 25 V
    ("5.1k", FP_R0402): ("C25905", "0402WGF5101TCE"),         # basic
    ("10k", FP_R0402): ("C25744", "0402WGF1002TCE"),          # basic
    ("1k", FP_R0402): ("C11702", "0402WGF1001TCE"),           # basic
    ("1M", FP_R0402): ("C26083", "0402WGF1004TCE"),           # basic
    ("0", FP_R0402): ("C17168", "0402WGF0000TCE"),            # basic
    ("2.2", FP_R0402): ("C2909330", "FRC0402F2R20TS"),
    ("600R@100MHz", FP_L0603): ("C1002", "GZ1608D601TF"),     # basic, 600 ohm @ 100 MHz, 200 mA
    ("LED", "LED_SMD:LED_0603_1608Metric"): ("C2286", "KT-0603R"),   # basic, red
    ("RESET", "Button_Switch_SMD:SW_Push_1P1T_NO_CK_KMR2"): ("C269272", "KMR221NGLFS"),
    ("FUNC", "Button_Switch_SMD:SW_Push_1P1T_NO_CK_KMR2"): ("C269272", "KMR221NGLFS"),
}
for _p in PARTS:
    if not _p["lcsc"] and (_p["value"], _p["footprint"]) in JLC:
        _p["lcsc"], _mpn = JLC[(_p["value"], _p["footprint"])]
        _p["mpn"] = _p["mpn"] or _mpn

# Footprint-only parts (copper, holes, test pads): not in the BOM, not assembled.
NOT_IN_BOM = {"AE1", "JP1", "J3", "H1", "H2"} | {p["ref"] for p in PARTS if p["ref"].startswith("TP")}
for _p in PARTS:
    _p["in_bom"] = _p["ref"] not in NOT_IN_BOM
