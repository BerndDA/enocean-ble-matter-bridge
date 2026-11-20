"""Photo-style renders of the bridge board in its case (Blender, Cycles).

    tools/render_case.sh [samples]      (exports the inputs, then runs this in Blender)

Inputs in the work folder given after `--`: base.stl, lid_asm.stl, pin_asm.stl (OpenSCAD,
mounted orientation) and board.glb (KiCad 3D export, origin at the board's lower-left
corner). Parts without a KiCad 3D model (TCM 515, buttons, whip) are modelled here as
simple shapes. Dimensions follow bridge_case.scad's defaults; keep them in step.
Adapted from the EnMT carrier's render (../../enocean-carrier/tools/render_case.py).

Output: render-closed.png, render-exploded.png, render-open.png in the output folder.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:]
WORK, OUT = args[0], args[1]
SAMPLES = int(args[2]) if len(args) > 2 else 192

# ---------------------------------------------------------------- dimensions (bridge_case.scad)
WALL, GAP, FLOOR, BOARD_T = 2.0, 0.4, 3.0, 1.6
BOARD_W, BOARD_H = 57.0, 26.0
INNER_H = 5.0
BOARD_Z = FLOOR
TOP_Z = BOARD_Z + BOARD_T
BASE_H = TOP_Z + INNER_H
OUT_W, OUT_D = BOARD_W + 2 * GAP + 2 * WALL, BOARD_H + 2 * GAP + 2 * WALL
OFF = WALL + GAP
SW_H = 1.5
LID_T, LED_H = 2.0, 0.8
ROD_D = 3.0
PIPE_LEN = INNER_H - LED_H - 0.5
LEDS = [(44.0, 22.6), (48.0, 22.6), (52.0, 22.6)]   # D1 red, D2 green, D3 yellow (KiCad board coordinates)
TCM = (15.4, 12.0, 19.0, 14.7, 3.0)                 # U4 centre, size, height (estimate)


def C(x, y):
    """KiCad board coordinates (y down) -> case coordinates (y up)."""
    return (x + OFF, BOARD_H - y + OFF)


BUTTONS = [C(8.5, 23.1), C(17.0, 23.1)]
WHIP = C(3.0, 2.2)

# ---------------------------------------------------------------- helpers
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene


def mat(name, color, rough=0.5, metal=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (*color, 1.0)
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    return m


M = {
    "case": mat("case", (0.045, 0.047, 0.052), 0.55),
    "lid": mat("lid", (0.05, 0.052, 0.058), 0.5),
    "pin": mat("pin", (0.95, 0.42, 0.08), 0.45),
    "chip": mat("chip", (0.02, 0.02, 0.02), 0.4),
    "metal": mat("metal", (0.8, 0.8, 0.82), 0.25, 1.0),
    "tcm": mat("tcm", (0.03, 0.22, 0.1), 0.4),
    "label": mat("label", (0.95, 0.95, 0.93), 0.6),
    "copper": mat("copper", (0.95, 0.6, 0.45), 0.3, 1.0),
    "floor": mat("floor", (0.55, 0.56, 0.58), 0.85),
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
rods = []
for i, l in enumerate(LEDS):                       # acrylic rods, flush with the lid top, move with the lid
    r = cyl(f"rod{i}", C(*l)[0], C(*l)[1], -PIPE_LEN, PIPE_LEN + LID_T, ROD_D, M["acrylic"], 32)
    r.parent = lid
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

# TCM 515 (no KiCad 3D model)
tx, ty = C(TCM[0], TCM[1])
box("tcm", tx - TCM[2] / 2, ty - TCM[3] / 2, TOP_Z, tx + TCM[2] / 2, ty + TCM[3] / 2, TOP_Z + TCM[4], M["tcm"], 0.1)
box("tcm_label", tx - TCM[2] / 2 + 2.0, ty - TCM[3] / 2 + 1.5, TOP_Z + TCM[4], tx + TCM[2] / 2 - 2.0,
    ty + TCM[3] / 2 - 1.5, TOP_Z + TCM[4] + 0.05, M["label"], 0.0)
# buttons (XKB TS-1187A)
for i, (bx, by) in enumerate(BUTTONS):
    box(f"sw{i}", bx - 2.55, by - 2.55, TOP_Z, bx + 2.55, by + 2.55, TOP_Z + 1.0, M["metal"], 0.1)
    cyl(f"sw_cap{i}", bx, by, TOP_Z + 1.0, SW_H - 1.0, 3.0, M["chip"])
whip = cyl("whip", WHIP[0], WHIP[1], TOP_Z - 0.5, 86.0, 0.8, M["copper"], 24)

bpy.ops.mesh.primitive_plane_add(size=2000, location=(OUT_W / 2, OUT_D / 2, 0))
bpy.context.object.data.materials.append(M["floor"])

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
shot("closed", (c.x + 0.95, c.y - 1.05, c.z + 0.75), (c.x, c.y, c.z + 0.02), lens=55, show_whip=True)
shot("exploded", (c.x + 1.0, c.y - 1.15, c.z + 0.95), (c.x, c.y, c.z + 0.12), lens=50,
     lid_z=BASE_H + 28, pin_lift=28 - 10)
shot("open", (c.x + 0.4, c.y - 0.85, c.z + 1.15), (c.x, c.y + 0.02, c.z - 0.06), lens=45, show_lid=False)
