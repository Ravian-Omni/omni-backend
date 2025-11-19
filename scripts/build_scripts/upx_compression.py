#!/usr/bin/env python3
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def check_upx_installed():
    """Check if UPX is installed and available"""
    try:
        result = subprocess.run(
            ["upx", "--version"], capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            print(f"UPX found: {result.stdout.split()[0]}")
            return True
    except FileNotFoundError:
        pass

    print("ERROR: UPX is not installed or not in PATH")
    print("\nInstallation instructions:")

    system = platform.system()
    if system == "Windows":
        print("  - Download from: https://github.com/upx/upx/releases")
        print("  - Or install via: winget install upx.upx")
        print("  - Or install via: choco install upx")
    elif system == "Darwin":  # macOS
        print("  - Install via Homebrew: brew install upx")
    elif system == "Linux":
        print("  - Install via apt: sudo apt install upx-ucl")
        print("  - Install via yum: sudo yum install upx")
        print("  - Or download from: https://github.com/upx/upx/releases")

    return False


def find_executable(dist_dir):
    """Find the main executable in the dist directory"""
    dist_path = Path(dist_dir)

    if not dist_path.exists():
        print(f"ERROR: Distribution directory '{dist_dir}' not found!")
        print("Please run the Nuitka build script first.")
        return None

    # Look for the main executable
    exe_name = "ravian.exe" if sys.platform == "win32" else "ravian"

    # Try multiple possible locations
    possible_paths = [
        dist_path / exe_name,  # dist/ravian
        dist_path / "ravian.dist" / exe_name,  # dist/ravian.dist/ravian
        dist_path / "main.dist" / exe_name,  # dist/main.dist/ravian
    ]

    for exe_path in possible_paths:
        if exe_path.exists():
            return exe_path

    print(f"ERROR: Could not find executable '{exe_name}' in {dist_dir}")
    print("Searched in:")
    for path in possible_paths:
        print(f"  - {path}")
    return None


def get_file_size(file_path):
    """Get file size in MB"""
    size_bytes = file_path.stat().st_size
    size_mb = size_bytes / (1024 * 1024)
    return size_mb


def compress_with_upx(exe_path, compression_level=9, backup=True):
    """
    Compress executable with UPX

    Args:
        exe_path: Path to executable
        compression_level: 1-9, where 9 is maximum compression (slower)
        backup: Whether to create a backup before compression
    """
    exe_path = Path(exe_path)

    # Create backup if requested
    if backup:
        backup_path = exe_path.with_suffix(exe_path.suffix + ".backup")
        print(f"Creating backup: {backup_path.name}")
        shutil.copy2(exe_path, backup_path)

    # Get original size
    original_size = get_file_size(exe_path)
    print(f"\nOriginal size: {original_size:.2f} MB")

    # Compress with UPX
    print(f"Compressing with UPX (level {compression_level})...")
    print("This may take a few minutes for large files...")

    upx_cmd = [
        "upx",
        f"-{compression_level}",  # Compression level
        "--lzma",  # Use LZMA compression (best compression)
        "-v",  # Verbose output
    ]

    # Add macOS flag if on macOS
    if platform.system() == "Darwin":
        upx_cmd.append("--force-macos")
        print("Note: Using --force-macos flag (macOS support is experimental)")

    upx_cmd.append(str(exe_path))

    try:
        subprocess.run(upx_cmd, check=True, capture_output=True, text=True)

        # Get compressed size
        compressed_size = get_file_size(exe_path)
        reduction = ((original_size - compressed_size) / original_size) * 100

        print("\n✓ Compression successful!")
        print(f"  Original size:   {original_size:.2f} MB")
        print(f"  Compressed size: {compressed_size:.2f} MB")
        print(f"  Reduction:       {reduction:.1f}%")

        if backup:
            print(f"\n  Backup saved as: {backup_path.name}")

        return True

    except subprocess.CalledProcessError as e:
        print("\n✗ Compression failed!")
        print(f"Error: {e.stderr}")

        # Restore backup if compression failed
        if backup and backup_path.exists():
            print("Restoring from backup...")
            shutil.copy2(backup_path, exe_path)
            backup_path.unlink()

        return False


def compress_all_libraries(dist_dir, compression_level=9):
    """
    Optionally compress all .dll/.so files in the distribution

    Note: This is optional and may cause issues with some libraries
    """
    dist_path = Path(dist_dir)

    # Find library files
    if sys.platform == "win32":
        lib_pattern = "*.dll"
    else:
        lib_pattern = "*.so"

    lib_files = list(dist_path.rglob(lib_pattern))

    if not lib_files:
        return

    print(f"\nFound {len(lib_files)} library files")
    response = input("Do you want to compress library files too? (y/N): ")

    if response.lower() != "y":
        return

    print("\nCompressing library files...")
    success_count = 0

    for lib_file in lib_files:
        try:
            subprocess.run(
                ["upx", f"-{compression_level}", "--lzma", "-q", str(lib_file)],
                check=True,
                capture_output=True,
            )
            success_count += 1
            print(f"  ✓ {lib_file.name}")
        except subprocess.CalledProcessError:
            print(f"  ✗ {lib_file.name} (failed or already compressed)")

    print(f"\nCompressed {success_count}/{len(lib_files)} library files")


def main():
    """Main compression workflow"""
    print("=" * 60)
    print("UPX Compression for Nuitka Build")
    print("=" * 60)

    # Check if UPX is installed
    if not check_upx_installed():
        sys.exit(1)

    # Find the executable
    dist_dir = "dist"
    exe_path = find_executable(dist_dir)

    if not exe_path:
        sys.exit(1)

    print(f"\nFound executable: {exe_path}")

    # Compression level selection
    print("\nCompression levels:")
    print("  1-3: Fast compression, larger file")
    print("  4-6: Balanced")
    print("  7-9: Maximum compression, slower (recommended: 9)")

    try:
        level_input = input("\nEnter compression level (1-9) [default: 9]: ").strip()
        compression_level = int(level_input) if level_input else 9

        if compression_level < 1 or compression_level > 9:
            print("Invalid level. Using default: 9")
            compression_level = 9
    except ValueError:
        print("Invalid input. Using default: 9")
        compression_level = 9

    # Compress the main executable
    success = compress_with_upx(exe_path, compression_level, backup=True)

    if not success:
        sys.exit(1)

    # Optionally compress library files
    compress_all_libraries(dist_dir, compression_level)

    print("\n" + "=" * 60)
    print("Compression complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
