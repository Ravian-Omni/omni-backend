# Pending requirements

Requests the product owner has asked for but that are not built yet. Newest first.

## Agent templates for campaign creatives

Requested 2026-10-29. Not started.

**The ask, in the owner's words:** "let them add some templates for these agents like image creation, video and what not for campaign. Agent to show 5 images and user to pick images from there to make creatives for the campaign."

**What it means**

- **Templates in Add agent.** Settings, Agents, Add agent offers ready-made agents: image creation, video, and more later. Picking one fills in the form: name, prompt, files it takes, MCP servers and when DAXAGENT should call it. The user can change any of it before saving, like any agent of their own.
- **Pick from five images.** An image agent makes five candidate images for a campaign and shows them in the chat as one card. The user picks one or more. The picks become the campaign's creatives, ready to attach to an email or place inside it.

**What it builds on**

- **The user's own agents** (2026-10-29): stored per user in prefs `custom_agents`, run by `personas.custom()`, and described to the planner by `omni/orchestrator.py`. A template is a pre-filled `CustomAgent`.
- **Campaign creatives:** the `creatives` table, `agent_runtime/assets.py`, the `/campaigns/{chat}/{plan}/creatives` routes and `CreativesPanel.tsx`. Picked images would be saved here.
- **Decision cards:** a "pick images" card would sit beside the existing choose, approve and form cards.
- **Images today:** agents can read images (`read_image`, `llm.describe_image`). Nothing generates images or video. The old image generator was removed with the `image_generator` capability.

**Open questions for the owner**

- Which image and video models to use, and the cost per image or clip.
- Where generated files live on Railway. The `/data` volume has a fixed size.
- Whether picking happens in the chat card, on the campaign page, or both.
