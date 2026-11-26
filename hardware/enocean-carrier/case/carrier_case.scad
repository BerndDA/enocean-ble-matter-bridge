// 3D-printable case for the EnOcean carrier board (hardware/enocean-carrier).
//
// Parts (choose with `part`): "plate" (everything for one print: base, lid, 4 pins incl. 2 spares),
// "base", "lid", "pin" (two needed), or "assembly" (preview).
//   openscad -D 'part="base"' -o base.stl carrier_case.scad
// tools/export_case.sh renders all STLs and preview PNGs.
//
// Board positions are taken from the KiCad layout (placement.py): board coordinates
// x right, y down from the USB edge; here mapped to X = x, Y = BOARD_H - y.
// Heights above the board are estimates: measure your Pro Micro stack and adjust
// pm_mount / the pm_* values before printing.

part = "assembly";

// ---------------------------------------------------------------- print process
// The fits below depend on how the parts are printed:
//   "fdm": holes come out ~0.1-0.2 mm small and round parts a little fat: generous clearances
//   "sla": resin (SLA/MSLA/DLP) prints close to size: tight clearances, or parts rattle and rods fall out
// tools/export_case.sh writes carrier_case-<part>.stl (FDM) and carrier_case-<part>-sla.stl.
process  = "fdm";
SLA      = process == "sla";

// ---------------------------------------------------------------- how the Pro Micro sits
// "direct": soldered on male pin headers (plastic spacer 2.5 mm)   -> Pro Micro 2.5 mm above the board
// "socket": female headers (8.5 mm) + male header spacer (2.5 mm) -> Pro Micro 11 mm above the board
pm_mount = "direct";
pm_gap   = pm_mount == "socket" ? 11.0 : 2.5;   // carrier top -> Pro Micro bottom
pm_pcb   = 1.2;                                 // Pro Micro board thickness (SuperMini 1.0-1.2, nice!nano 1.0)
pm_parts = 3.5;                                 // tallest part on the Pro Micro (USB-C receptacle ~3.2)
// USB-C receptacle (3.2 mm high) on the Pro Micro:
//   "bottom": sunk into a notch of the module, its underside flush with the module's underside
//             (measured on the board that arrived)
//   "mid":    centred on the module's PCB
//   "top":    on top of the module's PCB
pm_usb   = "bottom";
usb_rh   = 3.2;                                 // receptacle height
usb_z    = pm_gap + (pm_usb == "bottom" ? usb_rh / 2 : pm_usb == "mid" ? pm_pcb / 2 : pm_pcb + usb_rh / 2);   // USB-C centre above the carrier top
// USB opening: a stadium (oval with straight sides, like a USB-C plug's overmold) around the
// receptacle, big enough for the cable's plug body to reach in. Measure your cable's plug.
usb_hole_w = 12.4;
usb_hole_h = 6.6;

// ---------------------------------------------------------------- options
// How the board is held at H1 (2.2 mm hole):
//   "peg":   a printed peg on the floor goes up through H1, a tube under the lid presses the board
//            down around it. No screw, closed floor.
//   "screw": M2 screw from the top through board and floor into a hex nut in the underside.
board_fix  = "peg";
peg_d      = SLA ? 2.1 : 2.0;   // in the 2.2 mm hole; FDM pegs come out a little thin, so it isn't loose
sma_hole   = false;   // 6.5 mm hole in the right wall for an SMA bulkhead (u.FL pigtail instead of the whip)
whip_hole  = true;    // 3 mm hole in the lid above the whip pad: the 86 mm wire (up to 1.5 mm) goes straight up
light_pipe = true;    // a solid block from the lid down to just above the LEDs, one bore per LED, each holds a clear acrylic rod
rod_d      = 3.0;     // acrylic (PMMA) rods pressed into the light pipes
pipe_bore  = rod_d + (SLA ? 0.1 : 0.2);   // snug fit: FDM holes come out ~0.1-0.2 mm small, SLA ones close to size (resin over-cure ~0.05)
pipe_wall  = 0.8;     // also the wall between two pipes (LEDs 4 mm apart): two lines of a 0.4 mm nozzle
// piezo disc under the lid, over the TCM (the only spot with ~6 mm of height): the disc's rim rests
// on a ledge, a dab of glue in the lip below holds it; the chamber in front of it and the sound hole
// form a Helmholtz resonator (~4.5 kHz with these values: a smaller hole lowers it)
piezo      = true;
piezo_d    = 15.0;    // brass disc, e.g. Murata 7BB-15-6 (15 mm, 10 mm ceramic, 6 kHz) or equivalent
piezo_t    = 0.3;     // disc thickness (brass + ceramic)
piezo_at   = [28.0, 18.5];   // board coordinates of the centre: sound hole clear of the engraving
piezo_ch   = 1.2;     // front chamber between lid and disc
piezo_ledge = 0.8;    // the rim rests on this much of a ledge
piezo_lip  = 0.8;     // ring below the disc, for the glue
piezo_wall = 1.2;
piezo_hole = 2.5;     // sound hole through the lid

// ---------------------------------------------------------------- labels engraved in the lid top
labels     = true;
small_labels = false; // FUNC/RST/PWR/LINK/RX/868 next to buttons and LEDs: too fine for FDM, OK on MJF/SLS/resin
name       = "EnMT";  // product name, large, over the Pro Micro / TCM area ("" = none)
logo       = true;    // the EnMT logo (radio waves + triangle of nodes) left of the name
logo_h     = 9.0;     // logo height
label_font = "Liberation Sans:style=Bold";
label_d    = 0.6;     // engraving depth
label_grow = 0.12;    // widens the strokes by 2 x this: grooves >= 0.5 mm, printable on MJF/SLS/resin
label_h    = 2.0;     // small labels (cap height about 0.7 x this)
name_h     = 5.5;

// ---------------------------------------------------------------- board (from the PCB)
BOARD_W = 46.5;
BOARD_H = 33.4;
BOARD_T = 1.6;
function P(x, y) = [x, BOARD_H - y];      // KiCad board coordinates -> case coordinates

HOLES   = [P(22.2, 30.7)];               // H1: M2 (v0.1 had a second hole, H2, where the LEDs are now)
BUTTONS = [P(29.0, 30.75), P(41.6, 30.75)];  // SW2 FUNC, SW1 RESET (XKB TS-1187A, 5.1 x 5.1 x 1.5 mm)
LEDS    = [P(43.2, 16.4), P(43.2, 20.4), P(43.2, 24.4)];   // D1 red, D2 green, D3 yellow (0805)
WHIP    = P(44.4, 2.6);                   // TP1
UFL     = P(43.9, 9.5);                   // J1
PIEZO   = P(piezo_at[0], piezo_at[1]);
// wire pads (v0.4): first and last hole of each row, KiCad board coordinates
WIRE_PADS = [[[21.0, 1.75], [28.62, 1.75]],    // J2 I2C (SCL SDA 3V3 GND)
             [[21.0, 26.4], [23.54, 26.4]]];   // J3 piezo
USB_X   = 2.4 + 15.24 / 2;                // Pro Micro centre line (pads at x 2.4 and 17.64)
SW_H    = 1.5;                            // switch height above the board
LED_H   = 0.8;                            // 0805 LEDs

// [text, board x, board y, size, halign]; LEDs: D1 red PWR, D2 green LINK, D3 yellow RX
LABELS = [
    ["FUNC",  26.4, 30.75, label_h, "right"],   // left of each button
    ["RST",   39.0, 30.75, label_h, "right"],
    ["PWR",   41.0, 16.4, label_h, "right"],
    ["LINK",  41.0, 20.4, label_h, "right"],
    ["RX",    41.0, 24.4, label_h, "right"],
    ["868",   42.4,  2.6, label_h, "right"],
];
NAME_AT = [14.5, 10.5];                   // board coordinates of the centre of logo + name

// ---------------------------------------------------------------- case
hold_d   = 4.2;     // hold-down tube under the lid, inside H1's 4.9 mm keep-out
wall     = 2.0;
floor_t  = 3.0;     // the board lies on the floor; pockets take the solder joints
pocket_d = 2.0;     // pocket depth under the pin rows and the whip pad
gap      = 0.4;     // board to wall, each side
under    = 0.0;     // floor to board bottom
usb_head = 1.5;     // extra height: leaves 2.1 mm of base wall above the USB opening (0.6 mm without)
inner_h  = pm_gap + pm_pcb + pm_parts + 0.8 + usb_head;   // board top to lid underside
lid_t    = 2.0;
lip_h    = 3.0;     // lid lip reaching into the base
piezo_ring_h = piezo_ch + piezo_t + piezo_lip;   // how far the piezo ring hangs below the lid
pipe_len = inner_h - LED_H - 0.5;          // light pipes below the lid, end 0.5 mm above the LEDs
rod_len  = pipe_len + lid_t;               // rod flush with the lid top and the pipe end
fit      = SLA ? 0.12 : 0.25;   // lip clearance per side
$fn = 48;

IN_W = BOARD_W + 2 * gap;
IN_D = BOARD_H + 2 * gap;
OUT_W = IN_W + 2 * wall;
OUT_D = IN_D + 2 * wall;
board_z = floor_t + under;                 // board bottom
top_z   = board_z + BOARD_T;               // board top
base_h  = top_z + inner_h;                 // top of the base walls = underside of the lid
function B(p) = [p[0] + wall + gap, p[1] + wall + gap];   // board coordinates -> base coordinates

module rounded_box(w, d, h, r = 1.5) {
    hull() for (x = [r, w - r], y = [r, d - r]) translate([x, y, 0]) cylinder(r = r, h = h);
}

// pin rows of the Pro Micro headers (board x 2.4 and 17.64, pins y 3.81 .. 31.75, nice!nano v2)
PIN_ROWS_X = [2.4, 17.64];

module base() {
    // locating peg through H1, 1 mm above the board, tip chamfered so the board slides on
    if (board_fix == "peg") for (h = HOLES) translate([B(h)[0], B(h)[1], floor_t - 0.01]) {
        cylinder(d = peg_d, h = top_z - floor_t + 0.6);
        translate([0, 0, top_z - floor_t + 0.6]) cylinder(d1 = peg_d, d2 = peg_d - 0.8, h = 0.4);
    }
    difference() {
        difference() {
            rounded_box(OUT_W, OUT_D, base_h);
            translate([wall, wall, floor_t]) cube([IN_W, IN_D, base_h]);
        }
        // pockets for the solder joints on the board's underside (trim the pin ends flush)
        for (x = PIN_ROWS_X) {
            p0 = B(P(x - 1.6, 33.0));
            translate([p0[0], p0[1], floor_t - pocket_d]) cube([3.2, 31.0, pocket_d + 1]);
        }
        translate([B(WHIP)[0], B(WHIP)[1], floor_t - pocket_d]) cylinder(d = 5.0, h = pocket_d + 1);   // whip pad 3.2 mm + solder
        // wire pads J2 / J3: 1.6 mm pads, wire ends and solder below
        for (r = WIRE_PADS) {
            p0 = B(P(r[0][0] - 1.4, r[0][1] + 1.3));
            translate([p0[0], p0[1], floor_t - pocket_d]) cube([r[1][0] - r[0][0] + 2.8, 2.6, pocket_d + 1]);
        }
        // M2 screws from the top through board and floor into hex nuts in the underside
        if (board_fix == "screw") for (h = HOLES) {
            translate([B(h)[0], B(h)[1], -1]) cylinder(d = 2.4, h = floor_t + 2);
            translate([B(h)[0], B(h)[1], -0.01]) cylinder(d = 4.8, h = 1.8, $fn = 6);
        }
        // USB-C opening in the end wall (board y = 0 is the top wall here)
        usb_hole();
        if (sma_hole)
            translate([OUT_W - wall - 1, B(UFL)[1], top_z + 6]) rotate([0, 90, 0]) cylinder(d = 6.5, h = wall + 2);
    }
}

// The USB opening through the end wall, in base coordinates. Where its top reaches above the base
// wall (a top-mounted receptacle, or pm_mount = "socket" with a low lid), the lid's underside takes
// the same cut, so base and lid together form the full oval.
module usb_hole() {
    r = usb_hole_h / 2;
    hull() for (dx = [-1, 1] * (usb_hole_w / 2 - r))
        translate([B([USB_X, 0])[0] + dx, OUT_D - wall - 1, top_z + usb_z]) rotate([-90, 0, 0]) cylinder(r = r, h = wall + 2, $fn = 96);
}

module engrave(t, p, size, halign) {
    translate([B(p)[0], B(p)[1], lid_t - label_d]) linear_extrude(label_d + 1)
        offset(delta = label_grow) text(t, size = size, font = label_font, halign = halign, valign = "center");
}

// EnMT logo, drawn in the source image's pixel space (y down, ~230 x 200 px), scaled to logo_h:
// two radio-wave arcs left of a node, which links to two nodes on the right (a triangle)
LOGO_NODES = [[110, 100, 17], [198, 38, 19], [198, 162, 19]];   // x, y, radius
module logo2d() {
    k = logo_h / 162;
    scale([k, -k]) translate([-140, -100]) {
        for (n = LOGO_NODES) translate([n[0], n[1]]) circle(r = n[2]);
        for (e = [[0, 1], [0, 2], [1, 2]])
            hull() for (i = e) translate([LOGO_NODES[i][0], LOGO_NODES[i][1]]) circle(r = 8);
        for (r = [42, 68]) translate([LOGO_NODES[0][0], LOGO_NODES[0][1]]) arc2d(r, 6.5, 180 - 42, 180 + 42);
    }
}
module arc2d(r, w, a0, a1) {           // stroke of width 2w with round ends
    intersection() {
        difference() { circle(r = r + w, $fn = 96); circle(r = r - w, $fn = 96); }
        polygon([[0, 0], for (a = [a0 : 2 : a1]) (r + 2 * w) * [cos(a), sin(a)]]);
    }
    for (a = [a0, a1]) translate(r * [cos(a), sin(a)]) circle(r = w);
}
// logo, a gap, then the name; centred as a group around the origin
module brand2d() {
    lw = logo ? logo_h * 1.12 : 0;              // logo width (~182 x 162 px)
    tw = name == "" ? 0 : len(name) * name_h * 0.78;   // rough text width (bold caps)
    gap = (logo && name != "") ? 2.0 : 0;
    x0 = -(lw + gap + tw) / 2;
    if (logo) translate([x0 + lw / 2, 0]) logo2d();
    if (name != "") translate([x0 + lw + gap, 0]) offset(delta = label_grow)
        text(name, size = name_h, font = label_font, halign = "left", valign = "center");
}

module lid() {
    difference() {
        union() {
            rounded_box(OUT_W, OUT_D, lid_t);
            // lip into the base
            translate([wall + fit, wall + fit, -lip_h]) difference() {
                cube([IN_W - 2 * fit, IN_D - 2 * fit, lip_h]);
                translate([1.2, 1.2, -1]) cube([IN_W - 2 * fit - 2.4, IN_D - 2 * fit - 2.4, lip_h + 2]);
            }
            // hold-down tube: presses the board onto the floor around the peg
            if (board_fix == "peg")
                for (h = HOLES) translate([B(h)[0], B(h)[1], -inner_h]) cylinder(d = hold_d, h = inner_h);
            // light pipes: one rectangular block around all three bores, down to just above the LEDs,
            // reaching out to the lip's outer face so block and lip are one piece
            if (light_pipe) {
                r  = pipe_bore / 2 + pipe_wall;
                x0 = min([for (l = LEDS) B(l)[0]]) - r;
                y0 = min([for (l = LEDS) B(l)[1]]) - r;
                y1 = max([for (l = LEDS) B(l)[1]]) + r;
                translate([x0, y0, -pipe_len]) cube([OUT_W - wall - fit - x0, y1 - y0, pipe_len]);
            }
            // piezo ring
            if (piezo) translate([B(PIEZO)[0], B(PIEZO)[1], -piezo_ring_h])
                cylinder(d = piezo_d + 0.3 + 2 * piezo_wall, h = piezo_ring_h, $fn = 96);
        }
        // the buttons sit close to the front edge: notch the lip around each pin collar
        for (b = BUTTONS) translate([B(b)[0], B(b)[1], -lip_h - 1]) cylinder(d = pin_collar_d + 1.0, h = lip_h + 1);
        // the lip must not cover the USB opening: cut it there
        translate([B([USB_X, 0])[0] - 6.5, OUT_D - wall - 2, -lip_h - 1]) cube([13, 3, lip_h + 1]);
        translate([0, 0, -base_h]) usb_hole();   // the top of the oval
        if (light_pipe)
            for (l = LEDS) translate([B(l)[0], B(l)[1], -inner_h]) cylinder(d = pipe_bore, h = inner_h + lid_t + 1);
        // room for the peg's tip inside the hold-down tube
        if (board_fix == "peg")
            for (h = HOLES) translate([B(h)[0], B(h)[1], -inner_h - 1]) cylinder(d = peg_d + 0.6, h = 1 + 1.5);
        // piezo: bore for the disc and its glue lip, chamber, sound hole, wire notch toward J3
        if (piezo) translate([B(PIEZO)[0], B(PIEZO)[1], 0]) {
            translate([0, 0, -piezo_ring_h - 1]) cylinder(d = piezo_d + 0.3, h = piezo_ring_h + 1 - piezo_ch, $fn = 96);
            translate([0, 0, -piezo_ch - 0.01]) cylinder(d = piezo_d - 2 * piezo_ledge, h = piezo_ch + 0.02, $fn = 96);
            translate([0, 0, -1]) cylinder(d = piezo_hole, h = lid_t + 2);
            j3 = B(P(22.27, 26.4)) - B(PIEZO);
            rotate([0, 0, atan2(j3[1], j3[0])]) translate([piezo_d / 2 - 1, -1.5, -piezo_ring_h - 1])
                cube([piezo_wall + 2, 3, piezo_lip + piezo_t + 1]);
        }
        // button holes
        for (b = BUTTONS) translate([B(b)[0], B(b)[1], -1]) cylinder(d = pin_hole_d, h = lid_t + 2);
        if (whip_hole) translate([B(WHIP)[0], B(WHIP)[1], -1]) cylinder(d = 3.0, h = lid_t + 2);   // wire up to 1.5 mm, some play
        if (labels) {
            if (small_labels) for (l = LABELS) engrave(l[0], P(l[1], l[2]), l[3], l[4]);
            if (name != "" || logo) translate([B(P(NAME_AT[0], NAME_AT[1]))[0], B(P(NAME_AT[0], NAME_AT[1]))[1], lid_t - label_d])
                linear_extrude(label_d + 1) brand2d();
        }
    }
}

// push pin: collar under the lid keeps it captive, lower end 0.3 mm above the switch
pin_below = inner_h - SW_H - 0.3;   // collar top (lid underside) down to the pin tip
pin_hole_d   = 3.8;                 // button hole in the lid
pin_d        = SLA ? 3.55 : 3.3;    // shaft: 0.12 mm play per side on SLA; FDM holes shrink, so 0.25 there
pin_collar_d = 5.4;                 // keeps the pin captive (hole 3.8); 0.35 mm clear of the base wall
module pin() {
    collar = 1.2;
    cylinder(d = pin_d, h = pin_below + lid_t + 1.2);         // shaft: through the lid, 1.2 mm proud
    translate([0, 0, pin_below - collar]) cylinder(d = pin_collar_d, h = collar);
}

pins_n = 4;   // pins on the plate: two needed, two spares

module lid_print() translate([0, 0, lid_t]) rotate([180, 0, 0]) translate([0, -OUT_D, 0]) lid();   // upside down
module pin_print() rotate([180, 0, 0]) translate([0, 0, -(pin_below + lid_t + 1.2)]) pin();        // collar down

if (light_pipe) echo(str("light pipes: cut three ", rod_d, " mm acrylic rods to ", rod_len, " mm"));
if (piezo) echo(str("piezo: ", piezo_d, " mm disc, ring ", piezo_ring_h, " mm below the lid, ",
                    inner_h - piezo_ring_h - 3, " mm above the TCM"));

// ---------------------------------------------------------------- parts
if (part == "base") base();
else if (part == "lid_asm") lid();     // as mounted (renders)
else if (part == "pin_asm") pin();     // as mounted, tip at z = 0 (renders)
else if (part == "lid") lid_print();
else if (part == "pin") pin_print();
else if (part == "plate") {
    // one print job: base and lid side by side, the pins in a row in front of them
    plate_gap = 5;
    base();
    translate([OUT_W + plate_gap, 0, 0]) lid_print();
    for (i = [0 : pins_n - 1])
        translate([pin_collar_d / 2 + i * (pin_collar_d + 3), -plate_gap - pin_collar_d / 2, 0]) pin_print();
}
else {
    // assembly preview: base, board, lid lifted 12 mm
    color("lightgray") base();
    color("darkgreen") translate([wall + gap, wall + gap, board_z]) cube([BOARD_W, BOARD_H, BOARD_T]);
    color("navy") translate([B(P(USB_X - 9, 33.3))[0], B(P(0, 33.3))[1], top_z + pm_gap]) cube([18, 33.3, pm_pcb]);
    color("silver") translate([B([USB_X - 4.5, 0])[0], OUT_D - wall - gap - 7.3, top_z + usb_z - usb_rh / 2]) cube([9, 7.3, usb_rh]);
    color("tan") translate([B(P(19.9, 23.5))[0], B(P(19.9, 23.5))[1], top_z]) cube([14.7, 19, 3]);
    for (b = BUTTONS) color("black") translate([B(b)[0] - 2.55, B(b)[1] - 2.55, top_z]) cube([5.1, 5.1, SW_H]);
    color("white", 0.8) translate([0, 0, base_h + 12]) lid();
    if (light_pipe) for (l = LEDS) color("gold", 0.6) translate([B(l)[0], B(l)[1], base_h + 12 - pipe_len]) cylinder(d = rod_d, h = rod_len);
    if (piezo) translate([B(PIEZO)[0], B(PIEZO)[1], base_h + 12 - piezo_ch - piezo_t]) {
        color("goldenrod") cylinder(d = piezo_d, h = 0.2, $fn = 96);
        color("white") translate([0, 0, -0.1]) cylinder(d = piezo_d * 2 / 3, h = 0.1, $fn = 96);
    }
    for (b = BUTTONS) color("orange") translate([B(b)[0], B(b)[1], base_h + 12 - pin_below]) pin();
}
