#!/bin/zsh
set -u

project_dir="/Users/doc9/clawd/projects/noga-contact-card"
tunnel_log="$project_dir/tunnel.log"
backend_file="$project_dir/backend-url.json"

: > "$tunnel_log"
/opt/homebrew/bin/cloudflared tunnel --url http://127.0.0.1:8787 --no-autoupdate >> "$tunnel_log" 2>&1 &
tunnel_pid=$!

tunnel_url=""
for attempt in {1..45}; do
  tunnel_url=$(/usr/bin/sed -nE 's#.*(https://[a-z0-9-]+\.trycloudflare\.com).*#\1#p' "$tunnel_log" | /usr/bin/head -1)
  [[ -n "$tunnel_url" ]] && break
  /bin/sleep 1
done

if [[ -n "$tunnel_url" ]]; then
  /usr/bin/printf '{"url":"%s"}\n' "$tunnel_url" > "$backend_file"
  cd "$project_dir"
  /usr/bin/git add backend-url.json
  if ! /usr/bin/git diff --cached --quiet; then
    /usr/bin/git commit -m "Update live form endpoint"
    /usr/bin/git push
  fi
fi

wait "$tunnel_pid"
