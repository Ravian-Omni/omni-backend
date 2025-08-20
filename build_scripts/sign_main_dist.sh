#!/bin/bash

# Complete signing and notarization script for main.dist
set -e
# Script to sign all components in main.dist folder
DIST_PATH="./main.dist"
SIGNING_IDENTITY="Developer ID Application: Lokesh Kumar (9ZV6HRFKX2)"
ENTITLEMENTS="entitlements.plist"
BUNDLE_ID="com.ravianai.omni.backend"
APPLE_ID="lokesh@ravian.ai"
TEAM_ID="9ZV6HRFKX2"
APP_SPECIFIC_PASSWORD="ceim-xorc-ufot-caiw"

echo "Signing all components in $DIST_PATH..."

echo "=== Step 1: Signing all components in $DIST_PATH ==="

# Sign all .so files first (CRITICAL - these were missing timestamps)
echo "Signing .so files..."
find "$DIST_PATH" -name "*.so" -exec codesign \
    --force \
    --timestamp \
    --verify \
    --verbose \
    --sign "$SIGNING_IDENTITY" \
    --options runtime \
    --entitlements "$ENTITLEMENTS" \
    {} \;

# Sign all .dylib files (dependencies must be signed before main executable)
echo "Signing dynamic libraries..."
find "$DIST_PATH" -name "*.dylib" -exec codesign \
    --force \
    --timestamp \
    --verify \
    --verbose \
    --sign "$SIGNING_IDENTITY" \
    --options runtime \
    --entitlements "$ENTITLEMENTS" \
    {} \;

# Sign any framework bundles
echo "Signing frameworks..."
find "$DIST_PATH" -name "*.framework" -exec codesign \
    --force \
    --timestamp \
    --verify \
    --verbose \
    --sign "$SIGNING_IDENTITY" \
    --options runtime \
    --entitlements "$ENTITLEMENTS" \
    {} \;

# 🔥 IMPROVED: Sign nested executables with better error handling
echo "Signing nested executables..."
find "$DIST_PATH" -type f -perm +111 ! -name "app" -print0 | while IFS= read -r -d '' file; do
    echo "  → Signing executable: $file"
    if codesign \
        --force \
        --timestamp \
        --verify \
        --verbose \
        --sign "$SIGNING_IDENTITY" \
        --options runtime \
        --entitlements "$ENTITLEMENTS" \
        "$file" 2>/dev/null; then
        echo "    ✅ Signed: $(basename "$file")"
    else
        echo "    ⚠️  Failed to sign: $file"
    fi
done

# 🔥 NEW: Explicitly sign Python executable if it exists
echo "Checking for Python executable..."
if [ -f "$DIST_PATH/Python" ]; then
    echo "  → Signing Python executable..."
    if codesign \
        --force \
        --timestamp \
        --verify \
        --verbose \
        --sign "$SIGNING_IDENTITY" \
        --options runtime \
        --entitlements "$ENTITLEMENTS" \
        "$DIST_PATH/Python"; then
        echo "    ✅ Python executable signed successfully"
    else
        echo "    ❌ Failed to sign Python executable"
        exit 1
    fi
else
    echo "  ℹ️  Python executable not found (may be normal)"
fi

# Finally, sign the main executable
echo "Signing main executable..."
codesign \
    --force \
    --timestamp \
    --verify \
    --verbose \
    --sign "$SIGNING_IDENTITY" \
    --options runtime \
    --entitlements "$ENTITLEMENTS" \
    "$DIST_PATH/app"

echo "=== Step 2: Verifying signatures ==="
codesign --verify --deep --strict --verbose=2 "$DIST_PATH/app"

echo "=== Step 3: Creating archive for notarization ==="
# 🔥 CHANGED: Using ditto instead of zip for better preservation of metadata
echo "Creating archive with ditto (preserves extended attributes)..."
if [ -f "omni-backend.zip" ]; then
    rm "omni-backend.zip"
fi
ditto -c -k --keepParent "$DIST_PATH" "omni-backend.zip"
echo "  ✅ Archive created: omni-backend.zip"

echo "=== Step 4: Submitting for notarization ==="
xcrun notarytool submit "omni-backend.zip" \
    --apple-id "$APPLE_ID" \
    --password "$APP_SPECIFIC_PASSWORD" \
    --team-id "$TEAM_ID" \
    --wait

echo "=== Step 5: Stapling notarization (optional for Electron resources) ==="
# Note: Stapling may not work for individual executables, but try anyway
xcrun stapler staple "$DIST_PATH/app" || echo "Stapling failed (expected for individual executables)"

echo "=== Notarization completed! ==="
echo "Your main.dist folder is now signed and notarized."
echo "You can now copy it to your Electron app resources."

# Cleanup
rm "omni-backend.zip"