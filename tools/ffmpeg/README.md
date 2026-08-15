# Bundled FFmpeg tools

DDREC resolves ffmpeg.exe and ffprobe.exe from this directory before
checking the system PATH. Both executables must come from the same trusted
Windows build and the FFmpeg build must include the libx264 encoder.

The executables are runtime dependencies of the Windows client. PyInstaller
copies them to tools/ffmpeg in the onedir build, and the Inno Setup project
verifies that both files are present before creating an installer.

Keep the matching upstream license files alongside the binaries when updating
the bundled build.
