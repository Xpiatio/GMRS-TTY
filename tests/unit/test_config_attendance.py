"""AppConfig accessors for the nested ``attendance`` block.

The setter merges instead of replacing: the block holds sibling keys, and an
earlier version of this code dropped ``autosave_sessions`` whenever the
operator toggled the dock.
"""
from gmrs_tty.config import AppConfig


class TestDefaults:
    def test_both_default_off(self):
        cfg = AppConfig()
        assert cfg.attendance_enabled is False
        assert cfg.attendance_autosave_sessions is False

    def test_missing_block_is_tolerated(self):
        cfg = AppConfig({"attendance": None})
        assert cfg.attendance_enabled is False
        assert cfg.attendance_autosave_sessions is False

    def test_values_read_from_the_block(self):
        cfg = AppConfig({"attendance": {"enabled": True, "autosave_sessions": True}})
        assert cfg.attendance_enabled is True
        assert cfg.attendance_autosave_sessions is True


class TestEnabledSetter:
    def test_set_on_empty_config_creates_the_block(self):
        cfg = AppConfig()
        cfg.attendance_enabled = True
        assert cfg["attendance"] == {"enabled": True}

    def test_toggle_preserves_autosave_sibling(self):
        cfg = AppConfig({"attendance": {"autosave_sessions": True}})
        cfg.attendance_enabled = True
        assert cfg.attendance_autosave_sessions is True
        cfg.attendance_enabled = False
        assert cfg.attendance_autosave_sessions is True
        assert cfg.attendance_enabled is False

    def test_toggle_preserves_unknown_siblings(self):
        # Forward compatibility: a key written by a newer build must survive
        # a round-trip through an older one's toggle.
        cfg = AppConfig({"attendance": {"future_key": "keep me"}})
        cfg.attendance_enabled = True
        assert cfg["attendance"]["future_key"] == "keep me"

    def test_coerces_to_bool(self):
        cfg = AppConfig()
        cfg.attendance_enabled = "yes"
        assert cfg["attendance"]["enabled"] is True

    def test_does_not_mutate_the_original_block_in_place(self):
        block = {"autosave_sessions": True}
        cfg = AppConfig({"attendance": block})
        cfg.attendance_enabled = True
        assert "enabled" not in block   # copied, not mutated
