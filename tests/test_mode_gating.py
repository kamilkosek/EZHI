"""The rule behind the "this write will do nothing" warning.

const.py is Home-Assistant-free, so this needs no harness.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "ezhi_const",
    Path(__file__).resolve().parents[1]
    / "custom_components" / "apsystems_ezhi_local" / "const.py",
)
const = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(const)


def test_local_is_the_only_mode_that_acts_on_the_setpoint():
    assert const.local_setpoint_ignored_by("4") is None
    assert const.local_setpoint_ignored_by("1") == "Balcony Storage"
    assert const.local_setpoint_ignored_by("2") == "Portable"
    assert const.local_setpoint_ignored_by("3") == "AI"
    assert const.local_setpoint_ignored_by("6") == "No Battery"


def test_an_unknown_mode_is_silent_not_a_guess():
    """The cloud side is optional. No mode reading -> no claim either way."""
    assert const.local_setpoint_ignored_by(None) is None


def test_an_unmapped_but_real_mode_still_names_itself():
    """Mode 5 (AC-coupled) has no entity option but is a real device mode --
    it must not fall through as "Local" and suppress the warning."""
    assert const.local_setpoint_ignored_by("5") == "mode 5"


def test_a_value_that_is_not_a_mode_stays_quiet():
    """wire_str normalises 4 and 4.0 to "4" but leaves "4.0" and " 4 " alone.
    Treating those as "not Local" would warn on every write while the inverter
    sits in Local -- the one direction that trains people to ignore the log."""
    for junk in ("4.0", " 4 ", "04", "", "None", "local"):
        assert const.local_setpoint_ignored_by(junk) is None, junk
