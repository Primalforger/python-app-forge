"""Minimal Forge plugin example."""

class Plugin:
    def activate(self):
        """Return a JSON-safe readiness status for the example plugin."""
        return {"status": "ready", "plugin": "{{package}}"}

    def ping(self, message="hello"):
        return {"message": message}

def main():
    return 0
