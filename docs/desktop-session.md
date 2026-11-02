# Desktop session continuity

The optional PySide6 desktop shell uses the framework-independent stores in
`app_forge.session` for local continuity. No project source, credentials, or
service configuration is copied into the GUI session file.

## Restored state

On startup the GUI restores:
- the last selected primary screen;
- the light/dark theme;
- the window geometry and maximized state.

The session is saved on a normal close after any active background operation
has completed. It is versioned JSON, written by atomic replacement, and
bounded by the store's size limit. Invalid or unsupported state is ignored and
recorded as a local diagnostic rather than preventing the application from
opening.

## Recent projects

The **Recent Projects** menu lists up to ten existing project directories used
for analysis, planning, verification, or compliance reporting. Selecting one
populates both the Integration Workbench and Quality and Compliance project
fields. Missing directories are omitted from the menu; the underlying history
is retained until it is explicitly cleared.

Recent-project history is also local versioned JSON and contains paths only.
It does not store project contents or secrets.

## Verification

The real-Qt suite verifies state save/restore, theme and screen restoration,
recent-project selection, and clearing history. Run:

```bash
pip install -e ".[gui]"
python scripts/verify_gui.py
```
