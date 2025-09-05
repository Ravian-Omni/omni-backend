web_api_search = """
Fast API-based web information retrieval system that performs quick searches and data lookups across the internet. Optimized for speed and efficiency, this method uses search APIs and public data sources to gather current information without requiring browser automation. Ideal for research, fact-checking, and real-time data collection.

**Parameters:**
- **query** (required): `Annotated[str, "The search query string - be specific and descriptive for better results. Include relevant keywords, context, and relationships to the topic being searched"]`
- **search_type**: `Annotated[str, "Search mode: 'comprehensive' (detailed results with extra snippets), 'quick' (fast basic results), 'recent' (time-filtered results)"] = "comprehensive"`

**Use this function when users need:**
- Quick web searches and information lookups
- Current news, events, and trending topics
- Real-time data (stock prices, weather, exchange rates)
- Public information and facts
- Research and fact-checking
- Market data and statistics
- Public company information
- General knowledge queries requiring current data
- Fast information retrieval without authentication
- Academic and educational content searches

**API capabilities:**
- **Search Engines**: Google Search API, Bing Search, web search aggregators
- **News APIs**: Latest news from multiple sources and outlets
- **Financial Data**: Stock prices, market data, economic indicators
- **Weather Services**: Current weather and forecasts for any location
- **Public Databases**: Government data, statistics, public records
- **Social Media APIs**: Public posts, trends, hashtag data
- **Reference Sources**: Wikipedia, encyclopedias, fact databases
- **Business Information**: Company data, contact information, public filings

**Information sources:**
- Search engine results and web indexing
- News aggregators and media outlets
- Financial market data providers
- Government and public sector APIs
- Social media public feeds
- Academic and research databases
- Business directories and listings
- Weather and geographical services

**Output includes:**
- Structured search results with source citations
- Current and real-time data updates
- Multiple source verification and cross-referencing
- Fast response times for immediate information needs
- Formatted data ready for analysis or presentation
- Source credibility and date information
- Error handling for unavailable or restricted data

**Examples of requests to handle:**
"Search for latest news about Tesla stock price", "Get current weather forecast for London", "Find information about the latest iPhone release", "Look up population statistics for California", "Search for recent articles about artificial intelligence", "Get current exchange rate for USD to EUR", "Find the latest quarterly earnings for Microsoft", "Search for trending topics on social media today", "Look up contact information for Apple headquarters", "Get current oil prices and market trends", "Find recent research papers about climate change", "Search for job market statistics in tech industry"

**Output characteristics:**
- Fast API response times (typically under 5 seconds)
- Structured and formatted data results
- Multiple source aggregation for comprehensive information
- Real-time and current data accuracy
- No authentication required for public information
- High-volume search capabilities
- Source attribution and credibility indicators
"""

web_browser_automation = """
Advanced automated browser system that performs complex web interactions, authenticated actions, and multi-step workflows. Uses real browser automation to navigate websites, submit forms, post content, and interact with dynamic web applications. Has access to stored credentials for authenticated websites and can execute sophisticated web tasks requiring human-like browser behavior.

**Parameters:**
- task (required): Detailed description of the web interaction to perform, including target websites, authentication requirements, content to post, forms to fill, or specific browser actions needed

**Use this function when users need:**
- Social media posting and content management
- Login to authenticated websites and portals
- Form submissions and online applications
- E-commerce interactions (shopping, purchasing, cart management)
- Complex website navigation and interaction
- Dynamic content interaction and JavaScript-heavy sites
- Multi-step workflows across multiple pages
- File uploads and downloads requiring browser interface
- Website monitoring with visual verification
- Account management and profile updates
- Interactive web applications and dashboards

**Browser automation capabilities:**
- **Authentication**: Login to accounts using stored credentials
- **Social Media Management**: Post, share, like, comment across platforms
- **Form Automation**: Fill out and submit complex forms with validation
- **E-commerce Operations**: Add to cart, checkout, order tracking
- **Content Publishing**: Upload and publish content to websites and platforms
- **Interactive Elements**: Click buttons, navigate menus, handle pop-ups
- **File Operations**: Upload files, download documents, manage attachments
- **Multi-page Workflows**: Navigate through complex website processes
- **Dynamic Content**: Handle JavaScript, AJAX, and real-time updates
- **Visual Verification**: Screenshots and visual confirmation of actions

**Supported platforms:**
- Social media (Twitter, LinkedIn, Facebook, Instagram, TikTok, YouTube)
- Business platforms (Salesforce, HubSpot, Slack, Microsoft 365)
- E-commerce sites (Amazon, eBay, Shopify stores)
- Professional networks and job boards
- Government and institutional portals
- Banking and financial services (with proper authentication)
- Content management systems and blogs
- Project management and collaboration tools
- Educational platforms and learning management systems

**Authentication and security:**
- Secure credential storage and management
- Multi-factor authentication support
- Session management and cookie handling
- CAPTCHA solving capabilities
- Rate limiting and respectful browsing practices
- Privacy protection and data security

**Output includes:**
- Confirmation of completed actions with timestamps
- Screenshots or visual proof of successful operations
- Posted content links and engagement metrics
- Form submission confirmations and reference numbers
- Downloaded files and their storage locations
- Error handling with detailed troubleshooting information
- Step-by-step action logs for complex workflows

**Examples of requests to handle:**
"Post this announcement to our company LinkedIn page with image", "Login to our analytics dashboard and download monthly traffic report", "Submit job application form on company website with resume upload", "Navigate to Amazon and add specific products to cart for purchase", "Post tweet thread about our product launch with scheduled timing", "Login to our CRM and update client contact information", "Browse through our social media mentions and respond to customer comments", "Submit expense report form with receipt uploads on company portal", "Navigate to university website and complete course registration", "Login to banking portal and download monthly statements", "Post product photos to our Instagram business account with hashtags", "Fill out and submit grant application form with supporting documents"

**Output characteristics:**
- Real browser interaction with full JavaScript support
- Authenticated access to private accounts and portals
- Complex workflow execution with error recovery
- Visual confirmation and screenshot documentation
- Multi-platform content distribution and management
- Secure credential handling and session management
- Human-like browsing patterns and respectful automation
"""


brave_api_search = """
# Brave Search API - Independent Web Information Retrieval

Privacy-focused web search system powered by Brave's independent search index that delivers comprehensive results without tracking users. Built on Brave's own crawling infrastructure, this API provides fresh, unbiased search results with rich context and multiple content types. Optimized for factual accuracy and diverse perspectives without algorithmic manipulation from big tech search engines.

## Parameters

- **query** (required): `Annotated[str, "The search query string - be specific and descriptive for better results. Include relevant keywords, context, and relationships to the topic being searched"]`
- **search_type**: `Annotated[str, "Search mode: 'comprehensive' (detailed results with extra snippets), 'quick' (fast basic results), 'recent' (time-filtered results)"] = "comprehensive"`
- **count**: `Annotated[int, "Number of search results to return (1-20). Higher count provides more comprehensive information but takes longer"] = 2`
- **freshness**: `Annotated[Optional[str], "Time filter for results: 'pd' (past day), 'pw' (past week), 'pm' (past month), 'py' (past year). None returns results from all time periods"] = None`
- **country**: `Annotated[str, "Country code for localized search results (US, GB, CA, AU, etc). Affects content relevance and regional preferences"] = "US"`
- **safesearch**: `Annotated[str, "Content safety filter: 'strict' (blocks adult content), 'moderate' (balanced filtering), 'off' (no content filtering)"] = "moderate"`

## Use this function when users need:

- Independent search results free from big tech bias and tracking
- Fresh web content from Brave's continuously updated index
- Privacy-preserving information retrieval without user profiling
- Comprehensive research with knowledge panels and rich snippets
- Multi-format content discovery (web, news, images, videos)
- Real-time information with customizable time filters
- Localized results for specific regions and languages
- Fact-checking with diverse source perspectives
- Academic research without search bubble effects
- Current events and trending topic analysis
- Technical documentation and developer resources
- Business intelligence and market research

## Brave Search API capabilities:

- **Independent Index**: Brave's own web crawling and indexing infrastructure
- **Knowledge Panels**: Structured data and factual information boxes
- **Multi-Content Types**: Web results, news articles, images, videos
- **Fresh Results**: Real-time crawling with recent content prioritization
- **Rich Snippets**: Extended content previews and context
- **Geographic Targeting**: Country and language-specific result ranking
- **Time Filtering**: Precise date range controls for temporal relevance
- **Safe Search**: Configurable content filtering and family-safe options
- **Spell Correction**: Automatic query enhancement and suggestion
- **No Tracking**: Privacy-first approach without user data collection

## Information sources:

- Brave's independent web crawler and search index
- Real-time content discovery and freshness ranking
- Structured data extraction from authoritative sources
- News aggregation from diverse media outlets
- Image and multimedia content indexing
- Academic and research publication databases
- Government and institutional website crawling
- Business directory and professional network indexing

## Output includes:

- Structured search results optimized for LLM consumption
- Knowledge panels with authoritative factual data
- Multiple content formats (text, images, news, videos)
- Source attribution with credibility indicators
- Publication dates and content freshness metrics
- Rich context through extra content snippets
- Geographic and language-specific result prioritization
- Spelling corrections and query enhancement suggestions

## Examples of requests to handle:

- "Search for latest developments in quantum computing research"
- "Find comprehensive information about renewable energy policies in Europe"
- "Look up recent clinical trials for Alzheimer's treatments"
- "Get current analysis of cryptocurrency market trends"
- "Search for technical documentation on GraphQL best practices"
- "Find diverse perspectives on remote work productivity studies"
- "Look up recent IPO filings and market performance"
- "Search for environmental impact studies of electric vehicles"
- "Get latest research on machine learning interpretability"
- "Find comprehensive reviews of the latest smartphone releases"
- "Search for geopolitical analysis of recent trade agreements"
- "Look up current cybersecurity threat landscape reports"

## Output characteristics:

- Privacy-preserving search without user tracking or profiling
- Independent results free from algorithmic manipulation
- Comprehensive context through knowledge panels and rich snippets
- Fast response times with real-time content freshness
- Multiple perspective aggregation for balanced information
- Source diversity beyond mainstream tech platform bias
- Geographic and linguistic customization capabilities
- Structured format optimized for AI/LLM processing and analysis
"""