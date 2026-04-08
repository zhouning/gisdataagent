"""
DRL Optimization Animation — step-by-step replay of parcel transitions (v22.0).

Generates GIF animation showing the 200-step optimization process,
with each frame showing which parcels were swapped.
"""
from __future__ import annotations

import io
import os
from typing import Optional

import numpy as np

from .observability import get_logger

logger = get_logger("drl_animation")

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def generate_optimization_gif(
    grid_states: list[np.ndarray],
    output_path: str,
    class_colors: dict = None,
    frame_duration: int = 200,
    size: tuple = (400, 400),
    title: str = "DRL 优化过程",
) -> Optional[str]:
    """Generate a GIF animation from a sequence of grid states.

    Args:
        grid_states: List of 2D numpy arrays (each is a land-use grid at one step).
        output_path: Path to save the GIF.
        class_colors: Mapping of class value → RGB tuple. Defaults to a built-in palette.
        frame_duration: Milliseconds per frame.
        size: Output image size (width, height).
        title: Title text on each frame.

    Returns:
        Output path on success, None on failure.
    """
    if not HAS_PIL:
        logger.warning("PIL not installed, cannot generate GIF")
        return None

    if not grid_states:
        return None

    # Default color palette for land use classes
    if class_colors is None:
        class_colors = {
            0: (200, 200, 200),  # 未分类 - 灰色
            1: (34, 139, 34),    # 耕地 - 绿色
            2: (0, 100, 0),      # 林地 - 深绿
            3: (144, 238, 144),  # 草地 - 浅绿
            4: (255, 0, 0),      # 建设用地 - 红色
            5: (0, 0, 255),      # 水域 - 蓝色
            6: (255, 255, 0),    # 未利用地 - 黄色
        }

    frames = []
    h, w = grid_states[0].shape[:2]
    cell_w = size[0] // w
    cell_h = (size[1] - 30) // h  # reserve 30px for title

    for step_idx, grid in enumerate(grid_states):
        img = Image.new("RGB", size, (30, 30, 30))
        draw = ImageDraw.Draw(img)

        # Draw title bar
        draw.rectangle([0, 0, size[0], 28], fill=(20, 20, 40))
        draw.text((10, 6), f"{title} — Step {step_idx}/{len(grid_states)-1}",
                  fill=(200, 200, 200))

        # Draw grid
        for r in range(h):
            for c in range(w):
                val = int(grid[r, c]) if grid[r, c] == grid[r, c] else 0
                color = class_colors.get(val, (128, 128, 128))
                x0 = c * cell_w
                y0 = 30 + r * cell_h
                draw.rectangle([x0, y0, x0 + cell_w - 1, y0 + cell_h - 1], fill=color)

        # Highlight changes from previous frame
        if step_idx > 0:
            prev = grid_states[step_idx - 1]
            for r in range(h):
                for c in range(w):
                    if grid[r, c] != prev[r, c]:
                        x0 = c * cell_w
                        y0 = 30 + r * cell_h
                        draw.rectangle(
                            [x0, y0, x0 + cell_w - 1, y0 + cell_h - 1],
                            outline=(255, 255, 255), width=2,
                        )

        frames.append(img)

    if not frames:
        return None

    try:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        frames[0].save(
            output_path,
            save_all=True,
            append_images=frames[1:],
            duration=frame_duration,
            loop=0,
        )
        logger.info("Generated optimization GIF: %s (%d frames)", output_path, len(frames))
        return output_path
    except Exception as e:
        logger.warning("Failed to generate GIF: %s", e)
        return None


def generate_summary_frame(
    before: np.ndarray,
    after: np.ndarray,
    class_colors: dict = None,
    size: tuple = (800, 400),
) -> Optional[bytes]:
    """Generate a side-by-side comparison image (before vs after).

    Returns PNG bytes or None.
    """
    if not HAS_PIL:
        return None

    if class_colors is None:
        class_colors = {
            0: (200, 200, 200), 1: (34, 139, 34), 2: (0, 100, 0),
            3: (144, 238, 144), 4: (255, 0, 0), 5: (0, 0, 255), 6: (255, 255, 0),
        }

    half_w = size[0] // 2
    h, w = before.shape[:2]
    cell_w = half_w // w
    cell_h = (size[1] - 30) // h

    img = Image.new("RGB", size, (30, 30, 30))
    draw = ImageDraw.Draw(img)

    # Headers
    draw.rectangle([0, 0, half_w, 28], fill=(20, 40, 20))
    draw.text((10, 6), "优化前", fill=(200, 200, 200))
    draw.rectangle([half_w, 0, size[0], 28], fill=(40, 20, 20))
    draw.text((half_w + 10, 6), "优化后", fill=(200, 200, 200))

    # Draw both grids
    for grid, x_offset in [(before, 0), (after, half_w)]:
        for r in range(h):
            for c in range(w):
                val = int(grid[r, c]) if grid[r, c] == grid[r, c] else 0
                color = class_colors.get(val, (128, 128, 128))
                x0 = x_offset + c * cell_w
                y0 = 30 + r * cell_h
                draw.rectangle([x0, y0, x0 + cell_w - 1, y0 + cell_h - 1], fill=color)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
