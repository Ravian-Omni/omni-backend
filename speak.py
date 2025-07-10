import asyncio
import sys

async def speak(text, voice='Samantha'):
    """
    Asynchronously speak text using macOS 'say' command with Samantha voice by default.
    Falls back to system default if Samantha is not available.
    
    Args:
        text (str): The text to be spoken
        voice (str): Voice to use (default: 'Samantha')
    """
    if sys.platform != 'darwin':
        print("This function only works on macOS")
        return
    
    try:
        # Try with specified voice first
        process = await asyncio.create_subprocess_exec(
            'say', '-v', voice, text,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await process.wait()
        
        if process.returncode != 0:
            raise Exception("Voice not available")
            
    except Exception:
        # If specified voice fails, use system default
        print(f"Voice '{voice}' not available, using system default")
        process = await asyncio.create_subprocess_exec('say', text)
        await process.wait()

# Usage examples:

# Single call
async def main():
    # await speak("Hey there! Ravian finished your task!")
    # await speak("Ravian reporting: Task done!")
    await speak("Hey there! Ravian just wrapped up your task for you.")

# Run it
asyncio.run(main())

