# Project Dashboard

Standalone LAN dashboard for Dee's local projects.

## Files

- `index.html` - dashboard shell.
- `assets/styles.css` - dashboard styling.
- `assets/app.js` - browser-side rendering and filters.
- `assets/project-mark.svg` - local visual mark.
- `data/projects.json` - current project snapshot.

## Source

The data snapshot was built from `/srv/cloud-mirror/workspaces` handoff/status files and the existing Prepper Disk site state.

Serve from this folder with:

```bash
python3 -m http.server 8090 --bind 0.0.0.0
```
