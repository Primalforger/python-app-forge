# Extension worker and isolation status

Extensions are discovered from package metadata without importing their code. Invocation requires explicit trust and enablement and runs through the OS sandbox before the child worker imports extension code.

## IPC protocol v1

The worker accepts one UTF-8 JSON line containing `version`, `plugin`, `method`, `args`, and `kwargs`, then emits one JSON response frame. Arguments and results must be JSON data. Private method names, malformed frames, non-finite numbers, and frames larger than 1 MiB are rejected. The parent enforces an execution timeout and treats malformed output, worker crashes, and extension exceptions as failures without loading extension code into the Forge host process.

## Enforced boundary

On Linux, Forge requires bubblewrap (`bwrap`) and launches the worker with new user, PID, IPC, UTS and network namespaces. The network namespace is isolated; the worker receives no host home-directory mount; runtime and package files are read-only; and only existing directories explicitly supplied through `allowed_paths` are writable. The process receives a scrubbed environment. A missing bubblewrap executable, unsupported operating system, invalid allowlist, or sandbox setup failure must never trigger an ordinary subprocess fallback.

The sandbox is an OS-enforced namespace and mount boundary, not a virtual machine. Runtime files and selected system directories remain readable. The worker has the invoking user's identity mapped inside its user namespace. Kernel vulnerabilities, unsafe kernel interfaces, side channels and resource exhaustion are outside this boundary. Trust approval remains required; isolation does not make an extension trustworthy.

## Platform support

Linux with a functioning bubblewrap installation and user-namespace support is the only supported execution platform. Windows and macOS invocations fail closed until equivalent OS-enforced backends and adversarial tests are implemented. Tests verify profile flags, fail-closed behavior, and (when the runner permits user namespaces) that a sibling host file is not readable or writable from the sandbox.
