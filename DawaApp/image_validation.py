"""Pre-upload validation and normalisation for listing photos."""
from __future__ import annotations

import io
from dataclasses import dataclass

from django.core.files.base import ContentFile
from PIL import Image, ImageOps, ImageStat, UnidentifiedImageError

from listingModeration.stages import metadata as provenance

ALLOWED_TYPES = frozenset({"image/jpeg", "image/jpg", "image/png", "image/gif", "image/webp"})
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 60_000_000
MIN_SIDE = 400
MAX_ASPECT = 2.0
# Phone and 16:9 desktop screens; plain PNG product graphics are closer to square.
SCREEN_ASPECT = 1.7
MAX_OUTPUT_SIDE = 2048
JPEG_QUALITY = 85
# Grayscale standard deviation below this means a solid or near-solid picture.
MIN_DETAIL = 6.0
CAMERA_EXIF_TAGS = (271, 272)  # Make, Model


class ImageRejected(Exception):
    """Carries the user-facing reason a photo was refused."""


@dataclass
class RejectedImage:
    name: str
    reason: str


def _has_camera_exif(image: Image.Image) -> bool:
    exif = image.getexif()
    return any(exif.get(tag) for tag in CAMERA_EXIF_TAGS)


def _has_real_transparency(image: Image.Image) -> bool:
    if image.mode not in ("RGBA", "LA"):
        return False
    return image.getchannel("A").getextrema()[0] < 255


def _check_shape(image: Image.Image) -> None:
    width, height = image.size
    if min(width, height) < MIN_SIDE:
        raise ImageRejected(f"Photo is too small ({width}x{height}px). Use one at least {MIN_SIDE}px on each side.")
    if max(width / height, height / width) > MAX_ASPECT:
        raise ImageRejected(
            f"Photo is too tall or wide ({width}x{height}px) and looks like a screenshot. "
            "Upload a normal photo of the item."
        )


def _check_content(image: Image.Image, format_name: str | None) -> None:
    width, height = image.size
    screen_shaped = max(width / height, height / width) >= SCREEN_ASPECT
    if format_name == "PNG" and screen_shaped and not _has_camera_exif(image) and not _has_real_transparency(image):
        raise ImageRejected("This looks like a screenshot. Please upload a photo of the actual item.")
    if ImageStat.Stat(_thumbnail(image).convert("L")).stddev[0] < MIN_DETAIL:
        raise ImageRejected("This image looks blank. Please upload a clear photo of the item.")


def _thumbnail(image: Image.Image) -> Image.Image:
    small = image.copy()
    small.thumbnail((256, 256))
    return small


def _normalise(image: Image.Image) -> bytes:
    if _has_real_transparency(image):
        flattened = Image.new("RGB", image.size, "white")
        flattened.paste(image, mask=image.getchannel("A"))
        image = flattened
    else:
        image = image.convert("RGB")
    image.thumbnail((MAX_OUTPUT_SIDE, MAX_OUTPUT_SIDE), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return buffer.getvalue()


def prepare_listing_image(upload) -> ContentFile:
    """Validate one upload and return a resized, EXIF-stripped JPEG ready for storage."""
    if upload.size > MAX_UPLOAD_BYTES:
        raise ImageRejected(f"File is too large ({upload.size / 1024 / 1024:.1f}MB). Maximum is 5MB.")
    content_type = getattr(upload, "content_type", None)
    if content_type and content_type not in ALLOWED_TYPES:
        raise ImageRejected(f"Unsupported format ({content_type}). Use JPEG, PNG, GIF or WebP.")

    raw = upload.read()
    try:
        image = Image.open(io.BytesIO(raw))
        format_name = image.format
        if image.width * image.height > MAX_PIXELS:
            raise ImageRejected("Photo has too many pixels. Please use a smaller photo.")
        image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise ImageRejected("This file is not a readable image. Please choose a different photo.")

    # Provenance runs on the original because re-encoding drops the EXIF it inspects.
    reason = provenance.check(raw, upload.name)
    if reason:
        raise ImageRejected(reason)

    image = ImageOps.exif_transpose(image)
    _check_shape(image)
    _check_content(image, format_name)
    stem = upload.name.rsplit(".", 1)[0] or "photo"
    return ContentFile(_normalise(image), name=f"{stem}.jpg")


def prepare_listing_images(uploads) -> tuple[list[ContentFile], list[RejectedImage]]:
    prepared: list[ContentFile] = []
    rejected: list[RejectedImage] = []
    for upload in uploads:
        try:
            prepared.append(prepare_listing_image(upload))
        except ImageRejected as exc:
            rejected.append(RejectedImage(upload.name, str(exc)))
    return prepared, rejected
