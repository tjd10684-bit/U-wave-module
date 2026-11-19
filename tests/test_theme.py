import dataclasses
import json

import pytest

from uwave_accessory import theme
from uwave_accessory.theme import DARK, HOST_ROLES, LIGHT, PALETTES, ROLES, detect_mode, palette_from_host


def luminance(color):
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    red, green, blue = (value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4 for value in channels)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first, second):
    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def as_host_colors(palette):
    return {role: getattr(palette, part) for role, part in HOST_ROLES.items()}


@pytest.mark.parametrize("mode", [LIGHT, DARK])
@pytest.mark.parametrize("surface", ["bg", "canvas_bg", "card_fill", "ghost_fill", "moved_fill", "prompt_bg"])
def test_every_text_role_is_readable_on_every_surface(mode, surface):
    palette = PALETTES[mode]
    for role in ROLES:
        assert contrast(palette.color(role), getattr(palette, surface)) >= 4.5, (role, surface)
    assert contrast(palette.select_fg, palette.select_bg) >= 4.5


def test_an_explicit_mode_wins_over_everything_else(tmp_path):
    (tmp_path / "preferences.json").write_text(json.dumps({"theme": "dark"}), encoding="utf-8")

    assert detect_mode("light", config_dir=tmp_path, read_system=lambda: DARK) == LIGHT


def test_an_unknown_mode_is_an_error():
    with pytest.raises(ValueError, match="sepia"):
        detect_mode("sepia")


def test_auto_follows_the_mode_picked_in_open_erp(tmp_path):
    # utf-8-sig: Windows editors save a byte order mark.
    (tmp_path / "preferences.json").write_text(json.dumps({"theme": "light"}), encoding="utf-8-sig")

    assert detect_mode(config_dir=tmp_path, read_system=lambda: DARK) == LIGHT


@pytest.mark.parametrize("saved", [None, "{not json", json.dumps({"theme": "sepia"}), json.dumps(["dark"])])
def test_auto_uses_open_erps_default_when_it_has_run_but_nobody_picked_a_mode(tmp_path, saved):
    if saved is not None:
        (tmp_path / "preferences.json").write_text(saved, encoding="utf-8")

    assert detect_mode(config_dir=tmp_path, read_system=lambda: LIGHT) == theme.OPEN_ERP_DEFAULT == DARK


def test_auto_without_open_erp_follows_windows_then_light(tmp_path):
    missing = tmp_path / "never-installed"

    assert detect_mode(config_dir=missing, read_system=lambda: DARK) == DARK
    assert detect_mode(config_dir=missing, read_system=lambda: None) == LIGHT


@pytest.mark.parametrize("mode", [LIGHT, DARK])
def test_the_colours_open_erp_sends_reproduce_the_built_in_palette(mode):
    assert palette_from_host(mode, as_host_colors(PALETTES[mode])) == PALETTES[mode]


def test_the_host_colours_replace_the_built_in_ones_and_the_canvas_follows_them():
    palette = palette_from_host(DARK, {"background": "#101010", "field": "#181818", "field_readonly": "#141414",
                                       "text_muted": "#abcdef", "selection": "#112233"})

    assert (palette.bg, palette.field, palette.readonly_field) == ("#101010", "#181818", "#141414")
    assert (palette.muted, palette.select_bg) == ("#abcdef", "#112233")
    assert (palette.canvas_bg, palette.card_fill, palette.ghost_fill) == ("#101010", "#181818", "#141414")
    assert palette.text == PALETTES[DARK].text
    assert palette.moved_fill == PALETTES[DARK].moved_fill


def test_unusable_host_colours_fall_back_to_the_built_in_ones():
    colors = {"text": "red", "accent": "#12345", "error": 7, "gradient": "#000000", "ready": "#ABCDEF"}

    palette = palette_from_host(LIGHT, colors)

    assert dataclasses.replace(palette, ready=PALETTES[LIGHT].ready) == PALETTES[LIGHT]
    assert palette.ready == "#abcdef"


def test_a_host_mode_other_than_light_or_dark_is_an_error():
    with pytest.raises(ValueError, match="sepia"):
        palette_from_host("sepia", {})
