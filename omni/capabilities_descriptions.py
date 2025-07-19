python_coder_description = """ 
Advanced Python code generation system that solves any task requiring programming. Automatically plans, writes, executes, and debugs Python code to complete user requests. Specializes in data analysis, file processing, document generation, visualizations, automation, and calculations. Generates production-ready code with automatic dependency installation, error handling, and professional output formatting.

**Parameters:**
- query (required): The task or problem to solve with Python code along with proper context

**Use this function when users need:**
- Data analysis or processing (CSV, Excel, databases)
- File generation (PDF reports, PowerPoint presentations, Excel files, HTML dashboards)
- Data visualizations and interactive charts
- Document creation with professional formatting
- Automation or batch processing tasks
- Mathematical calculations or statistical analysis
- File format conversions
- Web scraping or API integration
- Any task that would benefit from Python programming

"""

email_manager_description = """ This tool will be used for managing emails. It can perform the following tasks
          can reply to emails
          can send out emails with attachments"
          can read emails from the inbox and also save the attachments,
          can search emails based on subject, sender, date, etc."""

file_finder_description = """This tool Can find any file from the local MAC OS system"""

web_browser_description = """This tool will be used to search the web
Can be used to get real time information about any subject,
          It has all the credentials for all the website that user want you to surf
          It can be used for any question or topic that needs a web searching capability
 """

Image_generator_description = """
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


def capability_descriptions():

    return {
        "python_coder": python_coder_description,
        "email_manager": email_manager_description,
        "file_finder": file_finder_description,
        "web_browser": web_browser_description,
        "image_generator": Image_generator_description
    }

if __name__ == "__main__":
    # Retrieve all capabilities and their descriptions
    all_caps = capability_descriptions()

    # Print all capabilities and their descriptions
    for capability, description in all_caps.items():
        print(f"Capability: {capability}\nDescription: {description}\n")  