import sys

from app.agents.supervisor import build_graph
from app.agents.workflow_service import resolve_review, start_review


def run(job_id: int) -> None:
    graph = build_graph()
    payload = start_review(graph, job_id)

    print(f"\n=== {payload['company']} — {payload['title']} (ATS score: {payload['ats_score']}) ===\n")

    if payload["resume_valid"]:
        print("✓ Resume passed claim validation and PDF validation\n")
    else:
        print("⚠ RESUME FAILED VALIDATION — cannot be finalized even if you approve below")
        for v in payload["resume_claim_violations"]:
            print(f"  [claim] {v}")
        for v in payload["resume_pdf_violations"]:
            print(f"  [pdf]   {v}")
        print()

    print("--- Tailored Resume (preview) ---\n")
    print(payload["tailored_resume"])
    print(f"\n(Full PDF staged at: {payload['resume_pdf_path']})")
    print("\n--- Outreach Draft ---\n")
    print(payload["outreach_message"])

    answer = input("\nApprove this output? [y/N]: ").strip().lower()
    approved = answer == "y"
    feedback = ""
    if not approved:
        feedback = input("Optional feedback (why not / what to change): ").strip()

    result = resolve_review(graph, job_id, payload["thread_id"], approved, feedback)

    if not result["approved"]:
        print("\nNot approved — nothing saved.")
        if feedback:
            print(f"Feedback recorded: {feedback}")
        return

    if result["blocked"]:
        print(
            "\n⛔ BLOCKED: resume failed automated validation, so it cannot be saved as a "
            "final deliverable even though you approved it. The outreach draft is saved "
            "below, but the resume PDF is not — fix the underlying data (usually the "
            "candidate profile) and regenerate."
        )
        print(f"Saved: {result['saved_paths'][0]}")
        return

    print("\nSaved:")
    for path in result["saved_paths"]:
        print(f"  {path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m app.agents.run_workflow <job_id>")
        sys.exit(1)
    run(int(sys.argv[1]))
