// Starts session_end.py with the first of python3, python and `py -3` that is Python 3.10 or later.
// hooks.json runs this file with node in exec form, with no shell, so the hook works the same
// whether Claude Code would use sh, Git Bash or PowerShell. The event JSON on stdin passes through.
"use strict";
const { spawn, spawnSync } = require("child_process");
const path = require("path");

const HOOK = path.join(__dirname, "session_end.py");
const PROBE = ["-c", "import sys; sys.exit(sys.version_info < (3, 10))"];
const CANDIDATES = [["python3"], ["python"], ["py", "-3"]];

function main() {
  for (const [exe, ...pre] of CANDIDATES) {
    // Missing, a stub such as the WindowsApps one, or too old: try the next one.
    const probe = spawnSync(exe, pre.concat(PROBE), { stdio: "ignore", windowsHide: true, timeout: 3000 });
    if (probe.status !== 0) continue;
    const child = spawn(exe, pre.concat([HOOK]), { stdio: "inherit", windowsHide: true });
    child.on("error", () => process.exit(1));
    child.on("exit", (code) => process.exit(code === null ? 1 : code));
    return;
  }
  process.stderr.write("session-receipt: no Python 3.10 or later found (tried python3, python, py -3)\n");
  process.exit(1);
}

main();
