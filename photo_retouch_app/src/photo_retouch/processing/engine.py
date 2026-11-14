"""
Image processing engine for real-time adjustments and compositing.
"""
import logging
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass
from enum import Enum
import numpy as np

from PIL import Image, ImageEnhance, ImageFilter, ImageFont, ImageDraw, ImageOps
import cv2

from photo_retouch.core.models import Adjustments, Transform, Point, TextStyle, TextOverlay, CostumeItem

logger = logging.getLogger(__name__)


class BlendMode(Enum):
    NORMAL = "normal"
    MULTIPLY = "multiply"
    SCREEN = "screen"
    OVERLAY = "overlay"
    SOFT_LIGHT = "soft_light"
    HARD_LIGHT = "hard_light"


@dataclass
class Layer:
    """Represents a compositing layer."""
    image: Image.Image
    name: str
    visible: bool = True
    opacity: float = 1.0
    blend_mode: BlendMode = BlendMode.NORMAL
    transform: Transform = None

    def __post_init__(self):
        if self.transform is None:
            self.transform = Transform()


class ImageProcessor:
    """Core image processing operations."""

    @staticmethod
    def apply_adjustments(image: Image.Image, adjustments: Adjustments) -> Image.Image:
        """Apply brightness, contrast, sharpness, saturation, temperature, vignette adjustments."""
        if image is None:
            return None

        adj = adjustments.clamp()
        result = image.copy()

        # Brightness
        if adj.brightness != 0:
            enhancer = ImageEnhance.Brightness(result)
            factor = 1.0 + (adj.brightness / 100.0)
            result = enhancer.enhance(factor)

        # Contrast
        if adj.contrast != 0:
            enhancer = ImageEnhance.Contrast(result)
            factor = 1.0 + (adj.contrast / 100.0)
            result = enhancer.enhance(factor)

        # Saturation
        if adj.saturation != 0:
            enhancer = ImageEnhance.Color(result)
            factor = 1.0 + (adj.saturation / 100.0)
            result = enhancer.enhance(factor)

        # Temperature (warm/cool)
        if adj.temperature != 0:
            result = ImageProcessor._apply_temperature(result, adj.temperature)

        # Sharpness (Unsharp Mask)
        if adj.sharpness > 0:
            alpha = result.getchannel("A") if result.mode == "RGBA" else None
            # Convert to OpenCV for better unsharp mask
            cv_image = np.array(result)
            if len(cv_image.shape) == 3:
                cv_image = cv2.cvtColor(cv_image, cv2.COLOR_RGBA2RGB)

            # Unsharp mask
            gaussian = cv2.GaussianBlur(cv_image, (0, 0), adj.sharpness / 10.0)
            strength = adj.sharpness / 50.0
            cv_image = cv2.addWeighted(cv_image, 1.0 + strength, gaussian, -strength, 0)

            # Convert back
            if len(cv_image.shape) == 3:
                cv_image = cv2.cvtColor(cv_image, cv2.COLOR_RGB2RGBA)
            result = Image.fromarray(cv_image)
            if alpha is not None:
                result.putalpha(alpha)

        # Vignette
        if adj.vignette > 0:
            result = ImageProcessor._apply_vignette(result, adj.vignette)

        return result

    @staticmethod
    def _apply_temperature(image: Image.Image, temperature: int) -> Image.Image:
        """Apply temperature adjustment (warm/cool)."""
        # Temperature: negative = cool (blue), positive = warm (orange/red)
        cv_image = np.array(image).astype(np.float32) / 255.0
        if len(cv_image.shape) == 3 and cv_image.shape[2] == 4:
            # Has alpha channel
            rgb = cv_image[:, :, :3]
            alpha = cv_image[:, :, 3:4]
        else:
            rgb = cv_image
            alpha = None

        # Temperature factor: -100 to 100 mapped to color shift
        factor = temperature / 100.0
        if factor > 0:
            # Warm: increase red, decrease blue
            rgb[:, :, 0] = np.clip(rgb[:, :, 0] + factor * 0.3, 0, 1)  # Red
            rgb[:, :, 2] = np.clip(rgb[:, :, 2] - factor * 0.2, 0, 1)  # Blue
        else:
            # Cool: increase blue, decrease red
            factor = abs(factor)
            rgb[:, :, 2] = np.clip(rgb[:, :, 2] + factor * 0.3, 0, 1)  # Blue
            rgb[:, :, 0] = np.clip(rgb[:, :, 0] - factor * 0.2, 0, 1)  # Red

        if alpha is not None:
            cv_image = np.concatenate([rgb, alpha], axis=2)
        else:
            cv_image = rgb

        cv_image = (np.clip(cv_image, 0, 1) * 255).astype(np.uint8)
        return Image.fromarray(cv_image, "RGBA" if alpha is not None else "RGB")

    @staticmethod
    def _apply_vignette(image: Image.Image, amount: int) -> Image.Image:
        """Apply vignette effect."""
        cv_image = np.array(image).astype(np.float32) / 255.0
        h, w = cv_image.shape[:2]

        # Create vignette mask
        center_x, center_y = w / 2, h / 2
        max_dist = np.sqrt(center_x**2 + center_y**2)

        y, x = np.ogrid[:h, :w]
        dist = np.sqrt((x - center_x)**2 + (y - center_y)**2)
        vignette = 1.0 - (dist / max_dist) * (amount / 100.0) * 0.5
        vignette = np.clip(vignette, 0, 1)

        # Apply to RGB channels
        if len(cv_image.shape) == 3:
            for c in range(min(3, cv_image.shape[2])):
                cv_image[:, :, c] *= vignette

        cv_image = (np.clip(cv_image, 0, 1) * 255).astype(np.uint8)
        return Image.fromarray(cv_image)

    @staticmethod
    def resize_to_canvas(image: Image.Image, canvas_size: Tuple[int, int],
                         keep_aspect: bool = True) -> Image.Image:
        """Resize image to fit canvas."""
        if image is None:
            return None

        if keep_aspect:
            image.thumbnail(canvas_size, Image.Resampling.LANCZOS)
            # Create new canvas and center the image
            result = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
            x = (canvas_size[0] - image.width) // 2
            y = (canvas_size[1] - image.height) // 2
            result.paste(image, (x, y))
            return result
        else:
            return image.resize(canvas_size, Image.Resampling.LANCZOS)

    @staticmethod
    def apply_transform(image: Image.Image, transform: Transform,
                        canvas_size: Tuple[int, int]) -> Image.Image:
        """Apply position, scale, rotation transform."""
        if image is None:
            return None

        result = image.copy()

        # Apply rotation
        if transform.rotation != 0:
            result = result.rotate(transform.rotation, expand=True, resample=Image.Resampling.BICUBIC)

        # Apply scale
        if transform.scale != 1.0:
            new_size = (int(result.width * transform.scale), int(result.height * transform.scale))
            result = result.resize(new_size, Image.Resampling.LANCZOS)

        # Apply position (create canvas and paste at position)
        canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        x = int(transform.position.x)
        y = int(transform.position.y)

        # Center the transformed image at the position
        paste_x = x - result.width // 2
        paste_y = y - result.height // 2

        canvas.paste(result, (paste_x, paste_y))
        return canvas

    @staticmethod
    def blend_layers(base: Image.Image, overlay: Image.Image,
                     opacity: float = 1.0, mode: BlendMode = BlendMode.NORMAL) -> Image.Image:
        """Blend two images with specified mode and opacity."""
        if base is None:
            return overlay
        if overlay is None:
            return base

        # Ensure both are RGBA
        if base.mode != "RGBA":
            base = base.convert("RGBA")
        if overlay.mode != "RGBA":
            overlay = overlay.convert("RGBA")

        # Resize overlay to match base if needed
        if overlay.size != base.size:
            overlay = overlay.resize(base.size, Image.Resampling.LANCZOS)

        if mode == BlendMode.NORMAL:
            # Simple alpha blend
            if opacity < 1.0:
                overlay = ImageProcessor._apply_opacity(overlay, opacity)
            return Image.alpha_composite(base, overlay)

        # For other blend modes, use OpenCV
        base_cv = np.array(base).astype(np.float32) / 255.0
        overlay_cv = np.array(overlay).astype(np.float32) / 255.0

        # Separate alpha channels
        base_rgb = base_cv[:, :, :3]
        base_alpha = base_cv[:, :, 3:4]
        overlay_rgb = overlay_cv[:, :, :3]
        overlay_alpha = overlay_cv[:, :, 3:4] * opacity

        # Apply blend mode
        if mode == BlendMode.MULTIPLY:
            blended_rgb = base_rgb * overlay_rgb
        elif mode == BlendMode.SCREEN:
            blended_rgb = 1.0 - (1.0 - base_rgb) * (1.0 - overlay_rgb)
        elif mode == BlendMode.OVERLAY:
            blended_rgb = np.where(base_rgb < 0.5,
                                   2.0 * base_rgb * overlay_rgb,
                                   1.0 - 2.0 * (1.0 - base_rgb) * (1.0 - overlay_rgb))
        elif mode == BlendMode.SOFT_LIGHT:
            blended_rgb = np.where(overlay_rgb < 0.5,
                                   base_rgb - (1.0 - 2.0 * overlay_rgb) * base_rgb * (1.0 - base_rgb),
                                   base_rgb + (2.0 * overlay_rgb - 1.0) * (np.sqrt(base_rgb) - base_rgb))
        elif mode == BlendMode.HARD_LIGHT:
            blended_rgb = np.where(overlay_rgb < 0.5,
                                   2.0 * base_rgb * overlay_rgb,
                                   1.0 - 2.0 * (1.0 - base_rgb) * (1.0 - overlay_rgb))
        else:
            blended_rgb = overlay_rgb

        # Composite with alpha
        out_alpha = base_alpha + overlay_alpha * (1.0 - base_alpha)
        out_rgb = (base_rgb * base_alpha + blended_rgb * overlay_alpha * (1.0 - base_alpha)) / np.maximum(out_alpha, 1e-6)

        result_cv = np.concatenate([out_rgb, out_alpha], axis=2)
        result_cv = (np.clip(result_cv, 0, 1) * 255).astype(np.uint8)
        return Image.fromarray(result_cv, "RGBA")

    @staticmethod
    def _apply_opacity(image: Image.Image, opacity: float) -> Image.Image:
        """Apply opacity to image."""
        if opacity >= 1.0:
            return image
        result = image.copy()
        alpha = result.split()[-1]
        alpha = ImageEnhance.Brightness(alpha).enhance(opacity)
        result.putalpha(alpha)
        return result


class Compositor:
    """High-level compositing engine for the photo retouch layers."""

    # Layer order (bottom to top)
    LAYER_ORDER = ["background", "photo", "costume", "frame", "text"]

    def __init__(self, canvas_size: Tuple[int, int] = (1024, 1024)):
        self.canvas_size = canvas_size
        self.layers: Dict[str, Layer] = {}
        self._initialize_layers()

    def _initialize_layers(self) -> None:
        """Initialize empty layers."""
        for name in self.LAYER_ORDER:
            self.layers[name] = Layer(
                image=Image.new("RGBA", self.canvas_size, (0, 0, 0, 0)),
                name=name
            )

    def set_canvas_size(self, size: Tuple[int, int]) -> None:
        """Change canvas size and resize all layers."""
        self.canvas_size = size
        for layer in self.layers.values():
            if layer.image.size != size:
                layer.image = layer.image.resize(size, Image.Resampling.LANCZOS)

    def set_layer_image(self, name: str, image: Image.Image,
                        transform: Transform = None) -> None:
        """Set image for a layer."""
        if name not in self.layers:
            logger.warning(f"Layer '{name}' not found in compositor")
            return

        layer = self.layers[name]
        if image is None:
            layer.image = Image.new("RGBA", self.canvas_size, (0, 0, 0, 0))
        else:
            # Resize to canvas if it's the background or photo layer
            if name in ("background", "photo"):
                layer.image = ImageProcessor.resize_to_canvas(image, self.canvas_size)
            elif name == "frame":
                layer.image = ImageProcessor.resize_to_canvas(image, self.canvas_size, keep_aspect=False)
            elif transform:
                layer.image = ImageProcessor.apply_transform(image, transform, self.canvas_size)
            else:
                # For costume and other layers, just resize to canvas
                layer.image = image.resize(self.canvas_size, Image.Resampling.LANCZOS)

        if transform:
            layer.transform = transform
        logger.debug(f"Set layer '{name}' image: {layer.image.size}")

    def set_layer_visibility(self, name: str, visible: bool) -> None:
        """Set layer visibility."""
        if name in self.layers:
            self.layers[name].visible = visible

    def set_layer_opacity(self, name: str, opacity: float) -> None:
        """Set layer opacity."""
        if name in self.layers:
            self.layers[name].opacity = max(0.0, min(1.0, opacity))

    def composite(self) -> Image.Image:
        """Composite all visible layers in order."""
        result = Image.new("RGBA", self.canvas_size, (0, 0, 0, 0))

        for name in self.LAYER_ORDER:
            layer = self.layers[name]
            if not layer.visible:
                continue
            if layer.image is None:
                continue

            result = ImageProcessor.blend_layers(
                result, layer.image,
                opacity=layer.opacity,
                mode=layer.blend_mode
            )

        return result

    def get_layer(self, name: str) -> Optional[Layer]:
        """Get layer by name."""
        return self.layers.get(name)


class TextRenderer:
    """Renders text overlays with styling."""

    @staticmethod
    def render_text(overlay: TextOverlay, canvas_size: Tuple[int, int],
                    font_path: str = "") -> Image.Image:
        """Render text overlay to image."""
        if not overlay.content or not overlay.visible:
            return Image.new("RGBA", canvas_size, (0, 0, 0, 0))

        # Create transparent canvas
        canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)

        # Load font
        try:
            if font_path and Path(font_path).exists():
                font = ImageFont.truetype(font_path, overlay.style.font_size)
            else:
                # Try system fonts
                font = ImageFont.load_default(size=overlay.style.font_size)
                # Try to get a better default
                try:
                    font = ImageFont.truetype("DejaVuSans.ttf", overlay.style.font_size)
                except:
                    pass
        except Exception as e:
            logger.warning(f"Font load failed: {e}")
            font = ImageFont.load_default(size=overlay.style.font_size)

        # Calculate text position (center of the position point)
        bbox = draw.textbbox((0, 0), overlay.content, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        x = int(overlay.position.x) - text_width // 2
        y = int(overlay.position.y) - text_height // 2

        # Draw shadow if enabled
        if overlay.style.shadow_enabled:
            shadow_offset = overlay.style.shadow_offset
            shadow_x = x + int(shadow_offset.x)
            shadow_y = y + int(shadow_offset.y)
            # Create shadow by drawing multiple times with blur
            for dx in range(-overlay.style.shadow_blur, overlay.style.shadow_blur + 1):
                for dy in range(-overlay.style.shadow_blur, overlay.style.shadow_blur + 1):
                    alpha = max(0, 255 - (abs(dx) + abs(dy)) * 255 // max(1, overlay.style.shadow_blur))
                    if alpha > 0:
                        draw.text((shadow_x + dx, shadow_y + dy), overlay.content,
                                  font=font, fill=overlay.style.shadow_color + f"{alpha:02x}")

        # Draw stroke if enabled
        if overlay.style.stroke_enabled:
            stroke_width = overlay.style.stroke_width
            for dx in range(-stroke_width, stroke_width + 1):
                for dy in range(-stroke_width, stroke_width + 1):
                    if dx != 0 or dy != 0:
                        draw.text((x + dx, y + dy), overlay.content,
                                  font=font, fill=overlay.style.stroke_color)

        # Draw main text
        draw.text((x, y), overlay.content, font=font, fill=overlay.style.color)

        return canvas


def load_image_safe(path: Path) -> Optional[Image.Image]:
    """Safely load an image file."""
    try:
        img = Image.open(path)
        img.load()  # Force load to verify
        return img.convert("RGBA")
    except Exception as e:
        logger.error(f"Failed to load image {path}: {e}")
        return None


def save_image(image: Image.Image, path: Path, quality: int = 95,
               dpi: Tuple[int, int] = (300, 300), format: str = None) -> bool:
    """Save image with options."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        if format is None:
            format = path.suffix[1:].upper()
            if format == "JPG":
                format = "JPEG"

        save_kwargs = {"dpi": dpi}

        if format == "JPEG":
            if image.mode == "RGBA":
                # Composite on white background
                bg = Image.new("RGB", image.size, (255, 255, 255))
                bg.paste(image, mask=image.split()[3])
                image = bg
            save_kwargs["quality"] = quality
            save_kwargs["optimize"] = True
        elif format == "PNG":
            save_kwargs["compress_level"] = 6
        elif format == "TIFF":
            save_kwargs["compression"] = "tiff_lzw"

        image.save(path, format=format, **save_kwargs)
        return True
    except Exception as e:
        logger.error(f"Failed to save image {path}: {e}")
        return False
