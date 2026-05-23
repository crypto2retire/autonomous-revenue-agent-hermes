#!/bin/sh
# Ensure data directory exists for persistent volume
mkdir -p /data
chmod 777 /data
ls -la /data

# Run the agent
exec python -c "import asyncio; from main import main; asyncio.run(main())"
