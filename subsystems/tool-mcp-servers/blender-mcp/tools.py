"""Helper functions for Blender CLI operations."""


def import_model_cmd(file_path: str, format: str = "obj") -> list[str]:
    """Build Blender CLI command for model import."""
    script = f'bpy.ops.import_scene.{format}(filepath="{file_path}")'
    return ["blender", "--background", "--python-expr", script]


def check_mesh_script(file_path: str) -> str:
    """Generate Blender Python script for mesh quality check."""
    return f'''
import bpy
import json
import bmesh

bpy.ops.import_scene.obj(filepath=r"{file_path}")
obj = bpy.context.selected_objects[0]
bm = bmesh.new()
bm.from_mesh(obj.data)

non_manifold = [e for e in bm.edges if not e.is_manifold]
loose_verts = [v for v in bm.verts if not v.link_edges]

result = {{
    "vertices": len(bm.verts),
    "edges": len(bm.edges),
    "faces": len(bm.faces),
    "non_manifold_edges": len(non_manifold),
    "loose_vertices": len(loose_verts),
    "is_watertight": len(non_manifold) == 0,
}}
bm.free()
print("RESULT:" + json.dumps(result))
'''


def render_preview_script(file_path: str, output_path: str, resolution: tuple[int, int] = (1920, 1080)) -> str:
    """Generate Blender Python script for rendering a preview."""
    return f'''
import bpy

bpy.ops.import_scene.obj(filepath=r"{file_path}")
scene = bpy.context.scene
scene.render.resolution_x = {resolution[0]}
scene.render.resolution_y = {resolution[1]}
scene.render.filepath = r"{output_path}"
bpy.ops.render.render(write_still=True)
print("RESULT:{{\\"output\\": \\"{output_path}\\", \\"status\\": \\"ok\\"}}")
'''
