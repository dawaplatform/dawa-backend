import io
import random

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image, ImageDraw

from DawaApp.image_validation import ImageRejected, prepare_listing_image, prepare_listing_images


def _picture(size, mode="RGB", seed=1):
    rng = random.Random(seed)
    image = Image.new(mode, size, (230, 230, 230, 255) if mode == "RGBA" else (230, 230, 230))
    draw = ImageDraw.Draw(image)
    for _ in range(120):
        x, y = rng.randrange(size[0]), rng.randrange(size[1])
        w, h = rng.randrange(20, size[0] // 4), rng.randrange(20, size[1] // 4)
        colour = tuple(rng.randrange(256) for _ in range(3)) + ((255,) if mode == "RGBA" else ())
        draw.rectangle([x, y, x + w, y + h], fill=colour)
    return image


def _upload(image, fmt="JPEG", name="photo.jpg", content_type="image/jpeg"):
    buffer = io.BytesIO()
    image.save(buffer, fmt)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


class ListingImageTests(SimpleTestCase):
    def test_large_photo_is_resized_and_reencoded(self):
        result = prepare_listing_image(_upload(_picture((3200, 2400))))
        out = Image.open(io.BytesIO(result.read()))
        self.assertEqual(out.format, "JPEG")
        self.assertLessEqual(max(out.size), 2048)

    def test_tiny_photo_rejected(self):
        with self.assertRaisesMessage(ImageRejected, "too small"):
            prepare_listing_image(_upload(_picture((300, 300))))

    def test_tall_screenshot_rejected(self):
        with self.assertRaisesMessage(ImageRejected, "screenshot"):
            prepare_listing_image(_upload(_picture((1080, 2400)), "PNG", "shot.png", "image/png"))

    def test_screen_shaped_png_without_camera_data_rejected(self):
        with self.assertRaisesMessage(ImageRejected, "screenshot"):
            prepare_listing_image(_upload(_picture((1200, 700)), "PNG", "shot.png", "image/png"))

    def test_blank_image_rejected(self):
        blank = Image.new("RGB", (900, 900), (255, 255, 255))
        with self.assertRaisesMessage(ImageRejected, "blank"):
            prepare_listing_image(_upload(blank))

    def test_corrupt_file_rejected(self):
        bad = SimpleUploadedFile("x.jpg", b"not an image at all", content_type="image/jpeg")
        with self.assertRaisesMessage(ImageRejected, "not a readable image"):
            prepare_listing_image(bad)

    def test_unsupported_type_rejected(self):
        upload = SimpleUploadedFile("x.pdf", b"%PDF", content_type="application/pdf")
        with self.assertRaisesMessage(ImageRejected, "Unsupported format"):
            prepare_listing_image(upload)

    def test_square_png_graphic_with_transparency_accepted(self):
        graphic = _picture((900, 900), "RGBA")
        graphic.putpixel((0, 0), (0, 0, 0, 0))
        result = prepare_listing_image(_upload(graphic, "PNG", "logo.png", "image/png"))
        self.assertEqual(Image.open(io.BytesIO(result.read())).mode, "RGB")

    def test_batch_reports_each_rejection_by_name(self):
        good = _upload(_picture((1200, 900)), name="good.jpg")
        bad = _upload(_picture((200, 200)), name="tiny.jpg")
        prepared, rejected = prepare_listing_images([good, bad])
        self.assertEqual(len(prepared), 1)
        self.assertEqual([r.name for r in rejected], ["tiny.jpg"])
