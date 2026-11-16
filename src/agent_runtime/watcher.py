"""The reply watcher (Settings, Team & Inbox, Watch replies): no task needed.

Every few minutes in working hours it checks each sent campaign thread in Gmail, then tells Brain_Hands of partner referrals
and booked meetings (agent_runtime/inbound.py). Jev reads every new
reply and the user's rules route it: unsubscribe, out of office and not now are recorded at once;
the rest become a handoff with a drafted answer for the contact's owner, who is told on Slack and by
email and sends from the handoff card. Nothing is ever sent to a contact from here.
"""

import asyncio
from collections import Counter
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from loguru import logger

from src.agent_runtime import crm, inbound, inbox, llm, prefs
from src.agent_runtime.tools import artifacts, campaign
from src.configs.datetime_utils import dt
from src.database import chat_collection, list_artifacts_of_kind, update_chat_history

TICK_SECONDS = 60  # how often it checks whether a sweep is due
PERSON_ROUTES = ("handoff", "propose_meeting", "answer")
state: dict[str, Any] = {"last_sweep": None, "summary": None, "running": False}


def due(rules: dict, now: datetime, last: datetime | None) -> bool:
    """Watching is on, it is working time, and the last sweep is old enough."""
    in_hours = rules["work_start"] <= now.hour < rules["work_end"] and (rules["weekends"] or now.weekday() < 5)
    return rules["watch"] and in_hours and (last is None or now - last >= timedelta(minutes=rules["every_minutes"]))


def _context(record: dict, user_id: str) -> SimpleNamespace:
    """What the campaign and inbox helpers need, for the chat a send log belongs to."""
    import os

    async def emit(content: dict) -> None:  # a handoff card in that chat, live and after a reload
        collection = await chat_collection(record["chat_id"]) or "omni"
        await update_chat_history(record["chat_id"], {"role": "assistant", "name": "inbox_agent", "raw_message": content,
                                                      "usage": {}, "task_id": record.get("task_id")}, collection)
        try:
            from src.dependencies import get_websocket_manager

            await (await get_websocket_manager()).send_chat_message(
                session_id=record["chat_id"], source="inbox_agent",
                content={"role": "assistant", "name": "inbox_agent", "content": content, "type": content["type"],
                         "call_id": None, "capability_id": None, "task_id": record.get("task_id")})
        except Exception as e:
            logger.debug(f"[watcher] chat {record['chat_id']} not open: {e}")

    # data_sources: artifacts.write reads it; without it every record_reply from a sweep raised AttributeError
    return SimpleNamespace(chat_id=record["chat_id"], user_id=user_id, task_id=record.get("task_id"), persona="inbox_agent",
                           artifacts_dir=os.path.dirname(record["path"]), emit=emit, data_sources=set())


async def _draft(ctx, plan_id: str, route: str, reply: str, read: dict) -> str:
    """A short suggested answer for the owner to edit ("" when it cannot be written)."""
    if route == "handoff":
        return ""
    try:
        brief = (artifacts.load(ctx, plan_id).get("meta") or {}).get("brief") or {}
        slots = await inbox.free_slots(ctx.user_id) if route == "propose_meeting" else []
    except Exception:
        brief, slots = {}, []
    try:
        return await llm.complete(
            "You draft a short, plain reply to a prospect's email for a salesperson to review and send. "
            "Use only facts from the brief; no new claims, prices or promises. Under 90 words. No subject line. "
            "Sign with the sender name from the brief.",
            f"Their reply:\n{reply}\n\nWhat to do: {route.replace('_', ' ')}"
            + (f"; offer these times (say they are suggestions): {', '.join(slots)}" if slots else "")
            + f"\nJev's reading: {read}\nCampaign brief: {brief}",
            max_tokens=400,
        )
    except Exception as e:
        logger.warning(f"[watcher] draft failed: {e}")
        return ""


async def sweep(user_id: str = "local_user") -> dict:
    """Check every sent campaign thread once; returns what happened."""
    if state["running"]:
        return state["summary"] or {}
    state["running"] = True
    rules = await prefs.get(user_id, "inbox")
    summary: dict[str, Any] = {"threads_checked": 0, "replies": 0, "bounces": 0, "routes": Counter(), "handoffs": [], "errors": [],
                               "dry_run": rules["dry_run"], "at": dt.now_iso()}
    try:
        for record in await list_artifacts_of_kind("send_log"):
            ctx = _context(record, user_id)
            try:
                plans = {r.get("plan_id") for r in artifacts.load(ctx, record["id"]).get("rows", []) if r.get("plan_id")}
            except FileNotFoundError:
                continue
            for plan_id in plans:
                try:
                    found = await campaign.fetch_replies(ctx, plan_id)
                except RuntimeError as e:  # Gmail not connected: nothing else can be checked either
                    summary["errors"].append(str(e))
                    return summary
                summary["threads_checked"] += found["threads_checked"]
                summary["bounces"] += len(found["bounces"])
                for h in [] if rules["dry_run"] else await campaign.settle_bounces(ctx, plan_id, found["bounces"]):
                    summary["handoffs"].append({"id": h["id"], "contact": h["contact"], "owner": h["owner"] or "shared inbox",
                                                "notified": h["notified"]})
                for r in found["replies"]:
                    route = r.get("route") or "handoff"  # without Jev's reading, a person decides
                    read = r.get("read") or {}
                    summary["replies"] += 1
                    summary["routes"][route] += 1
                    if rules["dry_run"]:
                        continue
                    await campaign.record_reply(ctx, plan_id, r["to"], read.get("intent", "other"), route, "", r.get("message_id") or "",
                                                text=r["text"], subject=r.get("subject", ""), thread_id=r["thread_id"])
                    if route in PERSON_ROUTES:
                        h = await inbox.open_handoff(ctx, contact=r["to"], route=route, reply=r["text"], read=read, plan_id=plan_id,
                                                     thread_id=r["thread_id"], subject=r.get("subject", ""),
                                                     draft=await _draft(ctx, plan_id, route, r["text"], read))
                        summary["handoffs"].append({"id": h["id"], "contact": h["contact"], "owner": h["owner"] or "shared inbox",
                                                    "notified": h["notified"]})
        if not rules["dry_run"]:  # what else Brain_Hands is told: partner referrals and booked meetings (off without BRAIN_HANDS_URL)
            for key, check in (("referrals", lambda: inbound.referrals(user_id, rules["partners"], state["last_sweep"])),
                               ("meetings", lambda: inbound.meetings(user_id)),
                               ("crm_suppressed", lambda: crm.pull_suppressed(user_id))):  # the CRM's do-not-contact list into ours
                try:
                    summary[key] = await check()
                except Exception as e:  # one failing never stops the other, or the replies already recorded
                    summary["errors"].append(f"{key}: {e}")
        return summary
    finally:
        summary["routes"] = dict(summary["routes"])
        state.update(last_sweep=datetime.now().astimezone(), summary=summary, running=False)


async def run_forever(user_id: str = "local_user") -> None:
    """Started with the app; sweeps whenever Settings say one is due."""
    while True:
        try:
            if (due(await prefs.get(user_id, "inbox"), datetime.now().astimezone(), state["last_sweep"])
                    and await prefs.agent_enabled(user_id, "inbox_agent")):
                result = await sweep(user_id)
                logger.info(f"[watcher] {result.get('replies', 0)} new replies, {len(result.get('handoffs', []))} handed off")
        except Exception as e:
            logger.warning(f"[watcher] sweep failed: {e}")
        await asyncio.sleep(TICK_SECONDS)
