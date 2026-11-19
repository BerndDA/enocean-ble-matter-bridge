// 3D-printable case for the EnOcean carrier board (hardware/enocean-carrier).
//
// Parts (choose with `part`): "base", "lid", "pin" (two needed), or "assembly" (preview).
//   openscad -D 'part="base"' -o base.stl carrier_case.scad
// tools/export_case.sh renders all STLs and preview PNGs.
//
// Board positions are taken from the KiCad layout (placement.py): board coordinates
// x right, y down from the USB edge; here mapped to X = x, Y = BOARD_H - y.
// Heights above the board are estimates: measure your Pro Micro stack and adjust
// pm_mount / the pm_* values before printing.

part = "assembly";

// ---------------------------------------------------------------- how the Pro Micro sits
// "direct": soldered on male pin headers (plastic spacer 2.5 mm)   -> Pro Micro 2.5 mm above the board
// "socket": female headers (8.5 mm) + male header spacer (2.5 mm) -> Pro Micro 11 mm above the board
pm_mount = "direct";
pm_gap   = pm_mount == "socket" ? 11.0 : 2.5;   // carrier top -> Pro Micro bottom
pm_pcb   = 1.2;                                 // Pro Micro board thickness (SuperMini 1.0-1.2, nice!nano 1.0)
pm_parts = 3.5;                                 // tallest part on the Pro Micro (USB-C receptacle ~3.2)
usb_z    = pm_gap + pm_pcb + 1.6;               // USB-C centre above the carrier top

// ---------------------------------------------------------------- options
sma_hole   = false;   // 6.5 mm hole in the right wall for an SMA bulkhead (u.FL pigtail instead of the whip)
whip_hole  = true;    // hole in the lid above the whip pad: the 86 mm wire goes straight up
light_pipe = true;    // tube from the lid down to just above the LED

// ---------------------------------------------------------------- board (from the PCB)
BOARD_W = 46.5;
BOARD_H = 33.4;
BOARD_T = 1.6;
function P(x, y) = [x, BOARD_H - y];      // KiCad board coordinates -> case coordinates

HOLES   = [P(22.2, 30.7), P(42.4, 24.2)]; // H1, H2: M2
BUTTONS = [P(29.0, 30.75), P(41.6, 30.75)];  // SW2 FUNC, SW1 RESET (XKB TS-1187A, 5.1 x 5.1 x 1.5 mm)
LED     = P(41.6, 18.0);                  // D1
WHIP    = P(44.4, 2.6);                   // TP1
UFL     = P(43.9, 9.5);                   // J1
USB_X   = 2.4 + 15.24 / 2;                // Pro Micro centre line (pads at x 2.4 and 17.64)
SW_H    = 1.5;                            // switch height above the board
LED_H   = 0.8;

// ---------------------------------------------------------------- case
wall     = 2.0;
floor_t  = 2.0;
gap      = 0.4;     // board to wall, each side
under    = 4.0;     // floor to board bottom: room for the header pins and solder
inner_h  = pm_gap + pm_pcb + pm_parts + 0.8;   // board top to lid underside
lid_t    = 2.0;
lip_h    = 3.0;     // lid lip reaching into the base
fit      = 0.25;    // lip clearance per side
ledge    = 0.8;     // board support around the edge
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

module base() {
    difference() {
        union() {
            difference() {
                rounded_box(OUT_W, OUT_D, base_h);
                translate([wall, wall, floor_t]) cube([IN_W, IN_D, base_h]);
            }
            // ledge around the inside: the board rests on it where it has no holes
            translate([wall, wall, floor_t]) difference() {
                cube([IN_W, IN_D, under]);
                translate([gap + ledge, gap + ledge, -1]) cube([IN_W - 2 * (gap + ledge), IN_D - 2 * (gap + ledge), under + 2]);
            }
            // standoffs for M2 self-tapping screws
            for (h = HOLES) translate([B(h)[0], B(h)[1], floor_t]) cylinder(d = 5.0, h = under);
        }
        for (h = HOLES) translate([B(h)[0], B(h)[1], floor_t - 1]) cylinder(d = 1.7, h = under + 2);
        // USB-C opening in the end wall (board y = 0 is the top wall here)
        translate([B([USB_X, 0])[0] - 6, OUT_D - wall - 1, top_z + usb_z - 3.5]) cube([12, wall + 2, 7]);
        if (sma_hole)
            translate([OUT_W - wall - 1, B(UFL)[1], top_z + 6]) rotate([0, 90, 0]) cylinder(d = 6.5, h = wall + 2);
    }
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
            // light pipe down to just above the LED
            if (light_pipe)
                translate([B(LED)[0], B(LED)[1], -(inner_h - LED_H - 1.0)]) cylinder(d = 4.6, h = inner_h - LED_H - 1.0);
        }
        // the lip must not cover the USB opening: cut it there
        translate([B([USB_X, 0])[0] - 6.5, OUT_D - wall - 2, -lip_h - 1]) cube([13, 3, lip_h + 1]);
        if (light_pipe)
            translate([B(LED)[0], B(LED)[1], -inner_h]) cylinder(d = 2.6, h = inner_h + lid_t + 1);
        // button holes
        for (b = BUTTONS) translate([B(b)[0], B(b)[1], -1]) cylinder(d = 3.8, h = lid_t + 2);
        if (whip_hole) translate([B(WHIP)[0], B(WHIP)[1], -1]) cylinder(d = 2.5, h = lid_t + 2);
    }
}

// push pin: collar under the lid keeps it captive, lower end 0.3 mm above the switch
pin_below = inner_h - SW_H - 0.3;   // collar top (lid underside) down to the pin tip
module pin() {
    collar = 1.2;
    cylinder(d = 3.3, h = pin_below + lid_t + 1.2);           // shaft: through the lid, 1.2 mm proud
    translate([0, 0, pin_below - collar]) cylinder(d = 6.0, h = collar);
}

// ---------------------------------------------------------------- parts
if (part == "base") base();
else if (part == "lid_asm") lid();     // as mounted (renders)
else if (part == "pin_asm") pin();     // as mounted, tip at z = 0 (renders)
else if (part == "lid") translate([0, 0, lid_t]) rotate([180, 0, 0]) translate([0, -OUT_D, 0]) lid();  // print upside down
else if (part == "pin") rotate([180, 0, 0]) translate([0, 0, -(pin_below + lid_t + 1.2)]) pin();     // print collar down
else {
    // assembly preview: base, board, lid lifted 12 mm
    color("lightgray") base();
    color("darkgreen") translate([wall + gap, wall + gap, board_z]) cube([BOARD_W, BOARD_H, BOARD_T]);
    color("navy") translate([B(P(USB_X - 9, 33.3))[0], B(P(0, 33.3))[1], top_z + pm_gap]) cube([18, 33.3, pm_pcb]);
    color("silver") translate([B([USB_X - 4.5, 0])[0], OUT_D - wall - gap - 7.3, top_z + pm_gap + pm_pcb]) cube([9, 7.3, 3.2]);
    color("tan") translate([B(P(19.9, 23.5))[0], B(P(19.9, 23.5))[1], top_z]) cube([14.7, 19, 3]);
    for (b = BUTTONS) color("black") translate([B(b)[0] - 2.55, B(b)[1] - 2.55, top_z]) cube([5.1, 5.1, SW_H]);
    color("white", 0.8) translate([0, 0, base_h + 12]) lid();
    for (b = BUTTONS) color("orange") translate([B(b)[0], B(b)[1], base_h + 12 - pin_below]) pin();
}
