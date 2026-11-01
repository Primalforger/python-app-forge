# Framework-aware component integration

Level 2/3 projects can use a framework registration patch instead of requiring a Forge-owned anchor marker. A component declares the target file and a registration contract:

```toml
[[integration.patches]]
id = "register-health"
file = "src/{{package}}/main.py"
kind = "framework-register"

[integration.patches.registration]
framework = "fastapi"
module = "{{package}}.health"
symbol = "router"
application = "app"
```

Supported adapters:

- **FastAPI** imports the declared router and calls app.include_router(router).
- **Flask** imports the declared blueprint and calls app.register_blueprint(blueprint).
- **Django** extends the top-level urlpatterns with a path()/include() entry. route is an optional URL prefix.

The adapter parses Python with ast; it never imports or executes project code. It requires a single unambiguous top-level application declaration (FastAPI() or Flask()) or one urlpatterns assignment. An application field selects the named FastAPI/Flask instance. Ambiguous or unsupported layouts become plan conflicts; they are never guessed. Use an ordinary insert patch with an explicit Forge anchor when a project uses a factory, app registry, custom router lifecycle, or otherwise non-conventional structure.

The registration is written as a Forge-managed block. It participates in plan preview, approval, digest checking, upgrade replacement, and safe removal/recovery exactly like other insert patches.
