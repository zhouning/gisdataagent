from tools import import_model_cmd, check_mesh_script, render_preview_script


def test_import_model_cmd_uses_blender():
    cmd = import_model_cmd("/data/building.obj", "obj")
    assert cmd[0] == "blender"
    assert "--background" in cmd
    assert "import_scene.obj" in cmd[-1]


def test_check_mesh_script_contains_bmesh():
    script = check_mesh_script("/data/model.obj")
    assert "bmesh" in script
    assert "non_manifold" in script
    assert "is_watertight" in script


def test_render_preview_script_sets_resolution():
    script = render_preview_script("/data/model.obj", "/tmp/preview.png", (800, 600))
    assert "resolution_x = 800" in script
    assert "resolution_y = 600" in script
    assert "render.render" in script
