"""Task mode does not offer web_browser or Growth Engineer (software_developer); Data Analyst came back on 2026-10-14."""

from src.agent_runtime import PERSONAS
from src.omni import prompts

REMOVED = ("web_browser", "software_developer")


def test_task_prompts_do_not_offer_them():
    for name, text in vars(prompts).items():
        if isinstance(text, str):
            assert not [r for r in REMOVED if r in text], name


def test_their_personas_stay_for_older_chats_but_are_not_listed():
    assert PERSONAS["software_developer"].retired and not PERSONAS["ml_engineer"].retired
    assert not any(p.retired for n, p in PERSONAS.items() if n not in REMOVED)
