"""叙事语言(agents.gm.narrative_language)回归测试。

用户诉求:非中文玩家(如印尼语)要能把 GM 叙事切到自己的语言 —— 此前语言硬编码在
_SYSTEM_BASE(「用中文写作」),剧本正文是中文就只能写中文。

钉死三件事:
  1. 未配置 → 追加空串,system prompt 与改动前逐字一致(零回归);
  2. 配置后覆盖块落在 system prompt **末尾**(末位 = 压过前文中文语言指令,含酒馆模板);
  3. 解析优先级 用户偏好 > env,代码别名/大小写/区域后缀都能解。
"""
from __future__ import annotations

import types

import pytest

from agents.gm import narrative_language as nl


# ── 解析 ──────────────────────────────────────────────────────────────
def test_unconfigured_is_noop(monkeypatch):
    monkeypatch.delenv("RPG_NARRATIVE_LANGUAGE", raising=False)
    assert nl.resolve_language(None) == ""
    assert nl.narrative_language_block(None) == ""


def test_chinese_values_are_noop(monkeypatch):
    for code in ("zh", "zh-CN", "zh-Hans", "  "):
        monkeypatch.setenv("RPG_NARRATIVE_LANGUAGE", code)
        assert nl.narrative_language_block(None) == "", code


def test_user_pref_beats_env(monkeypatch):
    monkeypatch.setenv("RPG_NARRATIVE_LANGUAGE", "id")
    monkeypatch.setattr(
        "core.request_cache.get_user_prefs_cached",
        lambda uid: {"gm.narrative_language": "en"},
    )
    block = nl.narrative_language_block(7)
    assert "Write all narration in English." in block
    assert "Bahasa Indonesia" not in block


def test_pref_read_failure_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("RPG_NARRATIVE_LANGUAGE", "id")
    monkeypatch.setattr(
        "core.request_cache.get_user_prefs_cached",
        lambda uid: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    assert "Bahasa Indonesia" in nl.narrative_language_block(7)


# ── 渲染 ──────────────────────────────────────────────────────────────
def test_indonesian_code_resolves_and_overrides(monkeypatch):
    monkeypatch.setenv("RPG_NARRATIVE_LANGUAGE", "id")
    block = nl.narrative_language_block(None)
    assert "Bahasa Indonesia" in block
    assert "覆盖前文" in block
    assert block.strip().endswith("Tulis seluruh narasi dalam Bahasa Indonesia.")


def test_region_suffix_and_case_resolve(monkeypatch):
    monkeypatch.setenv("RPG_NARRATIVE_LANGUAGE", "ID-id")
    assert "Bahasa Indonesia" in nl.narrative_language_block(None)


def test_unknown_value_passes_through_verbatim(monkeypatch):
    monkeypatch.setenv("RPG_NARRATIVE_LANGUAGE", "Sunda")
    block = nl.narrative_language_block(None)
    assert "本局叙事语言 = Sunda" in block


# ── 存档级覆盖(/set)──────────────────────────────────────────────────
def test_set_directive_switches_language_for_this_save(monkeypatch):
    """端到端接线:`/set narrative_language=id` → 用户变量 → 解析命中 → 覆盖块。
    别名在 state/path_ops._clean_path,少了它 /set 会写到一个没人读的路径。"""
    monkeypatch.setenv("RPG_NARRATIVE_LANGUAGE", "en")
    import copy

    from state import DEFAULT_STATE, GameState

    s = GameState(copy.deepcopy(DEFAULT_STATE))
    updates = s.apply_set_directive("/set narrative_language=id")
    assert any("强制设定" in u for u in updates), updates
    assert nl.resolve_language(None, s) == "id"
    assert "Bahasa Indonesia" in nl.narrative_language_block(None, s)


def test_save_override_beats_user_pref_and_env(monkeypatch):
    monkeypatch.setenv("RPG_NARRATIVE_LANGUAGE", "ja")
    monkeypatch.setattr(
        "core.request_cache.get_user_prefs_cached",
        lambda uid: {"gm.narrative_language": "en"},
    )
    assert nl.resolve_language(7, types.SimpleNamespace(data={"worldline": {"user_variables": {"narrative_language": {"value": "id"}}}})) == "id"


def test_reset_words_and_dirty_state_fall_back(monkeypatch):
    monkeypatch.setenv("RPG_NARRATIVE_LANGUAGE", "id")
    for word in ("default", "off", "默认"):
        assert nl.resolve_language(None, types.SimpleNamespace(data={"worldline": {"user_variables": {"narrative_language": {"value": word}}}})) == "id"
        assert "Bahasa Indonesia" in nl.narrative_language_block(None, types.SimpleNamespace(data={"worldline": {"user_variables": {"narrative_language": {"value": word}}}}))
    # 脏/缺失 state:任何形状都不许抛
    for bad in (None, types.SimpleNamespace(data={}), object(), types.SimpleNamespace(data={"worldline": "x"})):
        assert nl.resolve_language(None, bad) == "id"
        assert nl._from_save(bad) == ""


# ── 注入(端到端接线)──────────────────────────────────────────────────
def _bare_gm():
    import agents.gm.master as M

    gm = M.GameMaster.__new__(M.GameMaster)  # 跳过 __init__(无需凭证)
    gm.user_id = None
    gm._world_section_for_active_content = lambda: ""
    return M, gm


def test_build_system_identical_when_unconfigured(monkeypatch):
    monkeypatch.delenv("RPG_NARRATIVE_LANGUAGE", raising=False)
    _M, gm = _bare_gm()
    assert gm._build_system() == gm._build_system_base()


def test_build_system_appends_block_last(monkeypatch):
    monkeypatch.setenv("RPG_NARRATIVE_LANGUAGE", "id")
    _M, gm = _bare_gm()
    out = gm._build_system()
    assert out == gm._build_system_base() + nl.narrative_language_block(None)
    assert out.rstrip().endswith("Tulis seluruh narasi dalam Bahasa Indonesia.")


def test_tavern_path_also_gets_block(monkeypatch):
    """酒馆(含自举模板)走 _build_system 的早退分支 —— 覆盖块必须一样落在末尾,
    否则「用中文自然、简洁地回应玩家」会把叙事又拉回中文。"""
    monkeypatch.setenv("RPG_NARRATIVE_LANGUAGE", "id")
    import context_providers.registry as _reg

    _M, gm = _bare_gm()
    gm._active_state = types.SimpleNamespace(
        data={"tavern": {"character": {"name": "Arjuna"}}}
    )
    orig = _reg.resolve_content_pack
    _reg.resolve_content_pack = lambda st: {"gm_policy": {"mode": "tavern_gm"}}
    try:
        out = gm._build_system()
    finally:
        _reg.resolve_content_pack = orig
    assert "Arjuna" in out
    assert out.rstrip().endswith("Tulis seluruh narasi dalam Bahasa Indonesia.")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
