file_search_function_description="""
{
  "function_description": {
    "type": "function",
    "function": {
      "name": "file_search_function",
      "description": "Search for files on macOS system by name, type, date, size, and optionally within a specific directory. This function can search the entire user home directory or be limited to a specific folder. Use this when the user wants to find files, list directory contents, or search within a particular location.\n\nCommon use cases:\n- Find files by name: 'find my report', 'where is budget.xlsx'\n- List directory contents: 'show all files in Documents', 'list files in Desktop', 'what's in Downloads'\n- Search in specific location: 'find PDFs in Documents', 'search for images in Pictures'\n- Find by type: 'show all PDFs', 'find Excel files in Desktop'\n- Find by date: 'files modified yesterday', 'documents from last week in Documents'\n- Find by size: 'large files in Downloads', 'PDFs over 10MB in Documents'\n- Combined criteria: 'large PDFs from last week in Documents', 'recent budget spreadsheets in Desktop'\n\nThe 'directory' parameter accepts:\n- Shortcuts: 'Documents', 'Desktop', 'Downloads', 'Pictures', 'Movies', 'Music', 'Home'\n- Absolute paths: '/Users/username/Projects'\n- Home-relative: '~/Documents/Work'\n- Relative paths: 'Documents/Projects'\n\nReturns file paths, sizes, modification dates, and creation dates.",
      
      "parameters": {
        "type": "object",
        "properties": {
          "search_term": {
            "type": "string",
            "description": "The filename or partial filename to search for. Can be empty string for listing all files in a directory or filter-only searches. Examples: 'invoice', 'budget', 'report_2024', 'IMG_', or '' to list all files."
          },
          "file_type": {
            "type": "string",
            "description": "File extension to filter by, without the dot. Common types: 'pdf', 'docx', 'doc', 'xlsx', 'xls', 'txt', 'jpg', 'jpeg', 'png', 'gif', 'mp4', 'mov', 'mp3', 'py', 'js', 'json', 'csv', 'zip'. Omit to search all file types.",
            "enum": ["pdf", "docx", "doc", "xlsx", "xls", "pptx", "ppt", "txt", "md", "jpg", "jpeg", "png", "gif", "bmp", "svg", "mp4", "mov", "avi", "mkv", "mp3", "wav", "m4a", "py", "js", "java", "cpp", "c", "html", "css", "json", "xml", "csv", "zip", "tar", "gz", "rar"]
          },
          "modified_after": {
            "type": "string",
            "description": "Only return files modified after this datetime. Format: ISO 8601 datetime string 'YYYY-MM-DDTHH:MM:SS' (e.g., '2024-10-15T00:00:00'). Use for queries like 'modified yesterday', 'changed last week', 'updated this month'. Calculate relative to current date.",
            "format": "date-time"
          },
          "modified_before": {
            "type": "string",
            "description": "Only return files modified before this datetime. Format: ISO 8601 datetime string 'YYYY-MM-DDTHH:MM:SS'. Use with modified_after to define a specific date range. Example: files modified specifically on a certain day would have both modified_after (start of day) and modified_before (end of day).",
            "format": "date-time"
          },
          "created_after": {
            "type": "string",
            "description": "Only return files created after this datetime. Format: ISO 8601 datetime string 'YYYY-MM-DDTHH:MM:SS'. Use when user specifically mentions 'created', 'made', or 'new files' rather than 'modified' or 'changed'. Example: 'files created today', 'new files this week'.",
            "format": "date-time"
          },
          "size_min": {
            "type": "integer",
            "description": "Minimum file size in bytes. Use for queries like 'large files', 'over XMB', 'bigger than'. Common conversions: 1MB = 1,048,576 bytes, 10MB = 10,485,760 bytes, 100MB = 104,857,600 bytes, 1GB = 1,073,741,824 bytes. 'Large files' typically means >= 10MB (10485760 bytes).",
            "minimum": 0
          },
          "size_max": {
            "type": "integer",
            "description": "Maximum file size in bytes. Use for queries like 'small files', 'under XMB', 'smaller than'. 'Small files' typically means <= 1MB (1048576 bytes). Can be combined with size_min for a size range.",
            "minimum": 0
          },
          "directory": {
            "type": "string",
            "description": "Specific directory to search in. If omitted, searches common user directories (Documents, Desktop, Downloads, etc.). Accepts: 1) Shortcuts: 'Documents', 'Desktop', 'Downloads', 'Pictures', 'Photos', 'Movies', 'Videos', 'Music', 'Home'. 2) Absolute paths: '/Users/username/Projects'. 3) Home-relative: '~/Documents/Work'. 4) Relative: 'Documents/Projects'. Use this when user says 'in Documents', 'from Desktop', 'list files in Downloads', etc."
          },
          "max_results": {
            "type": "integer",
            "description": "Maximum number of results to return. Default is 20. Use 10-15 for specific searches, 20-30 for moderate searches, 50-100 for 'list all' queries or comprehensive searches like 'all PDFs' or 'all images'. The function returns the most relevant results first.",
            "default": 20,
            "minimum": 1,
            "maximum": 100
          }
        },
        "required": ["search_term"]
      },
      
      "examples": [
        {
          "description": "Find files with 'invoice' in the name",
          "call": {
            "search_term": "invoice"
          }
        },
        {
          "description": "List all files in Documents folder",
          "call": {
            "search_term": "",
            "directory": "Documents",
            "max_results": 50
          }
        },
        {
          "description": "Find all PDFs in Downloads",
          "call": {
            "search_term": "",
            "file_type": "pdf",
            "directory": "Downloads",
            "max_results": 30
          }
        },
        {
          "description": "Find Excel files with 'budget' in Desktop",
          "call": {
            "search_term": "budget",
            "file_type": "xlsx",
            "directory": "Desktop"
          }
        },
        {
          "description": "Find all PDF files modified in the last 7 days",
          "call": {
            "search_term": "",
            "file_type": "pdf",
            "modified_after": "2024-10-14T00:00:00",
            "max_results": 30
          }
        },
        {
          "description": "Find large PDF files (over 10MB) in Documents from last week",
          "call": {
            "search_term": "",
            "file_type": "pdf",
            "directory": "Documents",
            "modified_after": "2024-10-14T00:00:00",
            "size_min": 10485760,
            "max_results": 30
          }
        },
        {
          "description": "Find small images (under 1MB) in Pictures folder",
          "call": {
            "search_term": "",
            "file_type": "jpg",
            "directory": "Pictures",
            "size_max": 1048576,
            "max_results": 50
          }
        },
        {
          "description": "List all Python files in a specific project directory",
          "call": {
            "search_term": "",
            "file_type": "py",
            "directory": "~/Projects/MyApp",
            "max_results": 100
          }
        }
      ]
    }
  }
}
"""