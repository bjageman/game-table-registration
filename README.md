# Game table registration

The initial preview is a plain static page with inactive Register and Login buttons. Open `index.html` directly, or serve it with `python3 -m http.server 5180 --bind 0.0.0.0` and visit `http://your-server:5180`.

The separate frontend PR adds the React application under `frontend/`; use that application for continued development after it merges. The separate backend PR adds the Python API. Setup instructions live in `docs/frontend.md` and `docs/backend.md` in their respective PRs.

See the [development plan](docs/development-plan.md) and [issues](https://github.com/bjageman/game-table-registration/issues). Feature branches and PRs target `dev`; the owner performs all merges. Agents never merge or enable auto-merge.
