"""Minimal Forge plugin example."""

class Plugin:
    def ping(self, message="hello"):
        return {"message": message}

def main():
    return 0
