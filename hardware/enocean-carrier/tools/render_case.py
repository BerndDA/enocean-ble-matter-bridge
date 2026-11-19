"""Photo-style renders of the carrier in its case (Blender, Cycles).

    tools/render_case.sh            (exports the inputs, then runs this in Blender)

Inputs in the work folder given after `--`: base.stl, lid_asm.stl, pin_asm.stl (OpenSCAD,
mounted orientation) and board.glb (KiCad 3D export, origin at the board's lower-left
corner). Parts without a KiCad 3D model (Pro Micro on its headers, TCM 515, buttons,
whip) are modelled here as simple shapes. Dimensions follow carrier_case.scad's
defaults (pm_mount = "direct"); keep them in step when those change.

Output: render-closed.png, render-exploded.png, render-open.png in the output folder.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # for anim_case.py
args = sys.argv[sys.argv.index("--") + 1:]
WORK, OUT = args[0], args[1]
SAMPLES = int(args[2]) if len(args) > 2 else 192
MODE = args[3] if len(args) > 3 else "stills"        # "stills", "anim" (front view) or "anim-usb" (USB side)
FRAMES = args[4] if len(args) > 4 else ""            # anim: comma list of frames to render (test), default all

# ---------------------------------------------------------------- dimensions (carrier_case.scad)
WALL, GAP, FLOOR, UNDER, BOARD_T = 2.0, 0.4, 3.0, 0.0, 1.6
BOARD_W, BOARD_H = 46.5, 33.4
SOCKET = False                        # carrier_case.scad pm_mount: "direct" (False) or "socket"
PM_GAP = 11.0 if SOCKET else 2.5
PM_PCB, PM_PARTS = 1.2, 3.5
INNER_H = PM_GAP + PM_PCB + PM_PARTS + 0.8
BOARD_Z = FLOOR + UNDER
TOP_Z = BOARD_Z + BOARD_T
BASE_H = TOP_Z + INNER_H
OUT_W, OUT_D = BOARD_W + 2 * GAP + 2 * WALL, BOARD_H + 2 * GAP + 2 * WALL
OFF = WALL + GAP
SW_H = 1.5
LID_T, LED_H = 2.0, 0.8                # LED_H: 0805 LEDs
ROD_D = 3.0                           # acrylic rods in the light pipes (carrier_case.scad rod_d)
PIPE_LEN = INNER_H - LED_H - 0.5      # light pipe below the lid
LEDS = [(43.2, 16.4), (43.2, 20.4), (43.2, 24.4)]   # D1 red, D2 green, D3 yellow, KiCad board coordinates
LED = LEDS[1]                         # the one that blinks in the USB clip (green)


def C(x, y):
    """KiCad board coordinates (y down from the USB edge) -> case coordinates."""
    return (x + OFF, BOARD_H - y + OFF)


BUTTONS = [C(29.0, 30.75), C(41.6, 30.75)]
WHIP = C(44.4, 2.6)
PM_X0, PM_X1 = 1.02 + OFF, 19.02 + OFF
PM_Y0, PM_Y1 = BOARD_H - 33.02 + OFF, BOARD_H + OFF       # nice!nano v2, USB end flush with the board edge
PIN_ROWS_X = [2.4 + OFF, 17.64 + OFF]
PIN_YS = [BOARD_H - (3.81 + 2.54 * i) + OFF for i in range(12)]

# ---------------------------------------------------------------- helpers
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene


def mat(name, color, rough=0.5, metal=0.0, emit=None):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (*color, 1.0)
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    if emit:
        p.inputs["Emission Color"].default_value = (*emit[0], 1.0)
        p.inputs["Emission Strength"].default_value = emit[1]
    return m


M = {
    "case": mat("case", (0.045, 0.047, 0.052), 0.55),
    "lid": mat("lid", (0.05, 0.052, 0.058), 0.5),
    "pin": mat("pin", (0.95, 0.42, 0.08), 0.45),
    "pm_pcb": mat("pm_pcb", (0.015, 0.02, 0.06), 0.35),
    "chip": mat("chip", (0.02, 0.02, 0.02), 0.4),
    "metal": mat("metal", (0.8, 0.8, 0.82), 0.25, 1.0),
    "gold": mat("gold", (0.95, 0.75, 0.35), 0.25, 1.0),
    "header": mat("header", (0.02, 0.02, 0.02), 0.55),
    "tcm": mat("tcm", (0.03, 0.22, 0.1), 0.4),
    "label": mat("label", (0.95, 0.95, 0.93), 0.6),
    "copper": mat("copper", (0.95, 0.6, 0.45), 0.3, 1.0),
    "floor": mat("floor", (0.55, 0.56, 0.58), 0.85),
    "led": mat("led", (1.0, 0.75, 0.2), 0.3, 0.0, ((1.0, 0.7, 0.15), 12.0)),
    "acrylic": mat("acrylic", (0.95, 0.93, 0.85), 0.25),
}
_a = M["acrylic"].node_tree.nodes["Principled BSDF"].inputs
_a["Transmission Weight" if "Transmission Weight" in _a else "Transmission"].default_value = 0.9
_a["IOR"].default_value = 1.49


def box(name, x0, y0, z0, x1, y1, z1, material, bevel=0.15):
    bpy.ops.mesh.primitive_cube_add(size=1, location=((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    o = bpy.context.object
    o.name = name
    o.scale = (x1 - x0, y1 - y0, z1 - z0)
    bpy.ops.object.transform_apply(scale=True)
    if bevel:
        b = o.modifiers.new("bevel", "BEVEL")
        b.width = bevel
        b.segments = 2
    o.data.materials.append(material)
    return o


def cyl(name, x, y, z0, h, d, material, verts=48):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=d / 2, depth=h, location=(x, y, z0 + h / 2))
    o = bpy.context.object
    o.name = name
    o.data.materials.append(material)
    bpy.ops.object.shade_smooth()
    return o


def stl(name, path, material, loc=(0, 0, 0)):
    bpy.ops.wm.stl_import(filepath=path)
    o = bpy.context.selected_objects[0]
    o.name = name
    o.location = loc
    o.data.materials.clear()
    o.data.materials.append(material)
    try:
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(35))
    except Exception:
        pass
    return o


# ---------------------------------------------------------------- objects (mm)
base = stl("base", os.path.join(WORK, "base.stl"), M["case"])
lid = stl("lid", os.path.join(WORK, "lid_asm.stl"), M["lid"], (0, 0, BASE_H))
# acrylic rod in the light pipe, flush with the lid top, moves with the lid
# one rod per LED; the green one (middle) carries the other two, so the clips move all three
rod = cyl("rod", C(*LED)[0], C(*LED)[1], -PIPE_LEN, PIPE_LEN + LID_T, ROD_D, M["acrylic"], 32)
rod.parent = lid
rod["led"] = "green"
rods = [rod]
for i, l in enumerate(LEDS):
    if l == LED:
        continue
    dx, dy = C(*l)[0] - C(*LED)[0], C(*l)[1] - C(*LED)[1]
    r = cyl(f"rod{i}", dx, dy, -(PIPE_LEN + LID_T) / 2, PIPE_LEN + LID_T, ROD_D, M["acrylic"], 32)
    r.parent = rod
    r["led"] = ("red", "green", "yellow")[i]
    rods.append(r)
pins = [stl(f"pin{i}", os.path.join(WORK, "pin_asm.stl"), M["pin"], (bx, by, TOP_Z + SW_H + 0.3))
        for i, (bx, by) in enumerate(BUTTONS)]

before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=os.path.join(WORK, "board.glb"))
board_parts = [o for o in bpy.data.objects if o not in before]
board_root = bpy.data.objects.new("board", None)
scene.collection.objects.link(board_root)
for o in board_parts:
    if o.parent is None:
        o.parent = board_root
board_root.scale = (1000, 1000, 1000)
board_root.location = (OFF, OFF, BOARD_Z)

inside = []
# Pro Micro on its pin headers (plus female sockets when SOCKET)
for i, x in enumerate(PIN_ROWS_X):
    z_spacer = TOP_Z
    if SOCKET:
        inside.append(box(f"socket{i}", x - 1.27, PIN_YS[-1] - 1.27, TOP_Z, x + 1.27, PIN_YS[0] + 1.27, TOP_Z + 8.5, M["header"], 0.1))
        z_spacer = TOP_Z + 8.5
    inside.append(box(f"spacer{i}", x - 1.27, PIN_YS[-1] - 1.27, z_spacer, x + 1.27, PIN_YS[0] + 1.27, TOP_Z + PM_GAP, M["header"], 0.1))
    for y in PIN_YS:
        inside.append(box("pintip", x - 0.32, y - 0.32, TOP_Z + PM_GAP + PM_PCB, x + 0.32, y + 0.32, TOP_Z + PM_GAP + PM_PCB + 1.6, M["gold"], 0.05))
pm_z = TOP_Z + PM_GAP
# nice!nano v2: 13 pins per side; the top one of each side (USB end) is B+ / B- for a battery:
# plated holes without a header pin.
BAT_Y = BOARD_H - (3.81 - 2.54) + OFF
inside.append(box("promicro", PM_X0, PM_Y0, pm_z, PM_X1, PM_Y1, pm_z + PM_PCB, M["pm_pcb"], 0.2))
for i, x in enumerate(PIN_ROWS_X):
    inside.append(cyl(f"bat_pad{i}", x, BAT_Y, pm_z + PM_PCB, 0.03, 1.3, M["gold"], 24))
    inside.append(cyl(f"bat_hole{i}", x, BAT_Y, pm_z + PM_PCB, 0.05, 0.7, M["chip"], 24))
for x in PIN_ROWS_X:                           # gold rings of the 12 header pins on the top side
    for y in PIN_YS:
        inside.append(cyl("pin_pad", x, y, pm_z + PM_PCB, 0.03, 1.6, M["gold"], 24))
cx = (PM_X0 + PM_X1) / 2
inside.append(box("usb", cx - 4.5, PM_Y1 - 7.0, pm_z + PM_PCB, cx + 4.5, PM_Y1 + 0.4, pm_z + PM_PCB + 3.2, M["metal"], 0.6))
inside.append(box("nrf", cx - 3.5, PM_Y0 + 14, pm_z + PM_PCB, cx + 3.5, PM_Y0 + 21, pm_z + PM_PCB + 0.85, M["chip"], 0.1))
inside.append(box("ldo", cx - 1.5, PM_Y0 + 23.5, pm_z + PM_PCB, cx + 1.5, PM_Y0 + 25, pm_z + PM_PCB + 1.0, M["chip"], 0.05))
inside.append(box("pm_led", cx + 4.5, PM_Y0 + 23.5, pm_z + PM_PCB, cx + 5.5, PM_Y0 + 24.1, pm_z + PM_PCB + 0.4, M["chip"], 0.02))
# TCM 515 (upright next to the Pro Micro)
tx0, ty0 = C(19.85, 23.5)
inside.append(box("tcm", tx0, ty0, TOP_Z, tx0 + 14.7, ty0 + 19.0, TOP_Z + 1.0, M["tcm"], 0.1))
inside.append(box("tcm_label", tx0 + 1.5, ty0 + 3.0, TOP_Z + 1.0, tx0 + 13.2, ty0 + 16.0, TOP_Z + 1.05, M["label"], 0.0))
# buttons (XKB TS-1187A)
for i, (bx, by) in enumerate(BUTTONS):
    inside.append(box(f"sw{i}", bx - 2.55, by - 2.55, TOP_Z, bx + 2.55, by + 2.55, TOP_Z + 1.0, M["metal"], 0.1))
    inside.append(cyl(f"sw_cap{i}", bx, by, TOP_Z + 1.0, SW_H - 1.0, 3.0, M["chip"]))
whip = cyl("whip", WHIP[0], WHIP[1], TOP_Z - 0.5, 86.0, 0.8, M["copper"], 24)

# board + everything mounted on it move as one in the animation
board_group = bpy.data.objects.new("board_group", None)
scene.collection.objects.link(board_group)
board_root.parent = board_group
for o in inside:
    o.parent = board_group

floor = None
bpy.ops.mesh.primitive_plane_add(size=2000, location=(OUT_W / 2, OUT_D / 2, 0))
floor = bpy.context.object
floor.data.materials.append(M["floor"])

# everything into one root so the scene can be scaled to sensible light units (1 unit = 10 cm)
root = bpy.data.objects.new("root", None)
scene.collection.objects.link(root)
for o in list(scene.objects):
    if o is not root and o.parent is None:
        o.parent = root
root.scale = (0.01, 0.01, 0.01)
center = Vector((OUT_W / 2, OUT_D / 2, BASE_H / 2)) * 0.01

# ---------------------------------------------------------------- lights, world, render
world = bpy.data.worlds.new("world")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.82, 0.85, 0.9, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.25


def area(name, loc, size, power, color=(1, 1, 1)):
    l = bpy.data.lights.new(name, "AREA")
    l.size = size
    l.energy = power
    l.color = color
    o = bpy.data.objects.new(name, l)
    scene.collection.objects.link(o)
    o.location = loc
    d = center - Vector(loc)
    o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return o


area("key", (center.x + 0.9, center.y - 0.8, center.z + 1.1), 0.8, 70, (1.0, 0.96, 0.9))
area("fill", (center.x - 1.0, center.y - 0.4, center.z + 0.6), 1.2, 22, (0.88, 0.94, 1.0))
area("rim", (center.x - 0.3, center.y + 1.2, center.z + 0.9), 0.6, 60)

cam_data = bpy.data.cameras.new("cam")
cam_data.lens = 70
cam_data.clip_start = 0.01
cam_data.clip_end = 100
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
target = bpy.data.objects.new("target", None)
scene.collection.objects.link(target)
track = cam.constraints.new("TRACK_TO")
track.target = target
track.track_axis = "TRACK_NEGATIVE_Z"
track.up_axis = "UP_Y"
cam_data.dof.use_dof = True
cam_data.dof.focus_object = target
cam_data.dof.aperture_fstop = 5.6

scene.render.engine = "CYCLES"
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "METAL"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = True
    scene.cycles.device = "GPU"
except Exception:
    pass
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
scene.render.resolution_x = 1600
scene.render.resolution_y = 1100
scene.render.film_transparent = False
try:
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
except Exception:
    pass


def shot(name, cam_loc, target_loc, lens=70, lid_z=None, pin_lift=0.0, show_lid=True, show_whip=False, fstop=5.6):
    lid.hide_render = not show_lid
    for r in rods:
        r.hide_render = not show_lid
    for p in pins:
        p.hide_render = not show_lid
        p.location.z = TOP_Z + SW_H + 0.3 + pin_lift
    lid.location.z = BASE_H if lid_z is None else lid_z
    whip.hide_render = not show_whip
    cam.location = cam_loc
    target.location = target_loc
    cam_data.lens = lens
    cam_data.dof.aperture_fstop = fstop
    scene.render.filepath = os.path.join(OUT, f"render-{name}.png")
    bpy.ops.render.render(write_still=True)
    print("wrote", scene.render.filepath)


c = center
if MODE.startswith("anim"):
    import anim_case   # noqa: E402  (tools/anim_case.py, next to this script)
    plug = None
    if MODE == "anim-usb":
        # USB-C plug with cable, pointing out of the end wall, as one group
        plug = bpy.data.objects.new("plug", None)
        scene.collection.objects.link(plug)
        plug.parent = root
        uz = pm_z + PM_PCB + 1.6                 # receptacle centre
        yf = PM_Y1 + 0.4                         # receptacle front face
        parts = [
            box("plug_shell", cx - 4.1, yf - 6.4, uz - 1.25, cx + 4.1, yf + 0.3, uz + 1.25, M["metal"], 0.6),
            box("plug_body", cx - 5.4, yf + 0.3, uz - 2.8, cx + 5.4, yf + 17.0, uz + 2.8, M["chip"], 1.2),
            box("plug_relief", cx - 3.2, yf + 17.0, uz - 2.2, cx + 3.2, yf + 23.0, uz + 2.2, M["chip"], 1.0),
        ]
        bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=1.8, depth=60, location=(cx, yf + 53.0, uz),
                                            rotation=(math.radians(90), 0, 0))
        cable = bpy.context.object
        cable.data.materials.append(M["chip"])
        bpy.ops.object.shade_smooth()
        for o in parts + [cable]:
            o.parent = plug
        # status LEDs: each acrylic rod lights up in its LED's colour once the cable is in
        glows = []
        for name, l, rgb in (("red", LEDS[0], (1.0, 0.08, 0.05)), ("green", LEDS[1], (0.15, 1.0, 0.3)),
                             ("yellow", LEDS[2], (1.0, 0.75, 0.05))):
            r = next(o for o in rods if o.get("led") == name)
            gm = mat(f"led_{name}", tuple(0.35 + 0.3 * c for c in rgb), 0.3, 0.0, (rgb, 0.0))
            r.data.materials[0] = gm
            ld = bpy.data.lights.new(f"led_{name}", "POINT")
            ld.color = rgb
            ld.energy = 0.0
            ld.shadow_soft_size = 0.002
            lo = bpy.data.objects.new(f"led_{name}", ld)
            scene.collection.objects.link(lo)
            lo.parent = lid
            lo.location = (*C(*l), 3.5)
            gm["light"] = ld.name
            glows.append((name, gm))
    anim_case.run(scene, cam, cam_data, target, center, lid, pins, whip, board_group,
                  dict(BASE_H=BASE_H, TOP_Z=TOP_Z, SW_H=SW_H), OUT, FRAMES,
                  view="usb" if MODE == "anim-usb" else "front", plug=plug,
                  glows=glows if MODE == "anim-usb" else None, rod=rod,
                  samples=SAMPLES)
    raise SystemExit(0)
shot("closed", (c.x + 0.95, c.y - 1.05, c.z + 0.75), (c.x, c.y, c.z + 0.02), lens=60, show_whip=True)
shot("exploded", (c.x + 1.0, c.y - 1.15, c.z + 0.95), (c.x, c.y, c.z + 0.12), lens=55,
     lid_z=BASE_H + 32, pin_lift=32 - 12)
shot("open", (c.x + 0.4, c.y - 0.85, c.z + 1.15), (c.x, c.y + 0.02, c.z - 0.06), lens=50, show_lid=False)
