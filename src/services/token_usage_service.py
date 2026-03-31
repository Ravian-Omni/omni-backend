"""Local token usage tracking service.

Records LLM token usage to SQLite for informational purposes,
replacing the previous cloud billing API.
"""

from typing import Any

from loguru import logger

from src.configs.datetime_utils import dt
from src.database.connection import get_db


class TokenUsageService:
    """Service for recording and querying local token usage."""

    @staticmethod
    async def record_usage(
        chat_id: str,
        model_name: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        cost_estimate: float = 0.0,
        agent_name: str = "unknown",
        provider: str | None = None,
        capability: str | None = None,
        step_number: int | None = None,
    ) -> None:
        """Record a token usage entry.

        Args:
            chat_id: Chat session identifier.
            model_name: LLM model name.
            input_tokens: Number of input/prompt tokens.
            output_tokens: Number of output/completion tokens.
            total_tokens: Total tokens used.
            cost_estimate: Estimated cost in USD.
            agent_name: Name of the agent that used tokens.
            provider: LLM provider name.
            capability: Capability that triggered the usage.
            step_number: Step number (for browser automation).
        """
        db = await get_db()
        await db.execute(
            """INSERT INTO token_usage
               (chat_id, agent_name, model_name, provider, input_tokens,
                output_tokens, total_tokens, cost_estimate, capability,
                step_number, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                chat_id,
                agent_name,
                model_name,
                provider,
                input_tokens,
                output_tokens,
                total_tokens,
                cost_estimate,
                capability,
                step_number,
                dt.now_iso(),
            ),
        )
        await db.commit()
        logger.debug(
            f"Token usage recorded: {model_name} {total_tokens} tokens for {chat_id}"
        )

    @staticmethod
    async def get_usage_by_chat(chat_id: str) -> list[dict[str, Any]]:
        """Get all token usage entries for a specific chat.

        Args:
            chat_id: Chat session identifier.

        Returns:
            List of usage entry dicts.
        """
        db = await get_db()
        cursor = await db.execute(
            "SELECT * FROM token_usage WHERE chat_id = ? ORDER BY created_at DESC",
            (chat_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    async def get_usage_summary(days: int = 30) -> dict[str, Any]:
        """Get aggregated token usage summary.

        Args:
            days: Number of days to look back.

        Returns:
            Summary dict with totals by model and overall.
        """
        db = await get_db()

        # Overall totals
        cursor = await db.execute(
            """SELECT
                COALESCE(SUM(input_tokens), 0) as total_input,
                COALESCE(SUM(output_tokens), 0) as total_output,
                COALESCE(SUM(total_tokens), 0) as total_tokens,
                COALESCE(SUM(cost_estimate), 0) as total_cost,
                COUNT(*) as total_calls
               FROM token_usage
               WHERE created_at >= datetime('now', ?)""",
            (f"-{days} days",),
        )
        overall = dict(await cursor.fetchone())

        # Totals by model
        cursor = await db.execute(
            """SELECT model_name,
                COALESCE(SUM(input_tokens), 0) as input_tokens,
                COALESCE(SUM(output_tokens), 0) as output_tokens,
                COALESCE(SUM(total_tokens), 0) as total_tokens,
                COUNT(*) as calls
               FROM token_usage
               WHERE created_at >= datetime('now', ?)
               GROUP BY model_name
               ORDER BY total_tokens DESC""",
            (f"-{days} days",),
        )
        by_model = [dict(row) for row in await cursor.fetchall()]

        return {
            "period_days": days,
            "overall": overall,
            "by_model": by_model,
        }
