# Architecture Decision Records

Forge can render and create numbered Architecture Decision Records (ADRs)
without runtime dependencies.

    from app_forge.adr import ArchitectureDecision, create_adr, render_adr

    record = ArchitectureDecision(
        title="Use SQLite for local state",
        context="The application needs durable local state.",
        decision="Use SQLite with transactions.",
        consequences="Simple deployment; concurrency is bounded by SQLite.",
        status="proposed",
        decision_makers=("Platform team",),
    )
    markdown = render_adr(record)
    path = create_adr("docs/adr", record)

render_adr returns Markdown with status, date, optional decision participants,
and Context, Decision, and Consequences sections. create_adr chooses the next
four-digit sequence and writes a number-title-slug Markdown file. It creates
files exclusively and never overwrites an existing ADR. The target directory
cannot be a symlink.

Statuses are proposed, accepted, rejected, deprecated, and superseded. Titles
and required sections are bounded and validated; dates use YYYY-MM-DD. The
generator creates records only: teams remain responsible for review, approval,
and maintaining the decision history.
