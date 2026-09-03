from PIL import Image
from app.models.schema import SubtitleDirection
from app.services.subtitles.painter import render_slot_group


def make_slot():
    image = Image.new("RGBA", (20, 50), (255, 0, 0, 255))
    return image


def test_vertical_ltr_slots_start_at_left_edge():
    slots = [make_slot(), make_slot()]
    group = render_slot_group(
        slots,
        SubtitleDirection.vertical_ltr,
        gap=10,
        slot_align_h="center",
        slot_align_v="middle",
    )
    assert group.getpixel((10, 25)) == (255, 0, 0, 255)
    assert group.getpixel((40, 25)) == (255, 0, 0, 255)
    assert group.getpixel((25, 25)) == (0, 0, 0, 0)


def test_vertical_rtl_slots_start_at_right_edge():
    slots = [make_slot(), make_slot()]
    group = render_slot_group(
        slots,
        SubtitleDirection.vertical_rtl,
        gap=10,
        slot_align_h="center",
        slot_align_v="middle",
    )
    assert group.getpixel((30, 25)) == (255, 0, 0, 255)
    assert group.getpixel((0, 25)) == (255, 0, 0, 255)
    assert group.getpixel((25, 25)) == (0, 0, 0, 0)
