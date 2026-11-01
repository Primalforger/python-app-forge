# Extension worker and isolation status

Extensions are discovered from package metadata without importing their code. Invocation is gated by the existing trust and enablement policy and runs in a child Python process using `app_forge.extension_worker`.

## IPC protocol v1

The worker accepts one UTF-8 JSON line containing `version`, `plugin`, `method`, `args`, and `kwargs`, then emits one JSON response frame. Arguments and results must be JSON data. Private method names, malformed frames, non-finite numbers, and frames larger than 1 MiB are rejected. The parent enforces an execution timeout and treats malformed output, worker crashes, and extension exceptions as failures without loading extension code into the Forge host process.

## Security boundary

This release provides **process separation only**, not a sandbox. A child process runs with the operating-system identity and permissions of its parent. It may be able to read or modify files available to that user and may access the network. The scrubbed environment reduces accidental secret inheritance; it does not constrain filesystem or network access. Only explicitly trusted and enabled extensions may be invoked. Untrusted extensions remain disabled and are refused.

Do not describe this worker as filesystem-isolated, network-isolated, or safe for hostile extension code. OS-enforced sandbox backends, platform capability detection, minimal filesystem views, network denial, and adversarial tests remain required before untrusted extension execution can be enabled.
