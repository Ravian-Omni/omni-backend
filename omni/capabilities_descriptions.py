python_coder_description = """ 
Intelligent Python development assistant that automatically analyzes tasks, plans solutions, writes complete code, and executes programs to deliver results. Simply describe what needs to be accomplished - no coding required. The system handles all technical implementation, dependency management, error resolution, and output formatting.

**Parameters:**
- query (required): Complete description of the task you want accomplished, including all context, requirements, data sources, desired outputs, and specific formatting preferences. Be as detailed as possible about your goals and constraints.

**Use this function when you need to:**
- Analyze, process, or manipulate data from any source (CSV, Excel, JSON, databases, APIs)
- Generate professional documents (PDF reports, PowerPoint presentations, Excel dashboards, HTML pages)
- Create data visualizations, charts, graphs, or interactive dashboards
- Automate repetitive tasks or batch process files
- Perform complex calculations, statistical analysis, or mathematical modeling
- Convert between file formats or data structures
- Extract, transform, or clean data from various sources
- Build custom tools or utilities for specific workflows
- Process images, text, or multimedia content
"""

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

file_finder_description = """
Advanced file search and discovery system for macOS that locates files and folders across the entire system using multiple search criteria. Provides intelligent file finding with support for partial names, file types, content search, date ranges, and location-based filtering. Integrates with macOS Spotlight and file system APIs for comprehensive and fast search results.

**Parameters:**
- query (required): Complete description of the file search request, including filename, file type, location hints, content keywords, or any combination of search criteria

**Use this function when users need:**
- Find specific files by exact or partial filename
- Locate files by file type or extension (PDF, DOCX, JPG, etc.)
- Search for files in specific directories or locations
- Find files modified or created within certain date ranges
- Locate files containing specific text or keywords
- Find files by size criteria (large files, small files)
- Search for recently accessed or downloaded files
- Locate application files or system files
- Find duplicate files with similar names
- Discover files related to specific projects or topics

**Search capabilities:**
- **Name-based search**: Exact filename, partial matches, wildcards
- **Type-based search**: File extensions, MIME types, application-specific files
- **Location-based search**: Specific folders, Desktop, Downloads, Documents, Applications
- **Date filtering**: Creation date, modification date, last accessed date
- **Size filtering**: File size ranges, large file detection
- **System-wide search**: User directories, system folders, external drives
- **Folder discovery**: Find directories and folder structures by name

**Search scope:**
- User home directory and all subdirectories
- Desktop, Documents, Downloads, Pictures, Music, Movies folders
- Applications folder and installed software
- External drives and network locations
- System directories (with appropriate permissions)
- Cloud storage integration (iCloud, Dropbox, Google Drive if mounted)

**Output includes:**
- Complete file and folder paths for all matching results
- File metadata (size, creation date, modification date, file type)
- File location hierarchy for easy navigation
- File and folder count summary of search results
- Error handling for permission-denied or inaccessible locations

**Examples of requests to handle:**
"Find the presentation file about quarterly sales", "Locate all PDF files in the Documents folder", "Search for files containing 'budget' in the filename", "Find the Excel spreadsheet I downloaded yesterday", "Locate all image files with 'vacation' in the name", "Search for Python files in my projects folder", "Find the contract document file from last week", "Locate all video files larger than 100MB", "Search for files modified in the past 3 days", "Find the installer file for Adobe Photoshop", "Locate all Word documents with 'marketing' in filename", "Search for files in the Downloads folder from this month", "Find the folder named 'Project Alpha'", "Locate all folders containing 'backup' in the name"

**Output characteristics:**
- Fast search results using macOS file system indexing
- Organized results by relevance and file type
- Full file and folder paths for easy access and navigation
- Metadata-rich results for better file identification
- Permission-aware searching with graceful error handling
- Returns location paths only - no file content analysis
"""

web_browser_description = """
Advanced web browsing and automation system with dual capabilities: API-based information retrieval for fast data access and automated browser surfing for complex web interactions. Intelligently selects the appropriate method based on task requirements. Has access to stored credentials for authenticated websites and can execute complex web workflows including social media posting, form submissions, and real-time browsing.

**Parameters:**
- task (required): Complete description of the web-based action to perform. Include hints about method preference: use "search" or "quick lookup" for API-based retrieval, or "browse", "navigate", "interact", "post", "login" for automated browser surfing

**Dual Capability System:**

**API-Based Method** (Fast, efficient for information retrieval):
- Quick searches and data lookups
- Real-time information gathering
- News and current events
- Stock prices, weather, basic facts
- Public information without authentication

**Automated Browser Method** (Full interaction capabilities):
- Social media posting and management
- Authenticated website access
- Form submissions and applications
- Complex website interactions
- Multi-step workflows
- Visual content verification
- Dynamic content loading

**Use this function when users need:**
- **API Method**: Search for current information, news, stock prices, weather, quick facts, research topics
- **Browser Method**: Post to social media, login to accounts, submit forms, interact with dynamic websites, perform authenticated actions
- Extract information from specific websites or web pages
- Monitor websites for changes or updates
- Gather competitive intelligence or market research
- Perform online shopping or price comparisons
- Download files or resources from websites
- Verify information across multiple web sources
- Collect contact information or business details
- Track trends, mentions, or online discussions

**Method Selection Guide:**
- **Use API hints**: "search for", "find information about", "get current", "lookup", "check latest"
- **Use Browser hints**: "post to", "login and", "navigate to", "interact with", "submit form", "browse through"

**Output includes:**
- Retrieved information and data from web sources
- Confirmation of posted content with links and timestamps
- Extracted data in structured format
- Screenshots or visual confirmation of browser actions
- Status updates on completed web interactions
- Error handling for failed operations or inaccessible sites
- Method used (API or Browser) and execution details

**Examples of requests to handle:**
"Search for the latest news about artificial intelligence developments" (API method), "Post this announcement to our company LinkedIn page" (Browser method), "Find the current stock price for Apple Inc" (API method), "Login to our analytics dashboard and download the monthly report" (Browser method), "Get the weather forecast for New York next week" (API method), "Navigate to Amazon and add this product to cart" (Browser method), "Quick lookup of competitor pricing for cloud storage" (API method), "Browse through our social media mentions and respond to comments" (Browser method), "Search for job openings at Google" (API method), "Submit this application form on the university website" (Browser method)

**Output characteristics:**
- Method-optimized results (fast API responses or detailed browser interactions)
- Real-time web data and current information
- Authenticated access to personal and business accounts
- Social media posting confirmations with engagement metrics
- Cross-platform content distribution and management
- Secure credential handling and privacy protection
 """

image_generator_description = """
Advanced AI image generation system that creates high-quality images through a multi-agent approach. Uses intent classification to understand user requirements, generates optimized prompts for image creation, and provides completion status with file locations. Supports photorealistic images, artistic illustrations, logos, presentations, and creative content with professional quality output.

**Parameters:**
- query (required): Description of the image to be generated along with proper context

**Use this function when users need:**
- Photorealistic images (portraits, objects, scenes, animals)
- Artistic illustrations and creative content
- Logo and branding design
- Marketing and promotional visuals
- Presentation graphics and slides
- Concept art and character design
- Product mockups and prototypes
- Social media content and graphics
- Educational diagrams and illustrations
- Custom artwork for any purpose

**Image capabilities:**
- Photorealistic quality with accurate details and natural lighting
- Multiple artistic styles (cartoon, abstract, realistic, vintage, modern)
- Professional logo design with clean lines and brand-appropriate colors
- High-resolution output suitable for print and digital use
- Proper composition, lighting, and visual appeal
- Generic, descriptive filenames for easy identification

**Output includes:**
- High-quality generated image saved to specified location
- Descriptive filename reflecting image content
- Console status updates during generation process
- Completion report with file paths and generation details

**Examples of requests to handle:**
"Create a photorealistic image of a German Shepherd dog", "Design a modern logo for a tech company", "Generate a cartoon-style illustration of a smiling sun", "Create a professional headshot photo", "Design a vintage poster for a coffee shop", "Generate an abstract background for presentations", "Create product mockup images", "Design social media graphics"

**Output characteristics:**
- Professional quality suitable for commercial use
- Consistent styling and proper formatting
- Self-contained image files ready for immediate use
- Generic naming convention for easy file management
"""
