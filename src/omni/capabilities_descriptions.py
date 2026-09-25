email_manager_description = """
Comprehensive email management system that handles all aspects of email communication and organization. Provides intelligent email composition, automated responses, attachment handling, inbox management, and advanced search capabilities. Integrates with popular email providers and supports both personal and business email workflows with professional formatting and smart automation.

**Parameters:**
- query (required): Complete description of the email operation to perform, including all necessary context, recipients, content requirements, and specific instructions

**Use this function when users need:**
- Compose and format professional emails with proper structure
- Reply to existing emails with context-aware responses
- Send emails with single or multiple attachments
- Read and organize emails from inbox, sent items, or specific folders
- Search emails by sender, subject, date range, keywords, or content
- Download and save email attachments to specified locations
- Bulk email operations and automated responses
- Email template creation and management
- Draft email composition and editing

**Email capabilities:**
- **Content Generation**: Professional email formatting with proper greetings, body, and signatures
- **Reply Management**: Context-aware responses that reference original email content
- **Attachment Handling**: Send multiple file types, download and organize received attachments
- **Inbox Operations**: Read, sort, filter, and organize emails from various folders
- **Advanced Search**: Multi-criteria search including sender, subject, date ranges, keywords, and content
- **Professional Formatting**: HTML email support, proper styling, and business communication standards

**Search and filtering options:**
- Search by sender email address or name
- Filter by subject line keywords or exact matches
- Date range filtering (today, last week, specific dates)
- Content-based keyword search within email body
- Attachment presence filtering
- Read/unread status filtering
- Folder-specific searches (inbox, sent, drafts, custom folders)

**Output includes:**
- Confirmation of email operations (sent, saved, downloaded)
- Retrieved email content with metadata (sender, subject, date, attachments)
- Search results with relevant email details
- Attachment download confirmations with file locations
- Professional email formatting and content generation

**Examples of requests to handle:**
"Compose a professional email to the marketing team about the quarterly review and send it to team@marketing.com", "Reply to John's email about the project deadline with an update on our progress", "Send the presentation slides to all stakeholders at stakeholders@company.com", "Find all emails from sarah@company.com received last week", "Download all attachments from emails about the budget proposal to the downloads folder", "Search for emails containing 'invoice' in the subject from the past month", "Read my latest 5 unread emails from today", "Send a follow-up email with the contract.pdf attached to client@business.com", "Find all emails from manager@company.com about the product launch between March 1-15", "Compose and send a thank you email to interview@company.com after my job interview"

**Output characteristics:**
- Professional email formatting with proper business etiquette
- Secure handling of email credentials and sensitive information
- Organized attachment management with descriptive filenames
- Detailed logging of all email operations
"""

web_browser_description = """
Web search powered by Tavily, with real browser automation (browser-use) as a fallback. Answers lookups quickly with sources, and drives a Chrome browser when a task needs a specific page, interaction, or content extraction.

**Parameters:**
- query (required): The search query. Be specific and descriptive for better results.

**Use this function when users need:**
- Current information (news, stock prices, weather, events)
- Factual answers to questions
- Research on any topic
- Competitive intelligence or market data
- Technical documentation or tutorials
- Any information that requires up-to-date web data

**Examples:**
"What is the current stock price of Meta?", "Latest news about artificial intelligence", "Weather forecast for New York", "Best Python frameworks for web development 2026"

**Output characteristics:**
- Method-optimized results (fast API responses or detailed browser interactions)
- Real-time web data and current information
- Authenticated access to personal and business accounts
- Social media posting confirmations with engagement metrics
- Cross-platform content distribution and management
- Secure credential handling and privacy protection
 """

software_developer_description = """
Full software engineering assistant that builds working software end to end. Writes and edits real files on the local system, runs shell commands in an interactive terminal, installs dependencies, then runs and tests what it built until it works.

**Parameters:**
- query (required): Complete description of what to build, including language/platform preference, features, file or project layout, and how the result should be delivered.

**Use this function when the user wants to:**
- Build an application, website, game, dashboard page, CLI tool, script or automation
- Create a project from scratch in any language (HTML/CSS/JavaScript, Python, TypeScript, shell, etc.)
- Add features to, refactor, debug or fix existing code and files
- Set up a project structure, install packages, and run or test a program
- Produce ready-to-run deliverables such as a single HTML file, a script, or a multi-file project

**Capabilities:**
- Reads, writes and edits files anywhere in the working directory
- Real PTY terminal for running commands, build tools and test suites
- Iterates on its own output: runs the code, reads errors, fixes and re-runs
- Git operations and code analysis

**Examples of requests to handle:**
"Build a snake game I can play in the browser", "Create a single HTML file with a to-do list app", "Write a Python script that renames files by date", "Set up a small FastAPI service with one endpoint and test it", "Fix the failing tests in this project"

**Choosing between capabilities:**
- Use software_developer when the deliverable is an application, website, game, script or multi-file project.

**Output characteristics:**
- Returns a summary of what was built and where the files live
- Leaves ready-to-run files on disk in the chat workspace
"""
