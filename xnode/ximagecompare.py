"""
交互式 A/B 图像对比节点模块 (V3 API)
=================================

提供双图像对比功能，前端 Canvas 渲染 4 种对比模式。
后端负责保存图像到 output 目录并透传。
"""

import time
from pathlib import Path

import numpy as np
import torch
from comfy_api.latest import io, ui
from PIL import Image as PILImage

try:
    from ..xz3r0_utils import get_logger
except ImportError:
    from xz3r0_utils import get_logger  # type: ignore[import]

try:
    import folder_paths

    COMFYUI_AVAILABLE = True
except ImportError:
    COMFYUI_AVAILABLE = False

LOGGER = get_logger(__name__)

# 输出子目录名
_SAVE_SUBDIR = "XImageCompare"

# 错误常量（不暴露绝对路径）
_OUTPUT_DIRECTORY_ERROR = "Unable to create compare output directory"
_WRITE_IMAGE_ERROR = "Unable to write compare image file"


class XImageCompare(io.ComfyNode):
    """交互式 A/B 图像对比节点 (V3)。

    前端提供 Canvas 画布渲染，4 种对比模式：
    - 滑动横向过渡对比
    - 鼠标聚光局部对比
    - 透明度渐变对比
    - 自动乒乓式透明度循环对比

    后端职责：
    - 接受 image_a / image_b
    - 统一缩放到相同尺寸
    - 保存到 output/XImageCompare/（持久存储）
    - 透传两张图到下游
    """

    @classmethod
    def define_schema(cls) -> io.Schema:
        """定义节点输入输出模式。"""
        compare_template = io.MatchType.Template(
            "compare_passthrough",
            allowed_types=[io.Image, io.Mask],
        )
        return io.Schema(
            node_id="XImageCompare",
            display_name="XImageCompare",
            description=(
                "Interactive A/B image or mask comparison "
                "with 4 modes: slide, spotlight, blend, "
                "and auto ping-pong. "
                "Supports IMAGE and MASK inputs."
            ),
            category="♾️ Xz3r0/Workflow-Processing",
            is_output_node=True,
            inputs=[
                io.MatchType.Input(
                    "image_a",
                    template=compare_template,
                    optional=True,
                    tooltip="Image or Mask A for comparison (optional)",
                ),
                io.MatchType.Input(
                    "image_b",
                    template=compare_template,
                    optional=True,
                    tooltip="Image or Mask B for comparison (optional)",
                ),
                io.Boolean.Input(
                    "save_to_output",
                    default=False,
                    label_on="To Output (Persistent)",
                    label_off="Temp Cache",
                    tooltip=(
                        "Enable: save to output folder (persistent, "
                        "survives page refresh). "
                        "Disabled: use temp cache (cleaned on restart)"
                    ),
                ),
                io.Boolean.Input(
                    "swap_ab",
                    default=False,
                    label_on="A ↔ B Swapped",
                    label_off="A → A  B → B",
                    tooltip=(
                        "Swap both the display and output order "
                        "of Image/Mask A and B"
                    ),
                ),
                io.Int.Input(
                    "__compare_mode",
                    default=0,
                    socketless=True,
                    extra_dict={"hidden": True},
                ),
                io.Float.Input(
                    "__compare_slider",
                    default=50,
                    socketless=True,
                    extra_dict={"hidden": True},
                ),
            ],
            outputs=[
                io.MatchType.Output(
                    template=compare_template,
                    display_name="A",
                    tooltip="Passthrough of A",
                ),
                io.MatchType.Output(
                    template=compare_template,
                    display_name="B",
                    tooltip="Passthrough of B",
                ),
            ],
            hidden=[io.Hidden.prompt, io.Hidden.extra_pnginfo],
        )

    @classmethod
    def execute(
        cls,
        image_a=None,
        image_b=None,
        **_kwargs: object,
    ) -> io.NodeOutput:
        """保存对比图像并透传（可选输入，无输入时为 None）。"""
        save_to_output = bool(_kwargs.get("save_to_output", False))
        swap_ab = bool(_kwargs.get("swap_ab", False))

        # 选择目录和文件夹类型
        if save_to_output:
            base_dir = cls._get_output_directory()
            folder_type = io.FolderType.output
        else:
            base_dir = cls._get_temp_directory()
            folder_type = io.FolderType.temp

        save_dir = base_dir / _SAVE_SUBDIR
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(_OUTPUT_DIRECTORY_ERROR) from exc

        timestamp = int(time.time() * 1000)
        saved_results = []

        for tensor, label in [
            (image_a, "a"),
            (image_b, "b"),
        ]:
            if tensor is None:
                saved_results.append({})  # 空占位保持索引位置
                continue
            # MASK 是 (B,H,W) 或 (H,W)，取第一帧并扩展为 (H,W,1)
            frame = tensor[0] if tensor.dim() >= 3 else tensor
            pil_image = cls._tensor_to_pil(frame)
            filename = f"xcompare_{timestamp}_{label}.png"
            filepath = save_dir / filename
            try:
                pil_image.save(filepath, format="PNG")
            except OSError as exc:
                raise RuntimeError(_WRITE_IMAGE_ERROR) from exc

            saved_results.append(
                ui.SavedResult(
                    filename,
                    _SAVE_SUBDIR,
                    folder_type,
                )
            )

        LOGGER.debug(
            "XImageCompare saved: a=%s, b=%s",
            saved_results[0].get("filename", "none"),
            saved_results[1].get("filename", "none"),
        )

        # 透传（swap_ab 交换），无输入时输出为 None
        out_a = image_b if swap_ab else image_a
        out_b = image_a if swap_ab else image_b

        # 始终传递 2 个条目（可为 None），前端按位置区分 A/B
        return io.NodeOutput(
            out_a,
            out_b,
            ui=ui.SavedImages(saved_results) if any(
                r.get("filename") for r in saved_results
            ) else None,
        )

    # ------------ 私有辅助方法 ------------

    @classmethod
    def _tensor_to_pil(cls, tensor: torch.Tensor) -> PILImage.Image:
        """将图像或遮罩张量转换为 PIL Image。

        支持 IMAGE (H,W,C) 和 MASK (H,W) 格式。
        """
        tensor = tensor.detach().cpu()

        if tensor.dim() == 2:
            # MASK (H,W) → 单通道灰度
            numpy_array = (
                np.clip(255.0 * tensor.numpy(), 0, 255)
                .astype(np.uint8)
            )
            return PILImage.fromarray(numpy_array, mode="L")

        # IMAGE (H,W,C) 或 MASK (H,W,1)
        if not tensor.is_contiguous():
            tensor = tensor.contiguous()

        numpy_array = tensor.numpy()
        numpy_array = (
            np.clip(255.0 * numpy_array, 0, 255)
            .astype(np.uint8)
        )

        channels = tensor.shape[2]
        if channels == 4:
            mode = "RGBA"
        elif channels == 3:
            mode = "RGB"
        elif channels == 1:
            mode = "L"
            numpy_array = numpy_array.squeeze(2)
        else:
            raise ValueError(
                f"Expected 1, 3, or 4 channels, got {channels}"
            )

        return PILImage.fromarray(numpy_array, mode=mode)

    @classmethod
    def _get_output_directory(cls) -> Path:
        """获取 ComfyUI 输出目录。"""
        if COMFYUI_AVAILABLE:
            return Path(folder_paths.get_output_directory())
        return Path("test_output")

    @classmethod
    def _get_temp_directory(cls) -> Path:
        """获取 ComfyUI 临时目录。"""
        if COMFYUI_AVAILABLE:
            return Path(folder_paths.get_temp_directory())
        return Path("test_temp")
