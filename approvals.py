"""Human-approval workflow for sensitive actions (Layer 2).

send_email and approve_payment are NOT available to the document agent in defended mode. A person
runs them here, sees exactly what will happen, and must type APPROVE. Even then the tools only log
the simulated call to output/trap_calls.json; nothing is sent or paid.

Usage:
  python approvals.py send_email --to orders@bluehen-apparel.example --subject "PO 2640" --body "..."
  python approvals.py approve_payment --vendor "Blue Hen Apparel" --amount 1200 --memo "BHA-26-1187 deposit"
"""

from __future__ import annotations

import argparse
import json

from tools import append_json, approve_payment, init_trap_log, send_email, ROOT

APPROVAL_LOG = ROOT / "output" / "approval_log.json"
ACTIONS = {"send_email": send_email, "approve_payment": approve_payment}


def request_action(action: str, args: dict, approver_input=input) -> str:
    """Show the action to a human and run it only if they type APPROVE."""
    if action not in ACTIONS:
        raise ValueError(f"Unknown action: {action}")
    init_trap_log()
    print(f"\nAction requested: {action}")
    print(json.dumps(args, indent=2))
    try:
        answer = approver_input("Type APPROVE to run this simulated action (anything else cancels): ").strip()
    except EOFError:
        answer = ""  # no human at the keyboard, so refuse
    approved = answer == "APPROVE"
    append_json(APPROVAL_LOG, {"action": action, "args": args, "approved": approved})
    if not approved:
        print("Cancelled. Nothing was logged as executed.")
        return "cancelled"
    result = ACTIONS[action](**args)
    print(f"Simulated only: {result} (logged to output/trap_calls.json, nothing was sent or paid)")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Run a sensitive action after human approval (simulation only)")
    sub = ap.add_subparsers(dest="action", required=True)
    e = sub.add_parser("send_email")
    e.add_argument("--to", required=True)
    e.add_argument("--subject", required=True)
    e.add_argument("--body", required=True)
    p = sub.add_parser("approve_payment")
    p.add_argument("--vendor", required=True)
    p.add_argument("--amount", type=float, required=True)
    p.add_argument("--memo", required=True)
    a = vars(ap.parse_args())
    request_action(a.pop("action"), a)


if __name__ == "__main__":
    main()
