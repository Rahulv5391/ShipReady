"""Turn a digital PDF into what reaches an exporter's inbox: a scanned PDF or phone photos.

Every effect is driven by the caller's random generator, never by global randomness, so the
same seed gives the same pixels.
"""

import io
import random
from datetime import datetime

import pypdfium2 as pdfium
from PIL import Image, ImageChops, ImageEnhance, ImageFilter

_FIXED_DATE = datetime(2026, 1, 1).timetuple()  # Pillow takes a struct_time
Image.MAX_IMAGE_PIXELS = 60_000_000  # an A4 page at 300 dpi is about 8.7 million pixels


def pages(pdf: bytes, dpi: int) -> list[Image.Image]:
    """Render each page of `pdf` to an RGB image at `dpi`."""
    document = pdfium.PdfDocument(pdf)
    try:
        return [page.render(scale=dpi / 72).to_pil().convert("RGB") for page in document]
    finally:
        document.close()


def scan(page: Image.Image, rng: random.Random, rotation: int = 0) -> Image.Image:
    """A flatbed or office-printer scan: grey, a little skewed, blurred and noisy.
    `rotation` (90 or 180) is a page fed the wrong way round."""
    image = page.convert("L")
    image = ImageEnhance.Contrast(image).enhance(rng.uniform(1.1, 1.4))
    paper = rng.randint(228, 246)
    image = image.rotate(
        rng.uniform(-1.5, 1.5) + rotation,
        resample=Image.Resampling.BICUBIC,
        expand=True,
        fillcolor=paper,
    )
    image = image.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.8)))
    return _add_noise(image, rng, amplitude=rng.uniform(10, 22))


def photo(page: Image.Image, rng: random.Random) -> Image.Image:
    """A phone photo of the printed page on a desk: perspective, uneven light, colour cast."""
    width, height = page.size
    margin_x, margin_y = int(width * 0.06), int(height * 0.05)
    desk = (rng.randint(70, 130), rng.randint(60, 110), rng.randint(50, 100))
    canvas = Image.new("RGB", (width + 2 * margin_x, height + 2 * margin_y), desk)
    canvas.paste(page, (margin_x, margin_y))

    # Moving each corner of the source quad a little gives the camera's perspective.
    w, h = canvas.size

    def jitter(x: float, y: float) -> tuple[float, float]:
        return x + rng.uniform(-0.03, 0.03) * w, y + rng.uniform(-0.03, 0.03) * h

    quad = (*jitter(0, 0), *jitter(0, h), *jitter(w, h), *jitter(w, 0))
    image = canvas.transform(
        canvas.size,
        Image.Transform.QUAD,
        quad,
        resample=Image.Resampling.BICUBIC,
        fillcolor=desk,
    )

    # A shadow falling across the page from one side.
    gradient = Image.linear_gradient("L").rotate(rng.choice((0, 90, 180, 270))).resize(image.size)
    depth = rng.uniform(0.25, 0.45)
    shadow = gradient.point(lambda v: int(255 - v * depth))
    image = ImageChops.multiply(image, Image.merge("RGB", (shadow, shadow, shadow)))

    warm = rng.uniform(1.0, 1.08)
    red, green, blue = image.split()
    red = red.point(lambda v: min(255, int(v * warm)))
    blue = blue.point(lambda v: int(v / warm))
    image = Image.merge("RGB", (red, green, blue))
    image = image.filter(ImageFilter.GaussianBlur(rng.uniform(0.4, 1.0)))
    return _add_noise(image, rng, amplitude=rng.uniform(6, 14))


def _add_noise(image: Image.Image, rng: random.Random, amplitude: float) -> Image.Image:
    """Sensor or scanner noise, from the caller's generator so it is reproducible."""
    grey = Image.frombytes("L", image.size, rng.randbytes(image.size[0] * image.size[1]))
    # Scale the uniform bytes to +/- amplitude around 128, then add them with an offset.
    noise = grey.point(lambda v: int(128 + (v - 128) * amplitude / 128))
    if image.mode == "RGB":
        noise = Image.merge("RGB", (noise, noise, noise))
    return ImageChops.add(image, noise, scale=1.0, offset=-128)


def to_pdf(images: list[Image.Image], dpi: int) -> bytes:
    """An image-only PDF, as a scanner produces: no text layer."""
    buffer = io.BytesIO()
    first, *rest = images
    first.save(
        buffer,
        format="PDF",
        save_all=True,
        append_images=rest,
        resolution=dpi,
        # Fixed dates keep the same seed's output identical byte for byte.
        creationDate=_FIXED_DATE,
        modDate=_FIXED_DATE,
    )
    return buffer.getvalue()


def to_jpeg(image: Image.Image, rng: random.Random) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=rng.randint(68, 85))
    return buffer.getvalue()
