# Deployment artifact generators (C-40)

The app_forge.deployment module renders deployment files only. It never builds
images, installs services, modifies the host, or performs network operations.
Review generated files and adapt users, paths, secrets and writable directories
before deployment.

    from pathlib import Path
    from app_forge.deployment import DeploymentConfig, render_deployment_files

    config = DeploymentConfig(
        package="my_app", module="my_app.service", service_name="my-app",
        python_version="3.12", port=8080,
    )
    for relative_path, content in render_deployment_files(config).items():
        target = Path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

The Dockerfile uses an official slim Python image, installs the project and runs
as an unprivileged user. The systemd unit includes restart behavior and baseline
sandboxing; it assumes an app account and a writable /var/lib/<service-name>
directory provisioned by an operator. Do not put secrets in generated files.

Windows output includes a pywin32 service host and elevated PowerShell install
and removal scripts. pywin32 is an optional deployment-time dependency. The
host supervises the configured process and requests graceful termination before
force-killing it after the configured timeout.

Commands are represented as argument vectors, not shell command strings.
These are starter artifacts, not a complete production policy: operators must
configure least-privilege identities, filesystem ACLs, secret delivery, logging,
monitoring, firewall rules, image pinning and platform-specific testing.
