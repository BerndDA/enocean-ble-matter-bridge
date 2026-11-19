"""Board outline and part placement for enocean-carrier.kicad_pcb.

Board coordinates in mm, origin at the top-left corner, y down; rotation in
degrees counter-clockwise; side "F" (top) or "B" (bottom).

The Pro Micro sits on the left with its USB end flush with the top edge and
its antenna end flush with the bottom edge (the footprint keeps copper out
from under the antenna). The TCM 515 stands upright next to it (rotated 270
degrees): VDD and UART pins at its bottom edge, next to the Pro Micro's
P0.09/P0.10; RF_50 at its top edge, facing the whip and u.FL in the top-right
corner, as far as possible from the Pro Micro's 2.4 GHz antenna.
"""

BOARD_W = 46.5
BOARD_H = 33.4

# nothing like the custom board's 2.4 GHz keepout here (stitch.py expects the name)
ANT_KEEPOUT = (-10.0, -10.0, -9.0, -9.0)

# TCM 515 at (27.6, 14.0), rot 270 -> pads: RF_50 (32.55, 5.1) top edge;
# VDD (30.6, 22.9), UART_RX (28.6, 22.9), UART_TX (29.6, 22.9) bottom edge;
# nRESET (34.35, 21.1), nTURBO (34.35, 14.1) right edge. Courtyard x 19.85..35.35, y 4.1..23.9.
TCM = (27.6, 14.0)

# 868 MHz: RF_50 up to y = RF_Y, right to the node; node -> R2 -> whip (right),
# node -> R3 -> u.FL (down), C4 shunt on the line
RF_Y = 2.6
RF_NODE_868 = (38.6, RF_Y)

# (x, y, rot, side); the Pro Micro footprint's origin is pad 1 (USB end, left column)
PLACE = {
    "U1": (2.4, 2.7, 0, "F"),          # module outline x 1.0..19.0, y 0.0..33.3
    "U2": (TCM[0], TCM[1], 270, "F"),
    # TCM supply, below the module next to VDD
    "C2": (31.6, 25.9, 270, "F"),      # 100 nF, closest to VDD; rot 270: pad 1 (VDD) on top
    "C1": (33.9, 25.9, 270, "F"),      # 22 uF
    "FB1": (36.2, 25.9, 270, "F"),
    # right edge of the module
    "R1": (37.4, 14.1, 180, "F"),      # nTURBO pull-up, pad 2 (nTURBO) facing the pin
    "JP1": (41.0, 14.1, 0, "F"),
    "C3": (37.4, 21.1, 0, "F"),        # nRESET filter, pad 1 facing the pin
    # 868 MHz, top-right corner
    "C4": (36.4, 3.65, 270, "F"),      # shunt (DNP), pad 1 on the line
    "R2": (40.6, RF_Y, 0, "F"),        # to the whip
    "TP1": (44.4, RF_Y, 0, "F"),       # whip hole
    "R3": (38.6, 5.6, 270, "F"),       # to the u.FL (DNP), pad 1 on top
    "J1": (43.9, 9.5, 0, "F"),         # u.FL (DNP) at the right edge, signal pad facing R3
    # EnOcean LED (P1.11) right of the module, resistor below it: R4 pad 2 under D1 pad 2 (anode)
    "D1": (41.6, 18.0, 0, "F"),
    "R4": (41.6, 20.4, 0, "F"),
    # buttons (TS-1187A, 5.1 x 5.1 mm) side by side along the bottom edge, same orientation:
    # FUNC (P1.06) left, RESET right; holes
    "SW2": (29.0, 30.75, 0, "F"),
    "SW1": (41.6, 30.75, 0, "F"),
    "H1": (22.2, 30.7, 0, "F"),
    "H2": (42.4, 24.2, 0, "F"),
}
