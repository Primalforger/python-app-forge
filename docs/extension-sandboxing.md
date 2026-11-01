# Extension sandboxing

Extension discovery and invocation are separate operations. Discovery reads package metadata only; invocation requires explicit trust and enablement.

## Linux enforcement

On Linux, Forge starts the worker through bubblewrap (`bwrap`) with:

- new user, PID, IPC, UTS and network namespaces (`--unshare-all` and `--unshare-net`);
- no host home-directory mount;
- read-only mounts for the Python runtime, Forge package and system runtime directories;
- a private temporary directory; and
- writable mounts only for directories explicitly passed as `allowed_paths` to `ExtensionHost.invoke`.

The extension worker communicates through a bounded, versioned JSON message on standard input/output. Worker stderr is captured separately. The worker has the invoking user's identity inside its user namespace; bubblewrap is not a defense against kernel vulnerabilities or a hostile host kernel.

Example:

```python
host.invoke(
    "acme-extension",
    "generate",
    {"name": "example"},
    allowed_paths=(project_workspace,),
)
```

Only pass directories the extension genuinely needs to modify. Each allowlist entry must be an existing directory. Do not grant the filesystem root or the user's home directory.

## Fail-closed behavior and limitations

If Linux or bubblewrap is unavailable, invocation raises a security error. Forge does not fall back to an ordinary subprocess. Windows and macOS execution are therefore unavailable until an equivalent OS-enforced backend is implemented and tested for those platforms.

This is an OS-enforced namespace and mount boundary, not a complete virtual machine. The Python runtime, Forge code, installed Python packages and selected system runtime directories are readable inside the sandbox. Extensions execute with the caller's UID/GID mapped inside the user namespace. Kernel vulnerabilities, unsafe kernel interfaces, side channels and resource exhaustion are not fully addressed. Do not run hostile code on a machine containing sensitive data; use a disposable VM for that threat model.

The sandbox does not make an untrusted extension trustworthy. Trust approval remains an explicit prerequisite, and the IPC contract accepts JSON data only.
