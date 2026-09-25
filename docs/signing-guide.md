# macOS Code Signing & Notarization Guide

This guide explains how to sign and notarize your Omni Backend application for distribution on macOS.

## Prerequisites

1. **Apple Developer Account** (Required)
   - Enroll at [developer.apple.com](https://developer.apple.com/)
   - Cost: $99/year

2. **Developer ID Application Certificate** (Required)
   - Download from Apple Developer portal
   - Install in your Keychain

3. **App-Specific Password** (Required)
   - Generate at [appleid.apple.com](https://appleid.apple.com/account/manage)
   - Navigate to: Sign-In and Security > App-Specific Passwords

## Step 1: Get Your Signing Identity

Find your signing identity by running:

```bash
security find-identity -v -p codesigning
```

Look for a line like:
```
1) ABC123XYZ "Developer ID Application: Your Name (TEAM123)"
```

Copy the entire string in quotes (including "Developer ID Application:").

## Step 2: Get Your Team ID

1. Visit [developer.apple.com/account](https://developer.apple.com/account/)
2. Click on "Membership" in the sidebar
3. Your Team ID is listed there (10-character alphanumeric code)

## Step 3: Generate App-Specific Password

1. Go to [appleid.apple.com](https://appleid.apple.com/)
2. Sign in with your Apple ID
3. Navigate to: **Sign-In and Security** > **App-Specific Passwords**
4. Click the **+** button to generate a new password
5. Give it a label like "DAXAGENT Notarization"
6. Copy the generated password (format: xxxx-xxxx-xxxx-xxxx)

## Step 4: Configure Environment Variables

Create or update your `.env` file in the project root with the following variables:

```bash
# macOS Code Signing & Notarization
SIGNING_IDENTITY="Developer ID Application: Your Name (TEAM123)"
ENTITLEMENTS_FILE="scripts/build_scripts/entitlements.plist"
BUNDLE_ID="com.yourcompany.ravian"
APPLE_ID="your.email@example.com"
TEAM_ID="YOUR_TEAM_ID"
APP_PASSWORD="xxxx-xxxx-xxxx-xxxx"
```

### Variable Descriptions:

- **SIGNING_IDENTITY**: Your Developer ID Application certificate name (from Step 1)
- **ENTITLEMENTS_FILE**: Path to entitlements file (default is fine)
- **BUNDLE_ID**: Your app's unique identifier in reverse domain format
- **APPLE_ID**: Your Apple ID email address
- **TEAM_ID**: Your Apple Developer Team ID (from Step 2)
- **APP_PASSWORD**: App-specific password (from Step 3)

## Step 5: Build Your Application

Before signing, you need to build the application:

```bash
# From project root
python scripts/build.py

# Or use optimized build
python scripts/build_scripts/nuitka_optimized.py
```

This creates a `main.dist` directory with your application.

## Step 6: Sign and Notarize

Run the signing script:

```bash
cd scripts/build_scripts
./sign_main_dist.sh
```

The script will:
1. ✅ Load configuration from `.env`
2. ✅ Validate all required variables
3. ✅ Sign all components (.so files, .dylib files, frameworks, executables)
4. ✅ Sign the main binary
5. ✅ Verify all signatures
6. ✅ Create a ZIP archive
7. ✅ Submit to Apple for notarization (5-60 minutes)
8. ✅ Attach notarization ticket (stapling)

## Entitlements File

The [entitlements.plist](../scripts/build_scripts/entitlements.plist) file defines permissions for your app:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <!-- Allow JIT compilation for Python -->
    <key>com.apple.security.cs.allow-jit</key>
    <true/>

    <!-- Allow unsigned executable memory -->
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <true/>

    <!-- Disable library validation -->
    <key>com.apple.security.cs.disable-library-validation</key>
    <true/>
</dict>
</plist>
```

These entitlements are required for Python applications with JIT compilation.

## Troubleshooting

### "No identity found" Error

**Problem**: Can't find your signing identity

**Solution**:
1. Make sure you've installed your Developer ID certificate in Keychain
2. Run `security find-identity -v -p codesigning` to verify
3. If missing, download from [developer.apple.com/account/resources/certificates](https://developer.apple.com/account/resources/certificates)

### "Invalid Password" Error

**Problem**: App-specific password is rejected

**Solution**:
1. Verify you're using an app-specific password, not your Apple ID password
2. Generate a new app-specific password at [appleid.apple.com](https://appleid.apple.com/)
3. Make sure there are no extra spaces in your `.env` file

### "Stapling Failed" Error

**Problem**: Can't attach notarization ticket

**Solution**: This is normal for standalone binaries. Your app will still work but requires internet connection on first launch.

### Notarization Failed

**Problem**: Apple rejected your submission

**Solution**: Check the notarization log:
```bash
xcrun notarytool log <submission-id> \
    --apple-id your.email@example.com \
    --password xxxx-xxxx-xxxx-xxxx \
    --team-id TEAM123
```

Common issues:
- **Missing entitlements**: Add required entitlements to `entitlements.plist`
- **Unsigned components**: Make sure all `.dylib` and `.so` files are signed
- **Incorrect bundle ID**: Verify `BUNDLE_ID` format (reverse domain notation)

## Verification

After signing, verify the signature:

```bash
# Verify deep signature
codesign --verify --deep --strict main.dist/daxagent

# Display signature info
codesign -dv --verbose=4 main.dist/daxagent

# Check if notarized
spctl -a -vv main.dist/daxagent
```

## Distribution

After successful signing and notarization:

1. **Distribute the signed binary**: `main.dist/daxagent`
2. **Include the .dist folder**: Users need all the files in `main.dist/`
3. **Provide .env template**: Don't include your actual `.env` with secrets
4. **Include README**: Instructions for running the app

### Creating a Distribution Archive

```bash
# Create a ZIP for distribution
ditto -c -k --keepParent main.dist main.dist-notarized.zip
```

## Security Best Practices

1. **Never commit .env to git**: Add `.env` to `.gitignore`
2. **Use .env.example**: Provide a template without real credentials
3. **Rotate app-specific passwords**: Periodically generate new passwords
4. **Limit entitlements**: Only request permissions your app needs
5. **Test on clean Mac**: Verify your app runs on a machine without development tools

## Automatic Signing in CI/CD

For GitHub Actions or other CI/CD:

1. Store signing credentials as repository secrets
2. Import certificate from base64-encoded string
3. Use keychain password in the workflow
4. Clean up keychain after signing

Example GitHub Actions snippet:

```yaml
- name: Import Certificate
  env:
    CERTIFICATE_BASE64: ${{ secrets.CERTIFICATE_BASE64 }}
    CERTIFICATE_PASSWORD: ${{ secrets.CERTIFICATE_PASSWORD }}
  run: |
    echo $CERTIFICATE_BASE64 | base64 --decode > certificate.p12
    security create-keychain -p actions temp.keychain
    security import certificate.p12 -k temp.keychain -P $CERTIFICATE_PASSWORD
    security set-key-partition-list -S apple-tool:,apple: -s -k actions temp.keychain

- name: Sign and Notarize
  env:
    SIGNING_IDENTITY: ${{ secrets.SIGNING_IDENTITY }}
    APPLE_ID: ${{ secrets.APPLE_ID }}
    TEAM_ID: ${{ secrets.TEAM_ID }}
    APP_PASSWORD: ${{ secrets.APP_PASSWORD }}
  run: |
    ./scripts/build_scripts/sign_main_dist.sh
```

## Cost Summary

- **Apple Developer Program**: $99/year
- **Notarization**: Free (included in Developer Program)
- **Code Signing**: Free (included in Developer Program)

## Additional Resources

- [Apple Code Signing Guide](https://developer.apple.com/documentation/security/notarizing_macos_software_before_distribution)
- [Notarization Documentation](https://developer.apple.com/documentation/security/notarizing_macos_software_before_distribution)
- [Hardened Runtime](https://developer.apple.com/documentation/security/hardened_runtime)
- [Entitlements Reference](https://developer.apple.com/documentation/bundleresources/entitlements)

## Support

If you encounter issues:

1. Check the [Troubleshooting](#troubleshooting) section
2. Review Apple's notarization logs
3. Verify all environment variables are set correctly
4. Ensure you have the latest Xcode command-line tools: `xcode-select --install`
