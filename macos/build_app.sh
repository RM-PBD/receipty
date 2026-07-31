#!/bin/zsh

set -euo pipefail

readonly project_directory="${0:A:h:h}"
readonly source_directory="${project_directory}/macos"
readonly app_bundle="${project_directory}/Receipty.app"
readonly icon_source="${source_directory}/ReceiptyIcon.png"
readonly python_executable="${RECEIPTY_PYTHON:-${project_directory}/venv/bin/python}"

if [[ ! -f "$icon_source" ]]; then
    print -u2 "Missing icon source: $icon_source"
    exit 1
fi

if [[ ! -x "$python_executable" ]]; then
    print -u2 "Missing Python environment: $python_executable"
    exit 1
fi

/bin/rm -rf "$app_bundle"
/bin/mkdir -p \
    "$app_bundle/Contents/MacOS" \
    "$app_bundle/Contents/Resources"

"$python_executable" "$source_directory/build_icon.py" \
    "$icon_source" "$app_bundle/Contents/Resources/Receipty.icns"
/bin/cp "$source_directory/Info.plist" "$app_bundle/Contents/Info.plist"
/bin/cp "$source_directory/ReceiptyLauncher" "$app_bundle/Contents/MacOS/Receipty"
/bin/chmod +x "$app_bundle/Contents/MacOS/Receipty"
/usr/bin/codesign --force --deep --sign - "$app_bundle"

print "Built $app_bundle"
