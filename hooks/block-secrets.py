"""
PreToolUse hook: Block access to sensitive files and environment variables.

Intercepts Read, Bash, Grep, Edit, and Write tool calls to prevent API keys,
tokens, and credentials from entering the LLM context window.

Exit codes:
  0 = allow (tool proceeds normally)
  2 = block (stderr shown to Claude as feedback)
"""

import json
import re
import sys

# --- Sensitive file patterns ---
# Any file path matching these patterns should never be read or written by the LLM
SENSITIVE_FILE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\.env($|\.)", re.IGNORECASE),           # .env, .env.local, .env.production
    re.compile(r"\.pem$", re.IGNORECASE),                 # SSL/TLS certificates
    re.compile(r"\.key$", re.IGNORECASE),                 # Private keys
    re.compile(r"google_credentials\.json", re.IGNORECASE),  # OAuth client secret
    re.compile(r"google_token\w*\.json", re.IGNORECASE),  # OAuth refresh token (incl. per-profile files)
    re.compile(r"\.pending_oauth_", re.IGNORECASE),        # PKCE verifier parked between reconnect_google.py steps
    re.compile(r"credentials\.json", re.IGNORECASE),      # Generic credentials
    re.compile(r"\.credentials\.json", re.IGNORECASE),    # Claude credentials
    re.compile(r"master\.env", re.IGNORECASE),            # Master env file
    re.compile(r"\.ssh/", re.IGNORECASE),                 # SSH keys directory
    re.compile(r"id_rsa", re.IGNORECASE),                 # SSH private key
    re.compile(r"id_ed25519", re.IGNORECASE),             # SSH private key (ed25519)
    re.compile(r"\.aws/credentials", re.IGNORECASE),      # AWS credentials
    re.compile(r"\.netrc", re.IGNORECASE),                # Network credentials
    re.compile(r"secret", re.IGNORECASE),                 # Files with "secret" in the name
]

# Exclude false positives for "secret" pattern - these are safe to read
SECRET_FALSE_POSITIVES: list[re.Pattern[str]] = [
    re.compile(r"\.md$", re.IGNORECASE),          # Markdown docs discussing secrets
    re.compile(r"\.py$", re.IGNORECASE),           # Python code (may reference but not contain)
    re.compile(r"\.ts$", re.IGNORECASE),           # TypeScript code
    re.compile(r"\.js$", re.IGNORECASE),           # JavaScript code
    re.compile(r"\.txt$", re.IGNORECASE),          # Text files
    re.compile(r"\.yml$", re.IGNORECASE),          # YAML config
    re.compile(r"\.yaml$", re.IGNORECASE),         # YAML config
    re.compile(r"\.toml$", re.IGNORECASE),         # TOML config
    re.compile(r"\.example$", re.IGNORECASE),      # Example files (.env.example)
]


def is_sensitive_file(path: str) -> str | None:
    """Check if a file path matches a sensitive pattern. Returns the reason or None."""
    for pattern in SENSITIVE_FILE_PATTERNS:
        if pattern.search(path):
            # Special handling for "secret" - allow code/docs that discuss secrets
            if pattern.pattern == "secret":
                for fp in SECRET_FALSE_POSITIVES:
                    if fp.search(path):
                        return None
                # Also allow .env.example files
                if ".example" in path.lower():
                    return None
            # Allow .env.example explicitly
            if ".env.example" in path.lower() or ".env.sample" in path.lower():
                return None
            return f"Blocked: '{path}' matches sensitive file pattern '{pattern.pattern}'"
    return None


# --- Dangerous bash patterns for env/secret exposure ---
#
# Matched per simple command (split on ; && || | and newlines, here-doc bodies
# removed) rather than against the whole normalized command string. Before
# 2026-09-13 every `.*` could span pipes, heredoc bodies, and quoted Python
# source, so a heredoc that merely *mentioned* "credentials" in a docstring
# blocked, and `echo "== $q"` blocked because "oauth" appeared 300 chars later.
#
# `_ARG` = "somewhere in this command's argument list". Keeps the rule attached
# to the command's own arguments instead of anything that follows.
_ARG = r"(?:\s+\S+)*?\s+\S*"
# A shell variable whose *name* looks like a secret ($API_KEY, ${TOKEN}, $OAUTH_X).
_SECRET_VAR = r"\$\{?[A-Za-z_]*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)[A-Za-z0-9_]*"

DANGEROUS_BASH_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Direct env-file reads / opens
    (re.compile(r"\b(?:cat|head|tail|less|more|type|bat)\b" + _ARG + r"\.env\b", re.IGNORECASE),
     "Reading env file"),
    (re.compile(r"\b(?:vi|vim|nano|code)\b" + _ARG + r"\.env\b", re.IGNORECASE),
     "Opening env file in editor"),
    (re.compile(r"\bsource\s+\S*\.env\b", re.IGNORECASE), "Sourcing env file"),
    (re.compile(r"^\.\s+\S*\.env\b", re.IGNORECASE), "Sourcing env file with dot notation"),

    # Credential file reads
    (re.compile(r"\bcat\b" + _ARG + r"credentials", re.IGNORECASE), "Reading credentials file"),
    (re.compile(r"\bcat\b" + _ARG + r"google_token", re.IGNORECASE), "Reading Google token file"),
    (re.compile(r"\bcat\b" + _ARG + r"\.pending_oauth_", re.IGNORECASE), "Reading pending OAuth state"),
    (re.compile(r"\bcat\b" + _ARG + r"\.pem\b", re.IGNORECASE), "Reading certificate file"),
    (re.compile(r"\bcat\b" + _ARG + r"\.key\b", re.IGNORECASE), "Reading key file"),
    (re.compile(r"\bcat\b" + _ARG + r"id_rsa", re.IGNORECASE), "Reading SSH private key"),
    (re.compile(r"\bcat\b" + _ARG + r"id_ed25519", re.IGNORECASE), "Reading SSH private key"),
    (re.compile(r"\bcat\b" + _ARG + r"\.ssh/", re.IGNORECASE), "Reading SSH directory file"),
    (re.compile(r"\bcat\b" + _ARG + r"master\.env", re.IGNORECASE), "Reading master env file"),

    # Environment variable printing
    (re.compile(r"\bprintenv\b", re.IGNORECASE), "Printing environment variables"),
    (re.compile(r"^env\s*$", re.IGNORECASE), "Listing all environment variables"),
    (re.compile(r"^set\s*$", re.IGNORECASE), "Listing shell variables"),
    (re.compile(r"\bexport\s+-p\b", re.IGNORECASE), "Listing exported variables"),
    (re.compile(r"\bdeclare\s+-x\b", re.IGNORECASE), "Listing exported variables"),
    (re.compile(r"\bcompgen\s+-v\b", re.IGNORECASE), "Listing all variable names"),

    # Echo/printf of a secret-named variable
    (re.compile(r"\becho\b.*" + _SECRET_VAR, re.IGNORECASE), "Echoing secret environment variable"),
    (re.compile(r"\bprintf\b.*" + _SECRET_VAR, re.IGNORECASE), "Printf of secret environment variable"),

    # Python inline execution that accesses env vars
    (re.compile(r"python[3]?\s+-c\s+.*os\.environ", re.IGNORECASE),
     "Python inline code accessing os.environ"),
    (re.compile(r"python[3]?\s+-c\s+.*os\.getenv", re.IGNORECASE),
     "Python inline code accessing os.getenv"),
    (re.compile(r"python[3]?\s+-c\s+.*dotenv", re.IGNORECASE),
     "Python inline code loading dotenv"),
    (re.compile(r"python[3]?\s+-c\s+.*\.env\b", re.IGNORECASE),
     "Python inline code referencing env file"),

    # Node / other interpreters, inline
    (re.compile(r"node\s+-e\s+.*process\.env", re.IGNORECASE),
     "Node inline code accessing process.env"),
    (re.compile(r"\bruby\s+-e\b.*ENV", re.IGNORECASE), "Ruby inline code accessing ENV"),
    (re.compile(r"\bperl\s+-e\b.*ENV", re.IGNORECASE), "Perl inline code accessing %ENV"),
    (re.compile(r"\bphp\s+-r\b.*getenv", re.IGNORECASE), "PHP inline code accessing getenv"),

    # Grep/search targeting sensitive files
    (re.compile(r"\b(?:grep|rg)\b" + _ARG + r"\.env\b", re.IGNORECASE), "Searching env file"),
    (re.compile(r"\bfind\b" + _ARG + r"\.env\b", re.IGNORECASE), "Find searching for env files"),
    (re.compile(r"\bfind\b.*-exec\b.*cat", re.IGNORECASE), "Find with exec cat (potential env read)"),

    # Wildcard / expansion bypasses: cat .en*  cat .e??  cat .e[n]  cat .e$X  cat .e\nv
    (re.compile(r"\bcat\b" + _ARG + r"\.en\*", re.IGNORECASE), "Wildcard read that could match env file"),
    (re.compile(r"\bcat\b" + _ARG + r"\.e\?\?", re.IGNORECASE), "Wildcard read that could match env file"),
    (re.compile(r"\bcat\b" + _ARG + r"\.e\[", re.IGNORECASE), "Glob read that could match env file"),
    (re.compile(r"\bcat\b" + _ARG + r"\.e\$", re.IGNORECASE), "Variable expansion bypass targeting env file"),
    (re.compile(r"\bcat\b" + _ARG + r"\.e\\", re.IGNORECASE), "Backslash bypass targeting env file"),

    # Symlink / copy of sensitive files
    (re.compile(r"\bln\b.*-s.*\.env\b", re.IGNORECASE), "Creating symlink to env file"),
    (re.compile(r"\bln\b.*-s.*credentials", re.IGNORECASE), "Creating symlink to credentials"),
    (re.compile(r"\bln\b.*-s.*google_token", re.IGNORECASE), "Creating symlink to token file"),
    (re.compile(r"\bcp\b" + _ARG + r"\.env\b", re.IGNORECASE), "Copying env file"),

    # Interpreter here-docs are checked by body (see check_bash_command); the
    # bare `python <<` form is still refused outright because its body is the
    # program and could do anything.
    (re.compile(r"\b(?:python[3]?|perl|ruby)\s*<<", re.IGNORECASE),
     "Interpreter here-doc execution (use `python3 - <<` so the body can be inspected)"),

    # Base64 decoding piped to execution
    (re.compile(r"base64\s+(-d|--decode).*\|\s*(sh|bash|zsh|python|ruby|perl|node)", re.IGNORECASE),
     "Base64 decoded command piped to interpreter"),
    (re.compile(r"bash\s*<<<.*base64", re.IGNORECASE), "Base64 here-string piped to bash"),

    # Eval with env/secret references
    (re.compile(r"\beval\b.*\.env\b", re.IGNORECASE), "Eval referencing env file"),
    (re.compile(r"\beval\b.*" + _SECRET_VAR, re.IGNORECASE), "Eval referencing secret variable"),
    (re.compile(r"\beval\b.*os\.environ", re.IGNORECASE), "Eval accessing os.environ"),
    (re.compile(r"\bexec\b\s+\d*[<>]", re.IGNORECASE), "Exec with file descriptor redirect"),

    # Curl/wget exfiltration
    (re.compile(r"\b(?:curl|wget)\b.*" + _SECRET_VAR, re.IGNORECASE),
     "Curl/wget with secret variable in URL/data"),
    (re.compile(r"\bcurl\b.*(?:-d\s*@|--data).*\.env", re.IGNORECASE),
     "Curl posting env file contents"),

    # Process substitution / hex dumps of sensitive files
    (re.compile(r"<\(.*\.env", re.IGNORECASE), "Process substitution referencing env file"),
    (re.compile(r"\b(?:xxd|hexdump|od)\b" + _ARG + r"\.env", re.IGNORECASE), "Hex dump of env file"),

    # xargs execution that could target sensitive files
    (re.compile(r"\bxargs\b.*cat", re.IGNORECASE), "xargs with cat (potential env read)"),
]


_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
# Rules that legitimately span a pipe (the danger *is* the pipe), checked
# against the whole shell text after here-doc bodies are removed.
CROSS_SEGMENT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"base64\s+(-d|--decode).*\|\s*(sh|bash|zsh|python|ruby|perl|node)", re.IGNORECASE),
     "Base64 decoded command piped to interpreter"),
    (re.compile(r"\bxargs\b.*cat", re.IGNORECASE), "xargs with cat (potential env read)"),
    (re.compile(r"\bfind\b.*-exec\b.*cat", re.IGNORECASE), "Find with exec cat (potential env read)"),
]


def _split_segments(shell_text: str) -> list[str]:
    """Split shell text into simple commands on ; | || && and newlines,
    ignoring separators inside single or double quotes so
    `python3 -c "import os; print(x)"` stays one command."""
    segments: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i = 0
    n = len(shell_text)
    while i < n:
        ch = shell_text[i]
        if quote:
            buf.append(ch)
            if ch == quote and (quote == "'" or shell_text[i - 1] != "\\"):
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "#" and (i == 0 or shell_text[i - 1].isspace()):
            # Unquoted comment: never executes, skip to end of line.
            while i < n and shell_text[i] != "\n":
                i += 1
            continue
        two = shell_text[i : i + 2]
        if two in ("||", "&&"):
            segments.append("".join(buf))
            buf = []
            i += 2
            continue
        if ch in (";", "|", "\n"):
            segments.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    segments.append("".join(buf))
    return segments
_SHELL_HEREDOC_CMD_RE = re.compile(r"\b(?:bash|sh|zsh|ksh|dash)\b")


def _split_heredocs(command: str) -> tuple[str, list[tuple[str, str]]]:
    """Separate here-doc bodies from the shell text that introduces them.

    Returns (shell_text_without_bodies, [(introducing_line, body), ...]).
    A body runs from the line after `<<DELIM` to the line equal to DELIM.
    """
    lines = command.split("\n")
    shell_lines: list[str] = []
    bodies: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        shell_lines.append(line)
        i += 1
        m = _HEREDOC_RE.search(line)
        if not m:
            continue
        delim = m.group(2)
        body: list[str] = []
        while i < len(lines) and lines[i].strip() != delim:
            body.append(lines[i])
            i += 1
        i += 1  # skip the delimiter line
        bodies.append((line, "\n".join(body)))
    return "\n".join(shell_lines), bodies


def check_bash_command(command: str, _depth: int = 0) -> str | None:
    """Check if a bash command would expose secrets. Returns the reason or None.

    Shell text is checked one simple command at a time so a pattern's `.*`
    can't reach across a pipe or into an unrelated argument. Here-doc bodies
    are checked as *content*: bodies fed to a shell are re-checked as shell,
    everything else (Python source, file contents) goes through the same
    exfiltration patterns used for Write/Edit. Mentioning a secret filename in
    a docstring is fine; printing its contents is not.
    """
    if _depth > 4:
        return None
    shell_text, bodies = _split_heredocs(command)

    whole = " ".join(shell_text.split()).strip()
    for pattern, reason in CROSS_SEGMENT_PATTERNS:
        if pattern.search(whole):
            return f"Blocked: {reason}"

    for segment in _split_segments(shell_text):
        seg = " ".join(segment.split()).strip()
        if not seg:
            continue
        for pattern, reason in DANGEROUS_BASH_PATTERNS:
            if pattern.search(seg):
                return f"Blocked: {reason}"
        # Subshell content: $(...) and `...`
        for sp in (re.compile(r"\$\((.*?)\)", re.DOTALL), re.compile(r"`(.*?)`", re.DOTALL)):
            for match in sp.finditer(seg):
                result = check_bash_command(match.group(1), _depth + 1)
                if result:
                    return f"{result} (inside subshell)"

    for intro, body in bodies:
        if _SHELL_HEREDOC_CMD_RE.search(intro):
            result = check_bash_command(body, _depth + 1)
            if result:
                return f"{result} (inside here-doc)"
        else:
            result = check_written_content(body)
            if result:
                return result.replace("writing scripts", "here-doc scripts")
    return None


# --- Two-step attack: content patterns that would exfiltrate secrets ---
# These patterns detect when a script is being WRITTEN that would print/expose env vars.
# We allow scripts that USE env vars (e.g., load_dotenv() + os.getenv for API calls)
# but block scripts that PRINT/LOG/RETURN them to stdout where Claude would see them.
EXFILTRATION_CONTENT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Python: printing env vars
    (re.compile(r"print\s*\(.*os\.environ", re.IGNORECASE),
     "Script prints os.environ to stdout"),
    (re.compile(r"print\s*\(.*os\.getenv\s*\(", re.IGNORECASE),
     "Script prints os.getenv() to stdout"),
    (re.compile(r"print\s*\(.*\.env", re.IGNORECASE),
     "Script prints .env content to stdout"),
    (re.compile(r"json\.dumps?\s*\(.*os\.environ", re.IGNORECASE),
     "Script serializes os.environ to JSON"),
    (re.compile(r"sys\.stdout\.write.*os\.environ", re.IGNORECASE),
     "Script writes os.environ to stdout"),
    (re.compile(r"pprint.*os\.environ", re.IGNORECASE),
     "Script pretty-prints os.environ"),

    # Python: reading .env and printing
    (re.compile(r"open\s*\(.*\.env.*\).*read\(\)", re.IGNORECASE),
     "Script reads env file contents"),
    (re.compile(r"open\s*\(.*(?:_token\w*\.json|credentials\.json).*\).*read\(\)", re.IGNORECASE),
     "Script reads token/credential file contents"),
    (re.compile(r"(?:_token\w*\.json|credentials\.json)[^\n]*read_text\(\)[^\n]*print", re.IGNORECASE),
     "Script prints token/credential file contents"),

    # Bash script: cat/echo env vars
    (re.compile(r"\bcat\b(?:\s+\S+)*?\s+\S*\.env\b", re.IGNORECASE),
     "Script cats .env file"),
    (re.compile(r"echo\s+\$\{?[A-Z_]*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE),
     "Script echoes secret variable"),
    (re.compile(r"printenv", re.IGNORECASE),
     "Script runs printenv"),

    # Ruby/Perl/Node
    (re.compile(r"puts\s+ENV", re.IGNORECASE), "Script prints Ruby ENV"),
    (re.compile(r"print\s+%ENV", re.IGNORECASE), "Script prints Perl %ENV"),
    (re.compile(r"console\.log\s*\(\s*process\.env", re.IGNORECASE), "Script logs process.env"),

    # Curl/wget exfiltration in script
    (re.compile(r"curl.*\$\{?[A-Z_]*(?:KEY|TOKEN|SECRET|PASSWORD)", re.IGNORECASE),
     "Script exfiltrates secret via curl"),
    (re.compile(r"requests\.(get|post).*os\.getenv", re.IGNORECASE),
     "Script sends env var via HTTP request"),
]


def check_written_content(content: str) -> str | None:
    """Check if file content being written would exfiltrate secrets."""
    if not content:
        return None
    for pattern, reason in EXFILTRATION_CONTENT_PATTERNS:
        if pattern.search(content):
            return f"Blocked: {reason} — writing scripts that expose secrets is not allowed"
    return None


def main() -> None:
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("Failed to parse hook input JSON", file=sys.stderr)
        sys.exit(1)

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    reason: str | None = None

    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        reason = is_sensitive_file(file_path)

    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        reason = check_bash_command(command)

    elif tool_name == "Grep":
        path = tool_input.get("path", "")
        pattern = tool_input.get("pattern", "")
        if path:
            reason = is_sensitive_file(path)
        # Also check if grepping for secret patterns in a way that would expose values
        if not reason and re.search(r"\.env", path or "", re.IGNORECASE):
            reason = "Blocked: Grep targeting .env file"

    elif tool_name in ("Edit", "Write"):
        file_path = tool_input.get("file_path", "")
        reason = is_sensitive_file(file_path)
        # Two-step attack defense: check if content being written would
        # create a script that prints/exfiltrates environment variables
        if not reason:
            content = tool_input.get("content", "") or tool_input.get("new_string", "")
            reason = check_written_content(content)

    elif tool_name == "Glob":
        pattern_str = tool_input.get("pattern", "")
        if re.search(r"\.env", pattern_str, re.IGNORECASE):
            reason = "Blocked: Glob pattern targeting .env files"

    if reason:
        print(
            f"SECURITY: {reason}. "
            "API keys and credentials must never enter the context window. "
            "Use the Python CLI wrapper (query.py) to interact with integrations instead.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Allow the tool call
    sys.exit(0)


if __name__ == "__main__":
    main()
