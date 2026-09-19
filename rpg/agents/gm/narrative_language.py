"""agents.gm.narrative_language — 本局「叙事语言」(≠ UI 语言)的确定性注入。

背景:叙事语言此前硬编码在 master._SYSTEM_BASE 里 ——「用中文写作」+「叙事语言跟随
剧本正文 / 玩家语言」。中文原著 + 中文玩家下这条规则成立;**非中文玩家**(如印尼语)
拿不到自己的语言:剧本正文是中文,模型就照中文写。本模块把「本局叙事语言」收成一处
配置,由 GameMaster._build_system 以【最高优先级覆盖块】追加在 system prompt 末尾
(末位 = 最后读到 = 压过前文所有语言指令,含酒馆/自举模板里的中文措辞)。

解析顺序(先命中先用):
  1. 存档级覆盖:state.data['worldline']['user_variables']['narrative_language']
     —— 玩家在游戏里用 `/set narrative_language=id` 就地切换(别名见 state/path_ops._clean_path;
     值写进用户变量面板,每回合注入 GM 提示词)。`default`/`off`/`默认` = 撤销该覆盖。
  2. 用户偏好 user_preferences["gm.narrative_language"]
     —— POST /api/me/preference 可写,设置页「偏好」有下拉(含移动端)。
  3. 环境变量 RPG_NARRATIVE_LANGUAGE(部署级默认,见 core.config.narrative_language)
  4. 都没有 → "" → 不追加任何内容,输出与改动前逐字一致(零回归)。

值 = 语言代码或语言名(zh / id / en / ja / "Bahasa Indonesia" ...)。已知代码走 _LANGS
表(带目标语言的原生硬指令,顺带挡掉「id 是哪个语言」的歧义);表外值原样透传 ——
**加语言 = 加一行表,不改代码**。

为什么是提示词而不是确定性后处理:叙事语言本身只能由生成侧决定;能确定的是「模型
收到的是哪一条语言指令」——本模块保证有且只有一条,且是最后一条。
"""
from __future__ import annotations

import os

# 语言代码 → (目标语言原生名, 原生硬指令)。
# 只有这些代码算「已知」;其余按用户给的字符串原样渲染。
_LANGS: dict[str, tuple[str, str]] = {
    "zh": ("中文(简体)", ""),
    "zh-cn": ("中文(简体)", ""),
    "zh-tw": ("繁體中文", "所有敘事一律使用繁體中文書寫。"),
    "en": ("English", "Write all narration in English."),
    "ja": ("日本語", "ナレーションはすべて日本語で書くこと。"),
    "id": ("Bahasa Indonesia", "Tulis seluruh narasi dalam Bahasa Indonesia."),
    "in": ("Bahasa Indonesia", "Tulis seluruh narasi dalam Bahasa Indonesia."),
}

# 这些值等于「不指定」→ 不追加块(现行行为:提示词里的中文规则照旧生效)。
_DEFAULT_CODES = frozenset({"", "zh", "zh-cn", "zh-hans"})


# 存档级覆盖的键名(与 state/path_ops._clean_path 的 /set 别名一致)。
_SAVE_KEY = "narrative_language"
# 这几个值 = 撤销存档级覆盖(回落到用户偏好 / env)。
_RESET_WORDS = frozenset({"default", "auto", "off", "默认", "自动", "跟随默认"})


def _from_save(state) -> str:
    """读存档级覆盖(`/set narrative_language=id` 写的用户变量)。无/脏数据 → ""。"""
    try:
        data = getattr(state, "data", None) or {}
        raw = ((data.get("worldline") or {}).get("user_variables") or {}).get(_SAVE_KEY)
        val = str((raw.get("value") if isinstance(raw, dict) else raw) or "").strip()
        return "" if val.lower() in _RESET_WORDS else val
    except Exception:
        return ""


def resolve_language(user_id: int | None, state=None) -> str:
    """存档覆盖 > 用户偏好 > 环境变量 > ""(现行中文行为)。

    任何异常/读失败都吞掉返回 "" —— 语言解析绝不影响 GM 主流程。
    """
    save_val = _from_save(state)
    if save_val:
        return save_val
    if user_id:
        try:
            from core.request_cache import get_user_prefs_cached

            pref = get_user_prefs_cached(int(user_id)).get("gm.narrative_language")
            if pref:
                return str(pref).strip()
        except Exception:
            pass
    try:
        from core.config import narrative_language

        return narrative_language()
    except Exception:
        return os.getenv("RPG_NARRATIVE_LANGUAGE", "").strip()


def narrative_language_block(user_id: int | None, state=None) -> str:
    """渲染 system prompt 末尾的语言覆盖块。未配置/中文 → ""(零回归)。"""
    raw = resolve_language(user_id, state)
    key = raw.strip().lower()
    if key in _DEFAULT_CODES:
        return ""
    display, native = _LANGS.get(key) or _LANGS.get(key.split("-", 1)[0]) or (raw.strip(), "")
    lines = [
        "",
        "",
        "# 叙事语言（最高优先级 · 覆盖前文所有语言相关指令）",
        f"本局叙事语言 = {display}。前文「用中文写作」「叙事语言跟随剧本正文 / 玩家语言」等规则在本局一律作废,以本段为准。",
        f"1. 正文(旁白、动作、神态、心理、场景描写、NPC 台词)一律用 {display} 书写;玩家即使写中文或其它语言,也用 {display} 回应。",
        "2. 人名、地名、组织名、专有名词保留原著写法,不翻译、不意译、不另造译名;必要时可夹注原文。",
        f"3. 剧本原文的引文/台词可原样保留,但叙事框架语言必须是 {display},正文里不出现中文句子(专有名词除外)。",
    ]
    if native:
        lines.append(native)
    return "\n".join(lines) + "\n"


__all__ = ["narrative_language_block", "resolve_language"]
