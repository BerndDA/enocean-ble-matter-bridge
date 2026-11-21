"""Assembly animation for render_case.py: board drops into the base, the push pins follow,
the lid closes, the whip slides in through the lid; the camera circles slowly. From the USB end
the acrylic rod then drops into the light pipe, a USB-C plug goes in and the LED blinks.
Renders PNG frames with EEVEE into <out>/anim-frames/; render_case.sh turns them into anim.mp4.
"""
import math
import os

import bpy
from mathutils import Vector

FPS = 24
END = 192           # 8 s


def key(obj, frame, z=None, **attrs):
    if z is not None:
        obj.location.z = z
        obj.keyframe_insert("location", index=2, frame=frame)
    for k, v in attrs.items():
        setattr(obj, k, v)
        obj.keyframe_insert(k, frame=frame)


def fcurves(owner):
    """All F-curves of an animated ID; Blender 4.4+ keeps them in layered actions."""
    ad = getattr(owner, "animation_data", None)
    act = ad.action if ad else None
    if act is None:
        return []
    if hasattr(act, "layers") and len(act.layers):
        out = []
        for layer in act.layers:
            for strip in layer.strips:
                for bag in getattr(strip, "channelbags", []):
                    out.extend(bag.fcurves)
        return out
    return list(getattr(act, "fcurves", []))


def interp(owner, mode):
    for fc in fcurves(owner):
        for kp in fc.keyframe_points:
            kp.interpolation = mode


def ease(obj):
    interp(obj, "BEZIER")


def run(scene, cam, cam_data, target, center, lid, pins, whip, board_group, d, out, frames,
        view="front", plug=None, glows=None, rod=None, samples=32, save=None):
    """view "front": the buttons side; "usb": the USB end: the acrylic rods (children of the lid) drop
    into the light pipes, then a USB-C plug goes in and the LEDs light up: red, green, yellow once
    each, then green blinks three times. glows: [(colour name, rod material with a "light")]."""
    base_h, top_z, sw_h = d["BASE_H"], d["TOP_Z"], d["SW_H"]
    usb = view == "usb"
    end = END + (96 if usb else 0)        # usb: rods go in, plug goes in, then the LEDs light up
    plug_in = 224 if usb else 200         # frame the plug is fully in
    pin_z = top_z + sw_h + 0.3

    # --- motion (object locations in mm, inside the 0.01-scaled root)
    key(board_group, 1, 42.0)
    key(board_group, 14, 42.0)
    key(board_group, 54, 0.0)
    for i, p in enumerate(pins):
        key(p, 1, pin_z + 60)
        key(p, 46 + 6 * i, pin_z + 60)
        key(p, 82 + 6 * i, pin_z)
    key(lid, 1, base_h + 80)
    key(lid, 84, base_h + 80)
    key(lid, 122, base_h)
    whip.hide_render = False
    wz = whip.location.z                  # mounted position (cylinder centre)
    key(whip, 1, wz + 120.0)
    key(whip, 120, wz + 120.0)
    key(whip, 156, wz)
    movers = [board_group, lid, whip, *pins]
    if usb and rod is not None:           # drops into the closed lid after the whip (frame 156)
        rz = rod.location.z               # mounted position, relative to the lid
        key(rod, 1, rz + 40.0)
        key(rod, 158, rz + 40.0)
        key(rod, 186, rz)
        movers.append(rod)
    if plug is not None:                  # slides in along the case's long axis (+Y = out of the end wall)
        plug.location.y = 45.0
        plug.keyframe_insert("location", index=1, frame=1)
        plug.keyframe_insert("location", index=1, frame=plug_in - 32)
        plug.location.y = 0.0
        plug.keyframe_insert("location", index=1, frame=plug_in)
        movers.append(plug)
    for o in movers:
        ease(o)
    if glows:                             # after the plug is in: lamp test, then green blinks
        t0 = plug_in + 6
        on = {"red": [t0], "green": [t0 + 6, t0 + 24, t0 + 34, t0 + 44], "yellow": [t0 + 12]}
        for name, gm in glows:
            inp = gm.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"]
            light = bpy.data.lights.get(gm.get("light", ""))
            inp.default_value = 0.0
            inp.keyframe_insert("default_value", frame=1)
            if light is not None:
                light.energy = 0.0
                light.keyframe_insert("energy", frame=1)
            for f in on.get(name, []):
                inp.default_value = 250.0
                inp.keyframe_insert("default_value", frame=f)
                inp.default_value = 0.0
                inp.keyframe_insert("default_value", frame=f + 6)
                if light is not None:
                    light.energy = 0.6
                    light.keyframe_insert("energy", frame=f)
                    light.energy = 0.0
                    light.keyframe_insert("energy", frame=f + 6)
            for owner in (gm.node_tree, light):
                interp(owner, "CONSTANT")
            assert fcurves(gm.node_tree), f"no keyframes found for the {name} LED"

    # --- camera: on a pivot that turns 60 degrees, target sinks as the parts come down
    pivot = bpy.data.objects.new("pivot", None)
    scene.collection.objects.link(pivot)
    pivot.location = center
    cam.parent = pivot
    cam.location = Vector((0.0, -1.55, 0.95))
    cam_data.lens = 45
    cam_data.dof.aperture_fstop = 8
    a0, a1 = (-35, 30) if view == "front" else (215, 140)
    pivot.rotation_euler = (0, 0, math.radians(a0))
    pivot.keyframe_insert("rotation_euler", index=2, frame=1)
    pivot.rotation_euler = (0, 0, math.radians(a1))
    pivot.keyframe_insert("rotation_euler", index=2, frame=end)
    interp(pivot, "LINEAR")
    target.location = center + Vector((0, 0, 0.32))
    target.keyframe_insert("location", index=2, frame=1)
    target.location = center + Vector((0, 0, 0.05))
    target.keyframe_insert("location", index=2, frame=150)

    # --- EEVEE
    scene.render.engine = "BLENDER_EEVEE"
    ee = scene.eevee
    for attr, val in (("taa_render_samples", samples), ("use_raytracing", True), ("use_shadows", True),
                      ("shadow_ray_count", 2), ("shadow_step_count", 8), ("use_gtao", True)):
        if hasattr(ee, attr):
            setattr(ee, attr, val)
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.fps = FPS
    scene.frame_start, scene.frame_end = 1, end
    scene.render.image_settings.file_format = "PNG"

    if save:                              # the scene as a .blend file instead of frames
        scene.frame_set(1)
        scene.render.filepath = "//anim-frames/f"
        bpy.ops.file.pack_all()           # board textures from the KiCad GLB
        bpy.ops.wm.save_as_mainfile(filepath=save, compress=True)
        print("wrote", save)
        return

    fdir = os.path.join(out, "anim-frames")
    os.makedirs(fdir, exist_ok=True)
    todo = [int(f) for f in frames.split(",")] if frames else range(1, end + 1)
    for f in todo:
        scene.frame_set(f)
        scene.render.filepath = os.path.join(fdir, f"f{f:04d}.png")
        bpy.ops.render.render(write_still=True)
    print("wrote", len(list(todo)), "frames to", fdir)
