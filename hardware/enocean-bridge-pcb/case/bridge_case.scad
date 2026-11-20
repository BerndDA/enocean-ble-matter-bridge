// 3D-printable case for the EnOcean–Matter bridge board (hardware/enocean-bridge-pcb).
// Same construction as the EnMT carrier's case (../../enocean-carrier/case/carrier_case.scad):
// base with walls, lid with a friction lip, light pipes for 3 mm acrylic rods over the LEDs,
// captive push pins over the buttons, a hole for the whip.
//
// Parts (choose with `part`): "base", "lid", "pin" (two needed), or "assembly" (preview).
//   openscad -D 'part="base"' -o base.stl bridge_case.scad
// tools/export_case.sh renders all STLs and preview PNGs.
//
// Board positions are taken from the KiCad layout (tools/placement.py): board coordinates
// x right, y down from the top edge; here mapped to X = x, Y = BOARD_H - y. The USB-C
// connector is at the bottom edge (board y = 26), i.e. the front wall here (Y = 0).
// Part heights are estimates (TCM 515 about 3 mm, SWD header pins about 4 mm): measure
// before printing and adjust inner_h.

part = "assembly";

// ---------------------------------------------------------------- options
whip_hole  = true;    // 3 mm hole in the lid above the whip pad: the 86 mm wire goes straight up
swd_hole   = true;    // opening in the lid over J3: the DK's 10-pin cable plugs in with the lid on
light_pipe = true;    // one tube per LED from the lid down to just above it, each holds a clear acrylic rod
rod_d      = 3.0;     // acrylic (PMMA) rods pressed into the light pipes
pipe_bore  = rod_d + 0.2;   // printed holes come out ~0.1-0.2 mm small: press fit
pipe_wall  = 0.8;     // also the wall between two pipes (LEDs 4 mm apart)

// ---------------------------------------------------------------- labels engraved in the lid top
labels     = true;
name       = "EnMT";  // product name over the TCM area ("" = none)
logo       = true;    // the EnMT logo left of the name
logo_h     = 9.0;
label_font = "Liberation Sans:style=Bold";
label_d    = 0.6;     // engraving depth
label_grow = 0.12;    // widens the strokes by 2 x this: grooves >= 0.5 mm
label_h    = 2.0;     // small labels (cap height about 0.7 x this)
name_h     = 5.5;

// ---------------------------------------------------------------- board (from the PCB)
BOARD_W = 57.0;
BOARD_H = 26.0;
BOARD_T = 1.6;
function P(x, y) = [x, BOARD_H - y];      // KiCad board coordinates -> case coordinates

BUTTONS = [P(8.5, 23.1), P(17.0, 23.1)];                     // SW2 FUNC, SW1 RESET (XKB TS-1187A)
LEDS    = [P(44.0, 22.6), P(48.0, 22.6), P(52.0, 22.6)];     // D1 red PWR, D2 green LINK, D3 yellow RX
WHIP    = P(3.0, 2.2);                                       // TP1, 1.0 mm hole: wire up to about 0.9 mm
USB_X   = 31.5;                                              // J1 centre line
SWD     = P(47.635, 16.14);                                  // J3 pin field centre (pins x 47.0 / 48.27, y 13.6 .. 18.68)
SW_H    = 1.5;                                               // switch height above the board
LED_H   = 0.8;                                               // 0805 LEDs
USB_Z   = 1.6;                                               // USB-C centre above the board top (HRO TYPE-C-31-M-12, 3.2 mm tall)
// posts from the lid down onto bare board: they hold the board on the floor (no screw holes)
POSTS   = [P(2.5, 14.0), P(31.0, 1.8), P(40.5, 24.6)];

// [text, board x, board y, size, halign]; button labels along the front edge
LABELS = [
    ["FUNC", 8.5, 26.6, label_h, "center"],
    ["RST",  17.0, 26.6, label_h, "center"],
    // 4 mm LED pitch leaves no room for three words in a row: left of, below and right of the row
    ["PWR",  41.2, 22.6, label_h, "right"],
    ["LNK",  48.0, 26.6, label_h, "center"],
    ["RX",   54.8, 22.6, label_h, "left"],
    ["868",  5.2, 2.2, label_h, "left"],
    ["SWD",  50.6, 16.1, label_h, "left"],
];
NAME_AT = [15.4, 12.0];                   // board coordinates of the centre of logo + name (over the TCM)

// ---------------------------------------------------------------- case
wall     = 2.0;
floor_t  = 3.0;     // the board lies on the floor; pockets take the through-hole solder joints
pocket_d = 2.0;
gap      = 0.4;     // board to wall, each side
inner_h  = 5.0;     // board top to lid underside: SWD header pins ~4 mm, TCM 515 ~3 mm, USB-C 3.2 mm
lid_t    = 2.0;
lip_h    = 3.0;     // lid lip reaching into the base
pipe_len = inner_h - LED_H - 0.5;          // light pipes below the lid, end 0.5 mm above the LEDs
rod_len  = pipe_len + lid_t;               // rod flush with the lid top and the pipe end
post_d   = 2.5;
fit      = 0.25;    // lip clearance per side
swd_open = [4.6, 7.9];                     // lid opening over J3: the 10-pin IDC socket (about 4 x 7.6 mm)
$fn = 48;

IN_W = BOARD_W + 2 * gap;
IN_D = BOARD_H + 2 * gap;
OUT_W = IN_W + 2 * wall;
OUT_D = IN_D + 2 * wall;
board_z = floor_t;                         // board bottom
top_z   = board_z + BOARD_T;               // board top
base_h  = top_z + inner_h;                 // top of the base walls = underside of the lid
function B(p) = [p[0] + wall + gap, p[1] + wall + gap];   // case coordinates -> base coordinates

module rounded_box(w, d, h, r = 1.5) {
    hull() for (x = [r, w - r], y = [r, d - r]) translate([x, y, 0]) cylinder(r = r, h = h);
}

// pockets for the through-hole joints on the board's underside: [board x0, y0, x1, y1]
POCKETS = [
    [45.9, 12.5, 49.4, 19.8],      // J3 pin header
    [26.2, 17.8, 28.2, 20.7],      // J1 shell legs
    [26.2, 22.3, 28.2, 24.5],
    [34.8, 17.8, 36.8, 20.7],
    [34.8, 22.3, 36.8, 24.5],
];

module base() {
    difference() {
        difference() {
            rounded_box(OUT_W, OUT_D, base_h);
            translate([wall, wall, floor_t]) cube([IN_W, IN_D, base_h]);
        }
        for (k = POCKETS) {
            p0 = B(P(k[0], k[3]));
            translate([p0[0], p0[1], floor_t - pocket_d]) cube([k[2] - k[0], k[3] - k[1], pocket_d + 1]);
        }
        translate([B(WHIP)[0], B(WHIP)[1], floor_t - pocket_d]) cylinder(d = 4.5, h = pocket_d + 1);   // whip pad 2 mm + solder
        // USB-C opening in the front wall (board bottom edge), open at the top; the lid's lip is notched there
        translate([B([USB_X, 0])[0] - 6, -1, top_z + USB_Z - 3.5]) cube([12, wall + 2, inner_h + 5]);
    }
}

module engrave(t, p, size, halign) {
    translate([B(p)[0], B(p)[1], lid_t - label_d]) linear_extrude(label_d + 1)
        offset(delta = label_grow) text(t, size = size, font = label_font, halign = halign, valign = "center");
}

// EnMT logo (as on the carrier's lid): two radio-wave arcs left of a node linked to two more
LOGO_NODES = [[110, 100, 17], [198, 38, 19], [198, 162, 19]];   // x, y, radius in the source image's pixels
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
module brand2d() {
    lw = logo ? logo_h * 1.12 : 0;
    tw = name == "" ? 0 : len(name) * name_h * 0.78;
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
            if (light_pipe)
                for (l = LEDS) translate([B(l)[0], B(l)[1], -pipe_len]) cylinder(d = pipe_bore + 2 * pipe_wall, h = pipe_len);
            // hold-down posts, 0.1 mm above the board
            for (p = POSTS) translate([B(p)[0], B(p)[1], -(inner_h - 0.1)]) cylinder(d = post_d, h = inner_h - 0.1);
        }
        // the buttons sit close to the front edge: notch the lip around each pin collar
        for (b = BUTTONS) translate([B(b)[0], B(b)[1], -lip_h - 1]) cylinder(d = pin_collar_d + 1.0, h = lip_h + 1);
        // the lip must not cover the USB opening
        translate([B([USB_X, 0])[0] - 6.5, -1, -lip_h - 1]) cube([13, wall + 2, lip_h + 1]);
        if (light_pipe)
            for (l = LEDS) translate([B(l)[0], B(l)[1], -inner_h]) cylinder(d = pipe_bore, h = inner_h + lid_t + 1);
        for (b = BUTTONS) translate([B(b)[0], B(b)[1], -1]) cylinder(d = 3.8, h = lid_t + 2);
        if (whip_hole) translate([B(WHIP)[0], B(WHIP)[1], -1]) cylinder(d = 3.0, h = lid_t + 2);
        if (swd_hole) translate([B(SWD)[0] - swd_open[0] / 2, B(SWD)[1] - swd_open[1] / 2, -1])
            cube([swd_open[0], swd_open[1], lid_t + 2]);
        if (labels) {
            for (l = LABELS) engrave(l[0], P(l[1], l[2]), l[3], l[4]);
            if (name != "" || logo) translate([B(P(NAME_AT[0], NAME_AT[1]))[0], B(P(NAME_AT[0], NAME_AT[1]))[1], lid_t - label_d])
                linear_extrude(label_d + 1) brand2d();
        }
    }
}

// push pin: collar under the lid keeps it captive, lower end 0.3 mm above the switch
pin_below = inner_h - SW_H - 0.3;
pin_collar_d = 5.4;
module pin() {
    collar = 1.2;
    cylinder(d = 3.3, h = pin_below + lid_t + 1.2);           // shaft: through the lid, 1.2 mm proud
    translate([0, 0, pin_below - collar]) cylinder(d = pin_collar_d, h = collar);
}

if (light_pipe) echo(str("light pipes: cut three ", rod_d, " mm acrylic rods to ", rod_len, " mm"));
echo(str("case ", OUT_W, " x ", OUT_D, " x ", base_h + lid_t, " mm"));

// ---------------------------------------------------------------- parts
if (part == "base") base();
else if (part == "lid_asm") lid();     // as mounted (renders)
else if (part == "pin_asm") pin();     // as mounted, tip at z = 0 (renders)
else if (part == "lid") translate([0, 0, lid_t]) rotate([180, 0, 0]) translate([0, -OUT_D, 0]) lid();  // print upside down
else if (part == "pin") rotate([180, 0, 0]) translate([0, 0, -(pin_below + lid_t + 1.2)]) pin();     // print collar down
else {
    // assembly preview: base, board with its tall parts, lid lifted 12 mm
    color("lightgray") base();
    color("darkgreen") translate([wall + gap, wall + gap, board_z]) cube([BOARD_W, BOARD_H, BOARD_T]);
    color("tan") translate([B(P(5.9, 19.35))[0], B(P(5.9, 19.35))[1], top_z]) cube([19.0, 14.7, 3.0]);       // TCM 515
    color("silver") translate([B([USB_X - 4.5, 0])[0], wall + gap - 0.5, top_z]) cube([9, 7.3, 3.2]);        // USB-C
    color("black") translate([B(SWD)[0] - 1.6, B(SWD)[1] - 3.2, top_z]) cube([3.2, 6.4, 4.0]);               // SWD header
    for (b = BUTTONS) color("black") translate([B(b)[0] - 2.55, B(b)[1] - 2.55, top_z]) cube([5.1, 5.1, SW_H]);
    color("white", 0.8) translate([0, 0, base_h + 12]) lid();
    if (light_pipe) for (l = LEDS) color("gold", 0.6) translate([B(l)[0], B(l)[1], base_h + 12 - pipe_len]) cylinder(d = rod_d, h = rod_len);
    for (b = BUTTONS) color("orange") translate([B(b)[0], B(b)[1], base_h + 12 - pin_below]) pin();
}
