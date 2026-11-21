import copy
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import build

ROOT = Path(__file__).resolve().parent.parent
PROFILE = json.loads((ROOT / "profile.json").read_text())


@pytest.fixture
def out(tmp_path):
    return tmp_path / "assets"


def test_writes_light_and_dark_for_every_card(out):
    names = build.build(PROFILE, out)
    assert names == ["hero", "pillars", "metrics", "work", "stack"]
    assert sorted(p.name for p in out.iterdir()) == sorted(f"{n}-{m}.svg" for n in names for m in ("light", "dark"))


def test_every_file_is_valid_xml_with_a_title(out):
    build.build(PROFILE, out)
    for f in out.iterdir():
        root = ET.parse(f).getroot()
        assert root.get("role") == "img"
        assert root.find("{http://www.w3.org/2000/svg}title").text


def test_light_and_dark_differ_only_in_palette(out):
    build.build(PROFILE, out)
    light = (out / "hero-light.svg").read_text()
    dark = (out / "hero-dark.svg").read_text()
    strip = lambda s: re.sub(r"svg\{--bg:[^}]*\}", "", s)
    assert light != dark
    assert strip(light) == strip(dark)
    assert "--bg:#FFFFFF" in light and "--bg:#0D1117" in dark


def test_palette_is_fixed_not_media_query(out):
    build.build(PROFILE, out)
    for f in out.iterdir():
        assert "prefers-color-scheme" not in f.read_text()


def test_reduced_motion_is_honoured(out):
    build.build(PROFILE, out)
    for f in out.iterdir():
        text = f.read_text()
        assert "@media (prefers-reduced-motion:reduce)" in text
        if "animateMotion" in text:  # SMIL ignores CSS animation:none, so movers must be hidden
            assert re.search(r"<circle[^>]*class=\"[^\"]*mover", text)


def test_user_text_is_escaped(out):
    p = copy.deepcopy(PROFILE)
    p["name"] = "Sam <Dev> & Co"
    p["work"][0]["title"] = "R&D <tools>"
    build.build(p, out)
    for f in out.iterdir():
        ET.parse(f)  # would raise on a raw < or &
    assert "Sam &lt;Dev&gt; &amp; Co" in (out / "hero-light.svg").read_text()


def test_optional_sections_are_skipped(out):
    p = {"name": "Min Profile", "title_lines": ["Engineer"]}
    assert build.build(p, out) == ["hero"]


def test_missing_required_field_fails_clearly(out):
    with pytest.raises(ValueError, match="title_lines"):
        build.build({"name": "No Title"}, out)


def test_palette_override(out):
    p = dict(PROFILE, palette={"dark": {"acc": "#FF5A1F"}})
    build.build(p, out)
    assert "--acc:#FF5A1F" in (out / "hero-dark.svg").read_text()
    assert "--acc:#2457E6" in (out / "hero-light.svg").read_text()


def test_accent_markup():
    line = build.accent_line(0, 0, "{and} Data Lead", 40)
    assert '<tspan class="acct">and</tspan> Data Lead' in line


def test_long_text_warns(capsys):
    lines = build.clip(["a", "b", "c"], 2, "work card 'x'")
    assert lines == ["a", "b"]
    assert "only 2 fit" in capsys.readouterr().err


def test_sample_assets_match_profile(tmp_path):
    """The committed assets/ folder is what profile.json builds today."""
    build.build(PROFILE, tmp_path)
    for f in tmp_path.iterdir():
        assert f.read_text() == (ROOT / "assets" / f.name).read_text()
