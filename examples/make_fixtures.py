#!/usr/bin/env python3
"""Generate synthetic fixtures (COMPACT JSON: ccusage silently ignores non-compact lines).

All paths are fake (/home/alice/...), all content is PRIVATE-SAMPLE-TEXT, which must
never appear in any public export.  Usage: make_fixtures.py [OUTDIR]
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(HERE, "fixtures")

SID_A = "aaaaaaaa-1111-4111-8111-000000000001"
SID_B1 = "bbbbbbbb-1111-4111-8111-000000000001"
SID_B2 = "bbbbbbbb-2222-4222-8222-000000000002"
SID_C = "cccccccc-1111-4111-8111-000000000001"
SID_D = "dddddddd-1111-4111-8111-000000000001"
SID_F = "ffffffff-1111-4111-8111-000000000001"
SID_G = "99999999-1111-4111-8111-000000000001"
# Windows forbids < and > in file names, so there the hostile project dir uses & and ' instead.
HOSTILE_DIR = "-home-alice-a&b='x'" if os.name == "nt" else "-home-alice-<img src=x>"


def compact(o):
    return json.dumps(o, separators=(",", ":"))


def rec(sid, ts, mid, model, inp, out, cw=0, cr=0, cwd="/home/alice/secret-project",
        sidechain=False, cw1h=None):
    usage = {"input_tokens": inp, "output_tokens": out,
             "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr}
    if cw1h is not None:
        usage["cache_creation"] = {"ephemeral_5m_input_tokens": cw - cw1h,
                                   "ephemeral_1h_input_tokens": cw1h}
    d = {"type": "assistant", "timestamp": ts, "sessionId": sid, "cwd": cwd,
         "requestId": "req_" + mid, "uuid": "uuid-" + mid,
         "message": {"id": "msg_" + mid, "type": "message", "role": "assistant",
                     "model": model,
                     "content": [{"type": "text", "text": "PRIVATE-SAMPLE-TEXT"}],
                     "usage": usage}}
    if sidechain:
        d["isSidechain"] = True
    return d


def write_lines(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for ln in lines:
            f.write((ln if isinstance(ln, str) else compact(ln)) + "\n")


def build(out):
    if os.path.exists(out):
        shutil.rmtree(out)
    S, H = "claude-sonnet-5-5", "claude-haiku-5-5"

    # A: simple. dup pair has the LARGER output FIRST; the second record differs in
    # input and cache_read so we can see which one ccusage kept.
    p = os.path.join(out, "a_simple", "projects", "-home-alice-secret-project")
    write_lines(os.path.join(p, SID_A + ".jsonl"), [
        rec(SID_A, "2026-01-05T10:00:00.000Z", "a1", S, 100, 50, 1000, 2000),
        rec(SID_A, "2026-01-05T10:01:00.000Z", "a2", S, 10, 400, 0, 500),
        rec(SID_A, "2026-01-05T10:01:05.000Z", "a2", S, 12, 20, 0, 600),
        rec(SID_A, "2026-01-05T10:02:00.000Z", "a3", H, 1000, 200),
        rec(SID_A, "2026-01-05T10:03:00.000Z", "a4", "mystery-model-9", 300, 30),
        "{this line is malformed",
    ])

    # B: concurrent, interleaved timestamps, different projects
    pb = os.path.join(out, "b_concurrent", "projects")
    write_lines(os.path.join(pb, "-home-alice-proj-one", SID_B1 + ".jsonl"), [
        rec(SID_B1, "2026-01-05T09:00:00.000Z", "b1a", S, 100, 10, cwd="/home/alice/proj-one"),
        rec(SID_B1, "2026-01-05T09:20:00.000Z", "b1b", S, 200, 20, cwd="/home/alice/proj-one"),
    ])
    write_lines(os.path.join(pb, "-home-alice-proj-two", SID_B2 + ".jsonl"), [
        rec(SID_B2, "2026-01-05T09:10:00.000Z", "b2a", S, 1000, 100, cwd="/home/alice/proj-two"),
        rec(SID_B2, "2026-01-05T09:30:00.000Z", "b2b", S, 2000, 200, cwd="/home/alice/proj-two"),
    ])

    # C: subagent
    pc = os.path.join(out, "c_subagent", "projects", "-home-alice-secret-project")
    write_lines(os.path.join(pc, SID_C + ".jsonl"), [
        rec(SID_C, "2026-01-05T11:00:00.000Z", "c1", S, 100, 10, 0, 1000)])
    write_lines(os.path.join(pc, SID_C, "subagents", "agent-x.jsonl"), [
        rec(SID_C, "2026-01-05T11:00:30.000Z", "c2", H, 50, 5, 0, 400, sidechain=True)])

    # D: tz boundary
    pd = os.path.join(out, "d_tz_boundary", "projects", "-home-alice-secret-project")
    write_lines(os.path.join(pd, SID_D + ".jsonl"), [
        rec(SID_D, "2026-01-05T04:30:00.000Z", "d1", S, 100, 10),
        rec(SID_D, "2026-01-05T05:30:00.000Z", "d2", S, 200, 20)])

    # E: empty
    pe = os.path.join(out, "e_empty", "projects", "-home-alice-empty")
    os.makedirs(pe)
    open(os.path.join(pe, "empty.jsonl"), "w").close()

    # F: hostile
    pf = os.path.join(out, "f_hostile", "projects", HOSTILE_DIR)
    write_lines(os.path.join(pf, SID_F + ".jsonl"), [
        rec(SID_F, "2026-01-05T10:00:00.000Z", "f1", "<script>alert(1)</script>", 10, 5,
            cwd="/home/alice/<img src=x>")])

    # G: Codex home. Structure copied from event type / field NAMES of a real rollout only.
    pg = os.path.join(out, "g_codex", "codex_home", "sessions", "2026", "01", "05")
    cx = []
    cx.append({"timestamp": "2026-01-05T12:00:00.000Z", "type": "session_meta",
               "payload": {"id": SID_G, "timestamp": "2026-01-05T12:00:00.000Z",
                           "cwd": "/home/alice/secret-project", "originator": "codex_cli_rs",
                           "cli_version": "0.0.0", "source": "cli"}})
    cx.append({"timestamp": "2026-01-05T12:00:01.000Z", "type": "turn_context",
               "payload": {"cwd": "/home/alice/secret-project", "model": "gpt-5"}})
    def tc(ts, last, total):
        return {"timestamp": ts, "type": "event_msg",
                "payload": {"type": "token_count",
                            "info": {"total_token_usage": total, "last_token_usage": last,
                                     "model_context_window": 200000}}}
    u1 = {"input_tokens": 1000, "cached_input_tokens": 400, "output_tokens": 100,
          "reasoning_output_tokens": 30, "total_tokens": 1100}
    u2 = {"input_tokens": 2000, "cached_input_tokens": 1500, "output_tokens": 300,
          "reasoning_output_tokens": 100, "total_tokens": 2300}
    tot = {k: u1[k] + u2[k] for k in u1}
    cx.append(tc("2026-01-05T12:00:05.000Z", u1, u1))
    cx.append(tc("2026-01-05T12:00:10.000Z", u2, tot))
    write_lines(os.path.join(pg, "rollout-2026-01-05T12-00-00-" + SID_G + ".jsonl"), cx)


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT)
    print("fixtures written")
