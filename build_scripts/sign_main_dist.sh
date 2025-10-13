#!/bin/bash

# Complete signing and notarization script for main.dist
set -e
# Script to sign all components in main.dist folder
DIST_FOLDER="main.dist"
BINARY_NAME="ravian"                       # Name of your main executable
SIGNING_IDENTITY="Developer ID Application: Lokesh Kumar (9ZV6HRFKX2)"
ENTITLEMENTS_FILE="entitlements.plist"
BUNDLE_ID="com.ravianai.omni.backend"
APPLE_ID="lokesh@ravian.ai"
TEAM_ID="9ZV6HRFKX2"
APP_PASSWORD="ceim-xorc-ufot-caiw"

# Archive name (auto-generated from folder name)
ARCHIVE_NAME="${DIST_FOLDER}-signed.zip"

# ============================================================
# CHECK EVERYTHING BEFORE STARTING
# ============================================================
echo "🔍 Checking configuration..."

# Check if folder exists
if [ ! -d "$DIST_FOLDER" ]; then
    echo "❌ Error: Folder not found: $DIST_FOLDER"
    exit 1
fi

# Check if binary exists
if [ ! -f "$DIST_FOLDER/$BINARY_NAME" ]; then
    echo "❌ Error: Binary not found: $DIST_FOLDER/$BINARY_NAME"
    echo "   Make sure BINARY_NAME is set correctly"
    exit 1
fi

# Check if entitlements file exists
if [ ! -f "$ENTITLEMENTS_FILE" ]; then
    echo "❌ Error: Entitlements file not found: $ENTITLEMENTS_FILE"
    exit 1
fi

# Check if you changed the default values
if [[ "$SIGNING_IDENTITY" == *"Your Name"* ]]; then
    echo "❌ Error: Please update SIGNING_IDENTITY in this script"
    exit 1
fi

if [[ "$APPLE_ID" == *"example.com"* ]]; then
    echo "❌ Error: Please update APPLE_ID in this script"
    exit 1
fi

echo "✅ All checks passed!"
echo "📁 Folder: $DIST_FOLDER"
echo "🎯 Binary: $BINARY_NAME"
echo "🔑 Identity: $SIGNING_IDENTITY"
echo ""

# ============================================================
# STEP 1: SIGN EVERYTHING
# ============================================================
echo "================================================"
echo "STEP 1: Signing all files"
echo "================================================"
echo ""

# Sign .so files (Python extensions)
echo "📦 Signing .so files..."
SO_COUNT=$(find "$DIST_FOLDER" -name "*.so" 2>/dev/null | wc -l | tr -d ' ')
if [ "$SO_COUNT" -gt 0 ]; then
    find "$DIST_FOLDER" -name "*.so" | while read file; do
        echo "  → $(basename "$file")"
        codesign --force --timestamp --options runtime \
            --sign "$SIGNING_IDENTITY" \
            --entitlements "$ENTITLEMENTS_FILE" \
            "$file" 2>/dev/null || echo "    ⚠️  Failed (continuing...)"
    done
    echo "   Done: $SO_COUNT files"
else
    echo "   No .so files found"
fi

# Sign .dylib files (dynamic libraries)
echo ""
echo "📚 Signing .dylib files..."
DYLIB_COUNT=$(find "$DIST_FOLDER" -name "*.dylib" 2>/dev/null | wc -l | tr -d ' ')
if [ "$DYLIB_COUNT" -gt 0 ]; then
    find "$DIST_FOLDER" -name "*.dylib" | while read file; do
        echo "  → $(basename "$file")"
        codesign --force --timestamp --options runtime \
            --sign "$SIGNING_IDENTITY" \
            --entitlements "$ENTITLEMENTS_FILE" \
            "$file" 2>/dev/null || echo "    ⚠️  Failed (continuing...)"
    done
    echo "   Done: $DYLIB_COUNT files"
else
    echo "   No .dylib files found"
fi

# Sign frameworks
echo ""
echo "🖼️  Signing frameworks..."
FRAMEWORK_COUNT=$(find "$DIST_FOLDER" -name "*.framework" 2>/dev/null | wc -l | tr -d ' ')
if [ "$FRAMEWORK_COUNT" -gt 0 ]; then
    find "$DIST_FOLDER" -name "*.framework" | while read file; do
        echo "  → $(basename "$file")"
        codesign --force --timestamp --options runtime \
            --sign "$SIGNING_IDENTITY" \
            --entitlements "$ENTITLEMENTS_FILE" \
            "$file" 2>/dev/null || echo "    ⚠️  Failed (continuing...)"
    done
    echo "   Done: $FRAMEWORK_COUNT frameworks"
else
    echo "   No frameworks found"
fi

# Sign other executables (but not our main binary)
echo ""
echo "⚙️  Signing other executables..."
EXEC_COUNT=0
find "$DIST_FOLDER" -type f -perm +111 | while read file; do
    # Skip our main binary (we sign it last)
    if [ "$(basename "$file")" == "$BINARY_NAME" ]; then
        continue
    fi
    
    # Skip non-binary files
    if file "$file" | grep -q "text"; then
        continue
    fi
    
    echo "  → $(basename "$file")"
    if codesign --force --timestamp --options runtime \
        --sign "$SIGNING_IDENTITY" \
        --entitlements "$ENTITLEMENTS_FILE" \
        "$file" 2>/dev/null; then
        EXEC_COUNT=$((EXEC_COUNT + 1))
    else
        echo "    ⚠️  Failed (continuing...)"
    fi
done
echo "   Done: $EXEC_COUNT executables"

# Sign Python executable if it exists
echo ""
if [ -f "$DIST_FOLDER/Python" ]; then
    echo "🐍 Signing Python executable..."
    if codesign --force --timestamp --options runtime \
        --sign "$SIGNING_IDENTITY" \
        --entitlements "$ENTITLEMENTS_FILE" \
        "$DIST_FOLDER/Python" 2>/dev/null; then
        echo "   ✅ Success"
    else
        echo "   ❌ FAILED - This is critical!"
        exit 1
    fi
else
    echo "ℹ️  No Python executable found (normal for some builds)"
fi

# Sign main binary (LAST - this is the most important!)
echo ""
echo "🎯 Signing main binary: $BINARY_NAME"
if codesign --force --timestamp --options runtime \
    --sign "$SIGNING_IDENTITY" \
    --entitlements "$ENTITLEMENTS_FILE" \
    "$DIST_FOLDER/$BINARY_NAME"; then
    echo "   ✅ Success"
else
    echo "   ❌ FAILED!"
    exit 1
fi

# ============================================================
# STEP 2: VERIFY EVERYTHING WORKED
# ============================================================
echo ""
echo "================================================"
echo "STEP 2: Verifying signatures"
echo "================================================"

if codesign --verify --deep --strict "$DIST_FOLDER/$BINARY_NAME" 2>/dev/null; then
    echo "✅ All signatures are valid!"
else
    echo "❌ Signature verification failed!"
    exit 1
fi

# ============================================================
# STEP 3: CREATE ZIP FILE FOR NOTARIZATION
# ============================================================
echo ""
echo "================================================"
echo "STEP 3: Creating zip file"
echo "================================================"

# Remove old zip if it exists
if [ -f "$ARCHIVE_NAME" ]; then
    rm "$ARCHIVE_NAME"
fi

echo "📦 Creating $ARCHIVE_NAME..."
if ditto -c -k --keepParent "$DIST_FOLDER" "$ARCHIVE_NAME"; then
    FILE_SIZE=$(du -h "$ARCHIVE_NAME" | cut -f1)
    echo "   ✅ Created: $FILE_SIZE"
else
    echo "   ❌ Failed to create zip!"
    exit 1
fi

# ============================================================
# STEP 4: SEND TO APPLE FOR NOTARIZATION
# ============================================================
echo ""
echo "================================================"
echo "STEP 4: Sending to Apple for notarization"
echo "================================================"
echo "⏳ This will take 5-60 minutes..."
echo "   (You can close this and check status later)"
echo ""

if xcrun notarytool submit "$ARCHIVE_NAME" \
    --apple-id "$APPLE_ID" \
    --password "$APP_PASSWORD" \
    --team-id "$TEAM_ID" \
    --wait; then
    echo ""
    echo "✅ Notarization successful!"
else
    echo ""
    echo "❌ Notarization failed!"
    echo "   Run this to see why:"
    echo "   xcrun notarytool log <submission-id> --apple-id $APPLE_ID --password $APP_PASSWORD --team-id $TEAM_ID"
    exit 1
fi

# ============================================================
# STEP 5: ATTACH NOTARIZATION TO BINARY (Optional)
# ============================================================
echo ""
echo "================================================"
echo "STEP 5: Attaching notarization ticket"
echo "================================================"

if xcrun stapler staple "$DIST_FOLDER/$BINARY_NAME" 2>/dev/null; then
    echo "✅ Ticket attached successfully!"
else
    echo "⚠️  Stapling failed (this is normal for standalone binaries)"
    echo "   Your app will work fine, but needs internet on first run"
fi

# ============================================================
# ALL DONE!
# ============================================================
echo ""
echo "================================================"
echo "🎉 SUCCESS! Your app is ready to distribute"
echo "================================================"
echo ""
echo "✅ Signed: $DIST_FOLDER/$BINARY_NAME"
echo "✅ Notarized by Apple"
echo "✅ Ready to ship to users"
echo ""
echo "📦 Archive saved: $ARCHIVE_NAME"
echo ""

# Ask if they want to delete the zip
read -p "Delete the zip file? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm "$ARCHIVE_NAME"
    echo "✅ Deleted $ARCHIVE_NAME"
fi

echo ""
echo "You can now distribute: $DIST_FOLDER/$BINARY_NAME"
echo "Done!"