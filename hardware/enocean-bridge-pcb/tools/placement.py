"""Board outline and part placement for enocean-bridge.kicad_pcb.

Board coordinates in mm, origin at the top-left board corner, y down; rotation
in degrees counter-clockwise (KiCad convention); side "F" (top) or "B" (bottom).

Left to right: 868 MHz whip | TCM 515 | USB-C (bottom edge) | nRF52840 |
2.4 GHz PCB antenna (along the right edge). The TCM's RF pin faces the left end,
its UART pins face the nRF; the nRF's ANT pin faces the antenna.
"""

BOARD_W = 57.0       # v0.1: 67.2; the antenna stands along the right edge
BOARD_H = 26.0

# 2.4 GHz PCB antenna (SWRA117D, "Left" variant turned 270 deg): it stands along the
# right board edge, radiating towards the edge, open end in the top-right corner, feed
# and short pads at its lower end. Feed pad at ANT_FEED; the antenna spans x feed-0.4 ..
# feed+5.64, y feed-12.35 .. feed+3.25.
ANT_FEED = (BOARD_W - 6.0, 12.7)
# Keepout (all copper layers): right of the ground-plane edge, which runs 0.4 mm right of
# the feed and short pads, down to just past the antenna's lower end.
ANT_KEEPOUT = (ANT_FEED[0] + 0.4, 0.0, BOARD_W, ANT_FEED[1] + 3.7)     # x0, y0, x1, y1

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
    "R7": (3.0, 4.9, 90, "F"),         # to whip; rot 90 puts pad 1 (node side) at the bottom
    "TP1": (3.0, 2.2, 0, "F"),         # whip hole
    # --- USB, power
    "J1": (31.5, 22.35, 0, "F"),       # front flush with the bottom edge
    "U3": (39.4, 20.4, 0, "F"),        # ESD
    "U2": (29.3, 13.2, 0, "F"),        # LDO (SOT-23-3)
    "C2": (26.4, 13.2, 90, "F"),
    "C3": (32.3, 13.4, 90, "F"),
    # all parts on top: one-sided assembly
    "R1": (30.2, 16.0, 90, "F"),       # CC1, above pad A5
    "R2": (33.3, 16.0, 90, "F"),       # CC2, above pad B5
    "R3": (25.0, 21.0, 90, "F"),       # shield, next to the left shell pads
    "C1": (25.0, 23.4, 90, "F"),
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
    # 32 MHz crystal turned 180 deg: XC2 pad bottom-left above the nRF's XC2 (A23), XC1 pad
    # top-right towards XC1 (B24) and C15, so the two lines don't cross
    "Y1": (43.2, 3.4, 180, "F"),       # 32 MHz
    "C15": (46.3, 2.0, 0, "F"),        # XC1 load cap, right of the crystal
    "C16": (40.9, 1.2, 180, "F"),      # XC2 load cap, top left; pad 1 (XC2) faces the crystal
    # --- 2.4 GHz RF along y = RF_Y from ANT (42.25, 9.0) to the antenna feed (ANT_FEED): 45 deg down right after L2, straight down, 45 deg into the feed.
    # RF_Y = 8.75 is the middle of the free channel between pads E24 and J24.
    # Series parts on the line, shunts below it with pad 1 on the line;
    # 0402 courtyards need 2.78 mm from shunt to shunt.
    "C19": (44.6, 9.23, 270, "F"),     # 1.0 pF
    "L1": (45.99, 8.75, 0, "F"),       # 4.7 nH
    "C20": (47.38, 9.23, 270, "F"),    # 1.2 pF
    "L2": (48.77, 8.75, 0, "F"),       # 2.2 nH
    "AE1": (ANT_FEED[0], ANT_FEED[1], 270, "F"),   # feed pad 1 here, short pad 2 at y + 2.1
    # --- UI, debug
    "J3": (47.0, 13.6, 0, "F"),        # SWD 2 x 5 header (1.27 mm), upright between C12 and the antenna; origin = pin 1
    # buttons below the TCM: only two lines (nRESET, P1.06) cross the board to them
    "SW1": (17.0, 23.1, 0, "F"),       # RESET (TS-1187A, courtyard 7.6 x 5.7 mm)
    "SW2": (8.5, 23.1, 0, "F"),        # FUNC
    # status LEDs in a row at the bottom edge near the nRF52840 (P1.11/13/15 are balls B19,
    # A16, A14 on its top edge): 4.0 mm apart and 3.4 mm from the edge, like the EnMT carrier,
    # so its case's light pipes (3 mm acrylic rods) fit. See LIGHT_PIPE_D.
    "D1": (44.0, 22.6, 0, "F"),        # red, PWR
    "D2": (48.0, 22.6, 0, "F"),        # green, LINK
    "D3": (52.0, 22.6, 0, "F"),        # yellow, RX
    # their resistors outside the light pipes, in the strip at the right edge
    "R9": (55.6, 24.1, 90, "F"),
    "R10": (55.6, 21.1, 90, "F"),
    "R11": (55.6, 18.1, 90, "F"),
}

# Board areas of the schematic's blocks (design.GROUPS, by title): one or more
# rectangles x0, y0, x1, y1 each.
# gen_pcb.py checks that every part with a net sits in the area of its block.
BLOCKS = {
    "TCM 515, 868 MHz": (0.0, 0.0, 30.0, 20.0),
    "USB-C, ESD, 3.3 V LDO": (22.0, 10.5, 42.0, BOARD_H),
    "nRF52840 (PS config 3), 32 MHz crystal, 2.4 GHz match": (30.0, 0.0, BOARD_W, 18.0),
    "Buttons, LEDs, SWD": [(42.0, 13.0, BOARD_W, BOARD_H),     # buttons, SWD header
                           (5.0, 20.0, 24.0, BOARD_H)],          # buttons below the TCM
}

# Light pipes over the LEDs, as in the carrier's case (case/carrier_case.scad): 3.2 mm bore
# for a 3 mm acrylic rod plus 0.8 mm walls. gen_pcb.py keeps every other part out of the
# circle of this diameter around each LED.
LIGHT_PIPE_D = 3.2 + 2 * 0.8
LIGHT_PIPE_LEDS = ("D1", "D2", "D3")

RF_Y = 8.75
RF_NODE_868 = (3.0, 7.05)   # TCM pin 2 RF_50 is at (6.5, 7.05)
