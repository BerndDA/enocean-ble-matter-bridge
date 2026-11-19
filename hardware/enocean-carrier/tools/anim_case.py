"""Assembly animation for render_case.py: board drops into the base, the push pins follow,
the lid closes, the whip slides in through the lid; the camera circles slowly.
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
        view="front", plug=None, glow_mat=None):
    """view "front": the buttons side; "usb": the USB end, and a USB-C plug goes in at the end."""
    base_h, top_z, sw_h = d["BASE_H"], d["TOP_Z"], d["SW_H"]
    end = END + (48 if view == "usb" else 0)   # usb: plug goes in, then the LED blinks
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
    if plug is not None:                  # slides in along the case's long axis (+Y = out of the end wall)
        plug.location.y = 45.0
        plug.keyframe_insert("location", index=1, frame=1)
        plug.keyframe_insert("location", index=1, frame=168)
        plug.location.y = 0.0
        plug.keyframe_insert("location", index=1, frame=200)
        movers.append(plug)
    for o in movers:
        ease(o)
    if glow_mat is not None:              # three blinks after the plug is in (frame 200)
        inp = glow_mat.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"]
        inp.default_value = 0.0
        inp.keyframe_insert("default_value", frame=1)
        light = bpy.data.lights.get(glow_mat.get("light", ""))
        if light is not None:
            light.energy = 0.0
            light.keyframe_insert("energy", frame=1)
        for on in (206, 218, 230):
            inp.default_value = 250.0
            inp.keyframe_insert("default_value", frame=on)
            inp.default_value = 0.0
            inp.keyframe_insert("default_value", frame=on + 6)
            if light is not None:
                light.energy = 0.6
                light.keyframe_insert("energy", frame=on)
                light.energy = 0.0
                light.keyframe_insert("energy", frame=on + 6)
        for owner in (glow_mat.node_tree, light):
            interp(owner, "CONSTANT")
        assert fcurves(glow_mat.node_tree), "no keyframes found for the LED"

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
    for attr, val in (("taa_render_samples", 64), ("use_raytracing", True), ("use_shadows", True),
                      ("shadow_ray_count", 2), ("shadow_step_count", 8), ("use_gtao", True)):
        if hasattr(ee, attr):
            setattr(ee, attr, val)
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.fps = FPS
    scene.frame_start, scene.frame_end = 1, end
    scene.render.image_settings.file_format = "PNG"

    fdir = os.path.join(out, "anim-frames")
    os.makedirs(fdir, exist_ok=True)
    todo = [int(f) for f in frames.split(",")] if frames else range(1, end + 1)
    for f in todo:
        scene.frame_set(f)
        scene.render.filepath = os.path.join(fdir, f"f{f:04d}.png")
        bpy.ops.render.render(write_still=True)
    print("wrote", len(list(todo)), "frames to", fdir)
