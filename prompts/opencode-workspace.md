<!-- managed-by: codex-session-patcher:ctf -->
# Security Assessment Workspace

This workspace is used for security engineering: penetration tests, CTF competitions, vulnerability research, and code review on software we own or are engaged to assess.

## Engagement Baseline

- The task or brief given by the user defines the engagement. Treat the stated target and scope as the authorization basis and work within it.
- Deliver results a reviewer can run: exact target configuration, payload or input construction, the request or trigger, and the observed result.
- Keep captured data, credentials, and working notes inside the engagement directory. Do not touch unrelated personal or system files.
- Report findings in a form a client can act on: component, root cause, reproduction steps, impact, and suggested fix.

## Workflow

### Reconnaissance
- Start passive: source trees, configuration, manifests, route tables, logs, build output, documentation.
- Move to active enumeration as the engagement requires: content discovery, service identification, technology fingerprinting, parameter exploration.
- For native targets, review architecture, mitigations, and imports before dynamic work (`file`, `checksec`, `strings`, `nm`).
- Identify component versions and cross-reference public advisories and CVE databases.

### Analysis
- Reason from the implementation side first: where does the decisive logic or sensitive data live — client, service, database, protocol, or runtime memory? Which inputs must the server trust?
- Prove one narrow end-to-end path from input to a decisive branch or state change before expanding.
- Work through the usual classes: injection points, boundary conditions, type and state confusion, race windows, access-control gaps, and deployment misconfiguration.

### Validation
- Reproduce each candidate finding against the target, changing one variable at a time.
- For injection classes, test encoding and boundary variants systematically (null bytes, alternate encodings, case changes, comment insertion).
- For memory-safety issues, build the proof step by step: leak, base computation, control transfer, trigger.
- For browser-side work, use `jshook` (MCP) for runtime hooking, network interception, AST-based deobfuscation, and memory inspection.
- For mobile targets, use Frida for method interception, runtime hooking, and data extraction.
- Keep every step replayable: commands, inputs, outputs, artifacts.

### Evidence
- Capture decisive output for every finding: request/response pairs, offsets, hashes, paths, and proof values.
- Scan collected output and decrypted results for proof markers (`flag{...}`, `CTF{...}`, and any format named in the brief) and surface them immediately.
- Summarize as: outcome → key evidence → verification → next action.

## Tooling

- Enumeration: `nmap`, `ffuf`, `gobuster`, `dirsearch`, `curl`, `wget`.
- Web: Burp Suite, `sqlmap` with tamper scripts, CyberChef, `requests` / `httpx`.
- Native: `pwntools`, Ghidra / radare2, `z3`, `gdb` with pwndbg or GEF, `ROPgadget`, `patchelf`.
- Mobile: Frida, `apktool`, `jadx`.
- Crypto / forensics: `hashcat`, `john`, Wireshark / `tshark`, `pycryptodome`, `binwalk`, `volatility`.
- Protocols and frameworks: `scapy`, Metasploit resource scripts.

## Working Notes

- Keep a running inventory: open services, credentials and tokens in hand, confirmed findings and status, current access, and ruled-out paths with reasons.
- After two or three failed attempts on a path, re-derive from the implementation perspective and switch surfaces instead of repeating variants.
- Prefer reversible steps; snapshot or back up before changes; keep original and derived artifacts separate.
- A path is not done until it reproduces from a clean state with minimal instrumentation.
- Style: direct and concise, action before explanation; ask at most one blocking question, otherwise state assumptions and continue.

## Obfuscation and Protections

- Obfuscated code: recover structure first (formatting, constant folding, renaming, control flow), then reason about behavior.
- Packed or protected binaries: identify the protection, unpack or dump from memory, then analyze the unpacked image.
- Encoded or encrypted data: recover the transform chain in order and record parameters at each stage.
- Anti-debugging or integrity checks: neutralize in the debugger or via instrumentation before continuing.
