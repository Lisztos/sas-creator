#!/bin/bash
set -e

# Start virtual display
Xvfb :99 -screen 0 "${SCREEN_WIDTH:-1280}x${SCREEN_HEIGHT:-900}x${SCREEN_DEPTH:-24}" -ac &
sleep 1

# Start lightweight window manager
fluxbox &
sleep 1

# Start VNC server
VNC_ARGS="-display :99 -forever -shared -rfbport ${VNC_PORT:-5900}"
if [ -n "$VNC_PASSWORD" ]; then
    mkdir -p /tmp/vnc
    x11vnc -storepasswd "$VNC_PASSWORD" /tmp/vnc/passwd
    VNC_ARGS="$VNC_ARGS -rfbauth /tmp/vnc/passwd"
else
    VNC_ARGS="$VNC_ARGS -nopw"
fi
x11vnc $VNC_ARGS &
sleep 1

# Start noVNC web client
/opt/novnc/utils/novnc_proxy --vnc localhost:${VNC_PORT:-5900} --listen ${NOVNC_PORT:-6080} &
sleep 1

echo ">>> noVNC ready at http://localhost:${NOVNC_PORT:-6080}/vnc.html"

# Run the app as PID 1 (receives SIGTERM from docker stop)
exec python -m sas_creator
