import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from together import Together

from src.configs.llm_configs_manager import LLMConfigManager


@dataclass
class ImageGenerationConfig:
    """Configuration for Flux image generation."""

    model: str
    width: int = 1792
    height: int = 1792
    steps: int = 40  # Max: 40
    guidance_scale: float = 18.0  # Max: 20.0
    timeout: int = 3600
    default_format: str = "jpg"


@dataclass
class ImageGenerationResult:
    """Result of image generation operation."""

    success: bool
    file_path: str | None = None
    filename: str | None = None
    url: str | None = None
    error: str | None = None
    generation_time: float | None = None


class FluxImageGenerator:
    """Production-ready Flux image generator using Together AI API.

    Handles image generation with the Flux model, including:
    - Parameter validation and configuration
    - Image generation via Together AI
    - Image downloading and local storage
    - Comprehensive error handling and logging
    - File naming and directory management

    Attributes:
        api_key (str): Together AI API key
        config (ImageGenerationConfig): Generation configuration
        output_dir (Path): Directory for saving generated images
        client (Together): Together AI client instance
        logger (logging.Logger): Logger instance
    """

    # Image generation constraints
    MAX_WIDTH = 1792
    MAX_HEIGHT = 1792
    MAX_STEPS = 40
    MAX_GUIDANCE_SCALE = 20.0
    MIN_GUIDANCE_SCALE = 0.0

    def __init__(
        self,
        output_dir: str,
        config: ImageGenerationConfig | None = None,
    ):
        """Initialize the Flux Image Generator.

        Args:
            output_dir: Directory path for saving generated images
            config: Optional custom configuration for image generation

        Raises:
            ValueError: If api_key or model is not provided
            OSError: If output directory cannot be created
        """
        image_llm_config = LLMConfigManager.get_config("image_together_llm")
        self.image_llm_config = image_llm_config.get("config_list", [])[0]

        self.api_key = self.image_llm_config.get("api_key")
        self.output_dir = Path(output_dir)
        self.logger = logging.getLogger(__name__)

        # Use provided config or create default
        self.config = config or ImageGenerationConfig(
            model=self.image_llm_config.get("model")
        )

        # Initialize Together client
        self.client = Together(api_key=self.api_key)

        # Ensure output directory exists
        self._ensure_output_directory()

        self.logger.info(
            f"FluxImageGenerator initialized - Model: {self.config.model}, "
            f"Output: {self.output_dir}"
        )

    def _ensure_output_directory(self) -> None:
        """Create output directory if it doesn't exist.

        Raises:
            OSError: If directory cannot be created
        """
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.logger.debug(f"Output directory ready: {self.output_dir}")
        except Exception as e:
            error_msg = f"Failed to create output directory: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise OSError(error_msg)

    def generate_image(
        self,
        prompt: str,
        filename: str | None = None,
        width: int | None = None,
        height: int | None = None,
        steps: int | None = None,
        guidance_scale: float | None = None,
    ) -> ImageGenerationResult:
        """Generate an image using the Flux model.

        Main entry point for image generation. Orchestrates the entire process:
        1. Validates and prepares parameters
        2. Generates image via Together AI API
        3. Downloads and saves image locally
        4. Returns result with file information

        Args:
            prompt: Text description of the image to generate
            filename: Optional custom filename (with or without extension)
            width: Image width in pixels (default from config)
            height: Image height in pixels (default from config)
            steps: Number of generation steps (default from config)
            guidance_scale: How closely to follow prompt (default from config)

        Returns:
            ImageGenerationResult with success status and file information

        Example:
            >>> generator = FluxImageGenerator(api_key, model, "./images")
            >>> result = generator.generate_image(
            ...     prompt="A serene mountain landscape at sunset",
            ...     filename="mountain_sunset.jpg"
            ... )
            >>> if result.success:
            ...     print(f"Image saved to: {result.file_path}")
        """
        start_time = time.time()

        try:
            # Step 1: Validate and prepare parameters
            validated_params = self._prepare_generation_parameters(
                prompt=prompt,
                width=width,
                height=height,
                steps=steps,
                guidance_scale=guidance_scale,
            )

            # Step 2: Generate image via API
            image_url = self._generate_image_via_api(validated_params)

            # Step 3: Download and save image
            file_path = self._download_and_save_image(
                image_url=image_url,
                filename=filename,
            )

            generation_time = time.time() - start_time

            self.logger.info(
                f"Image generated successfully in {generation_time:.2f}s: {file_path}"
            )

            return ImageGenerationResult(
                success=True,
                file_path=str(file_path),
                filename=file_path.name,
                url=image_url,
                generation_time=generation_time,
            )

        except Exception as e:
            error_msg = f"Image generation failed: {str(e)}"
            self.logger.error(error_msg, exc_info=True)

            return ImageGenerationResult(
                success=False,
                error=error_msg,
                generation_time=time.time() - start_time,
            )

    def _prepare_generation_parameters(
        self,
        prompt: str,
        width: int | None,
        height: int | None,
        steps: int | None,
        guidance_scale: float | None,
    ) -> dict[str, Any]:
        """Validate and prepare parameters for image generation.

        Applies defaults from config and validates all parameters are within
        acceptable ranges for the Flux model.

        Args:
            prompt: Image generation prompt
            width: Optional width override
            height: Optional height override
            steps: Optional steps override
            guidance_scale: Optional guidance scale override

        Returns:
            Dict with validated parameters ready for API call

        Raises:
            ValueError: If any parameter is invalid
        """
        # Validate prompt
        if not prompt or not prompt.strip():
            raise ValueError("Prompt cannot be empty")

        # Use config defaults if not specified
        final_width = width or self.config.width
        final_height = height or self.config.height
        final_steps = steps or self.config.steps
        final_guidance = guidance_scale or self.config.guidance_scale

        # Validate dimensions
        if final_width <= 0 or final_width > self.MAX_WIDTH:
            raise ValueError(
                f"Width must be between 1 and {self.MAX_WIDTH}, got {final_width}"
            )
        if final_height <= 0 or final_height > self.MAX_HEIGHT:
            raise ValueError(
                f"Height must be between 1 and {self.MAX_HEIGHT}, got {final_height}"
            )

        # Validate steps
        if final_steps <= 0 or final_steps > self.MAX_STEPS:
            raise ValueError(
                f"Steps must be between 1 and {self.MAX_STEPS}, got {final_steps}"
            )

        # Validate guidance scale
        if not (self.MIN_GUIDANCE_SCALE <= final_guidance <= self.MAX_GUIDANCE_SCALE):
            raise ValueError(
                f"Guidance scale must be between {self.MIN_GUIDANCE_SCALE} and "
                f"{self.MAX_GUIDANCE_SCALE}, got {final_guidance}"
            )

        params = {
            "prompt": prompt.strip(),
            "model": self.config.model,
            "width": final_width,
            "height": final_height,
            "steps": final_steps,
            "guidance_scale": final_guidance,
        }

        self.logger.debug(f"Generation parameters: {params}")
        return params

    def _generate_image_via_api(self, params: dict[str, Any]) -> str:
        """Call Together AI API to generate image.

        Args:
            params: Validated generation parameters

        Returns:
            URL of the generated image

        Raises:
            Exception: If API call fails
        """
        self.logger.info(f"Generating image with prompt: '{params['prompt'][:50]}...'")

        try:
            response = self.client.images.generate(
                prompt=params["prompt"],
                model=params["model"],
                width=params["width"],
                height=params["height"],
                steps=params["steps"],
                guidance_scale=params["guidance_scale"],
            )

            if not response.data or len(response.data) == 0:
                raise ValueError("API returned no image data")

            image_url = response.data[0].url

            if not image_url:
                raise ValueError("API returned no image URL")

            self.logger.info(f"Image generated successfully: {image_url}")
            return image_url

        except Exception as e:
            error_msg = f"Together AI API call failed: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise Exception(error_msg)

    def _download_and_save_image(
        self,
        image_url: str,
        filename: str | None = None,
    ) -> Path:
        """Download image from URL and save to local storage.

        Args:
            image_url: URL of the generated image
            filename: Optional custom filename

        Returns:
            Path object pointing to the saved image file

        Raises:
            Exception: If download or save fails
        """
        self.logger.info(f"Downloading image from: {image_url}")

        try:
            # Download image
            response = requests.get(
                url=image_url,
                timeout=self.config.timeout,
                stream=True,
            )
            response.raise_for_status()

            # Generate filename
            final_filename = self._generate_filename(filename)
            file_path = self.output_dir / final_filename

            # Save image
            with open(file_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # Verify file was created
            if not file_path.exists():
                raise OSError(f"File was not created: {file_path}")

            file_size = file_path.stat().st_size
            self.logger.info(
                f"Image saved successfully: {file_path} ({file_size:,} bytes)"
            )

            return file_path

        except requests.RequestException as e:
            error_msg = f"Failed to download image: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise Exception(error_msg)
        except OSError as e:
            error_msg = f"Failed to save image: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise Exception(error_msg)

    def _generate_filename(self, custom_filename: str | None = None) -> str:
        """Generate a filename for the image.

        If custom filename is provided, ensures it has proper extension.
        Otherwise, generates timestamp-based filename.

        Args:
            custom_filename: Optional user-provided filename

        Returns:
            Final filename with proper extension

        Example:
            >>> generator._generate_filename("my_image")
            'my_image.jpg'
            >>> generator._generate_filename("my_image.png")
            'my_image.png'
            >>> generator._generate_filename(None)
            'flux_1700000000.jpg'
        """
        if custom_filename:
            # Check if filename has extension
            filename_path = Path(custom_filename)
            if filename_path.suffix:
                return custom_filename
            else:
                # Add default extension
                return f"{custom_filename}.{self.config.default_format}"
        else:
            # Generate timestamp-based filename
            timestamp = int(time.time())
            return f"flux_{timestamp}.{self.config.default_format}"

    def batch_generate(
        self,
        prompts: list[str],
        filenames: list[str] | None = None,
    ) -> list[ImageGenerationResult]:
        """Generate multiple images from a list of prompts.

        Useful for batch processing. Each image is generated independently,
        so one failure doesn't stop the entire batch.

        Args:
            prompts: List of image generation prompts
            filenames: Optional list of filenames (must match prompts length)

        Returns:
            List of ImageGenerationResult objects

        Raises:
            ValueError: If filenames list length doesn't match prompts

        Example:
            >>> prompts = ["A cat", "A dog", "A bird"]
            >>> results = generator.batch_generate(prompts)
            >>> successful = sum(1 for r in results if r.success)
            >>> print(f"{successful}/{len(prompts)} images generated")
        """
        if filenames and len(filenames) != len(prompts):
            raise ValueError(
                f"Filenames list length ({len(filenames)}) must match "
                f"prompts list length ({len(prompts)})"
            )

        self.logger.info(f"Starting batch generation of {len(prompts)} images")

        results = []
        for i, prompt in enumerate(prompts):
            filename = filenames[i] if filenames else None
            result = self.generate_image(prompt=prompt, filename=filename)
            results.append(result)

            if result.success:
                self.logger.info(f"Batch {i+1}/{len(prompts)}: Success")
            else:
                self.logger.warning(
                    f"Batch {i+1}/{len(prompts)}: Failed - {result.error}"
                )

        successful_count = sum(1 for r in results if r.success)
        self.logger.info(
            f"Batch generation complete: {successful_count}/{len(prompts)} successful"
        )

        return results

    def get_generation_stats(self) -> dict[str, Any]:
        """Get statistics about generated images in output directory.

        Returns:
            Dict with statistics about generated images

        Example:
            >>> stats = generator.get_generation_stats()
            >>> print(f"Total images: {stats['total_images']}")
        """
        try:
            image_files = list(self.output_dir.glob(f"*.{self.config.default_format}"))
            total_size = sum(f.stat().st_size for f in image_files)

            return {
                "output_directory": str(self.output_dir),
                "total_images": len(image_files),
                "total_size_bytes": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 2),
                "image_format": self.config.default_format,
            }
        except Exception as e:
            self.logger.error(f"Failed to get statistics: {str(e)}")
            return {"error": str(e)}


# Autogen Integration Wrapper
class FluxImageGeneratorAutogenTool:
    """Autogen-compatible wrapper for FluxImageGenerator.

    Provides simple interface that Autogen agents can call directly.
    Handles result formatting for agent consumption.
    """

    def __init__(self, generator: FluxImageGenerator):
        """Initialize Autogen wrapper.

        Args:
            generator: FluxImageGenerator instance
        """
        self.generator = generator
        self.logger = logging.getLogger(__name__)

    def generate_image(self, prompt: str, filename: str = "") -> str:
        """Generate image with simple string return for Autogen agents.

        Args:
            prompt: Image generation prompt
            filename: Optional filename

        Returns:
            Success message with file path or error message
        """
        self.logger.info(f"Autogen tool called with prompt: '{prompt[:50]}...'")

        result = self.generator.generate_image(
            prompt=prompt,
            filename=filename if filename else None,
        )

        if result.success:
            return (
                f"✅ Image successfully generated and saved at {result.file_path}\n"
                f"Generation time: {result.generation_time:.2f}s"
            )
        else:
            return f"❌ Error generating image: {result.error}"


# Usage Example
# if __name__ == "__main__":
#     # Configure logging
#     logging.basicConfig(
#         level=logging.INFO,
#         format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
#     )

#     # Example configuration
#     config = ImageGenerationConfig(
#         model="black-forest-labs/FLUX.1-schnell",
#         width=1024,
#         height=1024,
#         steps=30,
#         guidance_scale=15.0,
#     )

#     # Initialize generator
#     generator = FluxImageGenerator(
#         api_key="your_api_key_here", # pragma: allowlist secret
#         model="black-forest-labs/FLUX.1-schnell",
#         output_dir="./generated_images",
#         config=config,
#     )

#     # Single image generation
#     result = generator.generate_image(
#         prompt="A majestic dragon flying over a medieval castle at sunset",
#         filename="dragon_castle.jpg",
#     )

#     if result.success:
#         print(f"✅ Success: {result.file_path}")
#         print(f"⏱️  Generated in: {result.generation_time:.2f}s")
#     else:
#         print(f"❌ Error: {result.error}")

#     # Batch generation example
#     prompts = [
#         "A serene beach at sunset",
#         "A futuristic city skyline",
#         "A mystical forest with glowing mushrooms",
#     ]

#     batch_results = generator.batch_generate(prompts)
#     print(f"\nBatch: {sum(r.success for r in batch_results)}/{len(prompts)} successful")

#     # Get statistics
#     stats = generator.get_generation_stats()
#     print(f"\n📊 Stats: {stats['total_images']} images, {stats['total_size_mb']} MB")
