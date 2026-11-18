"""Board outline and part placement for enocean-bridge.kicad_pcb.

Board coordinates in mm, origin at the top-left board corner, y down; rotation
in degrees counter-clockwise (KiCad convention); side "F" (top) or "B" (bottom).

Left to right: 868 MHz whip/u.FL | TCM 515 | USB-C (bottom edge) | nRF52840 |
2.4 GHz PCB antenna (top-right corner). The TCM's RF pin faces the left end,
its UART pins face the nRF; the nRF's ANT pin faces the antenna.
"""

BOARD_W = 67.2
BOARD_H = 26.0

# 2.4 GHz antenna keepout (all copper layers): the antenna's area above the
# ground-plane edge, which runs just above the feed and short pads (y = 6.0).
ANT_KEEPOUT = (50.7, 0.0, BOARD_W, 5.6)          # x0, y0, x1, y1

# (x, y, rot, side)
PLACE = {
    # --- EnOcean
    "U4": (15.4, 12.0, 0, "F"),        # TCM 515; pin 2 RF_50 -> (6.5, 7.05)
    "R6": (15.5, 2.2, 0, "F"),         # nTURBO pull-up, pin 31 above
    "JP1": (18.8, 2.2, 0, "F"),        # nTURBO to GND (open)
    "C25": (22.5, 2.2, 0, "F"),        # nRESET filter, pin 24 above
    "FB1": (27.6, 5.4, 90, "F"),
    "C23": (27.6, 9.0, 90, "F"),       # 22 uF at VDD (pin 22 at (24.3, 9.0))
    "C24": (29.3, 9.0, 90, "F"),
    "C26": (1.6, 7.05, 180, "F"),      # 868 shunt (DNP), pad 1 on the node
    "R7": (3.0, 4.9, 90, "F"),         # to whip; rot 90 puts pad 1 (node side) at the bottom
    "TP1": (3.0, 2.2, 0, "F"),         # whip hole
    "R8": (3.0, 8.9, 270, "F"),        # to u.FL (DNP); rot 270 puts pad 1 (node side) on top
    "J2": (2.9, 12.6, 270, "F"),       # u.FL (DNP), signal pad facing R8
    # --- USB, power
    "J1": (31.5, 22.35, 0, "F"),       # front flush with the bottom edge
    "F1": (28.6, 16.0, 0, "F"),
    "U3": (39.4, 20.4, 0, "F"),        # ESD
    "U2": (29.8, 13.2, 0, "F"),        # LDO
    "C2": (27.0, 13.2, 90, "F"),
    "C3": (32.7, 15.2, 90, "F"),
    "R1": (29.9, 20.6, 90, "B"),       # CC1
    "R2": (33.1, 20.6, 90, "B"),       # CC2
    "R3": (25.2, 20.6, 90, "B"),       # shield
    "C1": (25.2, 23.2, 90, "B"),
    # --- nRF52840 (ANT at (42.25, 9.0))
    "U1": (39.5, 10.0, 0, "F"),
    "C9": (33.9, 6.6, 90, "F"),        # 1 uF, VDD B1
    "C4": (32.6, 8.4, 90, "F"),        # DEC1
    "C6": (37.5, 3.4, 90, "F"),        # 1 uF, DEC4/6
    "C5": (39.0, 3.4, 90, "F"),        # DEC3
    "C10": (40.5, 3.4, 90, "F"),       # VDD A22
    "C13": (33.9, 11.8, 90, "F"),      # 4.7 uF, VDD W1
    "R4": (37.4, 16.4, 90, "F"),       # VBUS series
    "C14": (38.8, 16.6, 90, "F"),      # VBUS_NRF
    "C8": (40.4, 16.6, 90, "F"),       # DECUSB
    "C11": (41.9, 16.4, 90, "F"),      # VDD AD14
    "C12": (43.2, 16.4, 90, "F"),      # VDD AD23
    "C7": (45.0, 12.6, 270, "F"),       # DEC5 (DNP)
    "Y1": (43.2, 3.4, 0, "F"),         # 32 MHz
    "C15": (46.3, 2.0, 0, "F"),
    "C16": (46.3, 4.4, 0, "F"),
    # --- 2.4 GHz RF along y = RF_Y from ANT (42.25, 9.0) to the antenna feed (54.4, 6.0).
    # RF_Y = 8.75 is the middle of the free channel between pads E24 and J24.
    # Series parts on the line, shunts below it with pad 1 on the line;
    # 0402 courtyards need 2.78 mm from shunt to shunt.
    "C19": (44.6, 9.23, 270, "F"),     # 1.0 pF
    "L1": (45.99, 8.75, 0, "F"),       # 4.7 nH
    "C20": (47.38, 9.23, 270, "F"),    # 1.2 pF
    "L2": (48.77, 8.75, 0, "F"),       # 2.2 nH
    "C21": (50.16, 9.23, 270, "F"),    # pi tuning (DNP)
    "R5": (51.55, 8.75, 0, "F"),       # pi tuning, 0 ohm
    "C22": (52.94, 9.23, 270, "F"),    # pi tuning (DNP)
    "AE1": (54.4, 6.0, 0, "F"),        # feed pad 1 here, ground pad 2 at x - 2.1
    # --- UI, debug
    "J3": (52.0, 16.2, 0, "F"),        # Tag-Connect TC2030
    "SW1": (50.5, 22.6, 0, "F"),       # RESET
    "SW2": (57.5, 22.6, 0, "F"),       # FUNC
    "R9": (58.5, 17.6, 0, "F"),
    "D1": (61.5, 17.6, 0, "F"),
    "H1": (2.8, 22.8, 0, "F"),
    "H2": (64.4, 23.2, 0, "F"),
}

# test points on the bottom, two rows under the TCM's lower half
_tps = ["TP2", "TP3", "TP4", "TP5", "TP6", "TP7", "TP8", "TP9", "TP10", "TP11", "TP12"]
for _i, _ref in enumerate(_tps):
    PLACE[_ref] = (7.0 + 2.8 * (_i % 6), 21.8 + 2.4 * (_i // 6), 0, "B")


RF_Y = 8.75
RF_NODE_868 = (3.0, 7.05)   # TCM pin 2 RF_50 is at (6.5, 7.05)
