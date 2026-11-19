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


def ease(obj):
    ad = obj.animation_data
    if not ad or not ad.action:
        return
    for fc in getattr(ad.action, "fcurves", []):
        for kp in fc.keyframe_points:
            kp.interpolation = "BEZIER"
            kp.easing = "AUTO"


def run(scene, cam, cam_data, target, center, lid, pins, whip, board_group, d, out, frames):
    base_h, top_z, sw_h = d["BASE_H"], d["TOP_Z"], d["SW_H"]
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
    for o in [board_group, lid, whip, *pins]:
        ease(o)

    # --- camera: on a pivot that turns 60 degrees, target sinks as the parts come down
    pivot = bpy.data.objects.new("pivot", None)
    scene.collection.objects.link(pivot)
    pivot.location = center
    cam.parent = pivot
    cam.location = Vector((0.0, -1.55, 0.95))
    cam_data.lens = 45
    cam_data.dof.aperture_fstop = 8
    pivot.rotation_euler = (0, 0, math.radians(-35))
    pivot.keyframe_insert("rotation_euler", index=2, frame=1)
    pivot.rotation_euler = (0, 0, math.radians(30))
    pivot.keyframe_insert("rotation_euler", index=2, frame=END)
    for fc in getattr(pivot.animation_data.action, "fcurves", []):
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
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
    scene.frame_start, scene.frame_end = 1, END
    scene.render.image_settings.file_format = "PNG"

    fdir = os.path.join(out, "anim-frames")
    os.makedirs(fdir, exist_ok=True)
    todo = [int(f) for f in frames.split(",")] if frames else range(1, END + 1)
    for f in todo:
        scene.frame_set(f)
        scene.render.filepath = os.path.join(fdir, f"f{f:04d}.png")
        bpy.ops.render.render(write_still=True)
    print("wrote", len(list(todo)), "frames to", fdir)
