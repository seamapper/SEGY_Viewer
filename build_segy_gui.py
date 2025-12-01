#!/usr/bin/env python3
"""
Build script for SEGY GUI Viewer executable
"""

import os
import sys
import subprocess
import shutil
import re
from pathlib import Path

def get_version_from_code():
    """Extract version from segy_gui.py"""
    try:
        with open('segy_gui.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Look for __version__ = "version_string"
        match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
        if match:
            return match.group(1)
        else:
            return "unknown"
    except Exception as e:
        print(f"Warning: Could not extract version: {e}")
        return "unknown"

def update_spec_file(exe_name):
    """Update the spec file with the new executable name"""
    try:
        with open('segy_gui.spec', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Replace the name in the EXE section
        content = re.sub(r"name='[^']*'", f"name='{exe_name}'", content)
        
        with open('segy_gui.spec', 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"✓ Updated spec file with name: {exe_name}")
    except Exception as e:
        print(f"Warning: Could not update spec file: {e}")

def build_segy_gui():
    """Build the SEGY GUI executable using PyInstaller"""
    
    # Get version from code
    version = get_version_from_code()
    exe_name = f"CCOM_SEGY_Viewer_v{version}"
    
    print("Building SEGY GUI Viewer executable...")
    print("=" * 50)
    print(f"Version: {version}")
    print(f"Executable name: {exe_name}.exe")
    print("=" * 50)
    
    # Check if we're in the right directory
    if not os.path.exists('segy_gui.py'):
        print("Error: segy_gui.py not found. Please run this script from the SEGY directory.")
        return False
    
    # Check if spec file exists
    if not os.path.exists('segy_gui.spec'):
        print("Error: segy_gui.spec not found.")
        return False
    
    # Convert PNG to ICO if needed
    if not os.path.exists('CCOM.ico'):
        print("Converting CCOM.png to CCOM.ico...")
        try:
            from convert_icon import convert_png_to_ico
            if not convert_png_to_ico():
                print("Warning: Failed to convert icon. Building without custom icon.")
        except Exception as e:
            print(f"Warning: Could not convert icon: {e}. Building without custom icon.")
    else:
        print("✓ Icon file CCOM.ico found")
    
    try:
        # Clean previous builds
        print("Cleaning previous builds...")
        if os.path.exists('build'):
            shutil.rmtree('build')
        if os.path.exists('dist'):
            shutil.rmtree('dist')
        
        # Update spec file with version
        update_spec_file(exe_name)
        
        # Run PyInstaller
        print("Running PyInstaller...")
        cmd = [sys.executable, '-m', 'PyInstaller', '--clean', 'segy_gui.spec']
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✓ Build successful!")
            print(f"\nExecutable created in: dist/{exe_name}.exe")
            
            # Check if executable was created
            exe_path = Path(f'dist/{exe_name}.exe')
            if exe_path.exists():
                size_mb = exe_path.stat().st_size / (1024 * 1024)
                print(f"✓ Executable size: {size_mb:.1f} MB")
                print(f"✓ Location: {exe_path.absolute()}")
            else:
                print("Warning: Executable not found in expected location")
            
            return True
        else:
            print("✗ Build failed!")
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)
            return False
            
    except Exception as e:
        print(f"✗ Build error: {e}")
        return False

def main():
    """Main function"""
    print("SEGY GUI Viewer - Build Script")
    print("=" * 50)
    
    # Check if PyInstaller is installed
    try:
        import PyInstaller
        print(f"✓ PyInstaller version: {PyInstaller.__version__}")
    except ImportError:
        print("✗ PyInstaller not found. Installing...")
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'pyinstaller'])
        print("✓ PyInstaller installed")
    
    # Build the executable
    success = build_segy_gui()
    
    if success:
        version = get_version_from_code()
        exe_name = f"CCOM_SEGY_Viewer_v{version}"
        print("\n" + "=" * 50)
        print("BUILD COMPLETED SUCCESSFULLY!")
        print(f"You can now run: dist/{exe_name}.exe")
        print("=" * 50)
    else:
        print("\n" + "=" * 50)
        print("BUILD FAILED!")
        print("Check the error messages above for details.")
        print("=" * 50)
        sys.exit(1)

if __name__ == "__main__":
    main()
